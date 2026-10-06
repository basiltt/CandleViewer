"""DE-L5 repro: SyncInterpreter._enqueue_restored ignores the persisted
priority lane. STANDALONE: stdlib + xstate_statemachine only. Run from cwd
C:/Users/basil.
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[4] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys, json
sys.path.insert(
    0,
    str(_XS / 'src'),
)
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter

cfg = {"id": "m", "initial": "w", "states": {"w": {"on": {"A": "w", "B": "w"}}}}
m = create_machine(cfg, logic=MachineLogic())
i = SyncInterpreter(m).start()
snap = json.loads(i.get_snapshot())
# 'A' recorded as normal-inbox, 'B' recorded as priority lane -- on restore
# a priority-lane record is supposed to be re-admitted ahead of the inbox.
snap["pending_events"] = [
    {"type": "A", "payload": {}, "lane": "normal"},
    {"type": "B", "payload": {}, "lane": "priority"},
]
snap = json.dumps(snap)
r = SyncInterpreter.from_snapshot(snap, m)
order = [getattr(e, "type", e) for e in r._event_queue]
print("restored queue order:", order)
reproduced = order == ["A", "B"]
print("priority lane not honoured (B stayed behind A):", reproduced)
print()
print("REPRODUCED:", reproduced)
sys.exit(1 if reproduced else 0)
