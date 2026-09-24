import logging, time
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
seen=[]
def note(i,c,e,a): seen.append(e.type)
# 'loop' state self-feeds; 'TICK' is a due timer event that arrives during the drain.
cfg={"id":"m","initial":"loop","states":{
 "loop":{"entry":[{"type":"raise","params":{"event":"GO"}}],"on":{"GO":{"target":"loop","actions":["note"]}}}}}
i=SyncInterpreter(create_machine(cfg), logic=None) if False else SyncInterpreter(create_machine(cfg, logic=MachineLogic(actions={"note":note})))
i.start()
print("GO delivered:", seen.count("GO"), "final:", i.current_state_ids, "status:", i.status)
