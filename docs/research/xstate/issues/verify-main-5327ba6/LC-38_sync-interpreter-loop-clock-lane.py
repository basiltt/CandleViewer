"""LC-38 (GH #50) verification on xstate-statemachine main @ 5327ba6.

Acceptance criteria under test (per issue #50 + task "need"):

  1. `SyncInterpreter` built INSIDE a running asyncio loop still creates NO
     OS threads for `after`; the deadline lands in the clock's heap, and
     `tick()` (or the next `send()`) delivers it on the calling thread.
  2. `set_timeout(sync=...)` lane follows the OWNING ENGINE, not whether a
     loop happens to be running on the constructing thread (`_clock_sync_lane`
     / `RealClock.set_timeout`).
  3. A third-party clock written against the 0.8.0 `Clock` protocol (no
     `sync` kwarg in its `set_timeout` signature) still works -- the engine
     inspects the signature ONCE at construction (`_clock_accepts_sync`) and
     calls `set_timeout` exactly once per timer (no retry-without-kwarg
     double-call, which would surface a clock's own error twice or lose the
     lane).

Exits 0 only if every criterion passes.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from typing import Any, Callable, List, Optional, Tuple

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

RESULTS: List[Tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


CFG = {
    "id": "order",
    "initial": "submitting",
    "context": {"n": 0},
    "states": {
        "submitting": {
            "after": {150: {"target": "timed_out", "actions": ["bump"]}},
        },
        "timed_out": {"type": "final"},
    },
}


def bump(interpreter, context, event, action_def):  # noqa: ANN001
    context["n"] += 1


# ---------------------------------------------------------------------------
# 1 & (partially) 2: build the SyncInterpreter INSIDE a running asyncio loop.
# ---------------------------------------------------------------------------
def build_inside_loop_and_check() -> None:
    machine = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))

    threads_before: Optional[set] = None
    sm_holder: dict = {}

    async def runner() -> None:
        threads_before_local = {t.ident for t in threading.enumerate()}
        sm = SyncInterpreter(machine).start()
        sm_holder["sm"] = sm
        # Sanity: we ARE inside a running loop right now.
        asyncio.get_running_loop()
        # Give the 150ms `after` deadline time to elapse while we do
        # NOTHING but sleep -- no send(), no tick().
        await asyncio.sleep(0.3)
        threads_after_local = {t.ident for t in threading.enumerate()}
        new_threads = threads_after_local - threads_before_local
        record(
            "1a. no new OS threads while built inside running loop",
            len(new_threads) == 0,
            f"new threads = {new_threads!r}",
        )
        record(
            "1b. state has NOT advanced from a bare sleep (no pump)",
            sm.current_state_ids == {"order.submitting"},
            f"state = {sorted(sm.current_state_ids)}",
        )
        # Now pump explicitly via tick() -- still on this thread, inside
        # the loop.
        sm.tick()
        record(
            "1c. tick() delivers the elapsed deadline on the caller's thread",
            sm.current_state_ids == {"order.timed_out"} and sm.context["n"] == 1,
            f"state = {sorted(sm.current_state_ids)}, n = {sm.context['n']}",
        )
        record(
            "2. _clock_sync_lane is True for a SyncInterpreter regardless of "
            "the ambient running loop",
            sm._clock_sync_lane is True,
            f"_clock_sync_lane = {sm._clock_sync_lane!r}",
        )

    asyncio.run(runner())


# ---------------------------------------------------------------------------
# 2b: RealClock.set_timeout picks the lane by explicit `sync=`, not by
#     whatever loop happens to be running on the CALLING thread at fire time.
# ---------------------------------------------------------------------------
def check_lane_follows_owner_not_ambient_context() -> None:
    from xstate_statemachine.clock import RealClock

    clock = RealClock()
    fired: List[str] = []

    async def runner() -> None:
        # sync=True inside a running loop -> heap, NOT call_later.
        handle = clock.set_timeout(
            lambda: fired.append("sync-lane"), 0.01, owner="x", sync=True
        )
        await asyncio.sleep(0.05)
        # It must NOT have fired via call_later (nothing pumped the heap).
        record(
            "2b. sync=True lane parks in the heap even inside a running loop "
            "(not delivered by the loop itself)",
            fired == [],
            f"fired = {fired!r}",
        )
        n = clock.pump()
        record(
            "2c. pump() delivers the sync-lane deadline",
            n == 1 and fired == ["sync-lane"],
            f"pump() returned {n}, fired = {fired!r}",
        )
        clock.clear_timeout(handle)

    asyncio.run(runner())


# ---------------------------------------------------------------------------
# 3: third-party 0.8.0-protocol clock (set_timeout WITHOUT a `sync` kwarg)
#    still works; engine inspects the signature once and calls it once.
# ---------------------------------------------------------------------------
class LegacyClock:
    """A pre-0.8.1 `Clock` implementation: no `sync` kwarg at all."""

    def __init__(self) -> None:
        self.calls = 0
        self._now = 0.0
        self._pending: List[Tuple[float, Callable[[], Any]]] = []

    def now(self) -> float:
        return self._now

    def set_timeout(self, fn, delay_sec, *, owner=None):  # noqa: ANN001
        self.calls += 1
        self._pending.append((self._now + delay_sec, fn))
        return object()

    def clear_timeout(self, handle) -> None:  # noqa: ANN001
        pass

    def pump(self) -> int:
        fired = 0
        remaining = []
        for due, fn in self._pending:
            if due <= self._now:
                fn()
                fired += 1
            else:
                remaining.append((due, fn))
        self._pending = remaining
        return fired

    def advance(self, sec: float) -> None:
        self._now += sec


def check_legacy_clock_protocol() -> None:
    machine = create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))
    clock = LegacyClock()
    sm = SyncInterpreter(machine, clock=clock).start()
    # Exactly one set_timeout call was made scheduling the `after`.
    calls_after_start = clock.calls
    record(
        "3a. legacy (no-`sync`-kwarg) clock's set_timeout called exactly once "
        "per timer at construction",
        calls_after_start == 1,
        f"clock.calls = {calls_after_start}",
    )
    clock.advance(0.2)
    sm.tick()
    record(
        "3b. legacy clock still delivers the deadline correctly via tick()",
        sm.current_state_ids == {"order.timed_out"} and sm.context["n"] == 1,
        f"state = {sorted(sm.current_state_ids)}, n = {sm.context['n']}",
    )
    record(
        "3c. no retry / double-call against the legacy clock (calls stayed 1)",
        clock.calls == 1,
        f"clock.calls = {clock.calls}",
    )


def main() -> int:
    build_inside_loop_and_check()
    check_lane_follows_owner_not_ambient_context()
    check_legacy_clock_protocol()

    print()
    all_ok = all(ok for _, ok, _ in RESULTS)
    for name, ok, detail in RESULTS:
        print(f"{'OK ' if ok else 'XX '} {name}")
    print(f"\nRESULT: {'ALL PASS' if all_ok else 'FAILURES PRESENT'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
