"""Verify #123 on main@3ed3099: SyncInterpreter.send() fires
on_event_dropped(reason='not_running') when called on a stopped/done
interpreter, matching Interpreter.send().

Acceptance criteria:
  - [ ] SyncInterpreter.send() fires on_event_dropped(reason='not_running')
        (or the sync-engine equivalent hook) when called on a stopped or
        already-done interpreter, matching Interpreter.send().
  - [ ] A test named test_sync_send_after_stop_fires_dropped_hook (or
        equivalent) exists under tests/.
  - [ ] repro/R4-28_sync_send_stopped_silent.py exits 0 once fixed.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys

sys.path.insert(
    0,
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src",
)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

FAILS = []


def check(label: str, cond: bool) -> None:
    print(f"[{'OK' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILS.append(label)


PY = "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python"
REPO = "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine"

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"T": "b"}}, "b": {}}}


class Drops(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, reason):
        self.dropped.append((getattr(event, "type", event), reason))


# --- Criterion 1: sync send() after stop() fires on_event_dropped ---
d1 = Drops()
s = SyncInterpreter(create_machine(CFG)).use(d1)
s.start()
s.stop()
s.send("T")
check(
    "SyncInterpreter.send() after stop() fires on_event_dropped(reason='not_running')",
    [r for _, r in d1.dropped] == ["not_running"],
)


async def async_main():
    d2 = Drops()
    i = Interpreter(create_machine(CFG)).use(d2)
    await i.start()
    await i.stop()
    await i.send("T")
    return d2.dropped


d2_result = asyncio.run(async_main())
check(
    "Interpreter (async) parity: also fires on_event_dropped(reason='not_running')",
    [r for _, r in d2_result] == ["not_running"],
)

# --- also cover 'already-done' (terminal state), not just explicit stop() ---
CFG_DONE = {"id": "m", "initial": "a", "states": {"a": {"type": "final"}}}
d3 = Drops()
s2 = SyncInterpreter(create_machine(CFG_DONE)).use(d3)
s2.start()
check("sync interpreter reaches 'done' status on entering final state", s2.status == "done")
s2.send("T")
check(
    "SyncInterpreter.send() on an already-done interpreter fires on_event_dropped",
    [r for _, r in d3.dropped] == ["not_running"],
)

# --- Criterion 2: dedicated test exists and passes ---
r = subprocess.run(
    [PY, "-m", "pytest", "tests/test_round4_findings.py", "-k", "HookParity", "-v"],
    cwd=REPO, capture_output=True, text=True, timeout=60,
)
check(
    "dedicated hook-parity tests pass (send_to_stopped_fires_not_running_on_both)",
    r.returncode == 0 and "send_to_stopped_fires_not_running_on_both PASSED" in r.stdout,
)
print(r.stdout[-500:])

# --- Criterion 3: original repro exits 0 ---
repro_path = (
    "C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/docs/"
    "research/xstate/issues/post-5e07ba8/new/repro/"
    "R4-28_sync_send_stopped_silent.py"
)
r2 = subprocess.run([PY, repro_path], capture_output=True, text=True, timeout=30)
print("--- original repro ---")
print(r2.stdout)
check("original repro (R4-28_sync_send_stopped_silent.py) exits 0", r2.returncode == 0)

print()
if FAILS:
    print(f"RESULT: {len(FAILS)} criterion/criteria FAILED: {FAILS}")
    sys.exit(1)
print("RESULT: all #123 acceptance criteria satisfied.")
sys.exit(0)
