"""Q10 -- replay the f2 B2-illegal-configuration hit captured on 221ce7c.
Is the torn compound (0 active children) stable, or a transient sample of the
D7-fuzz-1 spin? Drive both engines, with and without a settle delay."""
import asyncio, json, logging, warnings, copy, sys
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, SyncInterpreter, create_machine
from gen_config import make_logic

CFG = json.loads(open("out/q10_cfg.json", encoding="utf-8").read())

def legality(it):
    ids = set(it.current_state_ids)
    nodes = list(it._active_state_nodes)
    bad = []
    for n in nodes:
        if getattr(n, "states", None) and getattr(n, "type", "") != "parallel":
            kids = [k for k in n.states.values() if k in nodes]
            if len(kids) != 1 and getattr(n, "type", "") != "final":
                bad.append(f"{n.id}:{len(kids)}")
    return "LEGAL" if not bad else "TORN " + ",".join(bad)

def sync_run(evs):
    it = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=make_logic(sync=True)))
    it.start(); out = [legality(it)]
    for e in evs:
        try: it.send(e)
        except Exception as ex: out.append(f"raise:{type(ex).__name__}")
        out.append(legality(it))
    err = type(it.last_error).__name__ if it.last_error else None
    it.stop(); return out, err

async def async_run(evs, settle):
    it = Interpreter(create_machine(copy.deepcopy(CFG), logic=make_logic(sync=False)))
    await asyncio.wait_for(it.start(), 15)
    if settle: await asyncio.sleep(settle)
    out = [legality(it)]
    for e in evs:
        try: await asyncio.wait_for(it.send(e, wait=True), 10)
        except asyncio.TimeoutError: out.append("SEND_TIMEOUT")
        except Exception as ex: out.append(f"raise:{type(ex).__name__}")
        if settle: await asyncio.sleep(settle)
        out.append(legality(it))
    err = type(it.last_error).__name__ if it.last_error else None
    await it.stop(); return out, err

async def main():
    evs = ["GO", "GO"]
    o, e = sync_run(evs); print(f"  sync            {o} last_error={e}")
    for s in (0, 0.05, 0.3):
        o, e = await async_run(evs, s)
        print(f"  async settle={s:<5} {o} last_error={e}")
asyncio.run(main())
