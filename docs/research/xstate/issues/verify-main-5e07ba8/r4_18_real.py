import asyncio,gc,weakref
from xstate_statemachine import Interpreter,MachineLogic,create_machine
from xstate_statemachine.clock import RealClock
CFG={"id":"m","initial":"a","context":{},"states":{"a":{"after":{"1000":"a"}}}}
async def main():
    c=RealClock(); refs=[]
    for _ in range(30):
        it=Interpreter(create_machine(CFG,logic=MachineLogic()),clock=c)
        await it.start(); await it.stop(); refs.append(weakref.ref(it))
    gc.collect()
    print("RealClock alive:",sum(1 for r in refs if r() is not None),"/",len(refs))
    print("has _attach:",hasattr(c,"_attach"))
asyncio.run(main())
