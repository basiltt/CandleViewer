import time
from xstate_statemachine import SyncInterpreter, MachineLogic, create_machine
CHILD={"id":"kid","initial":"a","actionErrorPolicy":"fail",
       "states":{"a":{"on":{"BOOM":{"target":"b","actions":["boom"]}}},"b":{}}}
PARENT={"id":"par","initial":"run","states":{
    "run":{"invoke":{"src":"kid","id":"k","onError":{"target":"failed","actions":["rec"]},
                     "onDone":"ok"}},
    "failed":{"type":"final"},"ok":{"type":"final"}}}
def boom(i,c,e,a): raise ValueError("kaput")
seen=[]
def rec(i,c,e,a): seen.append(e.type)
kid=create_machine(CHILD, logic=MachineLogic(actions={"boom":boom}))
m=create_machine(PARENT, logic=MachineLogic(services={"kid":kid},actions={"rec":rec}))
i=SyncInterpreter(m).start()
ch=i._actors["par:k"]
ch.send("BOOM")
for k in range(5):
    i.tick(); time.sleep(0.02)
print("after ticks: child", ch.status, "parent", sorted(i.current_state_ids), "onError", seen)
i.send("NUDGE")
print("after nudge: parent", sorted(i.current_state_ids), "onError", seen)
