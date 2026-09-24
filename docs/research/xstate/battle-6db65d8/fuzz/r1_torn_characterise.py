"""R1 -- characterise the residual TORN/EMPTY configuration after a resolved
`await send(EV, wait=True)` on this build's own f2 B2 capture.

Questions the prior round's q11 did not answer on 6db65d8:
  * what do the caller-facing signals say at the torn instant
    (last_transition_ok / last_error / status / receipt)?
  * does it HEAL (D7-fuzz-2 never healed)?
  * is it the same with a `def` service as with `async def`?  (the lane that
    was blind)
  * are later events still applied, or silently dropped?
"""
import asyncio, json, logging, warnings, copy, sys
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, create_machine
from xstate_statemachine.exceptions import (
    SnapshotMidStepError,
    SnapshotCorruptError,
)
from gen_config import make_logic

WHICH = sys.argv[1] if len(sys.argv) > 1 else "0"
CFG = json.loads(open(f"out/q10_cfg_{WHICH}.json", encoding="utf-8").read())
EVS = json.loads(open(f"out/q10_evs_{WHICH}.json", encoding="utf-8").read())


def torn(it):
    nodes = list(it._active_state_nodes)
    bad = []
    for n in nodes:
        if getattr(n, "states", None) and getattr(n, "type", "") not in (
            "parallel",
            "final",
        ):
            if len([k for k in n.states.values() if k in nodes]) != 1:
                bad.append(f"{n.id}:{len([k for k in n.states.values() if k in nodes])}")
    return bad


def sig(it):
    return {
        "ids": sorted(it.current_state_ids),
        "ok": it.last_transition_ok,
        "err": type(it.last_error).__name__ if it.last_error else None,
        "status": it.status,
        "torn": torn(it),
    }


async def trial(sync_svc):
    it = Interpreter(
        create_machine(copy.deepcopy(CFG), logic=make_logic(sync=sync_svc))
    )
    await asyncio.wait_for(it.start(), 15)
    out = {"hit": False}
    for ev in ("GO", "GO", "PING"):
        try:
            await asyncio.wait_for(it.send(ev, wait=True), 10)
        except asyncio.TimeoutError:
            out["hit"] = "SEND_TIMEOUT"
            break
        except Exception as e:
            out.setdefault("send_err", type(e).__name__)
            continue
        s = sig(it)
        if s["torn"] or not s["ids"]:
            out["hit"] = True
            out["at_receipt"] = s
            try:
                it.get_persisted_snapshot()
                out["snapshot"] = "PRODUCED"
            except (SnapshotMidStepError, SnapshotCorruptError) as e:
                out["snapshot"] = f"REFUSED:{type(e).__name__}"
            except Exception as e:
                out["snapshot"] = f"UNTYPED:{type(e).__name__}"
            await asyncio.sleep(0.5)
            out["heal_500ms"] = sig(it)
            try:
                await asyncio.wait_for(it.send("GO", wait=True), 5)
            except Exception as e:
                out["later_send"] = type(e).__name__
            out["after_later_send"] = sig(it)
            break
    await it.stop()
    return out


async def main(n=25):
    for kind, sync_svc in (("async def", False), ("plain def", True)):
        hits = 0
        sample = None
        healed = 0
        snaps = {}
        for _ in range(n):
            r = await trial(sync_svc)
            if r["hit"]:
                hits += 1
                sample = sample or r
                snaps[str(r.get("snapshot"))] = snaps.get(str(r.get("snapshot")), 0) + 1
                h = r.get("heal_500ms") or {}
                if h.get("ids") and not h.get("torn"):
                    healed += 1
        print(f"== {kind} svc: torn/empty after resolved send = {hits}/{n}, healed_in_500ms={healed}")
        print(f"   snapshot at torn instant: {snaps}")
        if sample:
            for k in ("at_receipt", "heal_500ms", "later_send", "after_later_send"):
                if k in sample:
                    print(f"   {k}: {sample[k]}")


asyncio.run(main())
