"""D5-semantics-1 repro: `get_persisted_snapshot()` taken from inside an ENTRY
ACTION is accepted (no SnapshotMidStepError) and persists the NEW state with a
HALF-APPLIED context. Because a restore is static (entry actions are not
re-run), the restored machine is in `filled` with the fill never recorded.

#102 refuses only the no-leaf window (exit set applied, entry set not yet).
The entry-action window has a leaf, so the guard passes -- but the macrostep
is still in flight and the state's own entry actions have not all run.
"""
import asyncio, json, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import (Interpreter, MachineLogic, SyncInterpreter,
                                 create_machine)

CFG = {"id": "oms", "initial": "new", "context": {"filled_qty": 0},
       "states": {"new": {"on": {"FILL": "filled"}},
                  "filled": {"entry": ["snap", "record_fill"]},
                  }}

def build(cap):
    def snap(i, ctx, e, am):
        try:
            cap["blob"] = json.dumps(i.get_persisted_snapshot())
            cap["refused"] = False
        except Exception as x:
            cap["refused"] = type(x).__name__
    def record_fill(i, ctx, e, am):
        ctx["filled_qty"] = ctx.get("filled_qty", 0) + 100
    return lambda: create_machine(CFG, logic=MachineLogic(
        actions={"snap": snap, "record_fill": record_fill}))

def report(engine, mk, cap, live_ids, live_ctx, ok_flag, err):
    print(f"--- {engine}")
    print(f"  live after settle : {live_ids}  ctx={live_ctx}")
    if cap.get("refused"):
        print(f"  snapshot mid-entry: REFUSED ({cap['refused']})"); return
    blob = json.loads(cap["blob"])
    print(f"  snapshot mid-entry: ACCEPTED state_ids={blob['state_ids']} ctx={blob['context']}")
    print(f"  last_transition_ok={ok_flag}  last_error={err}")
    r = SyncInterpreter.from_snapshot(cap["blob"], mk()).start()
    print(f"  restored          : {sorted(r.current_state_ids)}  ctx={r.context}")
    print(f"  >>> TORN: state says filled, context says {r.context['filled_qty']} filled")
    r.stop()

cap = {}
mk = build(cap)
s = SyncInterpreter(mk()).start(); s.send("FILL")
report("SyncInterpreter", mk, cap, sorted(s.current_state_ids), dict(s.context),
       s.last_transition_ok, s.last_error)
s.stop()

cap2 = {}
mk2 = build(cap2)
async def go():
    i = await Interpreter(mk2()).start()
    await i.send("FILL", wait=True)
    out = (sorted(i.current_state_ids), dict(i.context), i.last_transition_ok, i.last_error)
    await i.stop(); return out
ids, ctx, ok, err = asyncio.run(go())
report("Interpreter (async)", mk2, cap2, ids, ctx, ok, err)
