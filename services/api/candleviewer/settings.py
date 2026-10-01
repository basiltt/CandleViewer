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

    # E04-T03: private-bind-only `/metrics` listener (`CV_METRICS_ENABLED`,
    # `CV_METRICS_BIND`). Non-private hosts are refused at startup.
    metrics_enabled: bool = True
    metrics_bind: str = "127.0.0.1:9108"

    bind_host: str = "127.0.0.1"
    bind_port: int = 8080

    # E09-T04: Tailscale-only reachability guard (US-ONB-008). Comma-joined
    # CIDR list (e.g. "100.64.0.0/10,192.168.1.0/24"); loopback/`::1` are
    # always allowed in addition (see `candleviewer.net.cidr.CidrAllowList`).
    # A plain string (not a JSON array) so the deployment runbook/`.env` can
    # set it without quoting a JSON list. Empty by default so a forgotten env
    # var fails closed to loopback-only rather than silently allowing
    # everything.
    mesh_cidrs_csv: str = ""
    # Boot + hourly re-check cadence (Performance notes: must not block the
    # event loop; runs in a thread executor with a 2s timeout — see
    # `candleviewer.net.scheduler`).
    mesh_self_check_interval_s: float = Field(default=3600.0, gt=0.0)
    # No trusted proxy by default: `X-Forwarded-For` and friends are always
    # ignored unless both are set, and even then only the configured proxy's
    # own immediate peer address is trusted to supply the header.
    mesh_trusted_proxy_header: str | None = None
    mesh_trusted_proxy_address: str | None = None

    # E09-S03: CSRF allow-list for cookie-authenticated `POST /auth/refresh`
    # (`CV_ALLOWED_ORIGINS`, comma separated, e.g. "http://127.0.0.1:5173").
    # Empty (default) fails closed: every cookie refresh is refused.
    allowed_origins: str = ""

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

    # QA #1658: auth key material (hex, 32 bytes each) resolved by the
    # composition root until E27-T02's M2 KEK loader lands. Required when
    # `storage_backend="real"` and environment is live (AuthService also
    # refuses a live start without them).
    auth_totp_key_hex: SecretStr | None = None
    auth_recovery_hmac_key_hex: SecretStr | None = None
    auth_pepper: SecretStr = SecretStr("")

    # E03-T10: bounds `pg_advisory_lock` acquisition in the boot-time
    # migration runner (`candleviewer.migrations.boot`). A deadlocked
    # migration in another process turns into a clear `CI-DEP-004` error at
    # this timeout instead of hanging startup indefinitely (ADR-0013 rule 9).
    migration_lock_timeout_s: float = Field(default=300.0, gt=0.0)

    # E09-T02: `audit.emit` durably buffers to an on-disk WAL before writing
    # to `audit_log` (F8 — survives a Postgres outage), and the daily
    # checkpoint job appends the head hash to a file outside the database
    # volume so tail truncation is detectable even if Postgres data is lost.
    audit_wal_path: str = "var/audit/audit.wal"
    audit_checkpoint_path: str = "var/audit/checkpoints.ndjson"

    kek_source: str = "host-keychain"

    # E04-T01: `configure_logging()` inputs. `log_format="console"` is only
    # permitted in dev/CI contexts — enforced by
    # `candleviewer.observability.logging.configure_logging`, not here.
    log_level: str = "info"
    log_format: Literal["json", "console"] = "json"
    # RFC 3339 instant; absent (`None`) means body logging is off (SR-123
    # default-off requirement). Kept as `str | None` rather than `datetime`
    # so an unparsable value fails fast at settings-load time with a clear
    # `CV_LOG_BODIES_UNTIL` error rather than silently becoming `None`.
    log_bodies_until: str | None = None

    recv_window_ms: int = 5000
    max_ws_topics_per_conn: int = 64
    heatmap_cadence_ms: int = 100
    book_depth: int = 200
    recorder_retention_days: int = 30
    recorder_hot_days: int = 7
    disk_cap_gb: int = 500
    # E07-T05: retention scheduler flag (off by default) and cron expressions.
    retention_enabled: bool = False
    retention_cron: str = "0 3 * * *"
    export_cron: str = "15 2 * * *"
    compact_cron: str = "0 3 * * 0"
    order_rate_per_uid: int = 8
    native_sl_deadline_ms: int = 3000
    killswitch_on_disconnect_s: int = 30

    git_sha: str = "unknown"
    version: str = "0.1.0"

    @property
    def mesh_cidrs(self) -> tuple[str, ...]:
        """`CV_MESH_CIDRS_CSV` split on commas, trimmed, empties dropped."""
        return tuple(part.strip() for part in self.mesh_cidrs_csv.split(",") if part.strip())

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        """`CV_ALLOWED_ORIGINS` split on commas, trimmed, trailing `/` dropped."""
        return frozenset(
            o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()
        )

    @field_validator("bind_host")
    @classmethod
    def _bind_host_not_wildcard(cls, value: str) -> str:
        """`CV_BIND_HOST` must never be `0.0.0.0` (C-12.9, no public exposure)."""
        if value == "0.0.0.0":  # noqa: S104  # nosec B104
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
