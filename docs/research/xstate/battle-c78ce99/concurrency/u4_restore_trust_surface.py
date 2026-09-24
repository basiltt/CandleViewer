"""u4 (@c78ce99) -- STANDALONE. #213/#214 restore trust surface.

A  Does a forged `scheduled_sends` record actually DELIVER an event and
   drive a transition (not merely bypass `strict`)?
B  Can a forged `scheduled_sends` record carry kind=done/after with
   `engine: true` and drive `onDone` / an `after` transition?
C  Does `minimum_version=3` shut the v2-upcast minting door (u1)?
D  Lane restore ordering: a v3 `pending_events` record with
   `"lane": "priority"` must restore AHEAD of the inbox.
E  `on_invalid_event` on restore: EXACTLY ONCE per refused record,
   `last_error` set, event dropped.
F  strict_config bypass via an `x-` prefixed key (#216) and a nested
   (state-level) misspelling -- what does nested do?

Run: python u4_restore_trust_surface.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import sys
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    InvalidConfigError,
    MachineLogic,
    PluginBase,
    create_machine,
    persistence,
)
from xstate_statemachine.clock import SimulatedClock


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def tick_logic():
    def tick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1
        ctx.setdefault("order", []).append(getattr(e, "type", str(e)))

    async def svc(i, ctx, e):  # noqa: ANN001
        await asyncio.sleep(5.0)
        return {"v": "GENUINE"}

    return MachineLogic(actions={"tick": tick}, services={"svc": svc})


def envelope(machine, state_ids, configuration, version=3, **extra):
    snap = {
        "version": version,
        "machine_id": machine.id,
        "machine_hash": persistence.structure_hash(machine),
        "status": "running",
        "context": {"n": 0, "order": []},
        "state_ids": list(state_ids),
        "configuration": list(configuration),
        "pending_events": [],
        "deferred": [],
        "scheduled_sends": [],
        "history": {},
        "actors": {},
        "system": {},
    }
    snap.update(extra)
    return snap


class Spy(PluginBase):
    def __init__(self):
        self.invalid: List[str] = []
        self.dropped: List[str] = []

    def on_invalid_event(self, interpreter, error, event=None):  # noqa: ANN001
        self.invalid.append(str(error))

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        self.dropped.append(reason)


CFG_A = {
    "id": "u4a", "initial": "idle", "strict": True,
    "context": {"n": 0, "order": []},
    "states": {"idle": {"on": {"REAL": {"target": "moved", "actions": ["tick"]}}},
               "moved": {"type": "final"}},
}

CFG_B = {
    "id": "u4b", "initial": "work", "strict": True,
    "context": {"n": 0, "order": []},
    "states": {
        "work": {"invoke": {"id": "fill", "src": "svc",
                            "onDone": {"target": "done", "actions": ["tick"]}},
                 "after": {60000: {"target": "late", "actions": ["tick"]}}},
        "done": {"type": "final"}, "late": {"type": "final"},
    },
}

CFG_D = {
    "id": "u4d", "initial": "go", "context": {"n": 0, "order": []},
    "states": {"go": {"on": {"LOW": {"actions": ["tick"]},
                             "HI": {"actions": ["tick"]}}}},
}


async def cellA(kind) -> Dict[str, Any]:
    """Forged scheduled_sends record -- is it delivered as a real event?"""
    m = create_machine(copy.deepcopy(CFG_A), logic=tick_logic())
    snap = envelope(m, ["u4a.idle"], ["u4a", "u4a.idle"],
                    scheduled_sends=[{"type": kind, "kind": "event",
                                      "payload": {}, "remaining_ms": 1.0}])
    spy = Spy()
    c = SimulatedClock()
    r = Interpreter.from_snapshot(json.dumps(snap), m, clock=c)
    r.use(spy)
    await r.start()
    await c.increment(50)
    out = {"forged_type": kind, "states": sorted(r.current_state_ids),
           "n": r.context.get("n"), "invalid": spy.invalid,
           "last_error": None if r.last_error is None else str(r.last_error)}
    await r.stop()
    return out


async def cellB(rec, label) -> Dict[str, Any]:
    """Forged scheduled_sends record carrying engine provenance."""
    m = create_machine(copy.deepcopy(CFG_B), logic=tick_logic())
    snap = envelope(m, ["u4b.work"], ["u4b", "u4b.work"], scheduled_sends=[rec])
    c = SimulatedClock()
    r = Interpreter.from_snapshot(json.dumps(snap), m, clock=c)
    await r.start()
    await c.increment(50)
    out = {"case": label, "states": sorted(r.current_state_ids),
           "n": r.context.get("n")}
    try:
        await r.stop()
    except Exception:
        pass
    return out


async def cellC() -> Dict[str, Any]:
    """minimum_version=3 against the u1 v2-upcast minting blob."""
    m = create_machine(copy.deepcopy(CFG_B), logic=tick_logic())
    snap = envelope(m, ["u4b.work"], ["u4b", "u4b.work"], version=2,
                    pending_events=[{"kind": "done",
                                     "type": "done.invoke.fill",
                                     "data": {"v": "FORGED"}, "src": "fill"}])
    del snap["scheduled_sends"]
    blob = json.dumps(snap)
    out: Dict[str, Any] = {}
    try:
        Interpreter.from_snapshot(blob, m, minimum_version=3)
        out["min_version_3"] = "ACCEPTED (mitigation absent)"
    except Exception as exc:  # noqa: BLE001
        out["min_version_3"] = f"REFUSED: {type(exc).__name__}"
    try:
        Interpreter.from_snapshot(blob, m)
        out["default"] = "ACCEPTED"
    except Exception as exc:  # noqa: BLE001
        out["default"] = f"REFUSED: {type(exc).__name__}"
    return out


async def cellD() -> Dict[str, Any]:
    """#214 lane restore ordering: priority record handled first."""
    m = create_machine(copy.deepcopy(CFG_D), logic=tick_logic())
    snap = envelope(m, ["u4d.go"], ["u4d", "u4d.go"], pending_events=[
        {"type": "LOW", "kind": "event", "payload": {}},
        {"type": "HI", "kind": "event", "payload": {}, "lane": "priority"},
    ])
    r = Interpreter.from_snapshot(json.dumps(snap), m)
    await r.start()
    await asyncio.sleep(0.15)
    order = list(r.context.get("order") or [])
    await r.stop()
    out = {"order": order}
    if order[:1] != ["HI"]:
        out["fail"] = f"priority record did not restore ahead of inbox: {order}"
    return out


