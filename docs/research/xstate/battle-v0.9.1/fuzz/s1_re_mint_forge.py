"""S1 -- can events.re_mint() forge a DIFFERENT completion?
A plugin captures a genuine engine-minted done.invoke.fast and re-mints it as
done.invoke.victim (victim never resolves). CONTROLS: plain Event and a
hand-built DoneEvent with the same type. STANDALONE (stdlib + library)."""
import asyncio, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine
from xstate_statemachine import events as E

CFG = {"id": "m", "type": "parallel", "states": {
  "A": {"initial": "run", "states": {"run": {"invoke": {"id": "fast", "src": "fast",
        "onDone": "ok"}}, "ok": {}}},
  "B": {"initial": "wait", "states": {"wait": {"invoke": {"id": "victim", "src": "victim",
        "onDone": "PAID"}}, "PAID": {}}}}}

async def fast(i, c, e): return {"v": 1}
async def victim(i, c, e): await asyncio.sleep(3600)

class Cap(PluginBase):
    def __init__(s): s.ev = None
    def on_event_received(s, it, ev):
        if getattr(ev, "type", "") == "done.invoke.fast" and s.ev is None: s.ev = ev

async def run(mode):
    cap = Cap()
    it = Interpreter(create_machine(CFG, logic=MachineLogic(services={"fast": fast, "victim": victim})))
    it.use(cap); await it.start()
    for _ in range(50):
        await asyncio.sleep(0.005)
        if cap.ev: break
    err = None
    try:
        if mode == "re_mint":
            forged = E.re_mint(cap.ev, type="done.invoke.victim", src="victim")
            sysflag = E.is_system_event(forged)
        elif mode == "plain":
            forged = E.Event("done.invoke.victim"); sysflag = E.is_system_event(forged)
        else:
            forged = E.DoneEvent("done.invoke.victim", {}, "victim"); sysflag = E.is_system_event(forged)
        await it.send(forged)
    except Exception as x: err = f"{type(x).__name__}: {str(x)[:90]}"; sysflag = locals().get("sysflag")
    for _ in range(10): await asyncio.sleep(0.005)
    ids = sorted(it.current_state_ids); st = it.status
    await it.stop()
    return sysflag, ids, st, err

async def main():
    bad = 0
    for mode in ("plain", "hand_done", "re_mint"):
        r = await run(mode)
        paid = any("PAID" in s for s in r[1])
        print(f"{mode:9s} system={r[0]} states={r[1]} status={r[2]} err={r[3]} PAID={paid}")
        if mode == "re_mint" and paid: bad += 1
    print("DEFECTS =", bad)
asyncio.run(main())
