import logging; logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
cnt={"n":0}
def bump(i,c,e,a): cnt["n"]+=1
cfg={"id":"m","initial":"a","states":{"a":{"on":{
  "T":{"actions":[{"type":"raise","params":{"event":"INNER"}}]},
  "INNER":{"actions":["bump"]}}}}}
i=SyncInterpreter(create_machine(cfg, logic=MachineLogic(actions={"bump":bump}))).start()
i.send_events(["T"]*3000)
print("INNER handled:", cnt["n"], "of 3000")
