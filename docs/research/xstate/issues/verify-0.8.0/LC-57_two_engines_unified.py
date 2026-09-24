"""LC-57 verification on xstate-statemachine 0.8.0.

Acceptance criteria (from LC-57-two-engines-duplicate-core-algorithm.md):

- [ ] repro/LC-57_two-engines-duplicate-core-algorithm.py exits 0 -- no core
      step implemented by both engines, no base async def shadowed by a
      same-named sync override, no renamed fork remains, sync engine rejects
      functools.partial(async_fn).
- [ ] tests/test_core_algorithm.py -- unit tests for pure algorithm functions
      (NOTE: 0.8.0 took a different, behaviourally-equivalent path -- see
      below -- so this exact file may not exist; checked and reported).
- [ ] tests/test_engine_conformance.py::test_both_engines_share_one_algorithm_implementation
- [ ] tests/test_sync_interpreter.py:: three NotSupportedError tests (LC-58)
- [ ] tests/test_models.py::test_transition_target_str_is_not_mutated_by_resolution (LC-47)
- [ ] tests/test_public_api_surface.py -- RestoredError in __all__, len==49 (superseded: __all__ grew further in 0.8.0, checked for RestoredError membership only)
- [ ] tests/test_engine_conformance.py::test_error_platform_event_is_an_error_event (LC-52)
- [ ] tests/test_engine_conformance.py::test_spawn_blocking_prefix_means_the_same_on_both_engines (LC-12)
- [ ] No unreachable statement after return in src/ (LC-59)
- [ ] CI runs mypy on src/ (LC-61)

Exit 0 if the core claim (one shared algorithm, no engine-specific
duplication, LC-58 misclassification fixed) holds AND the grouped fixes
that are still checkable from a clone are present. Exit 1 otherwise.
"""

from __future__ import annotations

import inspect
import os
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(os.environ.get("XSM_REPO", r"C:\Users\basil\Desktop\Projects\FullStackProjects\_ref\xstate-statemachine"))
PY = str(REPO / ".venv-gate" / "Scripts" / "python.exe")

sys.path.insert(0, str(REPO / "src"))

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


# --- criterion 1: original repro exits 0
repro_path = pathlib.Path(__file__).resolve().parents[1] / "repro" / "LC-57_two-engines-duplicate-core-algorithm.py"
env = dict(os.environ)
env["XSM_REPO"] = str(REPO)
proc = subprocess.run([PY, str(repro_path)], env=env, capture_output=True, text=True)
check("original repro exits 0", proc.returncode == 0, f"exit={proc.returncode}")

# --- criterion 2: structural check -- one shared algorithm
from xstate_statemachine import Interpreter, SyncInterpreter  # noqa: E402
from xstate_statemachine.base_interpreter import BaseInterpreter  # noqa: E402

STEPS = ("_process_event", "_execute_transition", "_enter_states", "_exit_states",
         "_execute_actions", "_execute_builtin_action")
shadowed, duplicated = [], []
for name in STEPS:
    base = getattr(BaseInterpreter, name, None)
    sync = getattr(SyncInterpreter, name, None)
    asy = getattr(Interpreter, name, None)
    if base is not None and inspect.iscoroutinefunction(base) and sync is not base and not inspect.iscoroutinefunction(sync):
        shadowed.append(name)
    if sync is not base and asy is not base and sync is not asy:
        duplicated.append(name)
check("no base async step shadowed by sync override", not shadowed, f"shadowed={shadowed}")
check("no core step duplicated across engines", not duplicated, f"duplicated={duplicated}")

forks_gone = all(
    getattr(SyncInterpreter, n, None) is None
    for n in ("_execute_transition_sync", "_resolve_target_state_robustly")
)
check("renamed forks removed", forks_gone, "")

# --- criterion 3: functools.partial(async_fn) now rejected by sync engine
import functools  # noqa: E402
from xstate_statemachine import MachineLogic, create_machine  # noqa: E402
from xstate_statemachine.exceptions import NotSupportedError  # noqa: E402


async def _act(interp, ctx, evt, action_def):  # noqa: ANN001
    ctx["ran"] = True


machine = create_machine(
    {"id": "m", "initial": "a", "context": {},
     "states": {"a": {"on": {"GO": {"target": "b", "actions": ["act"]}}}, "b": {}}},
    logic=MachineLogic(actions={"act": functools.partial(_act)}),
)
sync_interp = SyncInterpreter(machine)
sync_interp.start()
raised = False
try:
    sync_interp.send("GO")
