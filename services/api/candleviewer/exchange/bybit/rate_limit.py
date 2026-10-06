"""Per-UID token bucket for the Bybit REST client (E08-T02 "Rate budget is
shared per UID" scenario; `docs/plan/24-internal-schemas.md` §14.3/§8.7).

One bucket is keyed by `(uid, endpoint_class)` because Bybit's budgets
differ per endpoint family (technical notes: "`ExchangeCapabilities.
order_rate_per_uid_per_s` is a dict"). All callers sharing a UID — even
across different API keys — draw from the same bucket, which is what makes
the per-UID limit enforceable at all (ticket Context paragraph).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from candleviewer.exchange.bybit.config import EndpointClass


class _Bucket:
    """A single leaky/token bucket. Not thread-safe across event loops —
    the REST client owns exactly one asyncio loop per process, per C-2.2."""

    __slots__ = ("capacity", "lock", "refill_per_s", "tokens", "updated_at")

    def __init__(self, capacity: float, refill_per_s: float, *, now: float) -> None:
        self.capacity = capacity
        self.tokens = capacity
        self.refill_per_s = refill_per_s
        self.updated_at = now
        self.lock = asyncio.Lock()

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_s)
        self.updated_at = now


class TokenBucketGovernor:
    """Owns one bucket per `(uid, endpoint_class)` and one IP-wide bucket.

    `acquire` blocks (cooperatively, via `asyncio.sleep`) until a token is
    available rather than raising — the budget is *shaped*, never silently
    exceeded (acceptance criterion 2). `drain` is called by the client after
    a `10018`/rate-limited response to account for exchange-side budget
    consumption the client did not itself schedule (acceptance criterion 3).
    """

    def __init__(
        self,
        *,
        default_capacity: float = 10.0,
        default_refill_per_s: float = 5.0,
        ip_budget_per_5s: int = 600,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._sleep = sleep
        self._ip_hold_until: float = 0.0
        self._default_capacity = default_capacity
        self._default_refill_per_s = default_refill_per_s
        self._buckets: dict[tuple[str, EndpointClass], _Bucket] = {}
        self._now: Callable[[], float] = clock if clock is not None else time.monotonic
        ip_refill = ip_budget_per_5s / 5.0
        self._ip_bucket = _Bucket(float(ip_budget_per_5s), ip_refill, now=self._now())

    def _get_bucket(self, uid: str, endpoint_class: EndpointClass) -> _Bucket:
        key = (uid, endpoint_class)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(
                self._default_capacity,
                self._default_refill_per_s,
                now=self._now(),
            )
            self._buckets[key] = bucket
        return bucket

    async def acquire(self, uid: str, endpoint_class: EndpointClass) -> None:
        """Wait until both the per-UID/endpoint-class bucket and the
        IP-wide bucket have a spare token, then consume one from each."""
        await self._wait_ip_hold()
        bucket = self._get_bucket(uid, endpoint_class)
        for target in (bucket, self._ip_bucket):
            async with target.lock:
                while True:
                    now = self._now()
                    target._refill(now)
                    if target.tokens >= 1.0:
                        target.tokens -= 1.0
                        break
                    deficit = 1.0 - target.tokens
                    wait_s = deficit / target.refill_per_s if target.refill_per_s > 0 else 0.05
                    await asyncio.sleep(min(wait_s, 1.0))

    async def acquire_ip_only(self) -> None:
        """Wait for a spare token on the IP-wide bucket only, without
        touching any per-UID/endpoint-class bucket. Used by unauthenticated,
        unbudgeted-by-endpoint-class calls (e.g. the startup reachability
        probe) that must still respect the IP-wide ceiling (C-12.7)."""
        await self._wait_ip_hold()
        target = self._ip_bucket
        async with target.lock:
            while True:
                now = self._now()
                target._refill(now)
                if target.tokens >= 1.0:
                    target.tokens -= 1.0
                    return
                deficit = 1.0 - target.tokens
                wait_s = deficit / target.refill_per_s if target.refill_per_s > 0 else 0.05
                await asyncio.sleep(min(wait_s, 1.0))

    def hold_ip(self, duration_s: float) -> None:
        """Throttle every caller (all UIDs, all endpoint classes) for at least
        `duration_s` from now (`24-internal-schemas.md` §8.6, `10018`: IP-level
        backoff, all accounts throttled). Holds only ever extend, never shorten."""
        self._ip_hold_until = max(self._ip_hold_until, self._now() + max(0.0, duration_s))

    def ip_hold_remaining_s(self) -> float:
        return max(0.0, self._ip_hold_until - self._now())

    async def _wait_ip_hold(self) -> None:
        while (remaining := self.ip_hold_remaining_s()) > 0.0:
            await self._sleep(remaining)

    def remaining(self, uid: str, endpoint_class: EndpointClass) -> float:
        bucket = self._get_bucket(uid, endpoint_class)
        bucket._refill(self._now())
        return bucket.tokens

    def observe_header(self, uid: str, endpoint_class: EndpointClass, remaining: int) -> None:
        """Feed `X-Bapi-Limit-Status` back into the local bucket so a
        server-side view of the budget wins over our own accounting drift
        (technical notes: "fed back from `X-Bapi-Limit-Status` / `X-Bapi-
        Limit` response headers")."""
        bucket = self._get_bucket(uid, endpoint_class)
        bucket._refill(self._now())
        bucket.tokens = min(bucket.capacity, float(remaining))

    def drain(self, uid: str, endpoint_class: EndpointClass, amount: float) -> None:
        """Account for budget consumed server-side that a `RateLimitError`
        response reports (acceptance criterion 3: "the bucket is drained by
        the advertised amount")."""
        bucket = self._get_bucket(uid, endpoint_class)
        bucket._refill(self._now())
        bucket.tokens = max(0.0, bucket.tokens - amount)
