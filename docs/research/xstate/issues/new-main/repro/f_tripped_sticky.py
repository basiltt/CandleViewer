import logging; logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
inner=[]
def bump(i,c,e,a): inner.append(1)
# SPIN self-feeds forever (trips the budget). WORK is an ordinary user event
# whose handler raises exactly one INNER -- one deep, no loop.
cfg={"id":"m","initial":"a","states":{"a":{"on":{
  "SPIN":{"actions":[{"type":"raise","params":{"event":"SPIN"}}]},
  "WORK":{"actions":[{"type":"raise","params":{"event":"INNER"}}]},
  "INNER":{"actions":["bump"]}}}}}
i=SyncInterpreter(create_machine(cfg, logic=MachineLogic(actions={"bump":bump}))).start()
i.send_events(["SPIN"]+["WORK"]*5)
print("INNER handled:", len(inner), "of 5 (expected 5)")
