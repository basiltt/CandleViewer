"""Q11 -- does `await send(EV, wait=True)` resolve while the configuration is
still TORN (a compound with 0 active children)? The receipt is the caller's
'this step is done' signal; an OMS reads state right after it.
Also: can a get_persisted_snapshot() taken at that instant be PRODUCED?"""
import asyncio, json, logging, warnings, copy
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError, SnapshotCorruptError
from gen_config import make_logic

CFG = json.loads(open("out/q10_cfg.json", encoding="utf-8").read())

def torn(it):
    nodes = list(it._active_state_nodes)
    bad = []
    for n in nodes:
        if getattr(n, "states", None) and getattr(n, "type", "") not in ("parallel", "final"):
            if len([k for k in n.states.values() if k in nodes]) != 1:
                bad.append(n.id)
    return bad

async def trial(k):
    it = Interpreter(create_machine(copy.deepcopy(CFG), logic=make_logic(sync=False)))
    await asyncio.wait_for(it.start(), 15)
    res = {"torn_after_receipt": None, "snapshot": None, "ids": None}
    for ev in ("GO", "GO"):
        try:
            r = await asyncio.wait_for(it.send(ev, wait=True), 10)
        except asyncio.TimeoutError:
            res["torn_after_receipt"] = "SEND_TIMEOUT"; break
        b = torn(it)
        if b:
            res["torn_after_receipt"] = b
            res["ids"] = sorted(it.current_state_ids)
            try:
                it.get_persisted_snapshot(); res["snapshot"] = "PRODUCED (torn persisted!)"
            except (SnapshotMidStepError, SnapshotCorruptError) as e:
                res["snapshot"] = f"REFUSED:{type(e).__name__}"
            except Exception as e:
                res["snapshot"] = f"UNTYPED:{type(e).__name__}"
            break
    await it.stop(); return res

async def main():
    hits = 0; sample = None; snaps = {}
    N = 40
    for k in range(N):
        r = await trial(k)
        if r["torn_after_receipt"]:
            hits += 1; sample = sample or r
            snaps[str(r["snapshot"])] = snaps.get(str(r["snapshot"]), 0) + 1
    print(f"  torn configuration visible after send(wait=True) resolved: {hits}/{N}")
    print(f"  sample={sample}")
    print(f"  snapshot outcomes at the torn instant: {snaps}")
asyncio.run(main())
