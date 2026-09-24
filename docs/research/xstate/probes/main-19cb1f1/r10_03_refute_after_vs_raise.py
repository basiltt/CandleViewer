"""R10-03 refutation: is the timer-paced heartbeat cut ONLY via raise(delay=)?

A) `after` heartbeat ping-pong, maxIterations=8 -- the DOCUMENTED idiom
   (delayed-transitions guide 533-611: a poller that re-enters itself).
B) `raise(delay=)` heartbeat -- same chart shape, same budget.
C) same as B but polled to convergence (10 s) to rule out early sampling.
Both service/action kinds. STANDALONE: stdlib + xstate_statemachine.
"""
import asyncio, json, sys
SRC = sys.argv[1] if len(sys.argv) > 1 else (
    r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref"
    r"/xstate-statemachine/src")
sys.path.insert(0, SRC)
from xstate_statemachine import (Interpreter, MachineLogic, PluginBase,  # noqa
                                 create_machine)
HB = 30

def cfg_after():
    return {"id": "hb", "initial": "up", "maxIterations": 8,
            "context": {"n": 0},
            "states": {
                "up": {"entry": ["beat"], "after": {str(HB): "down"}},
                "down": {"entry": ["beat"], "after": {str(HB): "up"}}}}

def cfg_raise():
    r = {"type": "raise", "params": {"event": "TICK", "delay": HB}}
    return {"id": "hb", "initial": "up", "maxIterations": 8,
            "context": {"n": 0},
            "states": {
                "up": {"entry": ["beat", r], "on": {"TICK": "down"}},
                "down": {"entry": ["beat", r], "on": {"TICK": "up"}}}}

class Drops(PluginBase):
    def __init__(self): self.dropped = []
    def on_event_dropped(self, i, e, reason): self.dropped.append(reason)

def beat_impl(kind):
    def beat(i, c, e, a): c["n"] = c["n"] + 1
    async def abeat(i, c, e, a): beat(i, c, e, a)
    return abeat if kind == "async def" else beat

def mk(cfg, kind):
    return create_machine(json.loads(json.dumps(cfg)),
                          logic=MachineLogic(actions={"beat": beat_impl(kind)}))

async def run(cfg, kind, seconds):
    d = Drops(); i = Interpreter(mk(cfg, kind)).use(d)
    await i.start()
    laps, last, stable = 0, -1, 0
    deadline = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.1); laps += 1
        n = i.context["n"]
        stable = stable + 1 if n == last else 0
        last = n
        if stable >= 20: break          # converged: 2 s with no new beat
    out = (i.context["n"], d.dropped[:1], type(i.last_error).__name__)
    await i.stop(); return out

def go(c): return asyncio.new_event_loop().run_until_complete(c)

if __name__ == "__main__":
    print("SRC:", SRC)
    for kind in ("def", "async def"):
        print(f"A after-heartbeat   [{kind:9}] 6s :", go(run(cfg_after(), kind, 6)))
    for kind in ("def", "async def"):
        print(f"B raise(delay)      [{kind:9}] 6s :", go(run(cfg_raise(), kind, 6)))
    print("C raise(delay) polled to convergence 15s:", go(run(cfg_raise(), "def", 15)))
