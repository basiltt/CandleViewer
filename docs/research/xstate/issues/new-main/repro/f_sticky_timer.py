import logging, time; logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
cfg={"id":"m","initial":"a","maxIterations":20,"states":{
 "a":{"after":{5:{"target":"done"}},
      "on":{"SPIN":{"target":"a","reenter":False,"actions":[{"type":"raise","params":{"event":"SPIN"}}]}}},
 "done":{"type":"final"}}}
i=SyncInterpreter(create_machine(cfg)).start()
i.send("SPIN")     # trips the budget
time.sleep(0.05)
i.tick()           # the `after` deadline is now due
print("state after tick:", i.current_state_ids, "(expected m.done)")
