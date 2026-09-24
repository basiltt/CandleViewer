"""D-semantics: sync `tick()` delivers only ONE due `after` deadline per
call when the deadlines form a chain. Realistic case: a 3-stage timeout
ladder polled every 250 ms; after 1 s of wall clock the machine is two
stages behind."""
import logging, time
logging.disable(logging.CRITICAL)
from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
CFG={"id":"order","initial":"submitted","states":{
 "submitted":{"after":{50:"ack_timeout"}},
 "ack_timeout":{"after":{50:"retry"}},
 "retry":{"after":{50:"escalated"}},
 "escalated":{}}}
s=SyncInterpreter(create_machine(CFG,logic=MachineLogic())).start()
t0=time.time()
for n in range(4):
    time.sleep(0.25); s.tick()
    print(f"t={time.time()-t0:4.2f}s  after tick #{n+1}: "
          f"{sorted(s.current_state_ids)}  (all 3 deadlines due by t=0.25s)")
print("\nEvery deadline was due by 0.15s; a correct pump lands on "
      "['order.escalated'] at the first tick.")
s.stop()
