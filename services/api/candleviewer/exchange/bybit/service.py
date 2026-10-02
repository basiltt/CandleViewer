"""Lifecycle contract for the exchange.bybit module (M4).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.exchange.bybit.public_ws import (
    PublicSocket,
    public_socket_factory,
    topic_kind,
)
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic
from candleviewer.exchange.bybit.trades import (
    parse_trade_frame,
    recent_trades_fetcher,
    trade_topic,
)
from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext


class ExchangeBybitService:
    """Empty scaffold for the M4 `exchange.bybit` module lifecycle."""

    def __init__(self) -> None:
        self._started = False

    #: E08-T04: venue topic -> neutral stream kind, for ingestion's watchdog.
    topic_kind = staticmethod(topic_kind)
    #: E08-S03: ticker topic naming + frame parser, injected into ingestion.
    ticker_topic = staticmethod(ticker_topic)
    parse_ticker_frame = staticmethod(parse_ticker_frame)
    #: E08-S04: tape topic naming, frame parser and REST gap-backfill fetcher.
    trade_topic = staticmethod(trade_topic)
    parse_trade_frame = staticmethod(parse_trade_frame)
    recent_trades_fetcher = staticmethod(recent_trades_fetcher)

    #: E08-S05: order-book topic naming + frame parser.
    book_topic = staticmethod(book_topic)
    parse_book_frame = staticmethod(parse_book_frame)

    @staticmethod
    def public_socket_factory(
        env: str, *, max_frame_bytes: int
    ) -> Callable[[], Awaitable[PublicSocket]]:
        """E08-T04: unauthenticated public-stream socket factory for `env`."""
        return public_socket_factory(env, max_frame_bytes=max_frame_bytes)

    @staticmethod
    def public_rest_client(env: str) -> BybitRestClient:
        """E04-T06: credential-less public REST client (server-time probe).
        Public data always uses the live host (demo has no public feed)."""
        base = "https://api-testnet.bybit.com" if env == "testnet" else "https://api.bybit.com"
        return BybitRestClient(RestClientConfig(base_url=base))

    async def start(self, ctx: AppContext) -> None:
        """Start the module. No-op until the owning epic implements it."""
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. No-op scaffold."""
        self._started = False

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="", status=status, detail="scaffold module — no real logic yet")
