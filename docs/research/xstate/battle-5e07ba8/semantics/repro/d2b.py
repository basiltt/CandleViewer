import logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
def run(target, label):
    CFG = {"id":"m","initial":"p","states":{"p":{"type":"parallel","states":{
      "A":{"initial":"right","states":{
          "left":{"initial":"work","states":{"work":{}}},
          "right":{"initial":"work","states":{"work":{}}}}},
      "B":{"initial":"b1","states":{
          "b1":{"on":{"E":{"target":"b2","guard":{"type":"stateIn","params":{"state":target}}}}},
          "b2":{}}}}}}}
    s=SyncInterpreter(create_machine(CFG,logic=MachineLogic())).start()
    s.send("E"); ids=sorted(s.current_state_ids); s.stop()
    print(f"{label:46} target={target!r:24} fired={'m.p.B.b2' in ids}")
run("#m.p.A.left.work","fully-qualified inactive branch (want False)")
run("#m.p.A.right.work","fully-qualified active branch (want True)")
run("work","ambiguous bare leaf name (2 states named work)")
run("left.work","relative path of the INACTIVE branch (want False)")
run("right.work","relative path of the ACTIVE branch (want True)")
