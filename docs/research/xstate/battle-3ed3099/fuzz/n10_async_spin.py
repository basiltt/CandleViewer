"""N10 -- the async engine's start() RETURNS on the D5-fuzz-1 shape, but does the
run loop keep burning CPU forever afterwards?"""
import asyncio, copy, logging, time, warnings, collections
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import xstate_statemachine.base_interpreter as bi
from xstate_statemachine import Interpreter, create_machine
from gen_config import make_logic
import psutil
C = collections.Counter(); _o = bi.BaseInterpreter._process_event
async def _p(self, e):
    C[e.type] += 1; return await _o(self, e)
bi.BaseInterpreter._process_event = _p
NEST = {"id":"m","initial":"a","states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}
async def main():
    p = psutil.Process()
    i = Interpreter(create_machine(copy.deepcopy(NEST), logic=make_logic(sync=False)))
    await asyncio.wait_for(i.start(), 10)
    print(f"  start() returned; states={sorted(i.current_state_ids)}")
    prev = 0
    for k in range(4):
        c0 = p.cpu_times(); await asyncio.sleep(3); c1 = p.cpu_times()
        n = sum(C.values())
        print(f"  t={3*(k+1):2}s events_total={n:>8} delta={n-prev:>8} "
              f"cpu_delta={c1.user-c0.user:.2f}s rss={p.memory_info().rss//2**20}MB "
              f"status={i.status}")
        prev = n
    await i.stop()
asyncio.run(asyncio.wait_for(main(), 60))
