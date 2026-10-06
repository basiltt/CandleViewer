import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[3] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys, logging
sys.path.insert(0, str(_XS / 'src'))
logging.disable(logging.CRITICAL)
from xstate_statemachine import create_machine, SyncInterpreter, MachineLogic
from xstate_statemachine.plugins import PluginBase

CFG = lambda pol: {"id":"g","initial":"a","guardErrorPolicy":pol,
  "states":{"a":{"on":{"GO":{"target":"b","guard":"risk_ok"}}},"b":{}}}

class Watch(PluginBase):
    def __init__(self): self.ge=[]
    def on_guard_error(self,*a,**k): self.ge.append(a or k)

def boom(ctx, ev): raise ValueError("risk engine down")

for pol in ("false","true"):
    m = create_machine(CFG(pol), logic=MachineLogic(guards={"risk_ok": boom}))
    w = Watch(); i = SyncInterpreter(m); i.use(w); i.start()
    r = i.send("GO")
    print(f"policy={pol!r:8} receipt={r} last_transition_ok={i.last_transition_ok} "
          f"last_error={i.last_error!r} states={sorted(i.current_state_ids)} on_guard_error_fired={len(w.ge)}")
print("\n-> guard crash is absorbed: receipt.error is None and last_transition_ok True in BOTH policies,")
print("   indistinguishable at the Receipt surface from a legitimate boolean guard result.")
