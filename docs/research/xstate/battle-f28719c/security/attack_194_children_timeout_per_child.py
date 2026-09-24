"""NEW (f28719c): #194 - children_timeout is PER CHILD (not aggregate),
and the WARNING always fires on overrun. 5 invoked child-machines whose
entry action blocks past the per-child bound: start() must return at
~1x bound (not ~N*bound), machine keeps running, and a WARNING names it.
STANDALONE: stdlib + xstate_statemachine only."""
import sys, asyncio, logging, io, time, warnings
warnings.simplefilter("ignore")
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter

N = 5
BOUND = 0.3

stream = io.StringIO()
h = logging.StreamHandler(stream)
h.setLevel(logging.WARNING)
logging.getLogger("xstate_statemachine").addHandler(h)
logging.getLogger("xstate_statemachine").setLevel(logging.WARNING)

CHILD_CFG = {"id": "child", "initial": "a",
             "states": {"a": {"entry": ["slow_entry"]}}}

async def slow_entry(i, c, e, a):
    await asyncio.sleep(BOUND * 3)

many = {}
for k in range(N):
    many[f"c{k}"] = {"invoke": {"src": "childmachine", "id": f"child{k}"}}
CFG = {"id": "m", "initial": "many", "context": {},
       "states": {"many": {"type": "parallel", "states": many}}}

async def main():
    child_logic = MachineLogic(actions={"slow_entry": slow_entry})
    child_machine = create_machine(CHILD_CFG, logic=child_logic)
    logic = MachineLogic(services={"childmachine": child_machine})
    m = create_machine(CFG, logic=logic)
    interp = Interpreter(m)
    t0 = time.monotonic()
    await interp.start(children_timeout=BOUND)
    elapsed = time.monotonic() - t0
    print(f"N={N} children_timeout={BOUND} elapsed_at_start={elapsed:.3f}s "
          f"(aggregate-bound would be ~{N*BOUND:.1f}s)")
    print("per-child bound holds (elapsed << N*BOUND):", elapsed < BOUND * 2)
    log_text = stream.getvalue()
    print("WARNING logged:", bool(log_text.strip()))
    if log_text.strip():
        print("log excerpt:", log_text.strip().splitlines()[0][:200])
    await interp.stop()

asyncio.run(main())
