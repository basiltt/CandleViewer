"""Q7 -- D6-fuzz-2 follow-up. #171 claims start() returns with initial invokes
registered and (#116) start(); send(X) orders identically on both engines.
Is the remaining divergence observable in OUTCOME, or only in the transient
current_state_ids read between start() and the first send?"""
import asyncio, copy, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

CFG = {"id": "m", "initial": "a", "states": {
    "a": {"invoke": {"id": "i", "src": "svc", "onDone": {"target": "b"}},
          "on": {"GO": {"target": "z"}}},
    "b": {"on": {"GO": {"target": "c"}}}, "c": {}, "z": {}}}
def svc(i, c, e): return 1
L = MachineLogic(services={"svc": svc})

def sync_run():
    it = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=L)); it.start()
    at = sorted(it.current_state_ids); it.send("GO")
    r = sorted(it.current_state_ids); it.stop(); return at, r

async def async_run():
    it = Interpreter(create_machine(copy.deepcopy(CFG), logic=L))
    await asyncio.wait_for(it.start(), 10)
    at = sorted(it.current_state_ids)
    await it.send("GO", wait=True)
    r = sorted(it.current_state_ids); await it.stop(); return at, r

async def main():
    s_at, s_r = sync_run()
    outcome_div = 0; view_div = 0; sample = None
    for _ in range(20):
        a_at, a_r = await async_run()
        if a_r != s_r: outcome_div += 1
        if a_at != s_at: view_div += 1
        sample = (a_at, a_r)
    print(f"  sync   after_start={s_at} after_GO={s_r}")
    print(f"  async  sample      ={sample[0]} after_GO={sample[1]}")
    print(f"  OUTCOME divergence (state after GO): {outcome_div}/20  "
          f"{'PASS -- #116 parity holds' if outcome_div == 0 else 'FAIL'}")
    print(f"  VIEW divergence (current_state_ids at start() return): {view_div}/20")
asyncio.run(main())
