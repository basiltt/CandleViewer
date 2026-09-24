# A `RunawayChainError` chain trip reaches only `last_error`, and the next benign event erases it — a permanently inert machine reports healthy

**Severity:** Medium
**Build:** `main` @ `c78ce99` (merge of PR #217, `fix/0.8.1-round10`; unreleased 0.8.1). `__version__` still reports `0.8.0` — **key on the commit.**
**Environment:** CPython 3.13.7, Windows 11, fresh venv, neutral working directory.
**Both engines and both `def` / `async def` action spellings exercised — the defect is present on all three lanes.**
**r11:** R11-09 · **Labels:** bug, severity/medium, area/observability, error-handling

---

## Summary

When the chain budget trips, `RunawayChainError` reaches exactly one surface: `last_error`. And `last_error` is not a latch — it is recomputed **per processed event**:

```python
None if self.last_transition_ok else self._last_action_error
```

So the very next successfully-handled event resets it to `None`. **One benign, declared, correctly-handled event is enough to erase the only record that the machine discarded work.**

Meanwhile `interpreter.error` is never set, `status` stays `running`, and no hook carries chain context. `on_event_dropped` does fire with a `"chain_budget"` reason but names no error, and #207's `on_invocation_stranded` does not cover this shape at all, because no `invoke` is involved. Only the log remembers.

## Observed

```json
{
  "ASYNC-ENGINE / async def": {
    "last_error_AT_TRIP": "RunawayChainError",
    "interpreter.error": "NoneType",
    "status": "running",
    "last_error_AFTER_ONE_BENIGN_EVENT": "NoneType",
    "last_transition_ok": true
  },
  "ASYNC-ENGINE / def":  { ...identical... },
  "SYNC-ENGINE / def":   { ...identical... }
}
```

All three lanes. `interpreter.error` is never set on any of them.

The timer-driven variant is the dangerous one. A chart arming a 5 ms delayed `SLOW` alongside a zero-delay `FAST` trips **40/40** (ERROR logged, machine permanently inert at n=24, polled to convergence over 12 s and re-checked 2 s later) — yet on **6/40 (`def`) and 8/40 (`async def`)** runs the post-mortem reads `status='running'`, `last_transition_ok=True`, `last_error=None`, `pending_events=0`. A permanently inert machine reporting perfect health.

It is intermittent because it races the trip against the next tick. **Post-#212 that race has a predictable winner:** a legal `raise(delay=)` or `after` heartbeat guarantees events keep arriving, so in any machine with a heartbeat the eraser wins.

## Why it matters

A chain trip means work was silently discarded and the machine may be permanently wedged. That is precisely the condition a supervisor exists to detect, and the only programmatic signal for it is a field that any subsequent event clears.

Concretely, this observable is unusable as written: in our own harness it produced **99 false violations** before we latched the read — we were sampling a value that had already been reset by traffic arriving between the trip and the poll. Any supervisor polling on an interval slower than the event rate cannot observe the trip at all, and the higher the event rate, the smaller the window, so the busiest machines are the least observable.

## Suggested direction

Make the trip **sticky**, as #207 did for stranding. Either is sufficient:

1. A monotonic `chain_trips` counter on the interpreter, which a supervisor can sample at any interval and diff.
2. A dedicated `on_chain_budget_exceeded(...)` hook carrying the state, the event and the lap count.

A counter is probably the smaller change and composes better with metrics; a hook gives better diagnostics. Setting `interpreter.error` on a trip would also help, though it is a coarser signal than either.

It would also be worth documenting that `last_error` is a per-event read rather than a latch — the name reads like a latch, which is how we came to rely on it in the first place.

## Environment

CPython 3.13.7, Windows 11 Pro 10.0.26200, fresh venv, `xstate-statemachine` `main` @ `c78ce99`. `__version__` reports `0.8.0` (unreleased 0.8.1) — key on the commit.

## Repro

Standalone — stdlib plus `xstate_statemachine` only, all helpers inlined, runs from any working directory. Uses a zero-delay self-raise cycle, which still correctly trips under #212. **Exit 1 = defect present** (`last_error` holds `RunawayChainError` at the trip and `None` after one benign event); exit 0 = fixed.

```python
"""R11-09 (STANDALONE): a `RunawayChainError` chain trip reaches ONLY
`last_error`, and ONE BENIGN EVENT ERASES IT. No hook names the trip, and
`interpreter.error` / `status` never move -- so a permanently inert machine
reports healthy.

`last_error` is computed per processed event as
`None if self.last_transition_ok else self._last_action_error`. It is therefore
not a latch but a rolling read of the MOST RECENT event's outcome. A chain trip
sets it; the very next successfully-handled event recomputes it to `None`.

Meanwhile `interpreter.error` is untouched, `status` stays `running`, and no
hook carries chain context -- `on_event_dropped` fires with a "chain_budget"
reason but names no error, and #207's `on_invocation_stranded` does not cover
this shape at all (no invoke is involved).

Post-#212 this is materially worse in production: a legal `raise(delay=)` or
`after` heartbeat guarantees events keep arriving, so a supervisor polling
`last_error` races an eraser that always wins.

Exit 0 = the trip remains observable after a benign event (defect fixed).
Exit 1 = last_error holds RunawayChainError at the trip and None afterwards.

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 40 s.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import (
    create_machine,
    Interpreter,
    SyncInterpreter,
    MachineLogic,
)

MAXIT = 6


def cfg() -> dict:
    """A zero-delay self-raise cycle -- still correctly trips under #212."""
    return {
        "id": "trip",
        "initial": "spin",
        "maxIterations": MAXIT,
        "states": {
            "spin": {
                "entry": [
                    {"type": "raise", "params": {"event": "LAP"}},
                    "bump",
                ],
                "on": {
                    "LAP": {"target": "spin", "reenter": True},
                    "BENIGN": {"target": "spin", "reenter": False},
                },
            }
        },
    }


def _err_name(interp) -> str:
    return type(getattr(interp, "last_error", None)).__name__


def _logic(kind: str) -> MachineLogic:
    def _bump(i, c, e, a=None):  # noqa: ANN001  plain def
        pass

    async def _bump_async(i, c, e, a=None):  # noqa: ANN001  async def
        pass

    return MachineLogic(actions={"bump": _bump if kind == "def" else _bump_async})


async def lane_async(kind: str) -> dict:
    interp = Interpreter(create_machine(cfg(), logic=_logic(kind)))
    await interp.start()
    await asyncio.sleep(0.4)

    at_trip = _err_name(interp)
    err_attr = type(getattr(interp, "error", None)).__name__
    status_at_trip = str(getattr(interp, "status", "?"))

    await interp.send("BENIGN")          # ONE benign, declared, handled event
    await asyncio.sleep(0.2)
    after_benign = _err_name(interp)

    out = {
        "last_error_AT_TRIP": at_trip,
        "interpreter.error": err_attr,
        "status": status_at_trip,
        "last_error_AFTER_ONE_BENIGN_EVENT": after_benign,
        "last_transition_ok": bool(getattr(interp, "last_transition_ok", None)),
    }
    await interp.stop()
    return out


def lane_sync() -> dict:
    interp = SyncInterpreter(create_machine(cfg(), logic=_logic("def")))
    interp.start()
    at_trip = _err_name(interp)
    err_attr = type(getattr(interp, "error", None)).__name__
    status_at_trip = str(getattr(interp, "status", "?"))
    interp.send("BENIGN")
    after_benign = _err_name(interp)
    out = {
        "last_error_AT_TRIP": at_trip,
        "interpreter.error": err_attr,
        "status": status_at_trip,
        "last_error_AFTER_ONE_BENIGN_EVENT": after_benign,
        "last_transition_ok": bool(getattr(interp, "last_transition_ok", None)),
    }
    interp.stop()
    return out


async def main() -> int:
    results = {
        "ASYNC-ENGINE / async def": await lane_async("async def"),
        "ASYNC-ENGINE / def": await lane_async("def"),
        "SYNC-ENGINE / def": lane_sync(),
    }
    print(json.dumps(results, indent=2))

    erased = [
        lane
        for lane, r in results.items()
        if r["last_error_AT_TRIP"] == "RunawayChainError"
        and r["last_error_AFTER_ONE_BENIGN_EVENT"] == "NoneType"
    ]
    never_on_error_attr = all(
        r["interpreter.error"] == "NoneType" for r in results.values()
    )
    print()
    print(f"lanes where ONE benign event erased the trip: {erased}")
    print(f"interpreter.error never set on any lane     : {never_on_error_attr}")
    print(f"REPRODUCED: {bool(erased)}")
    return 1 if erased else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), 40)))
    except asyncio.TimeoutError:
        print("WATCHDOG: exceeded 40 s")
        sys.exit(2)
```

## Acceptance criteria

- `test_chain_trip_observable_after_subsequent_events__def` / `__async_def` — trip the budget, then send a benign handled event; the trip must remain observable (counter, hook record, or a latched error) on both spellings.
- `test_chain_trip_observable_on_sync_engine` — same on `SyncInterpreter`.
- `test_chain_trip_counter_monotonic` — N trips must be countable as N, not collapse to "the last one".
- `test_chain_trip_observable_under_heartbeat` — the timer-driven variant: a machine with a live `after` or `raise(delay=)` heartbeat must still report a trip that happened between two beats.
