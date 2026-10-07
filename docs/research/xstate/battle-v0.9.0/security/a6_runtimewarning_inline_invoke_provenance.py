"""#232 RuntimeWarning on a never-awaited def-action wait=True guard,
verified inside asyncio under -W error (where must a supervisor catch it?).
#231 inline-dict invoke.src -> named InvalidConfigError.
#235 pickle/deepcopy preserve provenance (documented intent, not a hole).
STANDALONE."""
import sys, asyncio, warnings, pickle, copy, gc
sys.path.insert(0, "<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.exceptions import InvalidConfigError
import xstate_statemachine.events as ev_mod

# --- Part A: #232 RuntimeWarning surfaces where? ---
cfg = {
    "id": "m", "initial": "a",
    "states": {"a": {"entry": ["dropit"], "on": {"GO": "b"}}, "b": {}},
}

def dropit(i, c, e, a):
    # def action cannot await; hands the guard object and drops it.
    r = i.send("GO", wait=True)  # noqa: F841 -- deliberately unused/dropped


async def main():
    m = create_machine(cfg, logic=MachineLogic(actions={"dropit": dropit}))
    interp = Interpreter(m)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await interp.start()
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0.05)
    kinds = [str(w.category.__name__) for w in caught]
    msgs = [str(w.message) for w in caught]
    print("A) categories seen:", kinds)
    print("A) RuntimeWarning present:", "RuntimeWarning" in kinds)
    print("A) message sample:", next((m_ for m_ in msgs if "never" in m_.lower() or "await" in m_.lower()), msgs[:1]))
    await interp.stop()

asyncio.run(main())

# --- Part B: -W error escalates it to an exception -- confirm it surfaces
# as an unhandled exception in gc, not silently inside the interpreter.
async def main_werror():
    m = create_machine(cfg, logic=MachineLogic(actions={"dropit": dropit}))
    interp = Interpreter(m)
    warnings.simplefilter("error", RuntimeWarning)
    try:
        await interp.start()
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0.05)
        outcome = "no exception surfaced to caller (warning is a GC-time side effect, not raised in-line)"
    except RuntimeWarning as ex:
        outcome = f"RuntimeWarning raised in-line: {ex}"
    finally:
        warnings.resetwarnings()
    print("B) -W error outcome:", outcome)
    if interp.status == "running":
        await interp.stop()

asyncio.run(main_werror())

# --- Part C: #231 inline-dict invoke.src named InvalidConfigError ---
bad_cfg = {
    "id": "m", "initial": "a",
    "states": {
        "a": {
            "invoke": {
                "id": "child",
                "src": {"id": "inline", "initial": "x", "states": {"x": {}}},
                "onDone": "b",
            }
        },
        "b": {},
    },
}
try:
    create_machine(bad_cfg, logic=MachineLogic())
    print("C) inline-dict invoke.src: NO ERROR RAISED (unexpected)")
except InvalidConfigError as ex:
    print("C) inline-dict invoke.src -> InvalidConfigError (named):", ex)
except TypeError as ex:
    print("C) inline-dict invoke.src -> TypeError (regression, #231 not fixed):", ex)

# --- Part D: #235 pickle/deepcopy preserve provenance (documented, not a hole) ---
forged = ev_mod._EngineDone("done.invoke.svc", {"x": 1}, "svc")
p = pickle.loads(pickle.dumps(forged))
d = copy.deepcopy(forged)
print("D) pickle preserves provenance:", ev_mod.is_system_event(p), type(p).__name__)
print("D) deepcopy preserves provenance:", ev_mod.is_system_event(d), type(d).__name__)
print("D) _replace demotes to public class:", type(forged._replace(data={})).__name__,
      ev_mod.is_system_event(forged._replace(data={})))