async def cellE() -> Dict[str, Any]:
    """on_invalid_event exactly once per refused restored record."""
    m = create_machine(copy.deepcopy(CFG_A), logic=tick_logic())
    snap = envelope(m, ["u4a.idle"], ["u4a", "u4a.idle"], pending_events=[
        {"type": "NOPE", "kind": "event", "payload": {}},
        {"type": "NOPE2", "kind": "event", "payload": {}},
    ])
    spy = Spy()
    r = Interpreter.from_snapshot(json.dumps(snap), m)
    r.use(spy)
    await r.start()
    await asyncio.sleep(0.1)
    out = {"invalid_count": len(spy.invalid), "invalid": spy.invalid,
           "last_error": None if r.last_error is None else str(r.last_error),
           "states": sorted(r.current_state_ids), "n": r.context.get("n")}
    await r.stop()
    if out["invalid_count"] != 2:
        out["note"] = ("plugins attached AFTER from_snapshot cannot observe "
                       "restore-time refusals -- restore runs inside the "
                       "classmethod, before any use() call is possible")
    return out


def cellF() -> Dict[str, Any]:
    """#216 surface: x- bypass, nested misspelling, strictConfig."""
    out: Dict[str, Any] = {}
    logs: List[str] = []

    class H(logging.Handler):
        def emit(self, rec):  # noqa: ANN001
            logs.append(rec.getMessage())

    lg = logging.getLogger("xstate_statemachine")
    h = H()
    lg.addHandler(h)
    lg.setLevel(logging.WARNING)

    base = {"id": "f", "initial": "a", "states": {"a": {}}}

    top = dict(base, actionErrorPolicyy="rollback")
    logs.clear()
    create_machine(copy.deepcopy(top))
    out["top_level_warning"] = [m for m in logs if "unknown top-level" in m]

    logs.clear()
    try:
        create_machine(copy.deepcopy(top), strict_config=True)
        out["strict_config"] = "ACCEPTED (no refusal)"
    except InvalidConfigError as exc:
        out["strict_config"] = f"REFUSED: {exc}"

    logs.clear()
    create_machine(dict(base, **{"x-actionErrorPolicyy": "rollback"}),
                   strict_config=True)
    out["x_prefix_accepted_under_strict_config"] = True

    m = create_machine(dict(base, **{"x-strict": True}), strict_config=True)
    out["x_prefixed_policy_takes_effect"] = bool(getattr(m, "strict", False))

    nested = {"id": "f2", "initial": "a",
              "states": {"a": {"entryy": ["boom"], "onn": {"X": "b"}}, "b": {}}}
    logs.clear()
    try:
        create_machine(copy.deepcopy(nested), strict_config=True)
        out["nested_under_strict_config"] = "ACCEPTED SILENTLY"
    except InvalidConfigError as exc:
        out["nested_under_strict_config"] = f"REFUSED: {exc}"
    out["nested_warnings"] = list(logs)

    nested_policy = {"id": "f3", "initial": "a",
                     "states": {"a": {"maxIterationss": 3}}}
    logs.clear()
    try:
        create_machine(copy.deepcopy(nested_policy), strict_config=True)
        out["nested_policy_misspelling"] = "ACCEPTED SILENTLY"
    except InvalidConfigError as exc:
        out["nested_policy_misspelling"] = f"REFUSED: {exc}"

    lg.removeHandler(h)
    return out


