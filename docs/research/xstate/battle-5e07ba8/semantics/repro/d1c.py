import logging, time
logging.disable(logging.CRITICAL)
from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
CFG={"id":"m","initial":"a","states":{"a":{"after":{0:"b"}},"b":{"after":{0:"c"}},"c":{"after":{0:"d"}},"d":{}}}
s=SyncInterpreter(create_machine(CFG,logic=MachineLogic())).start()
s.tick()
c=s.clock
print("ids after 1 tick:",sorted(s.current_state_ids))
print("clock pending timers:",c.pending, " next_due<=now:", c._heap.next_due() is not None and c._heap.next_due()<=c.now())
s.stop()
