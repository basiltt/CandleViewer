import json, asyncio
from xstate_statemachine import create_machine, Interpreter, MachineLogic
cfg={"id":"m","initial":"a","states":{"a":{"on":{"GO":"b"}},"b":{"on":{"NEXT":"a"}}}}
m1=create_machine(cfg)
async def go():
    i=Interpreter(m1); await i.start(); i.send("GO"); await asyncio.sleep(0.05)
    s=json.loads(i.get_snapshot()); await i.stop(); return s
snap=asyncio.run(go())
cfg2={"id":"m","initial":"a","states":{"a":{"on":{"GO":"b"}},"b":{"on":{"NEXT":{"target":"a","guard":"ok"}}}}}
m2=create_machine(cfg2, logic=MachineLogic(guards={"ok":lambda c,e:False}))
s={k:v for k,v in snap.items() if k!="machine_hash"}
r=Interpreter.from_snapshot(json.dumps(s),m2)
print("hash dropped, id-preserving drift: ACCEPTED silently, state=",r.current_state_ids)
s2=dict(snap)
try: Interpreter.from_snapshot(json.dumps(s2),m2); print("control: ACCEPTED (bad)")
except Exception as e: print("control with hash:",type(e).__name__)