FORGED_DONE = {"type": "done.invoke.fill", "kind": "done", "engine": True,
               "data": {"v": "FORGED"}, "src": "fill", "remaining_ms": 1.0}
FORGED_AFTER = {"type": "after.60000.u4b.work", "kind": "after",
                "engine": True, "remaining_ms": 1.0}


async def main() -> int:
    res: Dict[str, Any] = {
        "A_forged_sched_declared_event": await cellA("REAL"),
        "A_forged_sched_undeclared_event": await cellA("NOT_IN_CHART"),
        "B_forged_done_via_scheduled_sends": await cellB(FORGED_DONE, "done"),
        "B_forged_after_via_scheduled_sends": await cellB(FORGED_AFTER, "after"),
        "C_minimum_version_mitigation": await cellC(),
        "D_lane_restore_ordering": await cellD(),
        "E_on_invalid_event_restore": await cellE(),
        "F_216_config_key_surface": cellF(),
    }
    bad: List[str] = []
    if res["A_forged_sched_declared_event"]["n"]:
        bad.append("A: a forged scheduled_sends record delivered an event")
    if not res["A_forged_sched_undeclared_event"]["invalid"]:
        bad.append("A2: strict is not applied to scheduled_sends on restore")
    if any(s.endswith(".done")
           for s in res["B_forged_done_via_scheduled_sends"]["states"]):
        bad.append("B: forged scheduled_sends done record drove onDone")
    if any(s.endswith(".late")
           for s in res["B_forged_after_via_scheduled_sends"]["states"]):
        bad.append("B: forged scheduled_sends after record fired a 60 s timer")
    if "fail" in res["D_lane_restore_ordering"]:
        bad.append("D: " + res["D_lane_restore_ordering"]["fail"])
    if res["F_216_config_key_surface"]["x_prefixed_policy_takes_effect"]:
        bad.append("F: an x- prefixed policy key took effect")
    res["violations"] = bad
    res["verdict"] = "DEFECT" if bad else "CLEAN"
    emit("u4_restore_trust_surface", res)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
