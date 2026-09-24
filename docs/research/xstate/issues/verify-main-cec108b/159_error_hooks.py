"""Verify #159 on cec108b: error/refusal hooks reach PluginBase subclasses.

Acceptance criteria (issue #159 + CHANGELOG "#159" bullet):
  A) send(<non-str type>) raising InvalidEventError also fires
     PluginBase.on_invalid_event(interpreter, error, raw_event) before
     the exception propagates.
  B) A mid-macrostep get_persisted_snapshot() raising SnapshotMidStepError
     also fires PluginBase.on_snapshot_error(interpreter, error).
  C) Both hooks exist on PluginBase with default no-op implementations
     (so plugins that don't override them are unaffected).
  D) Parity: both sync and async engines fire these hooks (spot check
     SyncInterpreter here since it's cheaper; async covered indirectly
     since both share base_interpreter.py machinery).
"""
from __future__ import annotations

import sys

from xstate_statemachine import (
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import InvalidEventError, SnapshotMidStepError

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


class Spy(PluginBase):
    def __init__(self):
        self.invalid_calls = []
        self.snapshot_error_calls = []

    def on_invalid_event(self, interpreter, error, raw_event):
        self.invalid_calls.append((type(error).__name__, raw_event))

    def on_snapshot_error(self, interpreter, error):
        self.snapshot_error_calls.append(type(error).__name__)


def criterion_C_hooks_exist() -> bool:
    ok = callable(getattr(PluginBase, "on_invalid_event", None)) and callable(
        getattr(PluginBase, "on_snapshot_error", None)
    )
    print(f"  [C] PluginBase declares on_invalid_event/on_snapshot_error: {ok}")
    return ok


def criterion_A_invalid_event() -> bool:
    spy = Spy()
    i = SyncInterpreter(create_machine(CFG, logic=MachineLogic()))
    i.use(spy)
    i.start()
    raised = None
    try:
        i.send(42)
    except InvalidEventError as e:
        raised = e
    i.stop()
    ok = raised is not None and len(spy.invalid_calls) == 1 and spy.invalid_calls[0][0] == "InvalidEventError"
    print(f"  [A] on_invalid_event fired with InvalidEventError: {ok} (calls={spy.invalid_calls})")
    return ok


def criterion_B_snapshot_error() -> bool:
    spy = Spy()
    res = {}

    def grab(i, c, e, a):
        try:
            i.get_persisted_snapshot()
            res["raise"] = "NO-RAISE"
        except SnapshotMidStepError as exc:
            res["raise"] = type(exc).__name__

    logic = MachineLogic(actions={"grab": grab})
    cfg = {
        "id": "m2",
        "initial": "a",
        "states": {"a": {"on": {"GO": {"target": "b", "actions": ["grab"]}}}, "b": {}},
    }
    i = SyncInterpreter(create_machine(cfg, logic=logic))
    i.use(spy)
    i.start()
    i.send("GO")
    i.stop()
    ok = res.get("raise") == "SnapshotMidStepError" and "SnapshotMidStepError" in spy.snapshot_error_calls
    print(f"  [B] on_snapshot_error fired with SnapshotMidStepError: {ok} (calls={spy.snapshot_error_calls}, res={res})")
    return ok


def main() -> int:
    results = [
        criterion_C_hooks_exist(),
        criterion_A_invalid_event(),
        criterion_B_snapshot_error(),
    ]
    ok = all(results)
    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


sys.exit(main())
