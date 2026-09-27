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

from pydantic import Field, SecretStr, field_validator
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
    feed_rate_hz: float = Field(default=2.0, gt=0.0)
    feed_sample_path: str = "packages/fixtures/raw/synthetic_sample.jsonl"

    bybit_api_key: SecretStr | None = None
    bybit_api_secret: SecretStr | None = None

    bind_host: str = "127.0.0.1"
    bind_port: int = 8080

    pg_dsn: SecretStr = SecretStr("postgresql+asyncpg://cv:cv@localhost:5432/candleviewer")
    questdb_ilp: str = "questdb:9009"
    questdb_pg: str = "questdb:8812"
    parquet_root: str = "/data/parquet"

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

    @field_validator("feed_rate_hz")
    @classmethod
    def _feed_rate_positive(cls, value: float) -> float:
        """`CV_FEED_RATE_HZ` must be positive (acceptance criterion 2)."""
        if value <= 0:
            raise ValueError("CV_FEED_RATE_HZ must be > 0")
        return value

    def model_post_init(self, __context: object) -> None:
        """Fail fast on `CV_FEED=live` without credentials (acceptance criterion 3).

        A half-configured live feed must never start — this raises before any
        module is constructed, with a message that names the missing env vars
        and never echoes any credential material (C-12.6/C-12.9).
        """
        if self.feed is FeedMode.LIVE and (
            self.bybit_api_key is None or self.bybit_api_secret is None
        ):
            raise ValueError(
                "CV_FEED=live requires CV_BYBIT_API_KEY and CV_BYBIT_API_SECRET to be "
                "set; refusing to start half-configured (see "
                "docs/plan/20-architecture.md Sec.7.3). Use CV_FEED=synthetic for local "
                "development without Bybit credentials."
            )

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
