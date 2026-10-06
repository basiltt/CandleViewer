import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import asyncio, logging, sys
sys.path.insert(0,str(_XS / 'src'))
logging.disable(logging.CRITICAL)
from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine
CFG={"id":"d8","initial":"idle","context":{"ok":0,"cancel":0},
 "states":{"idle":{"on":{"GO":{"target":"busy"}}},
  "busy":{"invoke":{"id":"s","src":"work","onDone":{"target":"idle","actions":["ok"]}},
   "on":{"CANCEL":{"target":"idle","actions":["cancel"]}}}}}
def logic():
    def ok(i,c,e,a): c["ok"]+=1
    def cancel(i,c,e,a): c["cancel"]+=1
    def work(i,c,e): return 1
    return MachineLogic(actions={"ok":ok,"cancel":cancel},services={"work":work})
def build(): return create_machine(CFG,logic=logic())
N=10
async def a():  # DEFAULT clock, no SimulatedClock
    i=Interpreter(build()); await i.start()
    for _ in range(N):
        await i.send("GO"); await i.send("CANCEL")
    await asyncio.sleep(0.2)
    o=dict(i.context); await i.stop(); return o
def s():
    i=SyncInterpreter(build()); i.start()
    for _ in range(N): i.send("GO"); i.send("CANCEL")
    o=dict(i.context); i.stop(); return o
print("default-clock sync :",s())
for t in range(3):
    print("default-clock async:",asyncio.run(a()))
