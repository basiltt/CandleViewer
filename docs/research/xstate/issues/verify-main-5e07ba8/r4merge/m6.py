import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[3] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys
sys.path.insert(0, str(_XS / 'src'))
from xstate_statemachine import create_machine, SyncInterpreter, MachineLogic
class P:
    def __init__(s): s.calls=[]
    def __getattr__(s,n):
        if n.startswith("on_"):
            def f(*a,**k): s.calls.append(n)
            return f
        raise AttributeError(n)
m2=create_machine({"id":"s","initial":"a","states":{"a":{"on":{"GO":"nowhere"}}}}, strict_targets=False)
p=P(); i2=SyncInterpreter(m2); i2.use(p); i2.start()
r=i2.send("GO", wait=True)
print("OBS5 receipt:", r, "last_error:", type(i2.last_error).__name__, "hooks:", sorted(set(p.calls)))
m3=create_machine({"id":"v","initial":"a","states":{"a":{"invoke":{"src":"svc","id":"svc","onDone":"b"}},"b":{}}}, logic=MachineLogic(services={"svc":lambda i,c,e: 1}))
i3=SyncInterpreter(m3); i3.start(); snap=i3.get_persisted_snapshot()
i4=SyncInterpreter.from_snapshot(__import__("json").dumps(snap), m3, restart_services=True)
print("OBS7 before start: status=", i4.status, "dormant=", i4.has_dormant_invocations)
i4.start(); print("OBS7 after start: dormant=", i4.has_dormant_invocations)
