"""Standalone repro for #213: an armed, unfired delayed self-send must
survive a snapshot via `scheduled_sends`, re-arm with remaining delay on
restore, and a cancelled send must leave no record.
Run from neutral cwd (stdlib + xstate_statemachine only).
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[3] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import json
import sys

sys.path.insert(
    0,
    str(_XS / 'src'),
)

from xstate_statemachine import (
    SimulatedClock,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "debt",
    "initial": "a",
    "context": {},
    "states": {
        "a": {
            "entry": [
                {"type": "raise", "params": {"event": "PONG", "delay": 300}},
            ],
            "on": {"PONG": "b"},
        },
        "b": {},
    },
}

CANCEL_CFG = {
    "id": "c",
    "initial": "a",
    "states": {
        "a": {
            "entry": [
                {
                    "type": "raise",
                    "params": {"event": "X", "delay": 500, "id": "k"},
                },
                {"type": "cancel", "params": {"sendId": "k"}},
            ]
        }
    },
}


def mk(cfg):
    return create_machine(json.loads(json.dumps(cfg)))


def survives_and_restores():
    clock = SimulatedClock()
    s = SyncInterpreter(mk(CFG), clock=clock).start()
    clock.increment(50)
    blob = s.get_persisted_snapshot()
    s.stop()
    recs = blob["scheduled_sends"]
    assert len(recs) == 1, recs
    assert recs[0]["type"] == "PONG"
    assert abs(recs[0]["remaining_ms"] - 250.0) < 2.0, recs
    assert blob["pending_events"] == []

    clock2 = SimulatedClock()
    r = SyncInterpreter.from_snapshot(
        json.dumps(blob), mk(CFG), clock=clock2
    ).start()
    clock2.increment(200)
    v1 = r.value
    clock2.increment(60)
    v2 = r.value
    left = r.get_persisted_snapshot()["scheduled_sends"]
    r.stop()
    return {"recs": recs, "v1": v1, "v2": v2, "left_after_fire": left}


def cancelled_leaves_no_record():
    s = SyncInterpreter(mk(CANCEL_CFG)).start()
    recs = s.get_persisted_snapshot()["scheduled_sends"]
    s.stop()
    return recs


if __name__ == "__main__":
    out = {
        "survives_and_restores": survives_and_restores(),
        "cancelled_leaves_no_record": cancelled_leaves_no_record(),
    }
    print(json.dumps(out, indent=2, default=str))
