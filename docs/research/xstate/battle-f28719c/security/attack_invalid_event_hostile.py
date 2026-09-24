"""New attack: InvalidEventError (#113) over hostile event `type` values -
non-str types that a hostile upstream (network/db-sourced event) might hand
to send()."""
import sys
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.exceptions import InvalidEventError

cfg = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
m = create_machine(cfg, logic=MachineLogic())

hostile = [None, 123, 1.5, b"GO", ["GO"], {"type": "GO"}, object(), True, float("nan")]
results = []
for h in hostile:
    interp = SyncInterpreter(m).start()
    try:
        interp.send(h)
        results.append((repr(h), "NO ERROR RAISED"))
    except InvalidEventError as e:
        results.append((repr(h), f"InvalidEventError OK ({type(e).__mro__[:3]})"))
    except Exception as e:
        results.append((repr(h), f"UNCONTROLLED {type(e).__name__}: {e}"))

for h, r in results:
    print(h, "->", r)

bad = [r for h, r in results if not r.startswith("InvalidEventError")]
print("BAD_COUNT:", len(bad))
