"""`GET /market/klines` (`docs/plan/22-api-openapi.yaml`).

QA defect #1622 blocker: the E08-S06 backfill core (coverage index, paging,
rate-limit-safe fetch — `ingestion/kline_backfill.py`) landed in PR #1613,
but the ticket's own core deliverable, the REST endpoint itself, did not —
`grep -rln "market/klines" services/api/candleviewer/**/*.py` outside
`ingestion/` returned nothing. This module is the thin HTTP adapter, mirrors
the pattern `api/audit.py` and `api/health.py` already establish: a
structurally-typed Protocol for the injected cache reader (no import edge
beyond `storage`'s own public surface, which `api` — the composition root's
HTTP layer — is already allowed to depend on), RFC 9457 problem responses,
and a cache-first read so a fully-covered request never touches the
exchange (ticket "Cache hit" scenario).

Backfilling missing history (the exchange fetch itself) is intentionally
**out of scope for this endpoint** in the fake/CI-default storage backend:
`KlineBackfillService` needs a live `KlineFetcher` (the exchange adapter, not
yet implemented — E08-T02 is still a scaffold, see the adapter's
`service.py`), so until that adapter exists this route serves cache-only
reads and reports the request's coverage holes in `meta` rather than
silently pretending the exchange was consulted. Once E08-T02 lands, wiring
a real `KlineFetcher` here is a one-line change (mirrors the audit router's
own "one-line change once it lands" pattern in `app.py`).

PR #1626 review (defect #1622 fixer pass): `22-api-openapi.yaml` declares
`x-rbac: {permissions: [marketdata:read], scope: none}` for this route
(C-12.4 — RBAC is enforced server-side, never just hidden in the UI); the
first cut of this router served every request unauthenticated. This module
now mirrors `api/audit.py`'s own fail-closed `_authorize_or_raise` pattern
exactly: an injected, structurally-typed `PrincipalResolver` resolves the
caller from the request, and the caller must hold `marketdata:read` or the
request never reaches the cache. `principal_resolver=None` (no session
module wired yet, same as `app.py`'s current `make_audit_router(ctx.audit)`
call) degrades to `501`, not to "allow anyone" — there is a difference
between "no session-verification module exists yet" and "this caller is
unauthenticated", and only the resolver can tell those apart (mirrors
`api/audit.py`'s own docstring on this point).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from candleviewer.ingestion.kline_coverage import CoverageIndex, Range
from candleviewer.ingestion.kline_read import SOURCE_HOT, KlineReadService
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import TierHint, TimeRange

_REQUIRED_PERMISSION = "marketdata:read"

_MAX_LIMIT = 5000
_DEFAULT_LIMIT = 1000

#: exchange-compatible interval codes, mirrors `22-api-openapi.yaml`'s
#: `KlineInterval` enum — kept as a plain tuple (not an import from
#: `exchange.base`) so this router never needs an edge into `exchange.*`.
_MIN_US = 60_000_000
#: Bar width per interval for the window cap; `M` uses 31 days (its longest month).
_INTERVAL_US: dict[str, int] = {
    **{c: int(c) * _MIN_US for c in ("1", "3", "5", "15", "30", "60", "120", "240", "360", "720")},
    "D": 1440 * _MIN_US,
    "W": 7 * 1440 * _MIN_US,
    "M": 31 * 1440 * _MIN_US,
}
_VALID_INTERVALS = (
    "1",
    "3",
    "5",
    "15",
    "30",
    "60",
    "120",
    "240",
    "360",
    "720",
    "D",
    "W",
    "M",
)


@dataclass(frozen=True, slots=True)
class MarketDataPrincipal:
    """The authenticated caller, as resolved server-side from the session
    (mirrors `audit.access.AuditPrincipal` — the audit and market-data
    surfaces share the same session concept but not the same permission
    vocabulary, so this router keeps its own small principal type rather
    than importing `audit`'s)."""

    user_id: str
    permissions: frozenset[str]

    def has(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions  # nosem: no-adhoc-authz reason=Principal.has_permission-wildcard-impl-pending-E09-T01-authorize owner=@CandleViewer/security review=2026-12-31  # noqa: E501  # fmt: skip


class PrincipalResolver(Protocol):
    """Resolves the authenticated caller for a `/market/klines` request.

    Structurally typed so this router never imports a concrete session
    module; the composition root injects the real implementation once one
    exists. Returning `None` means "no verified session" (401) — mirrors
    `api/audit.py`'s own `PrincipalResolver`, including the distinction
    between a resolver that found no session (401) and no resolver being
    wired at all (501, see `_authorize_or_raise` below)."""

    def resolve(self, request: Request) -> MarketDataPrincipal | None: ...


class CoverageIndexProvider(Protocol):
    """`Callable[[str, str], CoverageIndex | None]` — declared as a Protocol
    (not a bare `object`) so the router's own strict typing covers this
    parameter the same way it covers `MarketDataCacheLike` and
    `PrincipalResolver`, instead of relying on a runtime `isinstance` check
    against the return value."""

    def __call__(self, symbol: str, interval: str) -> CoverageIndex | None: ...


class KlineRowLike(Protocol):
    """The subset of `storage.repositories.rows.KlineRow` this router
    reads back and serialises — declared structurally (mirrors
    `ingestion.kline_backfill.KlineRowLike`) so this module only needs the
    fields it actually renders."""

    @property
    def ts_us(self) -> int: ...
    @property
    def open(self) -> str: ...
    @property
    def high(self) -> str: ...
    @property
    def low(self) -> str: ...
    @property
    def close(self) -> str: ...
    @property
    def volume(self) -> str: ...
    @property
    def turnover(self) -> str: ...
    @property
    def confirmed(self) -> bool: ...


class MarketDataCacheLike(Protocol):
    """Structural type for `storage.repositories.market_data.
    MarketDataRepository.read_klines` — the composition root injects the
    real `ctx.storage.market_data` (or a test fake)."""

    async def read_klines(
        self,
        sym: str,
        interval: str,
        rng: TimeRange,
        tier: TierHint = "auto",
        limit: int | None = None,
    ) -> Sequence[KlineRowLike]: ...


def _problem(status_code: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"type": "about:blank", "title": title, "status": status_code, "detail": detail},
        media_type="application/problem+json",
    )


def _parse_time(value: str | None, *, default: datetime | None) -> datetime | None:
    if value is None:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _iso(ts_us: int) -> str:
    return datetime.fromtimestamp(ts_us / 1_000_000, tz=UTC).isoformat()


def _row_to_bar(row: KlineRowLike) -> dict[str, object]:
    return {
        "t": _iso(row.ts_us),
        "o": row.open,
        "h": row.high,
        "l": row.low,
        "c": row.close,
        "v": row.volume,
        "turnover": row.turnover,
        "confirm": row.confirmed,
    }


def make_market_router(
    cache_provider: Callable[[], MarketDataCacheLike | None],
    *,
    coverage_index_provider: CoverageIndexProvider | None = None,
    principal_resolver: PrincipalResolver | None = None,
    read_service_provider: Callable[[], KlineReadService | None] | None = None,
    symbol_listed: Callable[[str], bool] | None = None,
) -> APIRouter:
    """Bind `GET /market/klines` to a concrete cache reader.

    `cache_provider` is called once per request (not once at router
    construction) because `create_app()` builds this router before the
    ASGI lifespan runs `storage.start()` (`app.py`'s own docstring: "the
    module supervisor is *not* started here") — `ctx.storage.market_data`
    raises `StorageTierUnavailable` until then, so a request arriving
    before startup finishes must still get a clean `503`, not an
    unhandled exception. A provider returning `None` (mirrors
    `make_audit_router`'s own `audit_service=None` default) also degrades
    to `503` rather than raising at import time, so `create_app()` stays
    constructible with fakes only. `coverage_index_provider` is an
    optional `Callable[[str, str], CoverageIndex | None]` used only to
    compute the `meta.coverage_holes` diagnostic (never required for
    correctness of the returned bars) — the fake/default storage backend
    has no coverage tracking of its own, so a request against it simply
    reports an empty hole list.

    `principal_resolver=None` (no session-verification module wired yet,
    same posture as `make_audit_router`'s own default) makes every request
    fail closed with `501` rather than silently serving unauthenticated
    reads (C-12.4, PR #1626 review) — RBAC on this route ("marketdata:read")
    is enforced here, server-side, never left to the UI to hide a button.

    E12-S05: when `read_service_provider` yields a `KlineReadService`, reads go through it
    (cold + hot tiers merged; exchange backfill started in the background for hot holes and
    never awaited) and `meta.sources` / `meta.recording_started_at` come from it.

    SR-E12-08 (#2045 security review): a read that can start an exchange backfill is only
    served for a symbol `symbol_listed` accepts (instrument catalogue); an unknown symbol is
    `422` (declared by the route) before any read, job or per-key state. With a read service
    but no catalogue check wired, the route fails closed (`503`). The window may span at
    most `limit` bars (`422`), and `limit` is pushed into the hot-tier query.
    """
    router = APIRouter(tags=["market-data"])

    class _HttpProblem(Exception):
        def __init__(self, response: JSONResponse) -> None:
            self.response = response

    def _authorize_or_raise(request: Request) -> None:
        if principal_resolver is None:
            raise _HttpProblem(
                _problem(
                    501,
                    "Not implemented",
                    "no principal resolver wired — session verification is out of this "
                    "ticket's scope",
                )
            )
        principal = principal_resolver.resolve(request)
        if principal is None:
            raise _HttpProblem(
                _problem(401, "Unauthorized", "no verified session for this request")
            )
        if not principal.has(_REQUIRED_PERMISSION):
            raise _HttpProblem(_problem(403, "Forbidden", f"requires {_REQUIRED_PERMISSION}"))

    @router.get("/market/klines")
    async def get_klines(
        request: Request,
        symbol: str,
        interval: str,
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None, alias="to"),
        limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
        price_type: str = Query(default="trade"),
        include_open: bool = Query(default=False),
        include_delta: bool = Query(default=False),
    ) -> JSONResponse:
        try:
            _authorize_or_raise(request)
        except _HttpProblem as problem:
            return problem.response
        try:
            cache = cache_provider()
        except StorageTierUnavailable:
            cache = None
        if cache is None:
            return _problem(503, "Service unavailable", "market-data cache is not wired")
        if interval not in _VALID_INTERVALS:
            return _problem(400, "Bad request", f"unsupported interval {interval!r}")
        try:
            end_dt = _parse_time(to, default=datetime.now(UTC))
            start_dt = _parse_time(from_, default=None)
        except ValueError as exc:
            return _problem(400, "Bad request", f"invalid from/to timestamp: {exc}")
        if end_dt is None:
            return _problem(400, "Bad request", "invalid 'to' timestamp")
        if start_dt is None:
            return _problem(400, "Bad request", "'from' is required")
        if start_dt > end_dt:
            return _problem(400, "Bad request", "'from' must be <= 'to'")

        # Server-side bound on the requested range (security notes: "an
        # authenticated user cannot request an unbounded range and force a
        # large ... database scan") — `limit` already caps rows returned;
        # this additionally caps how far back a single call may scan.
        rng = TimeRange(
            start_us=int(start_dt.timestamp() * 1_000_000),
            end_us=int(end_dt.timestamp() * 1_000_000),
        )
        if rng.end_us - rng.start_us > limit * _INTERVAL_US[interval]:
            return _problem(
                422, "Unprocessable entity", "the from/to window spans more than 'limit' bars"
            )
        service = read_service_provider() if read_service_provider is not None else None
        if service is not None and symbol_listed is None:
            return _problem(503, "Service unavailable", "instrument catalogue is not wired")
        if symbol_listed is not None and not symbol_listed(symbol):
            # 422, not 404: the only client-error statuses this route declares are 400/422.
            return _problem(422, "Unprocessable entity", "unknown instrument")
        recording_started: str | None = None
        rows: list[KlineRowLike]
        if service is not None:
            # +1: room for the forming bar, which `include_open=false` drops below.
            try:
                read = await service.read(
                    symbol, interval, Range(rng.start_us, rng.end_us), limit=limit + 1
                )
            except StorageTierUnavailable:  # e.g. cold-tier DuckDB timeout: typed 503, not 500
                return _problem(503, "Service unavailable", "kline storage tier unavailable")
            rows = list[KlineRowLike](read.rows)
            sources = read.sources
            if read.recording_started_at_us is not None:
                recording_started = _iso(read.recording_started_at_us)
        else:
            rows = list(await cache.read_klines(symbol, interval, rng, limit=limit + 1))
            sources = [SOURCE_HOT] if rows else []
        if not include_open:
            rows = [r for r in rows if r.confirmed]
        rows = rows[-limit:]  # newest `limit` (the window cap makes this the whole window)

        holes: list[dict[str, int]] = []
        if coverage_index_provider is not None:
            index = coverage_index_provider(symbol, interval)
            if isinstance(index, CoverageIndex):
                cov_range = Range(rng.start_us, rng.end_us)
                holes = [
                    {"start_us": h.start_us, "end_us": h.end_us} for h in index.holes(cov_range)
                ]

        body = {
            "symbol": symbol,
            "interval": interval,
            "bar_type": "time",
            "bars": [_row_to_bar(r) for r in rows],
            "meta": {
                "next_cursor": None,
                "has_more": False,
                "count": len(rows),
                "sources": sources,
                "recording_started_at": recording_started,
                "generated_at": datetime.now(UTC).isoformat(),
                "coverage_holes": holes,
            },
        }
        return JSONResponse(status_code=200, content=body)

    return router


__all__ = [
    "CoverageIndexProvider",
    "MarketDataCacheLike",
    "MarketDataPrincipal",
    "PrincipalResolver",
    "make_market_router",
]
