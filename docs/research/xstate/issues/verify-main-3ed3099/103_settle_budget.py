"""Verify #103 on main@3ed3099: SyncInterpreter.start() terminates on a
cross-region `always` re-entering an invoking state, and a settle trip
leaves a legal configuration.

Criteria (CHANGELOG #103/#112 + test_round4_findings.py):
1. start() returns within a bounded time (thread join timeout) instead of
   spinning forever -- the settle budget is per-macrostep, not reset to 0
   every re-entry.
2. last_transition_ok is False and last_error is a RunawayChainError.
3. status remains 'running' (not crashed/corrupted) after the trip.
4. The "Exceeded ... microsteps ... Aborting" log fires ONCE per macrostep
   trip (bounded), not hundreds/thousands of times (i.e. budget is not
   re-armed on every settling pass).
5. A trip on a plain two-state always/always cycle leaves every active
   node's parent also active (no torn configuration).
"""
import logging
import sys
import threading

from xstate_statemachine import MachineLogic, RunawayChainError, SyncInterpreter, create_machine

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# --- 1,2,3: cross-region always into invoking state ---
CFG = {
    "id": "m",
    "type": "parallel",
    "maxIterations": 50,
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

out = {}


class _CountHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.count = 0

    def emit(self, record):
        if "Exceeded" in record.getMessage() and "Aborting" in record.getMessage():
            self.count += 1


handler = _CountHandler()
logging.getLogger("xstate_statemachine").addHandler(handler)
logging.getLogger("xstate_statemachine").setLevel(logging.WARNING)


def go():
    i = SyncInterpreter(create_machine(CFG, logic=MachineLogic(services={"svc": lambda i, c, e: 1})))
    i.start()
    out["ok"] = i.last_transition_ok
    out["err"] = type(i.last_error).__name__ if i.last_error else None
    out["status"] = i.status


th = threading.Thread(target=go, daemon=True)
th.start()
th.join(10)
check("1 start() returns within bound", not th.is_alive())
check("2 last_transition_ok is False", out.get("ok") is False, out)
check("2 last_error is RunawayChainError", out.get("err") == "RunawayChainError", out)
check("3 status remains running", out.get("status") == "running", out)
check("4 trip logged O(1) times, not thousands", handler.count <= 5, handler.count)

# --- 5: trip leaves a legal configuration ---
CFG5 = {
    "id": "m",
    "initial": "p",
    "maxIterations": 5,
    "states": {"p": {"initial": "x", "states": {"x": {"always": "y"}, "y": {"always": "x"}}}},
}
i5 = SyncInterpreter(create_machine(CFG5))
i5.start()
active = {n.id for n in i5._active_state_nodes}
legal = all((n.parent is None or n.parent.id in active) for n in i5._active_state_nodes)
check("5 no torn configuration (every active node's parent active)", legal, active)
check("5 last_transition_ok False", i5.last_transition_ok is False)
check("5 last_error is RunawayChainError", isinstance(i5.last_error, RunawayChainError), i5.last_error)

ok = True
for name, passed, detail in results:
    print(f"{'PASS' if passed else 'FAIL'}: {name}  {detail if not passed else ''}")
    ok = ok and passed

sys.exit(0 if ok else 1)
