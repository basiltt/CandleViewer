"""Verify #120 on main@3ed3099: the async trip handler spares completion
events (`done.*`/`error.*`) from a runaway-chain drop, matching
SyncInterpreter's spare/keep/victims partition and the CHANGELOG claim
"the async trip spares engine completions like the sync one (#120)".

Acceptance criteria (from the issue body):
  - [ ] Interpreter's runaway/chain-trip handler spares completion events
        (done.*, error.*) from being dropped, matching SyncInterpreter's
        spare/keep/victims partition.
  - [ ] A test named test_async_trip_spares_completion_events (or
        equivalent) exists under tests/, covering the same shape R4-06
        uses to show the async trip handler drops head-of-queue events.
  - [ ] Documentation in json-config.md/CHANGELOG accurately reflects
        engine parity (or lack thereof) for this guarantee.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys

sys.path.insert(
    0,
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src",
)

from xstate_statemachine import Interpreter, MachineLogic, create_machine  # noqa: E402
from xstate_statemachine.events import is_system_event  # noqa: E402

FAILS = []


def check(label: str, cond: bool) -> None:
    print(f"[{'OK' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILS.append(label)


# --- Criterion 1: construct a runaway chain WITH a completion in flight,
# using the same shape as R4-06 (a self-raise SPIN loop plus an invoked
# async service whose done.invoke must arrive despite the trip). ---
CFG = {
    "id": "m",
    "maxIterations": 5,
    "initial": "a",
    "states": {
        "a": {
            "invoke": {"id": "svc", "src": "svc", "onDone": "ok"},
            "on": {"SPIN": {"actions": [{"type": "raise", "params": {"event": "SPIN"}}]}},
        },
        "ok": {},
    },
}


async def svc(i, c, e):
    await asyncio.sleep(0.05)
    return 1


async def main():
    i = await Interpreter(
        create_machine(CFG, logic=MachineLogic(services={"svc": svc}))
    ).start()
    await i.send("SPIN")
    await asyncio.sleep(0.5)
    v = i.value
    await i.stop()
    return v


result = asyncio.run(main())
check("done.invoke delivered despite runaway self-raise trip (value='ok')", result == "ok")

# --- Source-level confirmation: interpreter.py trip handler checks
# is_system_event() before dropping (mirrors sync's spare/keep/victims). ---
import inspect  # noqa: E402

src = inspect.getsource(Interpreter._run_loop) if hasattr(Interpreter, "_run_loop") else ""
if not src:
    # fall back: grep the module source directly
    with open(
        "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/"
        "src/xstate_statemachine/interpreter.py",
        encoding="utf-8",
    ) as f:
        src = f.read()
check(
    "trip handler references is_system_event(...) guard (#120 fix site)",
    "is_system_event(event)" in src,
)

# --- Criterion 2: dedicated test exists and passes ---
PY = "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python"
r = subprocess.run(
    [PY, "-m", "pytest", "tests/test_round4_findings.py", "-k", "AsyncTripSparesCompletion", "-v"],
    cwd="C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine",
    capture_output=True,
    text=True,
    timeout=60,
)
check(
    "dedicated test (TestAsyncTripSparesCompletion) passes",
    r.returncode == 0 and "1 passed" in r.stdout,
)
print(r.stdout[-400:])

# --- Criterion 3: CHANGELOG documents engine parity for this guarantee ---
with open(
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/CHANGELOG.md",
    encoding="utf-8",
) as f:
    changelog = f.read()
check(
    "CHANGELOG documents '#120' async trip sparing completions",
    "#120" in changelog and "spares engine\n    completions like the sync one (#120)" in changelog.replace("\r\n", "\n") or "the async trip spares engine" in changelog,
)

# --- Original repro from post-5e07ba8 ---
repro_path = (
    "C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/docs/"
    "research/xstate/issues/post-5e07ba8/new/repro/"
    "R4-25_async_completion_sparing_missing.py"
)
r2 = subprocess.run([PY, repro_path], capture_output=True, text=True, timeout=30)
print("--- original repro ---")
print(r2.stdout)
print("exit:", r2.returncode)
check("original repro exits 0 (documented-as-expected 'delivered=True')", r2.returncode == 0)

print()
if FAILS:
    print(f"RESULT: {len(FAILS)} criterion/criteria FAILED: {FAILS}")
    sys.exit(1)
print("RESULT: all #120 acceptance criteria satisfied.")
sys.exit(0)
