"""`GET /market/data-coverage` (E16-T04; 22-api `getDataCoverage`, schema `DataCoverage`).

RBAC server-side (`marketdata:read`, C-12.4): no resolver wired -> 501, no session -> 401,
missing permission -> 403. The contract has no window parameters, so the report spans the
symbol's whole recorded history up to now. Gaps carry the contract's closed `reason` enum
(`recorder.coverage.GAP_REASON`); backfilled (kline) gaps stay listed — bars-derived data
never makes a tick window covered. `rows` is omitted (optional; needs QuestDB partition
metadata, not wired).
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Annotated, Any, Final, Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api.market_response import iso_us, problem
from candleviewer.recorder.coverage import GAP_REASON, CoverageService
from candleviewer.recorder.sessions import DEFAULT_STREAMS

_REQUIRED_PERMISSION: Final = "marketdata:read"
_SYMBOL: Final = re.compile(r"^[A-Z0-9]{2,20}USDT$")
_STREAMS: Final = frozenset(
    {
        "trades",
        "orderbook_delta",
        "orderbook_snapshot",
        "tickers",
        "klines",
        "liquidations",
        "open_interest",
        "funding",
    }
)


class _Resolver(Protocol):
    """Structural, like `market_bars._Resolver` (the composition root injects the real one)."""

    def resolve(self, request: Request) -> Any: ...


def _z(us: int) -> str:
    return iso_us(us).replace("+00:00", "Z")


def make_data_coverage_router(
    service_provider: Callable[[], CoverageService | None],
    *,
    principal_resolver: _Resolver | None = None,
    now_us: Callable[[], int],
) -> APIRouter:
    router = APIRouter(tags=["market-data"])

    @router.get("/market/data-coverage")
    async def get_data_coverage(
        request: Request,
        symbol: str,
        stream: Annotated[list[str] | None, Query()] = None,
    ) -> Response:
        if principal_resolver is None:
            return problem(501, "internal_error", "Not implemented",
                           "Session verification is not wired yet.")  # fmt: skip
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return problem(401, "unauthenticated", "Unauthorized", "Sign in to read market data.")
        if not principal.has(_REQUIRED_PERMISSION):
            return problem(403, "forbidden", "Forbidden",
                           f"Reading market data requires {_REQUIRED_PERMISSION}.")  # fmt: skip
        if not _SYMBOL.fullmatch(symbol):
            return problem(400, "validation_failed", "Bad request", "Invalid symbol.")
        streams = list(dict.fromkeys(stream or DEFAULT_STREAMS))
        if any(s not in _STREAMS for s in streams):
            return problem(400, "validation_failed", "Bad request", "Unknown stream kind.")
        service = service_provider()
        if service is None:
            return problem(503, "store_unavailable", "Service unavailable",
                           "Recording metadata is not available yet; retry shortly.")  # fmt: skip
        now = now_us()
        try:
            report = await service.coverage(symbol, streams, 0, now)
        except (TimeoutError, OSError):
            return problem(503, "store_unavailable", "Service unavailable",
                           "Recording metadata is not available yet; retry shortly.")  # fmt: skip
        body = {
            "symbol": symbol,
            "streams": [
                {
                    "stream": sc.stream,
                    "intervals": [
                        {"from": _z(i.lo), "to": _z(i.hi), "tier": i.tier} for i in sc.intervals
                    ],
                    "gaps": [
                        {
                            "from": _z(g.lo),
                            "to": _z(g.hi),
                            "reason": GAP_REASON.get(g.cause, "ws_disconnect"),
                        }
                        for g in sc.gaps
                    ],
                }
                for sc in report
            ],
            "generated_at": _z(now),
        }
        return JSONResponse(body)

    return router
