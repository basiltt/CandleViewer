"""Typed application settings (M1 `config`).

Loads configuration from the environment only (`.env` file + `CV_*` env vars,
never a checked-in secrets file — C-12.9), per the layering documented in
`docs/plan/20-architecture.md` Sec.7.2: packaged defaults -> `infra/compose/.env`
-> environment variables -> Postgres-stored runtime settings -> per-user
preferences. Only the first two layers are implemented by this class; the
runtime/per-user layers are owned by M21 `admin`.

Security: `__repr__`/`__str__` never print secret values (redacting `__str__`
below) — an early instance of M24's redaction-filter requirement. Any field
whose name matches `(key|secret|token|password|dsn)` (case-insensitive) is a
`SecretStr` so it can never leak into logs, tracebacks or `repr()` by
accident.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REDACT_NAME_RE = re.compile(r"(key|secret|token|password|dsn)", re.IGNORECASE)


class Environment(StrEnum):
    """The three structural Bybit environments (P9, `20-architecture.md` Sec.7.1).

    `live` | `demo` | `testnet` select hosts, keys, storage namespace and code
    paths — never inferred, always explicit (arch P9).
    """

    LIVE = "live"
    DEMO = "demo"
    TESTNET = "testnet"


class FeedMode(StrEnum):
    """`CV_FEED` switch (`20-architecture.md` Sec.7.3).

    `synthetic` replays `packages/fixtures/raw` at configurable rates so
    engineers and CI can work without Bybit credentials; E2E tests and dev
    defaults never use `live` here (this is a *feed* toggle, orthogonal to
    `Environment`).
    """

    LIVE = "live"
    SYNTHETIC = "synthetic"


class Settings(BaseSettings):
    """Root application settings, populated from the environment only.

    `git_sha`/`version` are build-time metadata (E02-T08 packaging injects
    `CV_GIT_SHA`; defaults are `"unknown"`/the package version) surfaced by
    `/healthz` and `/readyz` (E02-T05 acceptance criterion 3).
    """

    model_config = SettingsConfigDict(
        env_prefix="CV_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = Environment.DEMO
    feed: FeedMode = FeedMode.SYNTHETIC

    bind_host: str = "127.0.0.1"
    bind_port: int = 8080

    pg_dsn: SecretStr = SecretStr("postgresql+asyncpg://cv:cv@localhost:5432/candleviewer")
    questdb_ilp: str = "questdb:9009"
    questdb_pg: str = "questdb:8812"
    parquet_root: str = "/data/parquet"

    # E07-T01: selects the M10 `storage` tier client implementations.
    # `"fake"` (the default) wires the in-memory fakes from
    # `candleviewer.storage.testing` and performs no I/O — this is what lets
    # `create_app()`/the supervisor boot with no database containers running
    # (ticket acceptance criterion 1). `"real"` is reserved for E07-T02/T03/
    # T04's engine clients; selecting it before those land is a configuration
    # error the storage service surfaces via `StorageTierUnavailable`.
    storage_backend: Literal["fake", "real"] = "fake"

    kek_source: str = "host-keychain"

    recv_window_ms: int = 5000
    max_ws_topics_per_conn: int = 64
    heatmap_cadence_ms: int = 100
    book_depth: int = 200
    recorder_retention_days: int = 30
    recorder_hot_days: int = 7
    disk_cap_gb: int = 500
    order_rate_per_uid: int = 8
    native_sl_deadline_ms: int = 3000
    killswitch_on_disconnect_s: int = 30

    git_sha: str = "unknown"
    version: str = "0.1.0"

    @field_validator("bind_host")
    @classmethod
    def _bind_host_not_wildcard(cls, value: str) -> str:
        """`CV_BIND_HOST` must never be `0.0.0.0` (C-12.9, no public exposure)."""
        if value == "0.0.0.0":  # noqa: S104 - this validator is the guard, not a bind call
            raise ValueError(
                "CV_BIND_HOST must not be 0.0.0.0 (see docs/plan/20-architecture.md Sec.7.2)"
            )
        return value

    def __repr_args__(self) -> list[tuple[str | None, object]]:
        """Redact any field whose name looks like a secret before it is ever printed.

        Applies to `repr()`, `str()` and pydantic's own `__repr__` machinery,
        so `Settings` can never leak a DSN/key/token/password/secret into a
        log line, exception message or debugger dump (C-12.6/C-12.9).
        """
        redacted: list[tuple[str | None, object]] = []
        for name, value in super().__repr_args__():
            if name is not None and _REDACT_NAME_RE.search(name):
                redacted.append((name, "**redacted**"))
            else:
                redacted.append((name, value))
        return redacted


def get_settings() -> Settings:
    """Return a fresh `Settings` instance built from the current environment.

    Not cached (`functools.lru_cache`) on purpose: tests construct many
    independent instances with different env vars (`monkeypatch.setenv`) and
    must not see a stale cached instance from an earlier test.
    """
    return Settings()
