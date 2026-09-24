"""D14-fuzz-1 minimal repro: events.re_mint() re-targets a genuine completion
to a DIFFERENT invoke id, driving onDone of a service that never finished.
Capture point: the onDone ACTION of an unrelated invoke (def and async def).
CONTROL: a hand-built DoneEvent with the same type is correctly ignored.
STANDALONE: stdlib + xstate_statemachine. Run from any cwd."""
import asyncio, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.events import DoneEvent, re_mint, is_system_event

CFG = {"id": "m", "type": "parallel", "states": {
  "A": {"initial": "run", "states": {"run": {"invoke": {"id": "fast", "src": "fast",
        "onDone": {"target": "ok", "actions": ["relay"]}}}, "ok": {}}},
  "B": {"initial": "wait", "states": {"wait": {"invoke": {"id": "victim", "src": "victim",
        "onDone": "SETTLED"}}, "SETTLED": {}}}}}
async def fast(i, c, e): return {"v": 1}
async def victim(i, c, e): await asyncio.sleep(3600)   # never completes

def build(mode, kind):
    def forge(e):
        return (re_mint(e, type="done.invoke.victim", src="victim") if mode == "re_mint"
                else DoneEvent("done.invoke.victim", {}, "victim"))
    if kind == "def":
        def relay(i, c, e, a=None): i.send(forge(e))
    else:
        async def relay(i, c, e, a=None): await i.send(forge(e))
    return MachineLogic(services={"fast": fast, "victim": victim}, actions={"relay": relay})

async def cell(mode, kind):
    it = Interpreter(create_machine(CFG, logic=build(mode, kind))); await it.start()
    for _ in range(40): await asyncio.sleep(0.005)
    ids = sorted(it.current_state_ids); await it.stop()
    return "m.B.SETTLED" in ids, ids

async def main():
    fails = 0
    for kind in ("def", "async def"):
        for mode in ("hand_built", "re_mint"):
            settled, ids = await cell(mode, kind)
            print(f"{kind:9s} {mode:10s} victim SETTLED={settled} {ids}")
            fails += settled and mode == "re_mint"
    print("REPRODUCED" if fails else "NOT REPRODUCED", f"({fails}/2 cells)")
asyncio.run(main())

# ---- sync engine cell: re-target a fired after-timer onto an UNFIRED one ----
import time
from xstate_statemachine import SyncInterpreter
from xstate_statemachine.events import AfterEvent
SC = {"id": "s", "type": "parallel", "states": {
  "A": {"initial": "a", "states": {"a": {"after": {"10": {"target": "b", "actions": ["cap"]}}}, "b": {}}},
  "B": {"initial": "w", "states": {"w": {"after": {"99999": "EXPIRED"}}, "EXPIRED": {}}}}}
for mode in ("hand_built", "re_mint"):
    seen = []
    it = SyncInterpreter(create_machine(SC, logic=MachineLogic(actions={"cap": lambda i, c, e, a=None: seen.append(e)})))
    it.start()
    for _ in range(100):
        time.sleep(0.01); it.tick()
        if seen: break
    ev = re_mint(seen[0], type="after.99999.s.B.w") if mode == "re_mint" else AfterEvent("after.99999.s.B.w")
    it.send(ev); ids = sorted(it.current_state_ids); it.stop()
    print(f"sync/def  {mode:10s} 99999ms timer EXPIRED early={'s.B.EXPIRED' in ids} {ids}")
