"""Bounded on-disk spill WAL for the StreamWriter (E16-T03, ADR-0015 decision 8).

One WAL per stream lane (`<CV_RECORDER_WAL_DIR>/<stream>/`), so a stalled stream never
blocks another's replay. All lanes share one `WalBudget` (`CV_RECORDER_WAL_MAX_BYTES`, default
1 GiB): an append that would exceed it is refused **per frame** and the caller records the
refused frames as a `backpressure_drop` gap — the WAL itself never drops silently.

Frame: `>I length` + `>I crc32(payload)` + orjson payload
`{"t": stream, "s": symbol, "e": exch_ts, "q": seq, "u": sub, "r": row}`. A frame failing its
CRC (or a torn tail) ends the read; the remainder is moved to `<wal>/corrupt/` and reported to
the caller (`recorder_wal_corrupt`) — never skipped mid-file.

Two files per lane: new spills append to `spill.wal`; a replay first renames it to
`replay.wal` (unless an interrupted replay left one), replays that, then deletes it. A replay
that fails or is interrupted leaves `replay.wal` in place and is restarted from its start —
safe because every QuestDB table declares `DEDUP UPSERT KEYS`.

File I/O is synchronous here and always called through `asyncio.to_thread` by the writer
(never on the event loop).
"""

from __future__ import annotations

import os
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import orjson

_HEADER = struct.Struct(">II")
#: Hard ceiling on one frame (a 500-level snapshot is ~40 KiB); larger = corrupt length.
_MAX_FRAME = 8 * 1024 * 1024
SPILL_NAME = "spill.wal"
REPLAY_NAME = "replay.wal"
CORRUPT_DIR = "corrupt"


@dataclass(frozen=True, slots=True)
class WalRecord:
    """One recorded row. `(symbol, stream, exch_ts, seq, sub)` is its identity; `sub` is the
    row's index inside one exchange message (a book delta carries many levels)."""

    stream: str
    symbol: str
    exch_ts: int
    seq: int
    sub: int
    row: dict[str, object]

    @property
    def key(self) -> tuple[str, str, int, int, int]:
        return (self.symbol, self.stream, self.exch_ts, self.seq, self.sub)


def encode_frame(rec: WalRecord) -> bytes:
    payload = orjson.dumps(
        {
            "t": rec.stream,
            "s": rec.symbol,
            "e": rec.exch_ts,
            "q": rec.seq,
            "u": rec.sub,
            "r": rec.row,
        }
    )
    return _HEADER.pack(len(payload), zlib.crc32(payload)) + payload


def _decode_payload(payload: bytes) -> WalRecord:
    raw = orjson.loads(payload)
    return WalRecord(
        stream=str(raw["t"]),
        symbol=str(raw["s"]),
        exch_ts=int(raw["e"]),
        seq=int(raw["q"]),
        sub=int(raw["u"]),
        row=dict(raw["r"]),
    )


class WalBudget:
    """Shared byte budget across every lane's WAL files (single-threaded use: lanes only
    mutate it under their own lock from `to_thread` calls that never overlap per lane; the
    counter is a plain int updated atomically under the GIL)."""

    def __init__(self, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")
        self.max_bytes = max_bytes
        self.used = 0


@dataclass(slots=True)
class ReadResult:
    records: list[WalRecord]
    #: Bytes moved to `corrupt/` because a frame failed CRC or was torn (0 = clean).
    corrupt_bytes: int = 0


class SpillWal:
    """The WAL of one stream lane. Not concurrency-safe: the lane serialises access."""

    def __init__(self, directory: Path, budget: WalBudget) -> None:
        self._dir = directory
        self._budget = budget
        self._dir.mkdir(parents=True, exist_ok=True)
        # Recover the budget share of files left by a previous process (startup replay).
        for name in (SPILL_NAME, REPLAY_NAME):
            path = self._dir / name
            if path.exists():
                budget.used += path.stat().st_size

    @property
    def spill_path(self) -> Path:
        return self._dir / SPILL_NAME

    @property
    def replay_path(self) -> Path:
        return self._dir / REPLAY_NAME

    def has_data(self) -> bool:
        return any(p.exists() and p.stat().st_size > 0 for p in (self.spill_path, self.replay_path))

    def append(self, records: list[WalRecord]) -> int:
        """Append frames in order until the budget refuses one; return how many were
        written (a prefix). fsync'd before returning so an acknowledged spill survives a
        crash."""
        chunks: list[bytes] = []
        size = 0
        for rec in records:
            frame = encode_frame(rec)
            if self._budget.used + size + len(frame) > self._budget.max_bytes:
                break
            chunks.append(frame)
            size += len(frame)
        if chunks:
            with self.spill_path.open("ab") as fh:
                fh.write(b"".join(chunks))
                fh.flush()
                os.fsync(fh.fileno())
            self._budget.used += size
        return len(chunks)

    def begin_replay(self) -> bool:
        """Rotate `spill.wal` to `replay.wal` unless an interrupted replay is pending.
        Returns whether there is anything to replay."""
        if not self.replay_path.exists() and self.spill_path.exists():
            os.replace(self.spill_path, self.replay_path)
        return self.replay_path.exists()

    def read_replay(self) -> ReadResult:
        """Decode `replay.wal`; on the first bad frame, quarantine the rest."""
        data = self.replay_path.read_bytes()
        records: list[WalRecord] = []
        offset = 0
        for rec, end in _iter_frames(data):
            records.append(rec)
            offset = end
        corrupt = len(data) - offset
        if corrupt:
            qdir = self._dir / CORRUPT_DIR
            qdir.mkdir(exist_ok=True)
            n = len(list(qdir.iterdir()))
            (qdir / f"{n:06d}.wal").write_bytes(data[offset:])
            with self.replay_path.open("r+b") as fh:
                fh.truncate(offset)
            self._budget.used -= corrupt
        return ReadResult(records=records, corrupt_bytes=corrupt)

    def finish_replay(self) -> None:
        """The replay landed: delete `replay.wal` and release its budget."""
        if self.replay_path.exists():
            self._budget.used -= self.replay_path.stat().st_size
            self.replay_path.unlink()


def _iter_frames(data: bytes) -> Iterator[tuple[WalRecord, int]]:
    offset = 0
    while offset + _HEADER.size <= len(data):
        length, crc = _HEADER.unpack_from(data, offset)
        start = offset + _HEADER.size
        end = start + length
        if length > _MAX_FRAME or end > len(data):
            return
        payload = data[start:end]
        if zlib.crc32(payload) != crc:
            return
        try:
            rec = _decode_payload(payload)
        except (orjson.JSONDecodeError, KeyError, TypeError, ValueError):
            return
        yield rec, end
        offset = end
