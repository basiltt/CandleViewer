"""R2 -- greedy shrinker for the residual "resolved send(wait=True) leaves
current_state_ids == []" property on 6db65d8.  Same idea as q13 but with r1's
predicate (send errors are tolerated, three events are driven, and an EMPTY
configuration observed at ANY receipt counts)."""
import asyncio, copy, json, logging, warnings, sys
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, create_machine
from gen_config import make_logic

WHICH = sys.argv[1] if len(sys.argv) > 1 else "0"
BASE = json.loads(open(f"out/q10_cfg_{WHICH}.json", encoding="utf-8").read())
EVS = ("GO", "GO", "PING", "NOPE")


async def once(cfg):
    try:
        it = Interpreter(
            create_machine(copy.deepcopy(cfg), logic=make_logic(sync=False))
        )
        await asyncio.wait_for(it.start(), 8)
    except Exception:
        return None
    bad = False
    try:
        for ev in EVS:
            try:
                await asyncio.wait_for(it.send(ev, wait=True), 8)
            except asyncio.TimeoutError:
                break
            except Exception:
                continue
            if not list(it.current_state_ids):
                bad = True
                break
    except Exception:
        pass
    try:
        await asyncio.wait_for(it.stop(), 5)
    except Exception:
        pass
    return bad


async def holds(cfg, trials=8):
    for _ in range(trials):
        r = await once(cfg)
        if r:
            return True
    return False


def paths(o, pre=()):
    if isinstance(o, dict):
        for k in list(o):
            yield pre + (k,)
            yield from paths(o[k], pre + (k,))


def drop(o, p):
    o = copy.deepcopy(o)
    cur = o
    for k in p[:-1]:
        cur = cur[k]
    cur.pop(p[-1], None)
    return o


async def main():
    cur = copy.deepcopy(BASE)
    if not await holds(cur):
        print("baseline does NOT reproduce; abort")
        return
    print(f"baseline reproduces; size={len(json.dumps(cur))}")
    changed = True
    rounds = 0
    while changed and rounds < 8:
        changed = False
        rounds += 1
        for p in list(paths(cur)):
            if p[-1] in ("id", "initial", "states", "type"):
                continue
            try:
                cand = drop(cur, p)
            except Exception:
                continue
            if json.dumps(cand) == json.dumps(cur):
                continue
            if await holds(cand, trials=6):
                cur = cand
                changed = True
        print(f"  round {rounds}: size={len(json.dumps(cur))}")
    open(f"out/r2_min_{WHICH}.json", "w", encoding="utf-8").write(
        json.dumps(cur, indent=1)
    )
    print(f"FIXPOINT size={len(json.dumps(cur))} -> out/r2_min_{WHICH}.json")
    print(json.dumps(cur, indent=1))


asyncio.run(main())
