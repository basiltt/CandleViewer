"""Bybit v5 REST client (`docs/plan/24-internal-schemas.md` §14.3; ticket
body "Scope / Deliverables").

One `httpx.AsyncClient` per `BybitRestClient` instance, explicit connection
pool and timeouts (technical notes: "no global default timeouts"). Signing,
per-UID token-bucket shaping, retry-with-jitter and retCode mapping all live
here so every consumer — instrument catalogue, kline backfill, and later
the OMS order path (E29) — goes through one governed choke point (ticket
Context paragraph).

Out of scope (ticket body): WebSocket transport, any authenticated trading
call wired to live keys, key storage/encryption.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx
import structlog

from candleviewer.exchange.base.boundary import exchange_errors_total
from candleviewer.exchange.base.errors import (
    ClockDriftError,
    RateLimitError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.exchange.bybit.metrics import (
    bybit_rate_limit_remaining,
    bybit_rate_limited_total,
    bybit_rest_latency_seconds,
    bybit_rest_requests_total,
)
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.signer import BybitSigner

logger = structlog.get_logger(__name__)

#: Header/field name fragments that must never reach a log line, verbatim or
#: via a nested dict repr (ticket scenario "Secrets never reach a log or a
#: fixture"). Matched case-insensitively against header/query-param keys.
_SECRET_KEY_MARKERS = ("api_key", "api-key", "sign", "secret", "authorization")

_REDACTED = "**redacted**"

ClockOffsetProvider = Callable[[], Awaitable[int]] | Callable[[], int]
"""Returns the current clock offset in milliseconds, injected by the caller
(E08-S07 owns measurement; this client only *applies* it, per the ticket's
technical notes: "The clock offset is injected, not read from a global")."""


def _redact(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of `mapping` with any secret-shaped key's value
    replaced by a fixed placeholder — used before anything is logged."""
    out: dict[str, Any] = {}
    for key, value in mapping.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
            out[key] = _REDACTED
        else:
            out[key] = value
    return out


class _Clock:
    """Injected wall-clock + offset, so timestamps are testable and the
    offset can be re-measured without this client owning a global."""

    def __init__(self, offset_ms_provider: ClockOffsetProvider | None) -> None:
        self._offset_ms_provider = offset_ms_provider

    async def now_ms(self) -> int:
        base = int(time.time() * 1000)
        if self._offset_ms_provider is None:
            return base
        result = self._offset_ms_provider()
        offset = await result if asyncio.iscoroutine(result) else result
        return base + int(offset)  # type: ignore[arg-type]


