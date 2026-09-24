"""Verify #233, #234, #235 on xstate-statemachine v0.9.0/main.
STANDALONE: stdlib + xstate_statemachine only. Run from cwd C:/Users/basil.
"""
import sys, json, warnings, importlib.metadata

sys.path.insert(
    0,
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/"
    "xstate-statemachine/src",
)

import xstate_statemachine as x
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter
from xstate_statemachine.events import (
    engine_done, is_system_event, DoneEvent,
)

results = {}

# ---- #233: sync engine honours priority lane on restore ----
cfg = {"id": "m", "initial": "w", "states": {"w": {"on": {"A": "w", "B": "w"}}}}
m = create_machine(cfg, logic=MachineLogic())
i = SyncInterpreter(m).start()
snap = json.loads(i.get_snapshot())
snap["pending_events"] = [
    {"type": "A", "payload": {}, "lane": "normal"},
    {"type": "B", "payload": {}, "lane": "priority"},
]
r = SyncInterpreter.from_snapshot(json.dumps(snap), m)
order = [getattr(e, "type", e) for e in r._event_queue]
results["233_order"] = order
results["233_pass"] = order == ["B", "A"]

# ---- #234: version / tag / changelog / pypi ----
results["234_version"] = x.__version__
try:
    dist_ver = importlib.metadata.version("xstate_statemachine")
except Exception as e:
    dist_ver = f"ERR:{e}"
results["234_dist_version"] = dist_ver
changelog_path = (
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/"
    "xstate-statemachine/CHANGELOG.md"
)
with open(changelog_path, encoding="utf-8") as f:
    head = f.read(400)
results["234_changelog_head"] = head.splitlines()[0:4]
results["234_pypi_note"] = "NOT on PyPI as of this run (pip download 0.9.0 failed; latest is 0.8.0)"

# ---- #235: engine_* private, deprecation shim, _replace demotes ----
results["235_public_export"] = "engine_done" in x.__all__
with warnings.catch_warnings(record=True) as wlist:
    warnings.simplefilter("always")
    ev = engine_done("done.invoke.fill", {"x": 1}, "fill")
    results["235_deprecation_warned"] = any(
        issubclass(wi.category, DeprecationWarning) for wi in wlist
    )
results["235_original_is_system_event"] = is_system_event(ev)
mutated = ev._replace(data={"y": 2})
results["235_mutated_type"] = type(mutated).__name__
results["235_mutated_is_public_DoneEvent"] = (
    type(mutated) is DoneEvent and not is_system_event(mutated)
)

for k, v in results.items():
    print(f"{k}: {v}")

ok = (
    results["233_pass"]
    and results["234_version"] == "0.9.0"
    and results["235_deprecation_warned"]
    and results["235_original_is_system_event"]
    and results["235_mutated_is_public_DoneEvent"]
)
print("\nALL_PASS:", ok)
sys.exit(0 if ok else 1)
