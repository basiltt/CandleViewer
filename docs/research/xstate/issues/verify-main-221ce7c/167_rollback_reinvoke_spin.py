"""Verify #167 on main@221ce7c: rollback -> re-arm -> done -> rollback cycle
is bounded on the async engine (completion produced while processing is
charged to the chain budget).

Criteria:
  1. Async: service call count stops growing (settles) rather than spinning
     unbounded; call count <= maxIterations(default 1000) + small slack.
  2. `on_event_dropped` fires with reason "chain_budget".
  3. Status remains "running" (machine survives the trip, isn't bricked).
  4. Original R6-03 repro exits 0.
"""
import asyncio
import sys
import time

sys.path.insert(0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
import logging
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "spin",
    "actionErrorPolicy": "rollback",
    "initial": "starting",
    "context": {},
    "states": {
        "starting": {
            "invoke": {"id": "s", "src": "svc", "onDone": {"target": "#spin.recording"}},
        },
        "recording": {"entry": ["boom"]},
    },
}


class Drops:
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):
        self.dropped.append(reason)


async def check_async(use_coroutine_service: bool):
    calls = [0]

    def boom(*a):
        raise RuntimeError("boom")

    if use_coroutine_service:
        async def svc(i, c, e):
            calls[0] += 1
            return 1
    else:
        def svc(i, c, e):
            calls[0] += 1
            return 1

    d = Drops()
    i = Interpreter(create_machine(CFG, logic=MachineLogic(actions={"boom": boom}, services={"svc": svc}))).use(d)
    await i.start()
    await asyncio.sleep(0.6)
    first = calls[0]
    await asyncio.sleep(0.4)
    later = calls[0]
    status = i.status
    dropped = d.dropped
    await i.stop()

    settled = first == later
    bounded = first <= 1010
    chain_budget_seen = "chain_budget" in dropped
    running = status == "running"

    label = "coroutine-svc" if use_coroutine_service else "plain-svc"
    print(f"[{label}] calls@0.6s={first} calls@1.0s={later} status={status} dropped_reasons={set(dropped)}")
    print(f"[{label}] settled(no growth after budget trip)={settled} bounded(<=1002)={bounded} chain_budget_dropped={chain_budget_seen} status_running={running}")
    return settled and bounded and chain_budget_seen and running


def run_original_repro():
    import subprocess
    path = "C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/docs/research/xstate/issues/post-cec108b/new/repro/R6-03_rollback_ondone_reinvoke_spin.py"
    r = subprocess.run(
        ["C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python", path],
        capture_output=True, text=True, timeout=30,
    )
    print("[orig-repro stdout]\n" + r.stdout)
    if r.stderr:
        print("[orig-repro stderr]\n" + r.stderr)
    return r.returncode == 0, r.returncode


if __name__ == "__main__":
    a_ok_plain = asyncio.run(check_async(use_coroutine_service=False))
    a_ok_coro = asyncio.run(check_async(use_coroutine_service=True))
    orig_ok, orig_rc = run_original_repro()

    print("\n=== SUMMARY #167 ===")
    print(f"async cycle bounded & observable (plain-def service): {a_ok_plain}")
    print(f"async cycle bounded & observable (coroutine service, original repro shape): {a_ok_coro}")
    print(f"original repro (coroutine service) exit code: {orig_rc} (0=fixed)")

    sys.exit(0 if (a_ok_plain and a_ok_coro and orig_ok) else 1)
