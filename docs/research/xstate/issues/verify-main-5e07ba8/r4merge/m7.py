import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[3] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys, asyncio, json
sys.path.insert(0, str(_XS / 'src'))
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
