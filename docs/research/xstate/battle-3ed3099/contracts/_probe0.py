import json, sys
from xstate_statemachine import create_machine, MachineLogic
for b in ["B1","B2","B3","B4","B5"]:
    cfg=json.load(open(b+".orig.json",encoding="utf-8"))
    try:
        m=create_machine(cfg, logic=MachineLogic())
        print(b,"BUILD OK")
    except Exception as e:
        print(b,"BUILD FAIL",type(e).__name__,str(e)[:500])
