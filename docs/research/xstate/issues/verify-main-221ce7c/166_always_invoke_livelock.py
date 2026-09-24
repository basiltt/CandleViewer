"""Verify #166 on main@221ce7c: async settle budget is per-macrostep, reset only
by external events. Repro shape: `always` into a child with a completed
`invoke`, re-entered via an internal self-targeting event.

Criteria (from CHANGELOG/#166 + test_round6_findings.py):
  1. Async: `await send("GO", wait=True)` resolves (no livelock) within a
     generous timeout and the receipt's error is RunawayChainError (the
     chain trips, it isn't silently accepted).
  2. Sync: `send("GO")` also trips RunawayChainError (parity, and confirms
     the repro shape genuinely cycles).
  3. Original R6-01 repro (post-cec108b/new/repro) exits 0 (no watchdog fire).

Exit 0 only if all criteria pass.
"""
import asyncio
import sys
import time

sys.path.insert(0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
import logging
logging.disable(logging.CRITICAL)

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import RunawayChainError

CFG = {
    "id": "m",
    "initial": "a",
    "on": {"GO": {"target": "#m.a", "internal": True}},
    "states": {
        "a": {
            "initial": "a",
            "always": {"target": "#m.a.a", "guard": "g"},
            "states": {"a": {"invoke": {"id": "i", "src": "svc"}}},
        }
    },
}


def logic():
    return MachineLogic(guards={"g": lambda c, e: True}, services={"svc": lambda i, c, e: 1})


def check_sync():
    s = SyncInterpreter(create_machine(CFG, logic=logic())).start()
    s.send("GO")
    ok = isinstance(s.last_error, RunawayChainError)
    print(f"[sync] last_error={s.last_error!r} -> {'PASS' if ok else 'FAIL'}")
    return ok


async def check_async():
    i = await Interpreter(create_machine(CFG, logic=logic())).start()
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    try:
        receipt = await asyncio.wait_for(i.send("GO", wait=True), timeout=10)
    except asyncio.TimeoutError:
        print(f"[async] TIMEOUT after {time.monotonic()-t0:.2f}s -- LIVELOCK -> FAIL")
        await i.stop()
        return False
    await i.stop()
    ok = isinstance(receipt.error, RunawayChainError)
    print(f"[async] resolved in {time.monotonic()-t0:.2f}s receipt.error={receipt.error!r} -> {'PASS' if ok else 'FAIL'}")
    return ok


def run_original_repro():
    import subprocess
    path = "C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/docs/research/xstate/issues/post-cec108b/new/repro/R6-01_async_always_invoke_livelock.py"
    r = subprocess.run(
        ["C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python", path],
        capture_output=True, text=True, timeout=30,
    )
    print("[orig-repro stdout]\n" + r.stdout)
    if r.stderr:
        print("[orig-repro stderr]\n" + r.stderr)
    ok = r.returncode == 0
    print(f"[orig-repro] returncode={r.returncode} -> {'PASS(0)' if ok else 'exit=' + str(r.returncode)}")
    return ok, r.returncode


if __name__ == "__main__":
    a_sync = check_sync()
    a_async = asyncio.run(check_async())
    orig_ok, orig_rc = run_original_repro()

    print("\n=== SUMMARY #166 ===")
    print(f"sync trips RunawayChainError: {a_sync}")
    print(f"async resolves w/ RunawayChainError (no livelock): {a_async}")
    print(f"original repro exit code: {orig_rc} (0=fixed)")

    all_ok = a_sync and a_async and orig_ok
    sys.exit(0 if all_ok else 1)
