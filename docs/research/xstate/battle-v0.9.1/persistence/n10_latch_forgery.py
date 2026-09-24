"""Security framing for the new v3 latch fields.  A party who controls the
whole blob can write `chain_trips` / `last_chain_error`.  That is INSIDE the
documented from_snapshot trust boundary (state_ids/context are applied
verbatim), so it is only worth filing if the forgery crosses OUT -- e.g. it
can drive a transition, fire a hook, or resurrect after clear_chain_error().
"""
import asyncio, json, os
from xstate_statemachine import (Interpreter, MachineLogic, PluginBase,
                                 create_machine, RestoredError)

CFG = {"id": "fg", "initial": "a", "context": {"log": []},
       "states": {"a": {"on": {"P": {"actions": ["note"]}}}}}

def build():
    def note(i, c, e, a):
        c["log"].append(e.type)
    return create_machine(json.loads(json.dumps(CFG)),
                          logic=MachineLogic(actions={"note": note}))

class Spy(PluginBase):
    def __init__(self):
        self.budget = []
    def on_chain_budget_exceeded(self, interpreter, error=None, **kw):
        self.budget.append(str(error))

async def main():
    i = Interpreter(build())
    await i.start()
    b = i.get_persisted_snapshot()
    b = json.loads(b) if isinstance(b, str) else b
    await i.stop()
    rows = {}
    for name, trips, msg in (("huge", 10**9, "FORGED: pretend disaster"),
                             ("negative", -5, "neg"),
                             ("noninteger", "NaN", "x"),
                             ("count_no_msg", 7, None),
                             ("msg_no_count", 0, "orphan message")):
        f = dict(b)
        f["chain_trips"] = trips
        f["last_chain_error"] = msg
        spy = Spy()
        try:
            k = Interpreter.from_snapshot(json.dumps(f), build(),
                                          verify_machine_hash=False,
                                          plugins=[spy])
        except Exception as ex:                # noqa: BLE001
            rows[name] = {"restore": f"{type(ex).__name__}: {ex}"}
            continue
        await k.start()
        await k.send("P")
        await asyncio.sleep(0.1)
        rec = {"restore": "ok", "chain_trips": k.chain_trips,
               "latch": type(k.last_chain_error).__name__,
               "latch_is_RestoredError": isinstance(k.last_chain_error,
                                                    RestoredError),
               "budget_hook_fired": spy.budget,
               "normal_traffic_ok": list(k.context["log"]) == ["P"],
               "status": k.status}
        k.clear_chain_error()
        rec["after_clear_latch"] = type(k.last_chain_error).__name__
        rec["after_clear_trips"] = k.chain_trips
        b2 = k.get_persisted_snapshot()
        b2 = json.loads(b2) if isinstance(b2, str) else b2
        rec["re_persisted_trips"] = b2.get("chain_trips")
        rec["re_persisted_latch"] = b2.get("last_chain_error")
        await k.stop()
        rows[name] = rec
    crossings = [n for n, r in rows.items()
                 if r.get("budget_hook_fired")
                 or r.get("normal_traffic_ok") is False
                 or r.get("after_clear_latch") not in (None, "NoneType")]
    print(json.dumps({"rows": rows, "boundary_crossings": crossings,
                      "VERDICT": "in-boundary" if not crossings
                      else "CROSSES-BOUNDARY"}, indent=1))

asyncio.run(main())
