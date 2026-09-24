"""Q12 -- shrink Q11. Minimal config whose `send(GO, wait=True)` resolves while
current_state_ids is EMPTY, plus: does it self-heal, and is last_transition_ok
False at that instant (i.e. can a caller tell)?"""
import asyncio, logging, warnings, copy
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

MIN = {"id": "m", "initial": "a", "maxIterations": 1,
       "on": {"GO": {"target": "#m.a", "internal": True}},
       "states": {"a": {"initial": "a",
                        "always": {"target": "#m.a.a", "guard": "g"},
                        "states": {"a": {"initial": "a",
                                         "always": {"target": "#m.a.a.a", "guard": "g"},
                                         "states": {"a": {"type": "final"}}}}}}}
L = lambda: MachineLogic(guards={"g": lambda c, e: True})

async def run(mi, evs=("GO", "GO")):
    cfg = copy.deepcopy(MIN); cfg["maxIterations"] = mi
    it = Interpreter(create_machine(cfg, logic=L()))
    await asyncio.wait_for(it.start(), 15)
    rows = []
    for ev in evs:
        try: await asyncio.wait_for(it.send(ev, wait=True), 10)
        except asyncio.TimeoutError: rows.append("SEND_TIMEOUT"); break
        ids = sorted(it.current_state_ids)
        rows.append(f"after {ev}: ids={ids} ok={it.last_transition_ok} "
                    f"err={type(it.last_error).__name__ if it.last_error else None}")
        if not ids:
            await asyncio.sleep(0.3)
            rows.append(f"   +300ms heal? ids={sorted(it.current_state_ids)}")
    await it.stop(); return rows

def run_sync(mi):
    cfg = copy.deepcopy(MIN); cfg["maxIterations"] = mi
    it = SyncInterpreter(create_machine(cfg, logic=L())); it.start()
    out = []
    for ev in ("GO", "GO"):
        it.send(ev)
        out.append(f"after {ev}: ids={sorted(it.current_state_ids)} ok={it.last_transition_ok}")
    it.stop(); return out

async def main():
    for mi in (1, 5, 1000):
        print(f"== maxIterations={mi} ==")
        print("  sync :", run_sync(mi))
        for r in await run(mi): print("  async:", r)
asyncio.run(main())