class BybitRestClient:
    """Governed REST transport for one `(exchange, environment)` pair.

    Public (unauthenticated) calls work with `signer=None`; the signed path
    (`signed_request`) requires a `BybitSigner`. Every request is shaped by
    the shared per-UID token bucket, retried per the taxonomy's `retryable`
    flag with full jitter, and logged with secrets redacted.
    """

    def __init__(
        self,
        config: RestClientConfig,
        *,
        uid: str = "public",
        signer: BybitSigner | None = None,
        governor: TokenBucketGovernor | None = None,
        clock_offset_ms_provider: ClockOffsetProvider | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        self._config = config
        self._uid = uid
        self._signer = signer
        self._governor = (
            governor
            if governor is not None
            else TokenBucketGovernor(ip_budget_per_5s=config.ip_budget_per_5s)
        )
        self._clock = _Clock(clock_offset_ms_provider)
        self._sleep = sleep
        self._random = random_fn
        timeout = httpx.Timeout(config.total_timeout_s, connect=config.connect_timeout_s)
        limits = httpx.Limits(
            max_connections=config.max_connections,
            max_keepalive_connections=config.max_keepalive_connections,
        )
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=timeout,
            limits=limits,
            transport=transport,
        )

    async def check_reachable(self) -> bool:
        """Startup reachability probe for the configured `base_url` (ticket
        brief: "startup reachability check for the configured base URL").
        Calls the unauthenticated, unbudgeted server-time endpoint once and
        returns `True`/`False` rather than raising, so a caller can decide
        policy (retry, alert, refuse to start) without this client owning
        that decision."""
        try:
            await self._governor.acquire_ip_only()
            await self._client.request(
                "GET", "/v5/market/time", timeout=self._config.connect_timeout_s
            )
            return True
        except (TimeoutError, httpx.TransportError):
            return False

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> BybitRestClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def get_public(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        endpoint_class: EndpointClass = EndpointClass.MARKET_DATA,
    ) -> dict[str, Any]:
        """Unauthenticated `GET` — instrument catalogue, kline, server time."""
        return await self._request(
            "GET", path, params=params, body=None, endpoint_class=endpoint_class, signed=False
        )

    async def signed_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        endpoint_class: EndpointClass = EndpointClass.ACCOUNT,
    ) -> dict[str, Any]:
        """Authenticated request. Raises `TypeError` if no signer was
        configured — a signed call is never silently downgraded to public.

        A POST/PUT to `EndpointClass.ORDER` **must** carry `orderLinkId` in
        `body`: this client retries signed POSTs on transport errors and
        5xx automatically, and that is only safe for order placement when
        every attempt reuses the same client-generated id (C-2.10) so a
        duplicate is recognised as "already accepted" rather than
        resubmitted under a new id. This is enforced here, not merely
        documented, because a future OMS caller forgetting it would
        silently double-submit orders on a retried timeout."""
        if self._signer is None:
            raise TypeError("signed_request called without a configured BybitSigner")
        if (
            endpoint_class is EndpointClass.ORDER
            and method.upper() in ("POST", "PUT")
            and not (body and body.get("orderLinkId"))
        ):
            raise ValueError(
                "signed_request: ORDER-class POST/PUT requires a non-empty "
                "'orderLinkId' in body — this client retries automatically "
                "and retries without a stable client id can double-submit "
                "orders (C-2.10)"
            )
        return await self._request(
            method, path, params=params, body=body, endpoint_class=endpoint_class, signed=True
        )

    def _query_params(self, params: Mapping[str, Any] | None) -> httpx.QueryParams | None:
        if not params:
            return None
        return httpx.QueryParams(params)

    def _payload_string(
        self,
        method: str,
        query: httpx.QueryParams | None,
        body: Any,
    ) -> str:
        if method.upper() in ("GET", "DELETE"):
            if not query:
                return ""
            # Sign the exact wire-encoded query string (Bybit v5 signing spec:
            # the signature covers the URL-encoded query, not the raw repr of
            # the params mapping) so a value needing encoding — spaces,
            # `&`/`=`/unicode — can never desync the signature from what
            # httpx actually sends and trigger a spurious 10004.
            return str(query)
        return body if isinstance(body, str) else ("" if body is None else _json_dumps(body))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        body: Mapping[str, Any] | None,
        endpoint_class: EndpointClass,
        signed: bool,
    ) -> dict[str, Any]:
        attempt = 0
        clock_retry_used = False
        while True:
            attempt += 1
            await self._governor.acquire(self._uid, endpoint_class)
            headers: dict[str, str] = {}
            query = self._query_params(params)
            payload_str = self._payload_string(method, query, body)
            if signed:
                if self._signer is None:
                    raise TypeError("signed request reached _request without a signer")
                timestamp_ms = await self._clock.now_ms()
                signature = self._signer.sign(
                    timestamp_ms=timestamp_ms,
                    recv_window_ms=self._config.recv_window_ms,
                    payload=payload_str,
                )
                headers.update(
                    {
                        "X-BAPI-API-KEY": self._signer.api_key,
                        "X-BAPI-TIMESTAMP": str(timestamp_ms),
                        "X-BAPI-RECV-WINDOW": str(self._config.recv_window_ms),
                        "X-BAPI-SIGN": signature,
                    }
                )
            if method.upper() in ("POST", "PUT"):
                headers["Content-Type"] = "application/json"

            logger.debug(
                "bybit_rest_request",
                method=method,
                path=path,
                attempt=attempt,
                endpoint_class=str(endpoint_class),
                headers=_redact(headers),
                params=_redact(params or {}),
            )

            start = time.monotonic()
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=query if method.upper() in ("GET", "DELETE") else None,
                    content=payload_str if method.upper() in ("POST", "PUT") else None,
                    headers=headers,
                )
            except (TimeoutError, httpx.TransportError) as exc:
                bybit_rest_requests_total.labels(endpoint=path, result="transport_error").inc()
                if attempt > self._config.max_retries:
                    raise TransportError(f"transport error calling {path}: {exc}") from exc
                await self._backoff(attempt)
                continue
            finally:
                bybit_rest_latency_seconds.labels(endpoint=path).observe(time.monotonic() - start)

            self._observe_rate_headers(response, endpoint_class)

            if response.status_code >= 500:
                bybit_rest_requests_total.labels(endpoint=path, result="5xx").inc()
                if attempt > self._config.max_retries:
                    raise TransportError(
                        f"{path} returned HTTP {response.status_code} after {attempt} attempts"
                    )
                await self._backoff(attempt)
                continue

            is_http_error = response.status_code >= 400
            if is_http_error:
                bybit_rest_requests_total.labels(endpoint=path, result="4xx").inc()

            try:
                data = response.json()
            except ValueError as exc:
                bybit_rest_requests_total.labels(endpoint=path, result="error").inc()
                exchange_errors_total.labels(**{"class": UnknownStateError.code.value}).inc()
                raise UnknownStateError(
                    f"{path} returned HTTP {response.status_code} with a non-JSON body: {exc}"
                ) from exc

            # A missing `retCode`, or `retCode == 0` on an HTTP error status,
            # is never treated as success — the raw body defaulted `retCode`
            # to 0 previously, which failed open on a 4xx with an unusual
            # body (review finding). HTTP status is now load-bearing.
            has_ret_code = "retCode" in data
            ret_code = int(data["retCode"]) if has_ret_code else -1
            if not has_ret_code or (is_http_error and ret_code == 0):
                bybit_rest_requests_total.labels(endpoint=path, result="error").inc()
                exchange_errors_total.labels(**{"class": UnknownStateError.code.value}).inc()
                raise UnknownStateError(
                    f"{path} returned HTTP {response.status_code} with no usable retCode: {data!r}"
                )
            if ret_code == 0:
                bybit_rest_requests_total.labels(endpoint=path, result="ok").inc()
                return dict(data)

            ret_msg = str(data.get("retMsg", ""))
            error = map_ret_code(ret_code, ret_msg)
            exchange_errors_total.labels(**{"class": error.code.value}).inc()

            if isinstance(error, ClockDriftError) and not clock_retry_used:
                clock_retry_used = True
                bybit_rest_requests_total.labels(endpoint=path, result="clock_drift").inc()
                # Caller-injected offset provider is responsible for the
                # actual re-measurement; we simply retry once with whatever
                # it now returns (ticket scenario "Clock error self-heals
                # once").
                continue

            if isinstance(error, RateLimitError):
                bybit_rate_limited_total.labels(code=str(ret_code)).inc()
                bybit_rest_requests_total.labels(endpoint=path, result="rate_limited").inc()
                self._account_for_rate_limit(response, endpoint_class)
                if error.retryable and attempt <= self._config.max_retries:
                    retry_after = error.retry_after_s or self._retry_after_default(attempt)
                    await self._sleep(retry_after)
                    continue
                raise error

            bybit_rest_requests_total.labels(endpoint=path, result="error").inc()
            raise error

    def _observe_rate_headers(
        self, response: httpx.Response, endpoint_class: EndpointClass
    ) -> None:
        remaining_header = response.headers.get("X-Bapi-Limit-Status")
        if remaining_header is None:
            return
        try:
            remaining = int(remaining_header)
        except ValueError:
            return
        self._governor.observe_header(self._uid, endpoint_class, remaining)
        # E08-T06 security note: never a UID label (account identifier) - scope only.
        scope = "public" if self._uid == "public" else "account"
        bybit_rate_limit_remaining.labels(scope=scope, endpoint_class=str(endpoint_class)).set(
            remaining
        )

    def _account_for_rate_limit(
        self, response: httpx.Response, endpoint_class: EndpointClass
    ) -> None:
        """Reconcile the local bucket after a rate-limited response.

        `X-Bapi-Limit-Status` is the *remaining* budget, not the amount
        consumed (review finding: draining by that header's value drained
        the wrong quantity). `_observe_rate_headers` — called unconditionally
        on every response, above — already sets the bucket's `tokens` to
        that remaining value directly whenever the header is present, which
        is the correct reconciliation. When the header is absent we still
        know *some* budget was just consumed server-side that our own
        accounting did not schedule, so fall back to draining one token as a
        conservative, documented default (acceptance criterion 3's "drained
        by the advertised amount" only applies when an amount is
        advertised)."""
        if response.headers.get("X-Bapi-Limit-Status") is not None:
            return
        self._governor.drain(self._uid, endpoint_class, 1.0)

    def _retry_after_default(self, attempt: int) -> float:
        base = min(2.0**attempt, 30.0)
        return base * (0.5 + self._random() * 0.5)

    async def _backoff(self, attempt: int) -> None:
        await self._sleep(self._retry_after_default(attempt))


