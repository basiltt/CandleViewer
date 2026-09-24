"""STANDALONE: can events.re_mint forge a completion for a different invoke?
Machine: 'a' invokes fast service 'ok' and slow service 'victim' (never completes
within the test). An action on done.invoke.ok re_mints the captured event with
type='done.invoke.victim' and re-sends it. Expected (secure): refused / no
transition to 'victim_done'. Both SyncInterpreter and Interpreter; def+async def."""
import asyncio, json, sys, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, Interpreter, SyncInterpreter, MachineLogic, is_system_event
from xstate_statemachine.events import re_mint

CFG = {"id": "m", "initial": "s", "strict": True, "states": {"s": {"type": "parallel", "states": {
  "p1": {"initial": "run", "states": {"run": {"invoke": {"id": "ok", "src": "ok", "onDone": {"target": "fin", "actions": "forge"}}}, "fin": {}}},
  "p2": {"initial": "run", "states": {"run": {"invoke": {"id": "victim", "src": "victim", "onDone": "victim_done"}}, "victim_done": {}}}}}}}
out = {}
def run(kind, asyncsvc):
    captured = []
    def forge(i, ctx, ev, *a):
        captured.append(ev)
    if asyncsvc:
        async def ok(i, ctx, ev): return {"v": 1}
        async def victim(i, ctx, ev): await asyncio.sleep(3600)
    else:
        def ok(i, ctx, ev): return {"v": 1}
        def victim(i, ctx, ev):
            import time; time.sleep(2); return {"late": 1}
    logic = MachineLogic(actions={"forge": forge}, services={"ok": ok, "victim": victim})
    try:
        m = create_machine(json.loads(json.dumps(CFG)), logic=logic)
    except Exception as e:
        m = create_machine({k: v for k, v in CFG.items() if k != "strict"}, logic=logic)
    res = {}
    async def go_async():
        it = await Interpreter(m).start()
        for _ in range(100):
            if captured: break
            await asyncio.sleep(0.01)
        forged = re_mint(captured[0], type="done.invoke.victim", data={"forged": True}, src="victim")
        res["forged_is_system"] = is_system_event(forged)
        try:
            await it.send(forged); await asyncio.sleep(0.1)
        except Exception as e: res["send_exc"] = repr(e)
        res["state"] = sorted(it.current_state_ids); await it.stop()
    def go_sync():
        it = SyncInterpreter(m).start()
        import time
        for _ in range(300):
            if captured: break
            time.sleep(0.01)
        forged = re_mint(captured[0], type="done.invoke.victim", data={"forged": True}, src="victim")
        res["forged_is_system"] = is_system_event(forged)
        try: it.send(forged)
        except Exception as e: res["send_exc"] = repr(e)
        res["state"] = sorted(it.current_state_ids); it.stop()
    try:
        asyncio.run(asyncio.wait_for(go_async(), 20)) if kind == "async" else go_sync()
    except Exception as e: res["harness_exc"] = repr(e)
    res["forged_completion_accepted"] = any("victim_done" in s for s in res.get("state", []))
    return res
for kind in ("sync", "async"):
    for a in (False, True):
        if kind == "sync" and a: continue
        out[f"{kind}/{'async def' if a else 'def'}"] = run(kind, a)
bad = [k for k, v in out.items() if v.get("forged_completion_accepted")]
out["verdict"] = "DEFECT" if bad else "CLEAN"
print(json.dumps(out, indent=1, default=str))
