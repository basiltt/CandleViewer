"""`BookEngine` + resync discipline for one `(env, symbol, depth)` (E08-S05).

Hot path stays plain code (INV-B14-a): `on_event` applies deltas directly.
The B14 `book` chart only *supervises* the lifecycle; it is driven through
the injected `Supervisor` (built by the wiring layer via
`statechart.factory.build("book", ...)`, because hot-path modules never import
the statechart package - CV-LINT-HOTPATH). The chart's entry actions call
back into this engine (`request_snapshot`, `go_live`, `go_desynced`), which
publishes the phase as a plain enum (INV-B14-b). Desync is *enforced*
synchronously here before the chart is told (C-2.21).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Awaitable, Callable
from typing import Protocol

from candleviewer.book.errors import BookError, BookInvariantError
from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.book.state import BookState
from candleviewer.exchange.base.models import BookDelta, BookSnapshot

#: INV-B14-d: deltas buffered while a snapshot is in flight are bounded.
BUFFER_BOUND = 1_000
#: Security note: >5 resyncs in 60 s trips the breaker -> `degraded`.
BREAKER_MAX, BREAKER_WINDOW_US = 5, 60_000_000

Publish = Callable[[object], Awaitable[None]]


class Supervisor(Protocol):
    async def send(self, event: str) -> None: ...


class BookEngine:
    def __init__(
        self,
        *,
        symbol: str,
        depth: int,
        publish: Publish,
        resubscribe: Callable[[], Awaitable[None]],
        now_us: Callable[[], int],
    ) -> None:
        self.symbol, self.depth = symbol, depth
        self.phase = BookPhase.INIT
        self.book: BookState | None = None
        self.muted = False  # tier warm-up: build to LIVE without publishing
        self.resync_count = 0
        self.degraded = False
        self.last_u = 0
        self.last_good_ts_us: int | None = None
        self.supervisor: Supervisor | None = None
        self._publish, self._resubscribe, self._now = publish, resubscribe, now_us
        self._buffer: deque[BookDelta] = deque()
        self._staged: BookSnapshot | None = None
        self._template: BookSnapshot | None = None
        self._resync_times: deque[int] = deque()
        self._pending_since: int | None = None
        self._reason = "subscribe"

    # ---- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        if self.supervisor is not None:
            await self.supervisor.send("SUBSCRIBE")
        else:
            await self.request_snapshot()

    async def on_event(self, ev: BookSnapshot | BookDelta) -> None:
        """Hot path. Never touches an interpreter for a delta."""
        if isinstance(ev, BookSnapshot):
            await self._on_snapshot(ev)
            return
        if self.phase is not BookPhase.LIVE or self.book is None:
            if self.phase is BookPhase.SNAPSHOT_PENDING:
                if len(self._buffer) >= BUFFER_BOUND:
                    await self._desync("buffer_overflow")
                else:
                    self._buffer.append(ev)
            return
        if ev.prev_update_id != self.last_u:
            await self._desync("sequence_gap")
            return
        try:
            self.book.apply(ev.bids, ev.asks)
        except BookError as exc:
            kind = exc.kind if isinstance(exc, BookInvariantError) else "payload"
            await self._desync(kind)
            return
        self.last_u = ev.update_id
        self.last_good_ts_us = ev.ts_event
        if not self.muted:
            await self._publish(ev)

    async def _on_snapshot(self, ev: BookSnapshot) -> None:
        if self.phase is BookPhase.LIVE:  # server reset: drop and re-snapshot
            await self._desync("server_reset")
            return
        if self.phase is not BookPhase.SNAPSHOT_PENDING:
            return
        self._staged = ev
        if self.supervisor is not None:
            await self.supervisor.send("SNAPSHOT")
        else:
            await self.go_live()

    async def _desync(self, reason: str) -> None:
        self.phase = BookPhase.DESYNCED  # enforce first (C-2.21)
        self.book = None
        self._reason = reason
        if self.supervisor is not None:
            await self.supervisor.send("SEQUENCE_GAP")
        else:
            await self.go_desynced()
            await self.request_snapshot()

    def check_timeout(self, timeout_us: int) -> bool:
        """True when a snapshot has been pending longer than `timeout_us`;
        the caller then sends SNAPSHOT_TIMEOUT (or calls `request_snapshot`)."""
        since = self._pending_since
        return (
            self.phase is BookPhase.SNAPSHOT_PENDING
            and since is not None
            and (self._now() - since >= timeout_us)
        )

    # ---- B14 runtime hooks (called from chart entry actions) ---------------
    async def request_snapshot(self) -> None:
        self.phase = BookPhase.SNAPSHOT_PENDING
        self._buffer.clear()
        self._staged = None
        self._pending_since = self._now()
        await self._resubscribe()

    async def go_live(self) -> None:
        snap = self._staged
        if snap is None:
            return
        try:
            book = BookState.from_levels(self.depth, snap.bids, snap.asks)
        except BookError:
            await self._desync("bad_snapshot")
            return
        last_u = snap.update_id
        for d in self._buffer:  # INV-B14-d: strictly after snapshot seq
            if d.update_id <= last_u:
                continue
            if d.prev_update_id != last_u:
                await self._desync("sequence_gap")
                return
            try:
                book.apply(d.bids, d.asks)
            except BookError:
                await self._desync("bad_replay")
                return
            last_u = d.update_id
        self._buffer.clear()
        self._staged = None
        self._template = snap
        self.book, self.last_u, self.phase = book, last_u, BookPhase.LIVE
        self.last_good_ts_us = self._now()
        if not self.muted:
            await self.publish_current("subscribe" if self.resync_count == 0 else "resync")

    async def publish_current(self, reason: str) -> None:
        """Publish the full current book as a `BookSnapshot` (+ LIVE status)."""
        if self.book is None or self._template is None:
            return
        bids, asks = self.book.snapshot()
        await self._publish(
            self._template.model_copy(
                update={"bids": bids, "asks": asks, "update_id": self.last_u, "reason": reason}
            )
        )
        await self._status("live")

    async def go_desynced(self) -> None:
        self.phase = BookPhase.DESYNCED
        self.book = None
        self.resync_count += 1
        now = self._now()
        self._resync_times.append(now)
        while self._resync_times and now - self._resync_times[0] > BREAKER_WINDOW_US:
            self._resync_times.popleft()
        self.degraded = len(self._resync_times) > BREAKER_MAX
        if not self.muted:
            await self._status(self._reason)

    async def _status(self, reason: str) -> None:
        await self._publish(
            BookStatus(
                symbol=self.symbol,
                depth=self.depth,
                state=self.phase,
                reason=reason,
                ts_us=self._now(),
                last_good_ts_us=self.last_good_ts_us,
                resync_count=self.resync_count,
                degraded=self.degraded,
            )
        )
