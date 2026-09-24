"""R6-06 — a snapshot taken from inside an ENTRY action is
ACCEPTED and persists a TORN state: the new leaf with a half-applied context.

Round 5 replaced the any-leaf test with `_configuration_is_legal()` (exactly
one leaf per region, #142/#143). That closes the PARALLEL tear, but the
entry-action window still has a perfectly legal configuration -- the new leaf
is already active -- while the macrostep is still open and the entry actions
that write the context have not all run. The guard at
base_interpreter.py:1306 is `_step_in_flight() and not _configuration_is_legal()`,
so a legal-but-mid-step configuration passes.

Library only, no project machinery. cec108b (unreleased 0.8.1), Python 3.13.

Exit code 1 == the torn snapshot was accepted on BOTH engines.
"""
import asyncio, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 SnapshotMidStepError, create_machine)

def build():
    cap = {}
    def record_fill(i_, ctx, e, am):
        # a realistic two-phase entry action: clear, then write
        ctx["filled_qty"] = 0
        try:
            cap["blob"] = cap["i"].get_persisted_snapshot()
            cap["r"] = "ACCEPTED"
        except SnapshotMidStepError:
            cap["r"] = "SnapshotMidStepError"
        ctx["filled_qty"] = 100          # the fill is only recorded HERE
    cfg = {"id":"oms","initial":"open","context":{"filled_qty":0},
           "states":{"open":{"on":{"FILL":"filled"}},
                     "filled":{"entry":["record_fill"]}}}
    return create_machine(cfg, logic=MachineLogic(actions={"record_fill":record_fill})), cap

TORN = []

def show(label, i, cap):
    print(f"--- {label}")
    print("  live after settle :", sorted(i.current_state_ids), "ctx=", dict(i.context))
    print("  snapshot mid-entry:", cap.get("r"))
    if cap.get("r") == "ACCEPTED":
        b = cap["blob"]
        print("     persisted state :", b["configuration"], " context:", b["context"])
        r = SyncInterpreter.from_snapshot(__import__("json").dumps(b),
                                          build()[0]).start()
        print("     restored        :", sorted(r.current_state_ids), "ctx=", dict(r.context))
        if r.context.get("filled_qty") == 0 and "oms.filled" in r.current_state_ids:
            print("     >>> TORN: state says FILLED, context says 0 filled")
            TORN.append(label)
        r.stop()

m, cap = build(); i = SyncInterpreter(m).start(); cap["i"] = i
i.send("FILL"); show("SyncInterpreter", i, cap); i.stop()

async def a():
    m, cap = build(); i = await Interpreter(m).start(); cap["i"] = i
    await i.send("FILL", wait=True); show("Interpreter (async)", i, cap); await i.stop()
asyncio.run(a())

print()
if len(TORN) == 2:
    print("REPRODUCED on both engines: %s" % ", ".join(TORN))
    raise SystemExit(1)
print("NOT reproduced.")
raise SystemExit(0)
