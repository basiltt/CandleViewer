"""#233: SyncInterpreter must restore a `lane: "priority"` record at the HEAD
of its single queue, matching the async engine's two-lane order.

Blob carries inbox records P1,P2 (priority) interleaved with N1,N2 (normal)
in a persisted order that differs from the expected delivery order.
Expected: P1,P2 then N1,N2 -- FIFO within lane, priority lane first.
"""
import asyncio, json, os
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 create_machine)

TYPES = ["N1", "P1", "N2", "P2"]
CFG = {"id": "lane", "initial": "a", "context": {"log": []},
       "states": {"a": {"on": {t: {"actions": ["note"]} for t in TYPES}}}}

def build(kind):
    if kind == "def":
        def note(i, c, e, a):
            c["log"].append(e.type)
    else:
        async def note(i, c, e, a):
            c["log"].append(e.type)
    return create_machine(json.loads(json.dumps(CFG)),
                          logic=MachineLogic(actions={"note": note}))

def blob_for(kind, order):
    i = SyncInterpreter(build("def"))
    i.start()
    b = i.get_persisted_snapshot()
    b = json.loads(b) if isinstance(b, str) else b
    i.stop()
    b["context"] = {"log": []}
    b["pending_events"] = [
        {"type": t, "payload": {}, "kind": "event",
         "lane": ("priority" if t.startswith("P") else "normal")}
        for t in order]
    return b

async def main():
    kind = os.environ.get("XS_SVC", "async")
    # persisted order deliberately interleaved
    order = ["N1", "P1", "N2", "P2"]
    expect = ["P1", "P2", "N1", "N2"]
    out = {}
    b = blob_for(kind, order)

    s = SyncInterpreter.from_snapshot(json.dumps(b), build("def"),
                                      verify_machine_hash=False)
    s.start()
    out["sync"] = list(s.context["log"])
    s.stop()

    a = Interpreter.from_snapshot(json.dumps(b), build(kind),
                                  verify_machine_hash=False)
    await a.start()
    await asyncio.sleep(0.25)
    out["async"] = list(a.context["log"])
    await a.stop()

    fails = []
    if out["sync"] != expect:
        fails.append(f"sync {out['sync']} != {expect}")
    if out["async"] != expect:
        fails.append(f"async {out['async']} != {expect}")
    if out["sync"] != out["async"]:
        fails.append("engines disagree")
    print(json.dumps({"kind": kind, "persisted_order": order,
                      "expected": expect, "got": out, "fails": fails,
                      "VERDICT": "PASS" if not fails else "FAIL"}, indent=1))

asyncio.run(main())
