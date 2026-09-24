"""Standalone repros D14-semantics-1 (re_mint type forgery) and -2 (SyncInterpreter overflow_policy)."""
import asyncio, json, logging, inspect
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase
from xstate_statemachine import events as E
logging.disable(logging.CRITICAL)
CFG = {"id": "v", "initial": "a", "strict": True, "states": {
    "a": {"invoke": {"id": "benign", "src": "benign", "onDone": "b"}},
    "b": {"invoke": {"id": "victim", "src": "victim", "onDone": "PAID"}}, "PAID": {}}}
class Cap(PluginBase):
    def __init__(s): s.ev = []
    def on_event_received(s, i, e): s.ev.append(e)
async def victim(i, c, e): await asyncio.sleep(30)
async def run(forge):
    cap = Cap()
    i = await Interpreter(create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic(
        services={"benign": lambda i, c, e: 1, "victim": victim}))).use(cap).start()
    for _ in range(100):
        if i.value == "b": break
        await asyncio.sleep(0.01)
    src = next(e for e in cap.ev if e.type == "done.invoke.benign")
    ev = forge(src)
    try: await i.send(ev)
    except Exception as x: return "raised " + type(x).__name__
    for _ in range(30): await asyncio.sleep(0.01)
    v = i.value; await i.stop(); return v
async def main():
    print("hand-built DoneEvent        ->", await run(lambda s: E.DoneEvent("done.invoke.victim", {"f": 1}, "victim")))
    print("_replace demoted            ->", await run(lambda s: s._replace(type="done.invoke.victim", src="victim")))
    print("re_mint(data only, benign)  ->", await run(lambda s: E.re_mint(s, data={"f": 1})))
    print("re_mint(type->victim)       ->", await run(lambda s: E.re_mint(s, type="done.invoke.victim", src="victim", data={"f": 1})))
asyncio.run(asyncio.wait_for(main(), 30))
m = create_machine({"id": "q", "initial": "a", "states": {"a": {}}})
for kw in ({"max_queue_size": 5}, {"overflow_policy": "drop"}, {"overflow_policy": "raise"}):
    try: SyncInterpreter(m, **kw); print("SyncInterpreter", kw, "-> accepted")
    except Exception as x: print("SyncInterpreter", kw, "->", type(x).__name__)
print(inspect.signature(SyncInterpreter.__init__))
# cross-kind: an AfterEvent the engine minted, retyped to a completion
AC = {"id": "w", "initial": "a", "strict": True, "states": {
    "a": {"after": {"10": "b"}},
    "b": {"invoke": {"id": "victim", "src": "victim", "onDone": "PAID"}}, "PAID": {}}}
async def cross():
    cap = Cap()
    i = await Interpreter(create_machine(AC, logic=MachineLogic(services={"victim": victim}))).use(cap).start()
    for _ in range(100):
        if i.value == "b": break
        await asyncio.sleep(0.01)
    src = next(e for e in cap.ev if e.type.startswith("after."))
    await i.send(E.re_mint(src, type="done.invoke.victim"))
    await asyncio.sleep(0.2); v = i.value; await i.stop(); return v
print("re_mint(AfterEvent, type->done.invoke.victim) ->", asyncio.run(cross()))
