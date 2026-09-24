"""Q13 -- automatic shrinker for Q11's torn-after-receipt case. Greedily delete
keys/subtrees from the captured config while the property still holds:
`await send(GO, wait=True)` resolves with current_state_ids == []."""
import asyncio, copy, json, logging, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, create_machine
from gen_config import make_logic

BASE = json.loads(open("out/q10_cfg.json", encoding="utf-8").read())

async def holds(cfg, trials=6):
    """True if at least one of `trials` runs ends with an empty configuration
    after a resolved send()."""
    for _ in range(trials):
        try:
            it = Interpreter(create_machine(copy.deepcopy(cfg), logic=make_logic(sync=False)))
            await asyncio.wait_for(it.start(), 8)
        except Exception:
            return False
        bad = False
        try:
            for ev in ("GO", "GO"):
                await asyncio.wait_for(it.send(ev, wait=True), 8)
                if not list(it.current_state_ids): bad = True; break
        except Exception:
            bad = False
        try: await asyncio.wait_for(it.stop(), 5)
        except Exception: pass
        if bad: return True
    return False

def paths(o, pre=()):
    if isinstance(o, dict):
        for k in list(o):
            yield pre + (k,)
            yield from paths(o[k], pre + (k,))

def get(o, p):
    for k in p: o = o[k]
    return o

def drop(cfg, p):
    c = copy.deepcopy(cfg)
    parent = get(c, p[:-1]); del parent[p[-1]]
    return c

PROTECT = {"id", "initial", "states", "type"}

async def main():
    cur = copy.deepcopy(BASE)
    if not await holds(cur):
        print("baseline does NOT reproduce; abort"); return
    print("baseline reproduces")
    changed = True; rounds = 0
    while changed and rounds < 8:
        changed = False; rounds += 1
        for p in list(paths(cur)):
            if p[-1] in PROTECT: continue
            try: cand = drop(cur, p)
            except Exception: continue
            try:
                if await holds(cand):
                    cur = cand; changed = True
            except Exception: pass
        print(f"  round {rounds}: size={len(json.dumps(cur))}")
    json.dump(cur, open("out/q13_torn_min.json", "w", encoding="utf-8"), indent=1)
    print(json.dumps(cur, indent=1))
asyncio.run(main())
