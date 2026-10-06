import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[3] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys, asyncio, logging, io
sys.path.insert(0, str(_XS / 'src'))
from xstate_statemachine import create_machine, SyncInterpreter, Interpreter, MachineLogic
from xstate_statemachine.plugins import LoggingInspector

# --- D-observability-2: guard raise absorbed
cfg={"id":"g","initial":"a","states":{"a":{"on":{"GO":{"target":"b","guard":"boom"}}},"b":{}}}
for pol in ("false","true"):
    c=dict(cfg); c["guardErrorPolicy"]=pol
    def boom(ctx,e): raise ValueError("guard blew up")
    m=create_machine(c, logic=MachineLogic(guards={"boom":boom}))
    i=SyncInterpreter(m); i.start()
    r=i.send("GO")
    print(f"OBS2 policy={pol}: receipt={r} last_transition_ok={i.last_transition_ok} last_error={i.last_error}")

# --- D-security-1: LoggingInspector logs secrets
buf=io.StringIO(); h=logging.StreamHandler(buf); logging.getLogger().addHandler(h); logging.getLogger().setLevel(logging.INFO)
m2=create_machine({"id":"s","initial":"a","context":{"api_key":"sk-live-SECRET123"},"states":{"a":{"on":{"GO":"b"}},"b":{}}})
i2=SyncInterpreter(m2); i2.use(LoggingInspector()); i2.start(); i2.send("GO")
logging.getLogger().removeHandler(h)
print("SEC1 secret in logs:", "sk-live-SECRET123" in buf.getvalue())

# --- D-observability-8: stop(drain=False) abandons queued events with no hook
class P:
    def __init__(self): self.dropped=[]
    def on_event_dropped(self, interp, event, reason=None, **kw): self.dropped.append((getattr(event,'type',event),reason))
async def main():
    async def slow(ctx,e): await asyncio.sleep(0.4)
    m3=create_machine({"id":"q","initial":"a","states":{"a":{"on":{"GO":{"target":"a","actions":["slow"]},"CMD":{"target":"a"}}}}},
                      logic=MachineLogic(actions={"slow":slow}))
    p=P(); i3=Interpreter(m3); i3.use(p); await i3.start()
    await i3.send("GO")
    for n in range(5): await i3.send("CMD")
    pend=i3.pending_events() if callable(getattr(i3,'pending_events',None)) else None
    print("OBS8 pending before stop:", len(pend) if pend is not None else '?')
    await i3.stop()
    print("OBS8 status:", i3.status, "dropped hook calls:", p.dropped)
asyncio.run(main())
