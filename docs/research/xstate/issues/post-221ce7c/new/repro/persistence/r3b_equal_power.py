"""Does the version-downgrade give the editor anything they lack?"""
import asyncio, json, sys
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, Interpreter, SyncInterpreter
from xstate_statemachine.exceptions import SnapshotDriftError
from r3_version_downgrade import SNAP_MACHINE, DRIFTED_MACHINE

async def run(kind, cls):
    snap_m = create_machine(SNAP_MACHINE); drift_m = create_machine(DRIFTED_MACHINE)
    i = cls(snap_m); r=i.start()
    if asyncio.iscoroutine(r): await r
    raw = json.loads(i.get_snapshot()); r=i.stop()
    if asyncio.iscoroutine(r): await r
    print(f"--- {kind} ---")
    print("  structure_hash is public/unkeyed:", drift_m.structure_hash)

    # A) forge the hash to the TARGET machine's hash, keep version intact
    a = dict(raw); a["machine_hash"] = drift_m.structure_hash
    # B) keep everything intact but rewrite the active state directly
    b = dict(raw); b["machine_hash"] = drift_m.structure_hash; b["state_ids"]=["acct.c"]
    for name,p in (("forged hash, version intact",a),("forged hash + state_ids=c",b)):
        try:
            ri = cls.from_snapshot(json.dumps(p), drift_m)
            r=ri.start()
            if asyncio.iscoroutine(r): await r
            print(f"  {name}: ACCEPTED states={sorted(ri.current_state_ids)}")
            r=ri.stop()
            if asyncio.iscoroutine(r): await r
        except Exception as e:
            print(f"  {name}: {type(e).__name__}: {str(e)[:80]}")

asyncio.run(run("async", Interpreter)); asyncio.run(run("sync", SyncInterpreter))
