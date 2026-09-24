"""R4-04 repro: SyncInterpreter.start() never terminates for a cross-region
`always` transition that re-enters an invoking state.

Exits 1 while the defect is present (start() has not returned inside the
budget), 0 once fixed (start() returns, or raises a typed error).
Stdlib + xstate_statemachine only.
"""

import logging
import sys
import threading
import time

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

# The library logs "Exceeded 1000 microsteps ... Aborting" once per settling
# pass -- tens of thousands of times here, which is itself evidence that the
# budget is re-armed rather than terminal.  Counted, not printed.
BUDGET_S = 20.0


class _Counter(logging.Handler):
    count = 0

    def emit(self, record):
        _Counter.count += 1


logging.getLogger("xstate_statemachine").handlers[:] = [_Counter()]
logging.getLogger("xstate_statemachine").propagate = False

# `B.b1` has an eventless transition into the *other* region's invoking state
# `A.a1`.  Re-entering `A.a1` re-arms `invoke: svc`, whose `onDone` targets
# `a1` again -> the settling loop is re-entered from a fresh macrostep with
# `iterations` reset to 0 every time, so the microstep budget never bites.
CFG = {
    "id": "m",
    "type": "parallel",
    "maxIterations": 1000,  # library default, stated explicitly
    "states": {
        "A": {
            "initial": "a1",
            "states": {
                "a1": {"invoke": {"id": "s", "src": "svc", "onDone": "a1"}},
                "a2": {},
            },
        },
        "B": {
            "initial": "b1",
            "states": {"b1": {"always": {"target": "#m.A.a1"}}},
        },
    },
}


def svc(interpreter, ctx, event):
    return 1


result = {}


def run():
    t0 = time.time()
    interp = SyncInterpreter(
        create_machine(CFG, logic=MachineLogic(services={"svc": svc}))
    )
    try:
        interp.start()
    except Exception as exc:  # a typed RunawayChainError would be acceptable
        result["error"] = repr(exc)
    result["elapsed"] = time.time() - t0
    result["state_ids"] = sorted(interp.current_state_ids)
    result["status"] = interp.status
    result["last_transition_ok"] = interp.last_transition_ok
    result["last_error"] = interp.last_error
    result["queue_depth"] = interp.queue_depth


thread = threading.Thread(target=run, daemon=True)
thread.start()
thread.join(BUDGET_S)

print("OBSERVED:")
print("  'Exceeded 1000 microsteps ... Aborting' logged %d times" % _Counter.count)
if thread.is_alive():
    print("  SyncInterpreter.start() has NOT returned after %.0f s" % BUDGET_S)
    print("  no timeout, no exception, no way to interrupt the calling thread")
else:
    print("  start() returned in %.3f s" % result["elapsed"])
    print("  result:", result)

print("EXPECTED:")
print("  start() terminates: the iteration budget (maxIterations=1000) bounds")
print("  the whole settling loop and a typed RunawayChainError is raised, or")
print("  build-time validation rejects the cyclic `always` graph.")

if thread.is_alive():
    print("RESULT: FAIL - non-terminating start() on the sync engine")
    sys.exit(1)
print("RESULT: PASS")
sys.exit(0)
