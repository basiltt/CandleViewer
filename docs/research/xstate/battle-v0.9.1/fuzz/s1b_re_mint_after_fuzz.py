"""S1b -- re_mint mutation fuzz, BOTH engines. Capture a genuine engine-minted
event (after-timer on sync; done.invoke on async), mutate type/src/data to
target an unrelated transition, count transitions the original could not
drive. CONTROL: same mutated event hand-built. Async engine only (sync services resolve inline,
so there is no pending victim to target). STANDALONE."""
import asyncio, logging, random, time, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 PluginBase, create_machine)
from xstate_statemachine import events as E

CFG = {"id": "s", "type": "parallel", "states": {
  "T": {"initial": "a", "states": {"a": {"after": {"10": "b"}}, "b": {}}},
  "V": {"initial": "w", "states": {"w": {"invoke": {"id": "victim", "src": "victim",
        "onDone": "PAID", "onError": "FAILED"}}, "PAID": {}, "FAILED": {}}}}}

class Cap(PluginBase):
    def __init__(s): s.ev = []
    def on_event_received(s, it, ev):
        if E.is_system_event(ev): s.ev.append(ev)

TARGETS = ["done.invoke.victim", "error.platform.victim"]
async def amain():
    rnd = random.Random(11); res = {"re_mint": [0, 0], "hand": [0, 0]}
    for trial in range(40):
        mode = "re_mint" if trial % 2 else "hand"; tgt = rnd.choice(TARGETS)
        cap = Cap()
        async def victim(i, c, e): await asyncio.sleep(3600)
        it = Interpreter(create_machine(CFG, logic=MachineLogic(services={"victim": victim})))
        it.use(cap); await it.start()
        for _ in range(40):
            await asyncio.sleep(0.005)
            if cap.ev: break
        src = cap.ev[0]
        kind = "error" if tgt.startswith("error") else "done"
        if mode == "re_mint":
            # re_mint keeps the class of the original (AfterEvent/DoneEvent)
            ev = E.re_mint(src, type=tgt)
        else:
            ev = (E.DoneEvent(tgt, {}, "victim") if kind == "done" else E.ErrorEvent(tgt, RuntimeError("x"), "victim"))
        await it.send(ev)
        for _ in range(6): await asyncio.sleep(0.005)
        ids = it.current_state_ids
        moved = any(s.endswith(("PAID", "FAILED")) for s in ids)
        res[mode][0] += 1; res[mode][1] += moved
        await it.stop()
    print("async engine (captured=%s):" % type(src).__name__, {k: f"{v[1]}/{v[0]} forged transitions" for k, v in res.items()})
    return res

r = asyncio.run(amain())
print("DEFECTS =", 1 if r["re_mint"][1] else 0)
