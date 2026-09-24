import json
from xstate_statemachine import create_machine, Interpreter
cfg={"id":"m","initial":"a","states":{"a":{"on":{"GO":"b"}},"b":{}}}
m1=create_machine(cfg)
i=Interpreter(m1); import asyncio
async def go():
    await i.start(); i.send("GO"); await asyncio.sleep(0.05)
    s=json.loads(i.get_snapshot()); await i.stop(); return s
snap=asyncio.run(go())
print("snap state_ids:",snap["state_ids"])
# machine drifted: state 'b' renamed to 'c'
cfg2={"id":"m","initial":"a","states":{"a":{"on":{"GO":"c"}},"c":{}}}
m2=create_machine(cfg2)
for label,mut in [("hash present (control)",lambda s:s),("hash dropped",lambda s:{k:v for k,v in s.items() if k!="machine_hash"})]:
    s=mut(dict(snap))
    try:
        r=Interpreter.from_snapshot(json.dumps(s),m2)
        print(f"{label}: ACCEPTED -> state_ids={r.current_state_ids} value={r.value}")
        try:
            asyncio.run(r.start()); r.send("GO")
            print("   started ok, post-send:",r.current_state_ids)
        except Exception as e: print("   start/send blew up:",type(e).__name__,e)
    except Exception as e: print(f"{label}: {type(e).__name__}: {str(e)[:90]}")