def _json_dumps(body: Mapping[str, Any]) -> str:
    import json

    return json.dumps(body, separators=(",", ":"), sort_keys=True)


async def paginate_cursor(
    fetch_page: Callable[[str | None], Awaitable[tuple[list[dict[str, Any]], str | None]]],
) -> list[dict[str, Any]]:
    """Generic cursor-pagination helper (ticket deliverable "Cursor
    pagination helper"). `fetch_page(cursor)` returns `(rows, next_cursor)`;
    pagination stops when `next_cursor` is falsy."""
    all_rows: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        rows, cursor = await fetch_page(cursor)
        all_rows.extend(rows)
        if not cursor:
            return all_rows


async def paginate_klines(
    fetch_range: Callable[[int, int], Awaitable[list[dict[str, Any]]]],
    *,
    start_ms: int,
    end_ms: int,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Kline-specific paging helper (ticket deliverable "the kline 1 000-row
    limit paging helper"). Bybit returns at most `limit` rows per call,
    newest-first within the window; this walks the window backwards from
    `end_ms` until `start_ms` is covered or a page returns no rows. Both bounds
    are inclusive (Bybit semantics), so `start_ms == end_ms` is a one-bar window;
    only `start_ms > end_ms` is empty."""
    all_rows: list[dict[str, Any]] = []
    window_end = end_ms
    while window_end >= start_ms:
        page = await fetch_range(start_ms, window_end)
        if not page:
            break
        all_rows.extend(page)
        oldest_ts = min(int(row["start"]) for row in page if "start" in row)
        if oldest_ts <= start_ms or len(page) < limit:
            break
        window_end = oldest_ts - 1
    return all_rows
