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
