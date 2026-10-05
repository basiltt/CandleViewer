"""Capture tool (E08-T05): record raw Bybit public WS frames into the fixture corpus.

    python tools/fixtures/capture_fixture.py --topic publicTrade.BTCUSDT --frames 500 \
        --out packages/fixtures/bybit/<date>/ws/clean_publicTrade_BTCUSDT.jsonl

Public stream only (no credentials are ever read: private fixtures are E29).
Every frame is passed through `redact()` and re-checked with `find_leaks()`
before it is written; a frame that still leaks aborts the capture. Output is
newline-delimited raw frames plus a `<out>.manifest.json` entry in the corpus
manifest shape. NEVER run from tests/CI (C-13.5): tests inject a fake connector.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

if __package__ in (None, ""):  # pragma: no cover - script entry
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.fixtures.redact import find_leaks, redact

#: Mainnet public stream (demo has no public feed of its own, C-2.11).
PUBLIC_URL = "wss://stream.bybit.com/v5/public/linear"
HOST = "stream.bybit.com"
DEFAULT_SIZE_CAP = 512_000


class Socket(Protocol):
    async def send(self, frame: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


Connector = Callable[[str], Awaitable[Socket]]


class CaptureError(RuntimeError):
    """Capture aborted: leak after redaction, size cap exceeded, or no data."""


@dataclass(frozen=True)
class CaptureResult:
    frames: int
    bytes_written: int
    manifest: dict[str, Any]


def _is_data_frame(frame: str, topic: str) -> bool:
    try:
        msg = json.loads(frame)
    except ValueError:
        return False
    return isinstance(msg, dict) and msg.get("topic") == topic


async def capture(
    topic: str,
    out: Path,
    *,
    max_frames: int,
    connect: Connector,
    notable_event: str = "clean window",
    size_cap: int = DEFAULT_SIZE_CAP,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CaptureResult:
    """Subscribe to `topic`, record `max_frames` redacted data frames, write file + manifest."""
    if max_frames <= 0:
        raise ValueError("max_frames must be > 0")
    sock = await connect(PUBLIC_URL)
    lines: list[str] = []
    size = 0
    first_ts: int | None = None
    last_ts: int | None = None
    try:
        await sock.send(json.dumps({"op": "subscribe", "args": [topic]}))
        while len(lines) < max_frames:
            raw = await sock.recv()
            if not _is_data_frame(raw, topic):
                continue  # subscribe acks / pongs are not part of the fixture
            clean = redact(raw)
            leaks = find_leaks(clean)
            if leaks:
                raise CaptureError(f"frame still matches secret patterns after redaction: {leaks}")
            size += len(clean.encode()) + 1
            if size > size_cap:
                raise CaptureError(f"capture exceeds the {size_cap}-byte cap; lower --frames")
            ts = json.loads(clean).get("ts")
            if isinstance(ts, int):
                first_ts = ts if first_ts is None else first_ts
                last_ts = ts
            lines.append(clean)
    finally:
        await sock.close()
    parts = topic.split(".")
    entry: dict[str, Any] = {
        "path": f"ws/{out.name}",
        "symbol": parts[-1],
        "stream": topic,
        "host": HOST,
        "capture_date": now().date().isoformat(),
        "source": "capture_fixture.py",
        "notable_event": notable_event,
        "window_ms": [first_ts, last_ts],
        "http_status": 200,
        "size_cap_bytes": size_cap,
    }
    await asyncio.to_thread(_write, out, lines, entry)
    return CaptureResult(frames=len(lines), bytes_written=size, manifest=entry)


def _write(out: Path, lines: list[str], entry: dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    out.with_name(out.name + ".manifest.json").write_text(
        json.dumps(entry, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


async def _ws_connect(url: str) -> Socket:  # pragma: no cover - real network, manual only
    from websockets.asyncio.client import connect as ws_connect

    conn = await ws_connect(url, open_timeout=10, ping_interval=20)

    class _S:
        async def send(self, frame: str) -> None:
            await conn.send(frame)

        async def recv(self) -> str:
            msg = await asyncio.wait_for(conn.recv(), timeout=30)
            return msg if isinstance(msg, str) else msg.decode()

        async def close(self) -> None:
            await conn.close()

    return _S()


def main(argv: list[str] | None = None, *, connect: Connector = _ws_connect) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    p.add_argument("--topic", required=True)
    p.add_argument("--frames", type=int, default=500)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--event", default="clean window")
    p.add_argument("--size-cap", type=int, default=DEFAULT_SIZE_CAP)
    ns = p.parse_args(argv)
    try:
        res = asyncio.run(capture(ns.topic, ns.out, max_frames=ns.frames, connect=connect,
                                  notable_event=ns.event, size_cap=ns.size_cap))  # fmt: skip
    except CaptureError as exc:
        print(f"capture aborted: {exc}", file=sys.stderr)
        return 1
    print(f"captured {res.frames} frames ({res.bytes_written} bytes) -> {ns.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
