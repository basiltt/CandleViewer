"""Standalone repro for #214: restore path applies `strict`, upcasts a
pre-081 (v2) after-record as engine-minted so it still fires, and a v3
record without the engine flag stays untrusted user traffic.
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
    SyncInterpreter,
    MachineLogic,
    UnknownEventError,
    create_machine,
)
from xstate_statemachine.persistence import SNAPSHOT_VERSION

CFG = {
    "id": "t",
    "initial": "wait",
    "strict": True,
    "context": {"fired": 0},
    "states": {
        "wait": {
            "after": {60000: {"target": "done", "actions": ["mark"]}},
            "on": {"KNOWN": {}},
        },
        "done": {},
    },
}


def mk(cfg, **kw):
    return create_machine(json.loads(json.dumps(cfg)), **kw)


def logic():
    return MachineLogic(
        actions={"mark": lambda i, c, e, a: c.__setitem__("fired", 1)}
    )


def base_blob():
    s = SyncInterpreter(mk(CFG, logic=logic())).start()
    b = s.get_persisted_snapshot()
    s.stop()
    return b


def restore_applies_strict():
    blob = base_blob()
    blob["pending_events"] = [
        {"kind": "event", "type": "BOGUS", "payload": {}}
    ]
    r = SyncInterpreter.from_snapshot(json.dumps(blob), mk(CFG, logic=logic()))
    return {
        "last_error_type": type(r.last_error).__name__,
        "is_unknown_event_error": isinstance(r.last_error, UnknownEventError),
        "last_transition_ok": r.last_transition_ok,
        "pending_events_after": list(r.pending_events),
    }


def v2_after_record_upcast_and_fires():
    blob = base_blob()
    blob["version"] = 2
    blob["pending_events"] = [
        {
            "kind": "after",
            "type": "after.60000.t.wait",
            "scheduled_for": 1.0,
            "fired_at": 61.0,
        }
    ]
    r = SyncInterpreter.from_snapshot(
        json.dumps(blob), mk(CFG, logic=logic())
    ).start()
    out = (r.value, r.context["fired"])
    r.stop()
    return out


def v3_record_without_engine_flag_stays_user_traffic():
    blob = base_blob()
    assert blob["version"] == SNAPSHOT_VERSION
    blob["strict"] = False
    cfg2 = json.loads(json.dumps(CFG))
    cfg2["strict"] = False
    blob["pending_events"] = [
        {"kind": "after", "type": "after.60000.t.wait"}
    ]
    r = SyncInterpreter.from_snapshot(
        json.dumps(blob), create_machine(cfg2, logic=logic())
    ).start()
    out = (r.value, r.context["fired"])
    r.stop()
    return out


if __name__ == "__main__":
    out = {
        "restore_applies_strict": restore_applies_strict(),
        "v2_after_record_upcast_and_fires": v2_after_record_upcast_and_fires(),
        "v3_record_without_engine_flag_stays_user_traffic":
            v3_record_without_engine_flag_stays_user_traffic(),
    }
    print(json.dumps(out, indent=2, default=str))
