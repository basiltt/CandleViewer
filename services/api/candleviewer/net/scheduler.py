"""Hourly (configurable) re-check scheduler for the mesh guard (E09-T04 AC5).

"Drift after resume is caught": the host can sleep/resume with a changed
binding (WSL hazards), so the boot self-check alone is not enough — this
supervises a periodic re-run of `BindingSelfCheck.run()` for the lifetime of
the process, wiring each result through `apply_self_check_result` exactly
the same way the boot check does.

Runs in a thread executor (Performance notes: "must not block the event
loop... runs in a thread executor with a 2s timeout") since socket-table
enumeration is a syscall, not a coroutine.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .binding_check import BindingSelfCheck, apply_self_check_result

if TYPE_CHECKING:
    from prometheus_client import Gauge

    from .read_only_gate import ReadOnlyGate

logger = logging.getLogger(__name__)

_SELF_CHECK_TIMEOUT_S = 2.0


class MeshSelfCheckScheduler:
    """Owns the supervised background task that re-runs the self-check.

    Constructed with the same `BindingSelfCheck`/`ReadOnlyGate`/gauge the
    boot check used, so the boot pass and every hourly pass are the exact
    same code path (`apply_self_check_result`) — there is no separate
    "hourly" logic to drift from the boot logic.
    """

    def __init__(
        self,
        *,
        check: BindingSelfCheck,
        read_only_gate: ReadOnlyGate,
        gauge: Gauge | None = None,
        interval_s: float = 3600.0,
    ) -> None:
        self._check = check
        self._gate = read_only_gate
        self._gauge = gauge
        self._interval_s = interval_s
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the supervised background loop. Idempotent."""
        if self._task is not None:
            return
        self._task = asyncio.ensure_future(self._run_forever())

    async def stop(self) -> None:
        """Cancel and await the background loop, honouring cancellation."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def run_once(self) -> None:
        """Run exactly one re-check pass off the event loop, with a timeout.

        Exposed separately from the loop so the boot check and tests can
        both drive a single pass without waiting `interval_s`.
        """
        try:
            async with asyncio.timeout(_SELF_CHECK_TIMEOUT_S):
                result = await asyncio.to_thread(self._check.run)
        except TimeoutError:
            logger.error(
                "mesh guard self-check timed out after %.1fs; treating as unsafe "
                "(fail-closed) and tripping the read-only gate",
                _SELF_CHECK_TIMEOUT_S,
            )
            self._gate.trip(
                reason_code="net.self_check_timed_out",
                reason_text=(
                    f"Binding self-check did not complete within "
                    f"{_SELF_CHECK_TIMEOUT_S}s; treating as unsafe (fail-closed)."
                ),
            )
            if self._gauge is not None:
                self._gauge.set(0)
            return
        apply_self_check_result(result, read_only_gate=self._gate, gauge=self._gauge)

    async def _run_forever(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval_s)
                await self.run_once()
        except asyncio.CancelledError:
            raise
