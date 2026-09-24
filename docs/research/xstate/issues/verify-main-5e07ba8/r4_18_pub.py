import asyncio, gc, time, weakref
from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
CFG={"id":"m","initial":"a","context":{},"states":{"a":{"after":{"1000":"a"}}}}
async def main():
    clock=SimulatedClock(); refs=[]
    # 100% public API: constructor clock=, start, stop. No from_snapshot, no _attach.
    for i in range(30):
        it=Interpreter(create_machine(CFG,logic=MachineLogic()),clock=clock)
        await it.start(); await it.stop(); refs.append(weakref.ref(it))
    gc.collect()
    alive=sum(1 for r in refs if r() is not None)
    print("PUBLIC-API async: settlers=",len(clock._settlers)," alive=",alive,"/",len(refs))
    # CPU growth per tick
    c2=SimulatedClock(); ts=[]
    keep=[]
    for n in range(1,6):
        for _ in range(200):
            it=Interpreter(create_machine(CFG,logic=MachineLogic()),clock=c2)
            await it.start(); await it.stop()
        t=time.perf_counter(); await c2.increment(1); ts.append((len(c2._settlers),round((time.perf_counter()-t)*1000,2)))
    print("settlers vs ms/tick:",ts)
    # sync engine
    c3=SimulatedClock(); srefs=[]
    for _ in range(30):
        s=SyncInterpreter(create_machine(CFG,logic=MachineLogic()),clock=c3).start(); s.stop(); srefs.append(weakref.ref(s))
    gc.collect()
    print("PUBLIC-API sync: settlers=",len(c3._settlers)," alive=",sum(1 for r in srefs if r() is not None),"/",len(srefs))
asyncio.run(main())
