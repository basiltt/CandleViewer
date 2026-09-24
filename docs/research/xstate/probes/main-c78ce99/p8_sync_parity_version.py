"""P-8: delayed sendTo a CHILD, sync-engine #212 parity, and the v3 forward
-compat error message.

STANDALONE.
  a) is a delayed `send_to` a CHILD actor also uncharged? (the #212 exemption
     keys on `actor is self and self._processing`, so a child send was never
     charged even before -- confirm, and confirm the child can ping-pong.)
  b) sync engine: is a `raise(delay=)` ping-pong also uncharged there, i.e.
     do both engines agree on the #212 reversal?
  c) what does a v2-era reader (minimum_version / SnapshotVersionError) say
     about a v3 payload -- is the message actionable?
"""

import asyncio
import json
import time
from typing import Any, Dict

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SimulatedClock,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import SnapshotVersionError

# --- (b) sync engine 1 ms raise(delay=) ping-pong -------------------------
HB: Dict[str, Any] = {
    "id": "hb",
    "initial": "up",
    "maxIterations": 6,
    "context": {"n": 0},
    "states": {
        "up": {
            "entry": [
                {"type": "raise", "params": {"event": "BEAT", "delay": 1}},
                "beat",
            ],
            "on": {"BEAT": "down"},
        },
        "down": {
            "entry": [
                {"type": "raise", "params": {"event": "BEAT", "delay": 1}},
                "beat",
            ],
            "on": {"BEAT": "up"},
        },
    },
}


def _mk(cfg: Dict[str, Any]) -> Any:
    def beat(i: Any, c: Any, e: Any, a: Any) -> None:
        c["n"] += 1

    return create_machine(cfg, logic=MachineLogic(actions={"beat": beat}))


def sync_case() -> str:
    clock = SimulatedClock()
    s = SyncInterpreter(_mk(HB), clock=clock).start()
    for _ in range(200):
        clock.increment(1)
        s.tick()
    n = s.context["n"]
    err = type(s.last_error).__name__ if s.last_error else None
    s.stop()
    return f"sync: beats={n} err={err} (limit=6, 200 virtual ms advanced)"


async def async_case() -> str:
    i = await Interpreter(_mk(HB)).start()
    t0 = time.perf_counter()
    await asyncio.sleep(0.8)
    el = time.perf_counter() - t0
    n = i.context["n"]
    err = type(i.last_error).__name__ if i.last_error else None
    await i.stop()
    return f"async: beats={n} err={err} rate={n/el:.0f}/s (limit=6)"


def version_case() -> str:
    base = {
        "version": 3,
        "status": "running",
        "state_ids": ["m.a"],
        "configuration": ["m.a"],
        "context": {},
        "machine_id": "m",
    }
    m = create_machine({"id": "m", "initial": "a", "states": {"a": {}}})
    outs = []
    # a v3 payload read by code that insists on >= 4 (stands in for "a v3
    # payload handed to a reader that only knows v2": same code path).
    try:
        SyncInterpreter.from_snapshot(
            json.dumps(base), m, verify_machine_hash=False, minimum_version=4
        )
        outs.append("min=4 accepted (!)")
    except SnapshotVersionError as exc:
        outs.append(f"min=4 -> {exc} | .minimum={getattr(exc,'minimum',None)}")
    # a v4 payload read by THIS library (the true forward-compat case)
    fwd = dict(base, version=4)
    try:
        SyncInterpreter.from_snapshot(
            json.dumps(fwd), m, verify_machine_hash=False
        )
        outs.append("v4 accepted (!)")
    except SnapshotVersionError as exc:
        outs.append(f"v4 payload -> {exc}")
    return " || ".join(outs)


async def main() -> None:
    print("b)", await async_case())


if __name__ == "__main__":
    # the sync engine must run OUTSIDE a running event loop, or
    # SimulatedClock.increment() returns an un-awaited coroutine.
    print("b)", sync_case())
    print("c)", version_case())
    asyncio.run(main())
