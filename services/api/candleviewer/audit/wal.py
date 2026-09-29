"""Bounded on-disk WAL for durable audit buffering (ticket "Scope /
Deliverables": "writes are asynchronous but survive a Postgres outage via
the bounded on-disk WAL described in `20-architecture.md` Sec.F8, replayed
on recovery in original order so the chain stays monotonic").

Format: one JSON object per line (newline-delimited), each `fsync`'d before
`append()` returns so a process kill immediately after a successful
`append()` still has the record on disk. A companion `<file>.committed`
cursor file holds the byte offset up to which records have been durably
written to Postgres; `replay()` resumes from that offset, so a record is
never replayed twice after a clean restart and never lost across a crash
between "appended" and "committed".

Bounded (ticket "Security notes": "denial-of-service by flooding (bounded
WAL with a drop-oldest-plus-alarm policy, never dropping silently)"):
`append()` raises `AuditWalFull` once the file exceeds `max_bytes` rather
than growing unboundedly; `AuditWriter` catches this, calls the alarm
callback and drops the *oldest* undelivered record to make room, rather than
refusing new (more urgent) entries or silently discarding without a metric.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from candleviewer.audit.errors import AuditError


class AuditWalFull(AuditError):
    """Raised by `AuditWal.append` when the WAL file has reached `max_bytes`."""


class AuditWal:
    """A single append-only WAL file plus its commit cursor.

    Not safe for concurrent writers — `AuditWriter` owns exactly one
    `AuditWal` instance and serialises all appends through its single writer
    task (ticket "Technical notes": "a single writer task to keep the chain
    well-ordered").
    """

    def __init__(self, path: Path, max_bytes: int = 64 * 1024 * 1024) -> None:
        self._path = path
        self._cursor_path = path.with_suffix(path.suffix + ".committed")
        self._max_bytes = max_bytes
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        if not self._cursor_path.exists():
            self._cursor_path.write_text("0", encoding="utf-8")

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: dict[str, Any]) -> None:
        """Durably append one record. Raises `AuditWalFull` if this would
        exceed `max_bytes` — caller decides the drop-oldest-plus-alarm
        remediation (ticket "Security notes")."""
        line = json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
        encoded = line.encode("utf-8")
        current_size = self._path.stat().st_size if self._path.exists() else 0
        if current_size + len(encoded) > self._max_bytes:
            raise AuditWalFull(f"WAL at {self._path} would exceed max_bytes={self._max_bytes}")
        with open(self._path, "ab") as fh:
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())

    def size_bytes(self) -> int:
        return self._path.stat().st_size if self._path.exists() else 0

    def committed_offset(self) -> int:
        return int(self._cursor_path.read_text(encoding="utf-8").strip() or "0")

    def mark_committed(self, offset: int) -> None:
        """Record that every byte up to `offset` has been durably written to
        Postgres. `fsync`'d so a crash immediately after does not replay
        already-committed records (no duplicates, ticket AC "Postgres outage
        does not lose events" — "no duplicates")."""
        tmp = self._cursor_path.with_suffix(".tmp")
        tmp.write_text(str(offset), encoding="utf-8")
        with open(tmp, "r+", encoding="utf-8") as fh:
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self._cursor_path)

    def replay(self) -> Iterator[tuple[int, dict[str, Any]]]:
        """Yield `(end_offset, record)` for every record after
        `committed_offset()`, in original append order. `end_offset` is the
        byte offset immediately after this record — pass it to
        `mark_committed()` once the record is durably written to Postgres."""
        start = self.committed_offset()
        with open(self._path, "rb") as fh:
            fh.seek(start)
            offset = start
            for raw_line in fh:
                offset += len(raw_line)
                stripped = raw_line.strip()
                if not stripped:
                    continue
                yield offset, json.loads(stripped)

    def compact(self) -> None:
        """Drop every byte already committed, so the file does not grow
        forever across restarts. Safe to call any time; a concurrent
        `replay()` in this process is never in flight because the writer
        task is the sole caller of both."""
        committed = self.committed_offset()
        if committed == 0:
            return
        with open(self._path, "rb") as fh:
            fh.seek(committed)
            remainder = fh.read()
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            fh.write(remainder)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self._path)
        self.mark_committed(0)
