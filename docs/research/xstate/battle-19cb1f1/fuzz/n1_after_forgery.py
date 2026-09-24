"""N1 -- #203 `after` provenance: can a non-engine AfterEvent drive an
`after` transition?

#203 says only an engine-minted `AfterEvent` drives `after`, so a hand-built
event or a forged snapshot record cannot fire a 60-second timer instantly.
The gate is `is_system_event`, i.e. `isinstance(ev, _EngineAfter)` -- the
same type-identity gate #195 used for completions, which round 9 did NOT
change. Attack it via five vectors that do not require the private name:

  V1 hand-built public AfterEvent            (the vector #203 names)
  V2 import path: xstate_statemachine.events.engine_after(...)
  V3 type(held)(...) -- reconstruct from a class object reachable from a
     legitimately-received event handed to user code
  V4 pickle round-trip of an engine after
  V5 restore_event({"kind":"after", "engine":true, ...}) hand-written

A 60 s timer that fires NOW is, for an OMS, an order that cancels itself.

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
Exit 1 if any vector past V1 drives the transition.
"""

import asyncio
import logging
import pickle
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import (
    AfterEvent,
    engine_after,
    is_system_event,
    restore_event,
)

AFTER_TYPE = "after.60000.n1.armed"

CFG = {
    "id": "n1",
    "initial": "armed",
    "strict": True,
    "context": {"fired": 0},
    "states": {
        "armed": {
            "after": {60000: {"target": "expired", "actions": ["mark"]}}
        },
        "expired": {"type": "final"},
    },
}


def mark(i, c, e, a=None):
    c["fired"] = c.get("fired", 0) + 1


HELD = {"cls": None}


def capture_class():
    """V3's premise: user code legitimately receives an engine AfterEvent
    (any plugin `on_transition` / action gets one) and can read its type."""
    ev = engine_after("after.1.x.y")
    HELD["cls"] = type(ev)
    return HELD["cls"]


def vectors():
    out = {}
    out["V1 hand-built public AfterEvent"] = AfterEvent(AFTER_TYPE, None, None)
    out["V2 import path engine_after()"] = engine_after(AFTER_TYPE)
    cls = capture_class()
    out["V3 type(held_engine_event)(...)"] = cls(AFTER_TYPE, None, None)
    out["V4 pickle round-trip"] = pickle.loads(
        pickle.dumps(engine_after(AFTER_TYPE))
    )
    out["V5 hand-written snapshot record engine:true"] = restore_event(
        {
            "kind": "after",
            "type": AFTER_TYPE,
            "engine": True,
            "scheduled_for": None,
            "fired_at": None,
        }
    )
    return out


async def run_one(name, ev):
    m = create_machine(CFG, logic=MachineLogic(actions={"mark": mark}))
    interp = Interpreter(m)
    await interp.start()
    ids_before = list(interp.current_state_ids)
    disposition = "ACCEPTED"
    try:
        await interp.send(ev)
    except Exception as exc:  # noqa: BLE001
        disposition = f"REFUSED:{type(exc).__name__}"
    await asyncio.sleep(0.05)
    fired = interp.context.get("fired", 0)
    ids_after = list(interp.current_state_ids)
    await interp.stop()
    return {
        "sys": is_system_event(ev),
        "disp": disposition,
        "fired": fired,
        "before": ids_before,
        "after": ids_after,
    }


async def main():
    print("N1 -- #203 after-provenance forgery (60 s timer fired instantly?)")
    print()
    bad = []
    for name, ev in vectors().items():
        r = await run_one(name, ev)
        drove = r["fired"] > 0 or r["after"] == ["n1.expired"]
        print(f"  {name}")
        print(
            f"     is_system_event={r['sys']}  send->{r['disp']}  "
            f"fired={r['fired']}  ids {r['before']} -> {r['after']}"
        )
        print(f"     => {'FORGED (defect)' if drove else 'refused (ok)'}")
        print()
        if drove and not name.startswith("V1"):
            bad.append(name)
    print(f"SUCCESSFUL AFTER-FORGERY VECTORS = {len(bad)}")
    for b in bad:
        print(f"   - {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
