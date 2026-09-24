"""NEW (f28719c): #199 - snapshot taken from inside on_interpreter_start
must be refused (torn: status=running, empty configuration) on BOTH
engines, confirming the in-flight flag is up before the hook fires.
STANDALONE: stdlib + xstate_statemachine only."""
import sys, asyncio, warnings
warnings.simplefilter("ignore")
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter, Interpreter
from xstate_statemachine.exceptions import SnapshotMidStepError

CFG = {"id": "m", "initial": "a", "context": {}, "states": {"a": {}}}

class SnapPlugin:
    def __init__(self):
        self.result = None
    def on_interpreter_start(self, interpreter):
        try:
            s = interpreter.get_snapshot()
            self.result = ("ACCEPTED", s)
        except SnapshotMidStepError as e:
            self.result = ("REFUSED", type(e).__name__)
        except Exception as e:
            self.result = ("UNCONTROLLED", f"{type(e).__name__}: {e}")
    def __getattr__(self, name):
        return lambda *a, **k: None

# sync engine
m1 = create_machine(CFG, logic=MachineLogic())
p1 = SnapPlugin()
i1 = SyncInterpreter(m1)
i1.use(p1)
i1.start()
print("sync on_interpreter_start snapshot:", p1.result)

# async engine
async def run_async():
    m2 = create_machine(CFG, logic=MachineLogic())
    p2 = SnapPlugin()
    i2 = Interpreter(m2)
    i2.use(p2)
    await i2.start()
    print("async on_interpreter_start snapshot:", p2.result)
    await i2.stop()

asyncio.run(run_async())
