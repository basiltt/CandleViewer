import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[3] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys, logging, asyncio
sys.path.insert(0, str(_XS / 'src'))
from xstate_statemachine import create_machine, SyncInterpreter, Interpreter, MachineLogic
from xstate_statemachine.plugins import PluginBase, LoggingInspector

print("=== D-security-1: LoggingInspector redaction ===")
logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True, format="LOG %(message)s")
m = create_machine({"id":"s","initial":"a","context":{"api_key":"sk-live-SECRET123"},
                    "states":{"a":{"on":{"GO":"b"}},"b":{}}}, logic=MachineLogic())
i = SyncInterpreter(m); i.use(LoggingInspector()); i.start()
i.send({"type":"GO","password":"hunter2"})
logging.disable(logging.CRITICAL)

print("\n=== D-observability-8: stop(drain=False) drops queued events with no hook ===")
class Watch(PluginBase):
    def __init__(self): self.dropped=[]
    def on_event_dropped(self,*a,**k): self.dropped.append((a,k))
async def main():
    async def slow(ctx,ev): await asyncio.sleep(0.4)
    m2 = create_machine({"id":"o","initial":"a","states":{
        "a":{"invoke":{"src":"slow","onDone":"a"},"on":{"CMD":"a"}}}},
        logic=MachineLogic(services={"slow":slow}))
    w=Watch(); it=Interpreter(m2); it.use(w); await it.start()
    for n in range(5): await it.send(f"CMD")
    pend = it.pending_events
    print(f"  pending_events before stop : {len(pend)}")
    await it.stop()
    print(f"  status after stop(drain=False): {it.status}")
    print(f"  on_event_dropped fired for them: {len(w.dropped)}")
    print("  -> 5 accepted events vanish with zero observability signal" if len(w.dropped)==0 else "  hook fired")
asyncio.run(main())
