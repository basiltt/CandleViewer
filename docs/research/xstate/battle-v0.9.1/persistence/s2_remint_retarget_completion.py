"""STANDALONE. Security (D14-persistence-1 candidate): events.re_mint() retargets
a GENUINE completion to a different, still-outstanding invocation.
Region 'probe' invokes 'quick' (finishes at once); its onDone action receives
the engine-minted DoneEvent and calls
    re_mint(ev, type="done.invoke.victim", src="victim", data={"approved": True})
then send()s it. Region 'pay' invokes 'victim' (never finishes). If 'pay' moves
to 'settled' with the forged data, a completion the victim never produced was
accepted with engine provenance. Same for ErrorEvent -> onError.
Both action kinds (XS_SVC=async|def), both engines. Exit 1 if reproduced."""
import asyncio, json, os, sys
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine import events as E

KIND = os.environ.get("XS_SVC", "async")

def cfg(mode):
    return {"id": "m", "type": "parallel", "states": {
        "probe": {"initial": "run", "states": {
            "run": {"invoke": {"id": "quick", "src": "quick",
                               "onDone": {"target": "x", "actions": "forge"},
                               "onError": {"target": "x", "actions": "forge"}}},
            "x": {}}},
        "pay": {"initial": "awaiting", "states": {
            "awaiting": {"invoke": {"id": "victim", "src": "victim",
                                    "onDone": {"target": "settled", "actions": "rec"},
                                    "onError": {"target": "failed", "actions": "rec"}}},
            "settled": {}, "failed": {}}}}}

def build(sync, mode, box):
    def body(i, e):
        t = "done.invoke.victim" if mode == "done" else "error.platform.victim"
        f = E.re_mint(e, type=t, src="victim", **({"data": {"approved": True}} if mode == "done" else {}))
        box["forged"] = f
        box["sys"] = E.is_system_event(f)
    def rec_body(c, e):
        c["victim_data"] = e.data
    if KIND == "def" or sync:
        def forge(i, c, e, a): body(i, e)
        def rec(i, c, e, a): rec_body(c, e)
    else:
        async def forge(i, c, e, a): body(i, e)
        async def rec(i, c, e, a): rec_body(c, e)
    if sync:
        def quick(i, c, e):
            if mode == "error": raise RuntimeError("q")
            return 1
        def victim(i, c, e):
            return None
    else:
        async def quick(i, c, e):
            if mode == "error": raise RuntimeError("q")
            return 1
        async def victim(i, c, e):
            await asyncio.sleep(3600)
    return create_machine(cfg(mode), logic=MachineLogic(
        actions={"forge": forge, "rec": rec}, services={"quick": quick, "victim": victim}))

async def run_async(mode):
    box = {}
    i = Interpreter(build(False, mode, box)); await i.start()
    for _ in range(50):
        if "forged" in box: break
        await asyncio.sleep(0.01)
    if "forged" in box:
        await i.send(box["forged"])
        await asyncio.sleep(0.05)
    r = {"engine": "async", "mode": mode, "states": sorted(i.current_state_ids),
         "victim_data": i.context.get("victim_data"), "forged_is_system": box.get("sys")}
    await i.stop(); return r

def run_sync(mode):
    box = {}
    i = SyncInterpreter(build(True, mode, box)); i.start()
    r0 = sorted(i.current_state_ids)
    if "forged" in box:
        i.send(box["forged"])
    r = {"engine": "sync", "mode": mode, "before": r0, "states": sorted(i.current_state_ids),
         "victim_data": i.context.get("victim_data"), "forged_is_system": box.get("sys")}
    i.stop(); return r

bad = False
for mode in ("done", "error"):
    # sync engine: a sync service completes inside start(), so no invocation
    # can be outstanding when an action runs -> not applicable (N/A).
    for r in (asyncio.run(run_async(mode)),):
        r["FORGED"] = any(s.endswith("settled") or s.endswith("failed") for s in r["states"])
        bad |= r["FORGED"]
        print(json.dumps(r, default=str))
print("VERDICT:", "REPRODUCED: re_mint retargets a completion to another invocation" if bad else "not reproduced")
sys.exit(1 if bad else 0)
