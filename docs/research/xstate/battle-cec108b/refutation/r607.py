import json, asyncio
from xstate_statemachine import create_machine, Interpreter
from xstate_statemachine.exceptions import SnapshotDriftError, SnapshotCorruptError

cfg={"id":"m","initial":"a","states":{"a":{"on":{"GO":"b"}},"b":{}}}
m=create_machine(cfg)
async def main():
    i=await Interpreter(m).start(); snap=json.loads(i.get_snapshot()); await i.stop()
    print("version in snap:",snap.get("version"),"| hash present:",snap.get("machine_hash") is not None)
    # variant 1: drop hash, keep version 1  (claimed bug)
    s=dict(snap); s.pop("machine_hash")
    try:
        Interpreter.from_snapshot(json.dumps(s),m); print("A drop-hash(v1): ACCEPTED")
    except Exception as e: print("A:",type(e).__name__,e)
    # variant 2: attacker ALSO downgrades version to 0 -> proposed fix bypassed?
    s2=dict(snap); s2.pop("machine_hash"); s2["version"]=0
    try:
        Interpreter.from_snapshot(json.dumps(s2),m); print("B drop-hash+version=0: ACCEPTED (proposed fix bypassable)")
    except Exception as e: print("B:",type(e).__name__,e)
    # variant 3: attacker keeps hash correct but rewrites state+context (no drift error anyway)
    s3=dict(snap); s3["state_ids"]=["m.b"]; s3["configuration"]=["m.b"]; s3["context"]={"pwned":True}
    try:
        r=Interpreter.from_snapshot(json.dumps(s3),m); print("C valid-hash+forged-state: ACCEPTED, value=",r.current_state_ids,r.context)
    except Exception as e: print("C:",type(e).__name__,e)
asyncio.run(main())
