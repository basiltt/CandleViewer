"""R5-04 repro: nested invokes whose `onDone` targets their common compound
ancestor livelock `SyncInterpreter.start()`; `maxIterations` does not bound it.

Exits 1 while the defect is present (start() has not returned inside the
watchdog budget, at any `maxIterations`), 0 once fixed (start() returns, or
raises a typed error, in bounded time).

Stdlib + xstate_statemachine only.
"""

import copy
import logging
import sys
import threading

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)

WATCHDOG_S = 8.0

# `m.a` invokes `i1`; its child `m.a.a` invokes `i2`.  Both services succeed
# immediately and both `onDone` transitions target `#m.a` -- the common
# compound ancestor.  Re-entering `m.a` re-arms `i1` AND (via the initial
# child) `i2`, so the cycle consumes exactly as many events as it produces.
CFG = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {
            "initial": "a",
            "invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#m.a"}},
            "states": {
                "a": {
                    "invoke": {
                        "id": "i2",
                        "src": "svc",
                        "onDone": {"target": "#m.a"},
                    }
                }
            },
        }
    },
}


def svc(interpreter, ctx, event):  # noqa: ANN001, D103
    return {"ok": 1}


def probe(max_iterations):
    """Start a SyncInterpreter on a watchdog thread; report whether it returns."""
    cfg = copy.deepcopy(CFG)
    if max_iterations is not None:
        cfg["maxIterations"] = max_iterations
    machine = create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
    interp = SyncInterpreter(machine)
    out = {}

    def run():
        try:
            interp.start()
            out["returned"] = sorted(interp.current_state_ids)
            out["ok"] = getattr(interp, "last_transition_ok", None)
            out["last_error"] = repr(getattr(interp, "last_error", None))
        except BaseException as exc:  # noqa: BLE001
            out["raised"] = f"{type(exc).__name__}: {exc}"

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(WATCHDOG_S)
    alive = th.is_alive()
    print(
        f"  maxIterations={max_iterations!r:>6}  after {WATCHDOG_S}s: "
        f"start_alive={alive}  {out}"
    )
    return alive


print("OBSERVED:")
hung = [probe(mi) for mi in (None, 10, 1000)]

print("\nEXPECTED: start() returns (or raises a typed RunawayChainError) in")
print("          bounded time for every maxIterations -> start_alive=False.")
if any(hung):
    print("RESULT: FAIL -- SyncInterpreter.start() livelocked (watchdog fired).")
    sys.exit(1)
print("RESULT: PASS")
sys.exit(0)
