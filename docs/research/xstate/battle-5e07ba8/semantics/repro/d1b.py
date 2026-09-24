import logging, time
logging.disable(logging.CRITICAL)
from xstate_statemachine import MachineLogic, SyncInterpreter, SimulatedClock, create_machine
CFG={"id":"m","initial":"a","states":{"a":{"after":{0:"b"}},"b":{"after":{0:"c"}},"c":{"after":{0:"d"}},"d":{}}}
CFG10={"id":"m","initial":"a","states":{"a":{"after":{10:"b"}},"b":{"after":{10:"c"}},"c":{"after":{10:"d"}},"d":{}}}
c=SimulatedClock()
s=SyncInterpreter(create_machine(CFG,logic=MachineLogic()),clock=c).start()
print("simclock start:",sorted(s.current_state_ids))
c.increment(1); print("simclock +1ms:",sorted(s.current_state_ids)); s.stop()
# real clock, after:10 chain, ample elapsed time, single tick
s2=SyncInterpreter(create_machine(CFG10,logic=MachineLogic())).start()
time.sleep(0.2); s2.tick(); print("real after:10, 200ms, 1 tick:",sorted(s2.current_state_ids))
time.sleep(0.2); s2.tick(); print("  2nd tick:",sorted(s2.current_state_ids)); s2.stop()
# does an unrelated send() flush the chain?
s3=SyncInterpreter(create_machine(CFG,logic=MachineLogic())).start()
time.sleep(0.05); s3.send("NOPE"); print("after send(NOPE):",sorted(s3.current_state_ids)); s3.stop()