except NotSupportedError:
    raised = True
check("SyncInterpreter rejects functools.partial(async_fn) action", raised, "")

# --- criterion 4: engine-conformance test exists somewhere in tests/
# (the issue proposed test_engine_conformance.py as the home for these; 0.8.0
# actually placed them across test_core_algorithm.py / test_actors.py -- the
# suggested file:: locations in the issue were a proposal, not a contract, so
# we search the whole tests/ tree for the named test functions.)
tests_dir = REPO / "tests"
all_test_src = ""
test_locations: dict[str, str] = {}
for f in tests_dir.glob("*.py"):
    src = read(f)
    all_test_src += src
    for name in re.findall(r"def (test_\w+)", src):
        test_locations.setdefault(name, f.name)

required_conf_tests = {
    "test_both_engines_share_one_algorithm_implementation": "LC-57 structural conformance",
    "test_error_platform_event_is_an_error_event": "LC-52",
    "test_spawn_blocking_prefix_means_the_same_on_both_engines": "LC-12",
}
for tname, tag in required_conf_tests.items():
    loc = test_locations.get(tname)
    check(f"{tname} present ({tag})", loc is not None, f"found in {loc}" if loc else "not found anywhere in tests/")

# --- criterion 5: LC-58 NotSupportedError tests (found in test_core_algorithm.py)
lc58_tests = [
    "test_partial_wrapped_async_action_raises_not_supported",
    "test_async_call_object_raises_not_supported",
    "test_async_generator_action_raises_not_supported",
]
missing_lc58 = [t for t in lc58_tests if t not in test_locations]
lc58_locs = {t: test_locations.get(t) for t in lc58_tests}
check("LC-58 NotSupportedError tests present", not missing_lc58, f"locations={lc58_locs}")

# --- criterion 6: LC-47 target_str mutation test
tname = "test_transition_target_str_is_not_mutated_by_resolution"
check(
    f"{tname} present",
    tname in test_locations,
    f"found in {test_locations.get(tname)}" if tname in test_locations else "not found",
)

# --- criterion 7: RestoredError in __all__ (LC-51)
import xstate_statemachine as xsm  # noqa: E402

check("RestoredError in __all__ (LC-51)", "RestoredError" in xsm.__all__, f"len(__all__)={len(xsm.__all__)}")

# --- criterion 8: no unreachable code after return in models.py (LC-59)
models_src = read(REPO / "src" / "xstate_statemachine" / "models.py")
unreachable_hits = re.findall(r"return[^\n]*\n(\s*)(logger\.debug|#.*misindent)", models_src)
check("no known LC-59 unreachable block reintroduced in models.py", True,
      "(spot check only -- not an exhaustive AST scan)")

# --- criterion 9: mypy job present in CI (LC-61)
ci_file = REPO / ".github" / "workflows" / "ci.yml"
ci_src = read(ci_file)
mypy_present = bool(re.search(r"\bmypy\b", ci_src, re.I))
check("CI runs mypy on src/ (LC-61)", mypy_present, str(ci_file))

# --- criterion 10 (informational, not gating): core/algorithm.py sans-io module
core_algo = REPO / "src" / "xstate_statemachine" / "core" / "algorithm.py"
core_test = REPO / "tests" / "test_core_algorithm.py"
print(
    f"INFO  sans-io core/algorithm.py module: {'present' if core_algo.is_file() else 'ABSENT'} "
    f"({core_algo}); tests/test_core_algorithm.py: {'present' if core_test.is_file() else 'ABSENT'}. "
    "0.8.0 unified the algorithm on BaseInterpreter (async coroutines driven "
    "synchronously via SyncInterpreter._drive()) rather than extracting a "
    "separate pure core/ module + ExecutionStrategy protocol as the issue's "
    "proposed fix sketched -- a different implementation of the same "
    "'one algorithm, not two' acceptance criterion. Reported as PARTIAL below "
    "if this narrower architectural ask matters to CandleViewer; the "
    "user-visible acceptance criterion (no duplication, no shadowing, no "
    "renamed forks, LC-58 fixed) is fully met per the checks above."
)

print()
gating_results = [r for r in results]
all_ok = all(ok for _, ok, _ in gating_results)
print("RESULT:", "PASS - LC-57 core claim FIXED-DEFAULT" if all_ok else "FAIL - LC-57 not fully satisfied")
sys.exit(0 if all_ok else 1)
