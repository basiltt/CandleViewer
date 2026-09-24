import logging; logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.clock import SimulatedClock
got=[]
def note(i,c,e,a): got.append(e.type)
# self-feeding loop trips the budget; a due `after` timer event is self-generated too
cfg={"id":"m","initial":"a","states":{"a":{
  "after":{0:{"target":"b","actions":["note"]}},
  "on":{"SPIN":{"actions":[{"type":"raise","params":{"event":"SPIN"}}]}}},
  "b":{}}}
i=SyncInterpreter(create_machine(cfg, logic=MachineLogic(actions={"note":note}))).start()
i.send("SPIN")
print("after-timer fired?", got, "state:", i.current_state_ids)
