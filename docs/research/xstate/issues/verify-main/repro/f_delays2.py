import warnings, logging
logging.basicConfig(level=logging.DEBUG)
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter, SimulatedClock
cfg={"id":"m","initial":"a","states":{"a":{"after":{"MY_DELAY":{"target":"b"}}},"b":{"type":"final"}}}
c=SimulatedClock()
m=create_machine(cfg, logic=MachineLogic(delays={"my_delay":10}))
i=SyncInterpreter(m, clock=c).start()
c.advance(100); i.tick()
print("FINAL state", i.current_state_ids)
