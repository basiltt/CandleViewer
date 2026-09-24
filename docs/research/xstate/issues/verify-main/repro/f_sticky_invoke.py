import logging; logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
def svc(i,c,e): return {"v":1}
cfg={"id":"m","initial":"a","maxIterations":20,"states":{
 "a":{"on":{"SPIN":{"target":"a","actions":[{"type":"raise","params":{"event":"SPIN"}}]},
            "GO":{"target":"work"}}},
 "work":{"invoke":{"src":"svc","onDone":{"target":"done"}}},
 "done":{"type":"final"}}}
i=SyncInterpreter(create_machine(cfg, logic=MachineLogic(services={"svc":svc}))).start()
i.send_events(["SPIN","GO"])
print("state:", i.current_state_ids, "(expected m.done)")
