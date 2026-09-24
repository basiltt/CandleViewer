import sys, asyncio, json
sys.path.insert(0, r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, Interpreter, MachineLogic
async def svc(i,c,e):
    await asyncio.sleep(5); return 1
m=create_machine({"id":"v","initial":"a","states":{"a":{"invoke":{"src":"svc","id":"svc","onDone":"b"}},"b":{}}}, logic=MachineLogic(services={"svc":svc}))
async def main():
    i=Interpreter(m); await i.start(); await asyncio.sleep(0.05)
    snap=i.get_persisted_snapshot(); await i.stop()
    s = snap if isinstance(snap,str) else json.dumps(snap)
    i4=Interpreter.from_snapshot(s, m, restart_services=True)
    print("OBS7 before start: status=", i4.status, "dormant=", i4.has_dormant_invocations, "pending=", i4.pending_invocations())
    await i4.start(); await asyncio.sleep(0.05)
    print("OBS7 after start : dormant=", i4.has_dormant_invocations)
    await i4.stop()
asyncio.run(main())
