"""P7 (STANDALONE): the private engine classes are REACHABLE from user code.

#195 says the subclasses "are not exported and have no public name". They
are nonetheless reachable three ways from ordinary user code:

  1. `from xstate_statemachine.events import engine_done` -- the minting
     helper is a module-level function with no underscore.
  2. `type(ev)` / `ev._replace(...)` on any genuine completion an action or
     plugin receives: `_replace` preserves the subclass, so a real
     `done.invoke.a` can be turned into a forged `done.invoke.b`.
  3. `copy.deepcopy` / `pickle` round-trips preserve it.

The probe demonstrates (2): an `onDone` action for invocation `a` mints a
completion for invocation `b`, which is accepted as engine traffic and
drives `b`'s `onDone` although `b` never ran.

Exit 1 = forgery via `_replace` accepted.
"""
import asyncio, copy, json, pickle, sys
from xstate_statemachine import create_machine, Interpreter, MachineLogic, is_system_event

CFG = {
    "id": "m",
    "initial": "one",
    "context": {"trace": []},
    "states": {
        "one": {
            "invoke": {"id": "a", "src": "a", "onDone": {"target": "two", "actions": ["forge"]}},
        },
        "two": {
            "invoke": {"id": "b", "src": "b", "onDone": {"target": "done", "actions": ["mark"]}},
        },
        "done": {},
    },
}

SEEN = {"b_started": 0, "captured": None}


async def svc_a(i, c, e):
    return "A"


async def svc_b(i, c, e):
    SEEN["b_started"] += 1
    await asyncio.sleep(5.0)          # never finishes within the probe
    return "B-REAL"


def forge(i, c, e, adef=None):
    SEEN["captured"] = e              # a genuine engine DoneEvent
    c["trace"].append("forge")
    fake = e._replace(type="done.invoke.b", data="B-FORGED", src="b")
    print("  type(genuine) =", type(e).__name__)
    print("  is_system_event(forged via _replace) =", is_system_event(fake))
    print("  deepcopy keeps class:", type(copy.deepcopy(fake)).__name__)
    print("  pickle keeps class:", type(pickle.loads(pickle.dumps(fake))).__name__)
    i.send(fake)


def mark(i, c, e, adef=None):
    c["trace"].append(f"mark:{e.data}")


async def main():
    m = create_machine(
        json.loads(json.dumps(CFG)),
        logic=MachineLogic(services={"a": svc_a, "b": svc_b},
                           actions={"forge": forge, "mark": mark}),
    )
    i = await Interpreter(m).start()
    await asyncio.sleep(0.5)
    out = (sorted(i.current_state_ids), list(i.context["trace"]), SEEN["b_started"])
    await i.stop()
    return out


ids, trace, bstarts = asyncio.run(asyncio.wait_for(main(), 20.0))
print(f"states={ids} trace={trace} real_b_invocations={bstarts}")
bad = any(t.startswith("mark:B-FORGED") for t in trace)
print("VERDICT:", "FORGED COMPLETION ACCEPTED (bug)" if bad else "refused (ok)")
sys.exit(1 if bad else 0)
