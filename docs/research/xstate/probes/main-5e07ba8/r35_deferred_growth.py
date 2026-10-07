"""_deferred_this_step is a plain Set[int] that is only ever discarded via a
RECEIPT path. Fire-and-forget defers leak an entry each. Unbounded?"""
import sys, asyncio
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
CFG={"id":"m","initial":"a","onUnhandled":"defer","deferLimit":1,"states":{"a":{"on":{"GO":{"target":"a"}}}}}
async def main():
    i=Interpreter(create_machine(CFG, logic=MachineLogic())); await i.start()
    for n in range(50000):
        await i.send(f"NOPE{n}")
    await asyncio.sleep(1.0)
    print("deferred_events held :", len(i._deferred_events))
    print("_deferred_this_step  :", len(i._deferred_this_step), "<- grows without bound")
    import sys as s; print("approx bytes:", s.getsizeof(i._deferred_this_step))
    await i.stop()
asyncio.run(main())
