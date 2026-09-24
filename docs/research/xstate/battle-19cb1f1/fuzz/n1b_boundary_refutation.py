"""N1b -- refutation probe for R11-03 (after-provenance forgery).

Three questions, standalone (stdlib + xstate_statemachine, any cwd):

  Q1 Is `engine_after` reachable from the PUBLIC surface (package __all__
     / top-level import), or only by reaching into the implementation
     module? If only the latter, V2/V3 are in-process reflection, not a
     boundary crossing.
  Q2 Does V5's door (hand-written snapshot record, engine:true) grant any
     capability the SAME writer does not already hold outright via
     state_ids / context? i.e. is the attacker who can write a snapshot
     already inside?
  Q3 Does V4 (pickle) escalate? It needs an engine event in hand; can the
     holder achieve the same by sending the ORIGINAL?
"""

import asyncio, json, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)

import xstate_statemachine as pkg
from xstate_statemachine import Interpreter, MachineLogic, create_machine

AFTER_TYPE = "after.60000.n1.armed"
CFG = {
    "id": "n1", "initial": "armed", "strict": True,
    "context": {"fired": 0},
    "states": {
        "armed": {"after": {60000: {"target": "expired", "actions": ["mark"]}}},
        "expired": {"type": "final"},
    },
}
def mark(i, c, e, a=None): c["fired"] = c.get("fired", 0) + 1
async def amark(i, c, e, a=None): c["fired"] = c.get("fired", 0) + 1


def q1():
    print("Q1 public reachability of the mint helpers")
    for n in ("engine_after", "engine_done", "engine_error", "_EngineAfter"):
        top = hasattr(pkg, n)
        inall = n in getattr(pkg, "__all__", ())
        print(f"   {n:16s} top-level attr={top}  in __all__={inall}")
    print(f"   events module in __all__? {'events' in getattr(pkg,'__all__',())}")
    print()


async def q2(mkact, lane):
    print(f"Q2 snapshot-writer capability [{lane}]")
    m = create_machine(CFG, logic=MachineLogic(actions={"mark": mkact}))
    i = Interpreter(m); await i.start()
    snap = json.loads(i.get_snapshot()) if isinstance(i.get_snapshot(), str) else i.get_snapshot()
    await i.stop()
    print(f"   baseline snapshot keys: {sorted(snap.keys())}")
    # Direct forgery of the OUTCOME, no event needed at all:
    forged = json.loads(json.dumps(snap))
    for k in ("state_ids", "current_state_ids", "states", "configuration"):
        if k in forged:
            forged[k] = ["n1.expired"]
    ctxkey = "context" if "context" in forged else None
    if ctxkey: forged[ctxkey] = {"fired": 99}
    m2 = create_machine(CFG, logic=MachineLogic(actions={"mkact": mkact, "mark": mkact}))
    try:
        i2 = Interpreter.from_snapshot(json.dumps(forged), m2)
        if hasattr(i2, '__await__'): i2 = await i2
        if hasattr(i2, 'start'):
            r = i2.start()
            if hasattr(r, '__await__'): await r
        ids = list(i2.current_state_ids); ctx = dict(i2.context)
        r2 = i2.stop()
        if hasattr(r2,'__await__'): await r2
        print(f"   direct state/context forgery -> ids={ids} context={ctx}")
        print(f"   => snapshot writer reaches the target state WITHOUT any event: "
              f"{ids == ['n1.expired']}")
    except Exception as e:
        print(f"   direct forgery refused: {type(e).__name__}: {e}")
    print()


async def q3(mkact, lane):
    print(f"Q3 pickle escalation [{lane}]")
    import pickle
    from xstate_statemachine.events import engine_after
    orig = engine_after(AFTER_TYPE)
    clone = pickle.loads(pickle.dumps(orig))
    for label, ev in (("original engine event", orig), ("pickle clone", clone)):
        m = create_machine(CFG, logic=MachineLogic(actions={"mark": mkact}))
        i = Interpreter(m); await i.start()
        try:
            await i.send(ev); d = "ACCEPTED"
        except Exception as e: d = f"REFUSED:{type(e).__name__}"
        await asyncio.sleep(0.05)
        print(f"   {label:24s} -> {d} fired={i.context.get('fired',0)}")
        await i.stop()
    print("   => clone grants nothing the holder of the original lacked\n")


async def main():
    q1()
    for mkact, lane in ((mark, "def"), (amark, "async def")):
        await q2(mkact, lane)
        await q3(mkact, lane)

asyncio.run(main())
