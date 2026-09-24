"""S-probe 9: #231 inline-dict src message; #235 _replace demotion +
deprecation shims; strict_config interaction."""
import warnings
from xstate_statemachine import create_machine, MachineLogic
from xstate_statemachine.exceptions import InvalidConfigError
from xstate_statemachine.events import (is_system_event, _engine_done,
                                        engine_done, DoneEvent)

CFG = lambda src: {"id": "m", "initial": "a", "states": {
    "a": {"invoke": {"id": "child", "src": src}}}}

for label, src in (("dict", {"id": "inline", "initial": "x", "states": {"x": {}}}),
                   ("list", ["a"]), ("int", 7)):
    try:
        create_machine(CFG(src), logic=MachineLogic())
        print(label, "-> ACCEPTED (no error)")
    except InvalidConfigError as e:
        print(label, "->", str(e)[:150])
    except Exception as e:
        print(label, "-> OTHER", type(e).__name__, str(e)[:100])

e = _engine_done("done.invoke.x", 1, "x")
print("minted system:", is_system_event(e))
r = e._replace(data=2)
print("after _replace:", type(r).__name__, "system:", is_system_event(r))
import copy, pickle
print("deepcopy system:", is_system_event(copy.deepcopy(e)),
      "pickle system:", is_system_event(pickle.loads(pickle.dumps(e))))
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    d = engine_done("done.invoke.y", 1, "y")
    print("shim warns:", [x.category.__name__ for x in w], "still system:", is_system_event(d))
