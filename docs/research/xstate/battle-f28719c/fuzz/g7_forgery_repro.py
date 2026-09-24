"""D9-fuzz-2 REPRO -- an engine completion is forgeable three ways, and
each one drives a real `onDone` under `strict` while the genuine service is
still running.

#195 says: `is_system_event` requires a PRIVATE engine subclass, so a
hand-built `DoneEvent("done.invoke.fill", ...)` is refused.  That is true --
and it is the only vector closed.  Three cheaper vectors survive, because
NamedTuple machinery reconstructs the SUBCLASS:

  1. `ed._replace(data=...)` -- NamedTuple._replace calls `_make`, which is a
     classmethod, so it returns another `engine_done` with attacker data.
  2. `pickle.loads(pickle.dumps(ed))` -- the subclass is importable from
     `xstate_statemachine.events`, so it pickles and unpickles as itself.
  3. `restore_event({... "engine": true})` -- a HAND-WRITTEN snapshot record
     with the flag set restores as a trusted completion.  The changelog
     argues this is acceptable because "a caller who can write arbitrary
     snapshot records already controls state_ids and context outright" --
     but #198's rules REFUSE a forged configuration, so the record writer
     does NOT control state_ids; the event channel is now the weaker door.

In each case the forged completion drives `onDone` -> `s.b` with the real
`svc` still sleeping.  `strict=True` does not refuse it.

Expect: exit 1 on f28719c.
STANDALONE: stdlib + xstate_statemachine only.
"""
import asyncio, copy, logging, pickle, sys, warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import (
    DoneEvent,
    engine_done,
    is_system_event,
    restore_event,
)

CFG = {
    "id": "s",
    "initial": "a",
    "strict": True,
    "context": {"drove": 0},
    "states": {
        "a": {
            "invoke": {
                "id": "fill",
                "src": "svc",
                "onDone": {"target": "b", "actions": ["mark"]},
            }
        },
        "b": {"type": "final"},
    },
}

SERVICE_STILL_RUNNING = {"v": False}


async def svc(i, c, e):
    SERVICE_STILL_RUNNING["v"] = True
    await asyncio.sleep(30)  # never completes inside the test
    return {"filled": 100}


def mark(i, c, e, a=None):
    c["drove"] = c.get("drove", 0) + 1
    c["payload"] = getattr(e, "data", None)


def vectors():
    seed = engine_done("done.invoke.fill", {"filled": 0}, "fill")
    out = {}
    out["hand-built DoneEvent (#195 closed this)"] = DoneEvent(
        "done.invoke.fill", {"filled": 999999}, "fill"
    )
    out["NamedTuple._replace on any engine event"] = seed._replace(
        data={"filled": 999999}
    )
    out["pickle round-trip of an engine event"] = pickle.loads(
        pickle.dumps(engine_done("done.invoke.fill", {"filled": 999999}, "fill"))
    )
    out["hand-written snapshot record, engine:true"] = restore_event(
        {
            "kind": "done",
            "type": "done.invoke.fill",
            "data": {"filled": 999999},
            "src": "fill",
            "engine": True,
        }
    )
    return out


async def attack(name, ev):
    m = create_machine(
        copy.deepcopy(CFG),
        logic=MachineLogic(services={"svc": svc}, actions={"mark": mark}),
    )
    it = await Interpreter(m).start()
    await asyncio.sleep(0.05)
    res = "ACCEPTED"
    try:
        await asyncio.wait_for(it.send(ev, wait=True), 2.0)
    except Exception as exc:
        res = f"REFUSED:{type(exc).__name__}"
    drove = it.context.get("drove", 0)
    payload = it.context.get("payload")
    ids = sorted(it.current_state_ids)
    svc_live = SERVICE_STILL_RUNNING["v"]
    await it.stop()
    forged = drove > 0 and "s.b" in ids
    print(f"  {name}")
    print(
        f"     is_system_event={is_system_event(ev)}  send->{res}  "
        f"drove_onDone={drove}  ids={ids}"
    )
    print(
        f"     attacker payload landed in context = {payload!r}   "
        f"genuine service still running = {svc_live}"
    )
    print(f"     => {'FORGED (defect)' if forged else 'refused (ok)'}")
    return forged


async def main():
    print(
        "D9-fuzz-2: forging an engine completion past #195 under strict=True\n"
    )
    bad = []
    for name, ev in vectors().items():
        if await attack(name, ev):
            bad.append(name)
        print()
    print(f"SUCCESSFUL FORGERY VECTORS = {len(bad)}")
    for b in bad:
        print(f"   - {b}")
    sys.exit(1 if bad else 0)


asyncio.run(main())
