"""P2 -- why does the async chain budget never accumulate on the nested-invoke
onDone->ancestor cycle? Trace _raise_depth per lap."""
import asyncio, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import xstate_statemachine.base_interpreter as bi
from xstate_statemachine import Interpreter, create_machine
from gen_config import make_logic

CFG = {"id":"m","initial":"a","maxIterations":5,"states":{"a":{"initial":"a",
  "invoke":{"id":"i1","src":"svc_ok","onDone":{"target":"#m.a"}},
  "states":{"a":{"invoke":{"id":"i2","src":"svc_ok","onDone":{"target":"#m.a"}}}}}}}

rows = []
_o = bi.BaseInterpreter._process_event
async def _p(self, e):
    rows.append((e.type, self._raise_depth, len(self._internal_queue),
                 self._priority_queue.qsize() if hasattr(self._priority_queue,'qsize') else len(self._priority_queue),
                 self._threadsafe_self_sends_in_flight))
    return await _o(self, e)
bi.BaseInterpreter._process_event = _p

async def main():
    i = Interpreter(create_machine(CFG, logic=make_logic(sync=False)))
    await asyncio.wait_for(i.start(), 10)
    await asyncio.sleep(1.0)
    print("lap  event                depth  iq  pq  tsif")
    for r in rows[:25]:
        print(f"     {r[0]:<20} {r[1]:>5} {r[2]:>3} {r[3]:>3} {r[4]:>4}")
    print("total laps in 1s:", len(rows))
    print("last_error:", type(i.last_error).__name__ if getattr(i,'last_error',None) else None)
    await i.stop()
asyncio.run(main())
