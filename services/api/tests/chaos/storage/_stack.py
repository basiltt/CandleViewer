"""Compose-stack helpers for the docker chaos scenarios (E07-Q04, C-13.6).

The CI `integration` job brings up `postgres` + `questdb` from
`infra/compose/docker-compose.yml`, mounts a fixed-size loopback image on
the runner for scenario 3b, and runs Alembic before selecting
`-m "chaos and integration"`. Faults are injected with `docker compose
stop/start`; every wait is bounded and polls a condition (no bare sleeps).
The app side runs in-process with the production wiring: the E04-T04
`HealthRegistry` + `register_real_probes` + `PgSystemEventWriter`, and the
E07-T03 `IlpWriter` over a real TCP socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

import asyncpg

REPO = Path(__file__).resolve().parents[5]
COMPOSE_FILES = (REPO / "infra" / "compose" / "docker-compose.yml",)
QDB_DDL = REPO / "backend" / "db" / "questdb"
HOST = "127.0.0.1"
PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
QDB_PG_PORT = int(os.environ.get("QUESTDB_PG_PORT", "8812"))
QDB_ILP_PORT = int(os.environ.get("QUESTDB_ILP_PORT", "9009"))
#: Loopback-image mount for scenario 3b (created by the CI step, never a real volume).
LOOP_DIR = Path(os.environ.get("CV_CHAOS_LOOPBACK_DIR", "/mnt/cv-chaos-cold"))
LOOP_MAX_BYTES = 128 * 1024 * 1024


def pg_dsn() -> str:
    pw = os.environ.get("POSTGRES_PASSWORD", "cv")
    return f"postgresql+asyncpg://cv:{pw}@{HOST}:{PG_PORT}/candleviewer"


def _compose(*args: str) -> None:
    argv = ["docker", "compose", "--profile", "core"]
    for f in COMPOSE_FILES:
        argv += ["-f", str(f)]
    subprocess.run([*argv, *args], check=True, timeout=180)  # noqa: S603 - fixed argv


async def compose(*args: str) -> None:
    await asyncio.to_thread(_compose, *args)


async def until(pred: Callable[[], Awaitable[bool]], what: str, timeout_s: float = 90.0) -> None:
    """Poll `pred` until true; bounded, raises with `what` on timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not await pred():
        if loop.time() >= deadline:
            raise AssertionError(f"timed out after {timeout_s}s waiting for: {what}")
        await asyncio.sleep(0.5)


async def qdb_connect() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=HOST,
        port=QDB_PG_PORT,
        user="admin",
        password="quest",  # noqa: S106 - QuestDB OSS default, ephemeral CI container
        database="qdb",
    )


async def qdb_up() -> bool:
    with contextlib.suppress(OSError, asyncpg.PostgresError):
        conn = await asyncio.wait_for(qdb_connect(), timeout=3)
        await conn.close()
        return True
    return False


class TcpIlpTransport:
    """ILP-over-TCP transport that notices a peer close before writing.

    ILP/TCP has no acks; a write into a socket whose peer already sent FIN
    is silently lost. Checking `at_eof()` first turns that into an error, so
    the writer keeps the batch buffered (exactly-once on reconnect)."""

    def __init__(self) -> None:
        self._r: asyncio.StreamReader | None = None
        self._w: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        self._r, self._w = await asyncio.wait_for(
            asyncio.open_connection(HOST, QDB_ILP_PORT), timeout=3
        )

    async def write(self, data: bytes) -> None:
        if self._r is None or self._w is None or self._r.at_eof() or self._w.is_closing():
            raise ConnectionError("ILP peer closed")
        self._w.write(data)
        await asyncio.wait_for(self._w.drain(), timeout=5)

    async def close(self) -> None:
        if self._w is not None:
            self._w.close()
            with contextlib.suppress(Exception):
                await self._w.wait_closed()
        self._r = self._w = None
