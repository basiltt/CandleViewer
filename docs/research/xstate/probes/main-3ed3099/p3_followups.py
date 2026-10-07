"""J-7b/J-8b/J-1b follow-ups: restart_timers actually firing, DoneEvent log
leak, sync-engine mid-step parity, InvalidEventError hierarchy.

Run: python p3_followups.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time

sys.path.insert(0, r"<workspace>/_ref/xstate-statemachine")

from src.xstate_statemachine import (  # noqa: E402
    Interpreter,
    InvalidEventError,
    MachineLogic,
    SimulatedClock,
    SnapshotMidStepError,
    SyncInterpreter,
    create_machine,
)
from src.xstate_statemachine.exceptions import (  # noqa: E402
    XStateMachineError,
)
from src.xstate_statemachine.plugins import LoggingInspector  # noqa: E402

OUT = {}

TCFG = {
    "id": "tm",
    "initial": "a",
    "states": {"a": {"after": {1000: "b"}}, "b": {}},
}


def j7c_simclock_detail() -> None:
    """Does a re-armed timer on a FRESH SimulatedClock ever fire?"""
    c1 = SimulatedClock()
    i = SyncInterpreter(create_machine(TCFG), clock=c1).start()
    OUT["j7c_live_pending"] = c1.pending
    c1.increment(1100)
    OUT["j7c_live_value_after_1100"] = i.value  # baseline: timers DO work live
    i.stop()

    # restored + restart_timers on a fresh sim clock
    c0 = SimulatedClock()
    a = SyncInterpreter(create_machine(TCFG), clock=c0).start()
    snap = a.get_snapshot()
    a.stop()
    c2 = SimulatedClock()
    r = SyncInterpreter.from_snapshot(
        snap, create_machine(TCFG), clock=c2, restart_timers=True
    )
    r.start()
    OUT["j7c_restored_dormant"] = r.has_dormant_timers
    OUT["j7c_restored_clock_pending"] = c2.pending
    OUT["j7c_restored_clock_is_c2"] = r.clock is c2
    c2.increment(1500)
    OUT["j7c_value_after_1500"] = r.value
    r.tick()
    OUT["j7c_value_after_tick"] = r.value
    r.stop()

    # same thing on the REAL clock, for contrast
    b = SyncInterpreter(
        create_machine(
            {"id": "t2", "initial": "a", "states": {"a": {"after": {50: "b"}}, "b": {}}}
        )
    ).start()
    s2 = b.get_snapshot()
    b.stop()
    q = SyncInterpreter.from_snapshot(
        s2,
        create_machine(
            {"id": "t2", "initial": "a", "states": {"a": {"after": {50: "b"}}, "b": {}}}
        ),
        restart_timers=True,
    )
    q.start()
    time.sleep(0.2)
    q.tick()
    OUT["j7c_realclock_restored_value"] = q.value
    q.stop()


def j8b_doneevent_leak() -> None:
    """LoggingInspector._safe is applied to Event.payload only. Is a
    DoneEvent / AfterEvent `.data` (a service result) redacted?"""
    logs = []

    class _H(logging.Handler):
        def emit(self, rec):
            logs.append(rec.getMessage())

    lg = logging.getLogger("src.xstate_statemachine.plugins")
    lg.setLevel(logging.INFO)
    lg.propagate = False
    h = _H()
    lg.addHandler(h)

    cfg = {
        "id": "r",
        "initial": "w",
        "states": {
            "w": {"invoke": {"id": "s", "src": "svc", "onDone": "d"}},
            "d": {},
        },
    }
    i = SyncInterpreter(
        create_machine(
            cfg,
            logic=MachineLogic(
                services={
                    "svc": lambda i, c, e: {"api_key": "SECRET_DONE_123"}
                }
            ),
        )
    )
    i.use(LoggingInspector())
    i.start()
    i.tick()
    i.stop()

    # and a normal user Event payload, for contrast
    cfg2 = {
        "id": "u",
        "initial": "a",
        "states": {"a": {"on": {"GO": "b"}}, "b": {}},
    }
    j = SyncInterpreter(create_machine(cfg2))
    j.use(LoggingInspector())
    j.start()
    j.send("GO", api_key="SECRET_PAYLOAD_456")
    j.stop()
    lg.removeHandler(h)

    OUT["j8b_done_data_leaked"] = any("SECRET_DONE_123" in m for m in logs)
    OUT["j8b_payload_leaked"] = any("SECRET_PAYLOAD_456" in m for m in logs)
    OUT["j8b_done_lines"] = [m for m in logs if "SECRET_DONE" in m][:2]


def j1b_sync_midstep() -> None:
    """Sync engine, parallel machine, action in region A. Is the mid-step
    window refusable at all on the sync engine, and does a nested-region
    exit produce the same leaf-present false negative as J-1?"""
    PAR = {
        "id": "sp",
        "type": "parallel",
        "states": {
            "A": {
                "initial": "a1",
                "states": {
                    "a1": {"on": {"GO": {"target": "a2", "actions": ["p"]}}},
                    "a2": {},
                },
            },
            "B": {"initial": "b1", "states": {"b1": {}}},
        },
    }
    got = {}

    def p(i, c, e, a):
        try:
            got["snap"] = i.get_persisted_snapshot()
        except SnapshotMidStepError:
            got["refused"] = True

    i = SyncInterpreter(
        create_machine(PAR, logic=MachineLogic(actions={"p": p}))
    ).start()
    i.send("GO")
    OUT["j1b_sync_refused"] = got.get("refused", False)
    if "snap" in got:
        OUT["j1b_sync_state_ids"] = got["snap"]["state_ids"]
        r = SyncInterpreter.from_snapshot(
            json.dumps(got["snap"], default=str),
            create_machine(PAR, logic=MachineLogic(actions={"p": p})),
        )
        OUT["j1b_sync_restored_value"] = r.value
    i.stop()


def j11_invalid_event() -> None:
    cfg = {"id": "e", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
    i = SyncInterpreter(create_machine(cfg)).start()
    for label, arg in [
        ("none", None),
        ("int", 5),
        ("dict_no_type", {"payload": 1}),
        ("obj", object()),
        ("list", [1, 2]),
        ("bytes", b"GO"),
        ("dict_nonstr_type", {"type": 7}),
    ]:
        try:
            i.send(arg)  # type: ignore[arg-type]
            OUT[f"j11_{label}"] = "ACCEPTED"
        except Exception as exc:  # noqa: BLE001
            OUT[f"j11_{label}"] = (
                f"{type(exc).__name__}"
                f"|xsm={isinstance(exc, XStateMachineError)}"
                f"|TypeError={isinstance(exc, TypeError)}"
            )
    i.stop()

    # async engine parity
    async def m():
        j = await Interpreter(create_machine(cfg)).start()
        res = {}
        for label, arg in [("none", None), ("int", 5), ("obj", object())]:
            try:
                await j.send(arg)  # type: ignore[arg-type]
                res[label] = "ACCEPTED"
            except Exception as exc:  # noqa: BLE001
                res[label] = type(exc).__name__
        await j.stop()
        return res

    OUT["j11_async"] = asyncio.run(m())
    OUT["j11_is_typeerror_subclass"] = issubclass(InvalidEventError, TypeError)


def j12_midstep_docs_workaround() -> None:
    """The exception text tells callers to snapshot 'from on_transition'.
    Does on_transition actually guarantee a settled interpreter -- i.e. is
    the advice sound when the transition has POST-entry actions still to
    run in the same macrostep?"""
    cfg = {
        "id": "w",
        "initial": "a",
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {"entry": ["e1"], "always": {"target": "c"}},
            "c": {},
        },
    }
    from src.xstate_statemachine.plugins import PluginBase

    seen = []

    class P(PluginBase):
        def on_transition(self, i, f, t, tr):
            try:
                seen.append(i.get_persisted_snapshot()["state_ids"])
            except SnapshotMidStepError:
                seen.append("refused")

    i = SyncInterpreter(
        create_machine(
            cfg, logic=MachineLogic(actions={"e1": lambda *a: None})
        )
    )
    i.use(P())
    i.start()
    i.send("GO")
    OUT["j12_on_transition_snapshots"] = seen
    OUT["j12_final_value"] = i.value
    i.stop()


def main() -> None:
    j7c_simclock_detail()
    j8b_doneevent_leak()
    j1b_sync_midstep()
    j11_invalid_event()
    j12_midstep_docs_workaround()
    print(json.dumps(OUT, indent=2, default=str))


if __name__ == "__main__":
    logging.getLogger("src.xstate_statemachine.sync_interpreter").setLevel(
        logging.CRITICAL
    )
    main()
