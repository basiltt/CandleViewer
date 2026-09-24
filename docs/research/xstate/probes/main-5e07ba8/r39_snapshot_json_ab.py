"""End-to-end A/B: a pending DoneEvent with non-JSON data.
At 3c527b0 it was DROPPED (bug #87) so get_snapshot() succeeded.
At 5e07ba8 it is persisted -- does get_snapshot() still serialise?"""
import sys, asyncio, datetime
def run(src,label):
    sys.path.insert(0,src)
    for m in list(sys.modules):
        if m.startswith("xstate_statemachine"): del sys.modules[m]
    from xstate_statemachine import create_machine, MachineLogic, Interpreter
    from xstate_statemachine.events import DoneEvent
    CFG={"id":"m","initial":"a","states":{"a":{"on":{"done.invoke.svc":{"target":"b"}}},"b":{}}}
    async def main():
        i=Interpreter(create_machine(CFG, logic=MachineLogic())); await i.start()
        i._event_queue.put_nowait(DoneEvent(type="done.invoke.svc",
            data={"settled_at": datetime.datetime(2026,1,1)}, src="svc"))
        try:
            s=i.get_snapshot()           # the documented JSON-string API
            print(f"  {label}: get_snapshot() OK, len={len(s)}")
        except Exception as e:
            print(f"  {label}: get_snapshot() RAISED {type(e).__name__}: {e}")
        await i.stop()
    asyncio.run(main()); sys.path.pop(0)
run("/tmp/lib3c/src","3c527b0")
run("C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src","5e07ba8")
