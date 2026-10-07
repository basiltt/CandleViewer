"""J-4..J-10: self-send gate identity, #116 inline sync service, settle budget,
restart_timers vs SimulatedClock, redaction, on_plugin_error, exit-window snapshot.

Run: python p2_gate_and_inline.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time

sys.path.insert(0, r"<workspace>/_ref/xstate-statemachine")

from src.xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SimulatedClock,
    SnapshotMidStepError,
    SyncInterpreter,
    create_machine,
)
from src.xstate_statemachine.plugins import (  # noqa: E402
    LoggingInspector,
    PluginBase,
)

OUT = {}

SPIN = {
    "id": "spin",
    "initial": "a",
    "maxIterations": 20,
    "context": {"n": 0},
    "states": {"a": {"on": {"T": {"actions": ["inc_and_resend"]}}}},
}


# --- J-4: self-send gate -- send from a task the action SPAWNED -------------
async def j4_spawned_task() -> None:
    """An action does create_task(send(...)): the child task inherits the
    contextvar context at creation time, so is it still 'self'?"""
    seen = {"n": 0}

    async def act(i, c, e, a):
        seen["n"] += 1
        if seen["n"] < 60:
            asyncio.create_task(i.send("T"))

    i = await Interpreter(
        create_machine(SPIN, logic=MachineLogic(actions={"inc_and_resend": act}))
    ).start()
    await i.send("T")
    await asyncio.sleep(1.0)
    OUT["j4_spawned_task_count"] = seen["n"]
    OUT["j4_spawned_task_budgeted"] = seen["n"] <= 25
    await i.stop()


# --- J-4b: send from a callback scheduled via call_soon ---------------------
async def j4b_call_soon() -> None:
    seen = {"n": 0}

    def act(i, c, e, a):
        seen["n"] += 1
        if seen["n"] < 60:
            asyncio.get_running_loop().call_soon(
                lambda: asyncio.ensure_future(i.send("T"))
            )

    i = await Interpreter(
        create_machine(SPIN, logic=MachineLogic(actions={"inc_and_resend": act}))
    ).start()
    await i.send("T")
    await asyncio.sleep(1.0)
    OUT["j4b_call_soon_count"] = seen["n"]
    OUT["j4b_call_soon_budgeted"] = seen["n"] <= 25
    await i.stop()


# --- J-4c: send_threadsafe from a thread the action spawned ----------------
async def j4c_threadsafe() -> None:
    seen = {"n": 0}
    loop = asyncio.get_running_loop()

    def act(i, c, e, a):
        seen["n"] += 1
        if seen["n"] < 60:
            threading.Thread(
                target=lambda: i.send_threadsafe("T"), daemon=True
            ).start()

    i = await Interpreter(
        create_machine(SPIN, logic=MachineLogic(actions={"inc_and_resend": act}))
    ).start()
    await i.send("T")
    await asyncio.sleep(1.5)
    OUT["j4c_threadsafe_count"] = seen["n"]
    OUT["j4c_threadsafe_budgeted"] = seen["n"] <= 25
    await i.stop()


# --- J-4d: the gate leaks across interpreters via a nested action ----------
async def j4d_nested() -> None:
    """Interpreter P's action drives interpreter Q synchronously; Q's own
    action then sends to Q. Does Q see the owner as itself?"""
    seen = {"n": 0}

    async def qact(i, c, e, a):
        seen["n"] += 1
        if seen["n"] < 60:
            await i.send("T")

    q = await Interpreter(
        create_machine(
            {**SPIN, "id": "q"},
            logic=MachineLogic(actions={"inc_and_resend": qact}),
        )
    ).start()

    async def pact(i, c, e, a):
        await q.send("T")

    p = await Interpreter(
        create_machine(
            {
                "id": "p",
                "initial": "a",
                "states": {"a": {"on": {"GO": {"actions": ["drive"]}}}},
            },
            logic=MachineLogic(actions={"drive": pact}),
        )
    ).start()
    await p.send("GO")
    await asyncio.sleep(1.0)
    OUT["j4d_nested_count"] = seen["n"]
    OUT["j4d_nested_budgeted"] = seen["n"] <= 25
    await p.stop()
    await q.stop()


# --- J-5: #116 -- does a SLOW plain-sync service block the event loop? -----
async def j5_slow_sync_service() -> None:
    cfg = {
        "id": "s",
        "initial": "w",
        "states": {
            "w": {"invoke": {"id": "svc", "src": "slow", "onDone": "d"}},
            "d": {},
        },
    }

    def slow(i, c, e):
        time.sleep(0.8)
        return 1

    ticks = {"n": 0}

    async def ticker():
        while True:
            ticks["n"] += 1
            await asyncio.sleep(0.01)

    t = asyncio.ensure_future(ticker())
    start = time.monotonic()
    i = await Interpreter(
        create_machine(cfg, logic=MachineLogic(services={"slow": slow}))
    ).start()
    elapsed = time.monotonic() - start
    OUT["j5_start_blocked_s"] = round(elapsed, 3)
    OUT["j5_loop_ticks_during_start"] = ticks["n"]
    t.cancel()
    await i.stop()


# --- J-6: settle budget -- can a LEGITIMATE long settle be cut? ------------
def j6_long_legit_settle() -> None:
    """A single macrostep with a legitimate chain of N 'always' hops, where
    N < maxIterations, but issued repeatedly in ONE drain."""
    n = 40
    states = {}
    for k in range(n):
        states[f"s{k}"] = {"always": f"s{k+1}"}
    states[f"s{n}"] = {"on": {"GO": "t0"}}
    # a second, equally long chain reached by GO
    for k in range(n):
        states[f"t{k}"] = {"always": f"t{k+1}"}
    states[f"t{n}"] = {}
    cfg = {"id": "L", "initial": "s0", "maxIterations": 50, "states": states}
    i = SyncInterpreter(create_machine(cfg)).start()
    OUT["j6_after_start"] = i.value
    OUT["j6_start_ok"] = i.last_transition_ok
    i.send("GO")
    OUT["j6_after_go"] = i.value
    OUT["j6_go_ok"] = i.last_transition_ok
    OUT["j6_err"] = type(i.last_error).__name__ if i.last_error else None
    i.stop()


def j6b_two_sends_same_drain() -> None:
    """Two INDEPENDENT events in one send_events batch, each needing 40 of a
    50 budget. The budget is per drain, so #2 inherits #1's spend."""
    n = 40
    states = {"idle": {"on": {"GO": "s0", "GO2": "u0"}}}
    for k in range(n):
        states[f"s{k}"] = {"always": f"s{k+1}"}
    states[f"s{n}"] = {"on": {"GO2": "u0"}}
    for k in range(n):
        states[f"u{k}"] = {"always": f"u{k+1}"}
    states[f"u{n}"] = {}
    cfg = {"id": "L2", "initial": "idle", "maxIterations": 50, "states": states}
    i = SyncInterpreter(create_machine(cfg)).start()
    i.send_events(["GO", "GO2"])
    OUT["j6b_value"] = i.value
    OUT["j6b_ok"] = i.last_transition_ok
    OUT["j6b_err"] = type(i.last_error).__name__ if i.last_error else None
    i.stop()


# --- J-7: restart_timers with a SimulatedClock -----------------------------
def j7_restart_timers_simclock() -> None:
    cfg = {
        "id": "tm",
        "initial": "a",
        "states": {"a": {"after": {1000: "b"}}, "b": {}},
    }
    c1 = SimulatedClock()
    i = SyncInterpreter(create_machine(cfg), clock=c1).start()
    c1.increment(400)
    snap = i.get_snapshot()
    OUT["j7_dormant_before_stop"] = i.has_dormant_timers
    i.stop()
    c2 = SimulatedClock()
    r = SyncInterpreter.from_snapshot(
        snap, create_machine(cfg), clock=c2, restart_timers=True
    )
    OUT["j7_dormant_after_restore"] = r.has_dormant_timers
    r.start()
    OUT["j7_dormant_after_start"] = r.has_dormant_timers
    c2.increment(600)  # the 600 ms that "remained"
    r.tick()
    OUT["j7_value_after_600"] = r.value
    c2.increment(400)
    r.tick()
    OUT["j7_value_after_1000"] = r.value
    r.stop()


def j7b_restore_no_flags() -> None:
    cfg = {
        "id": "tm2",
        "initial": "a",
        "states": {"a": {"after": {50: "b"}}, "b": {}},
    }
    i = SyncInterpreter(create_machine(cfg)).start()
    snap = i.get_snapshot()
    i.stop()
    r = SyncInterpreter.from_snapshot(snap, create_machine(cfg))
    OUT["j7b_dormant"] = r.has_dormant_timers
    OUT["j7b_status"] = r.status
    r.start()
    time.sleep(0.15)
    r.tick()
    OUT["j7b_value_after_wait"] = r.value
    OUT["j7b_dormant_after_start"] = r.has_dormant_timers
    r.stop()


# --- J-8: LoggingInspector redaction coverage / bypass ---------------------
def j8_redaction() -> None:
    from src.xstate_statemachine.plugins import redact

    probe = {
        "password": 1,
        "pwd": 2,
        "access_token": 3,
        "sessionId": 4,
        "iban": 5,
        "pan": 6,
        "email": 7,
        "pin": 8,
        "seed_phrase": 9,
        "mnemonic": 10,
        "account_number": 11,
        "dob": 12,
        "signature": 13,
        "cookie": 14,
        "bearer": 15,
        "client_secret": 16,
    }
    OUT["j8_not_redacted"] = sorted(
        k for k, v in redact(probe).items() if v != "***"
    )
    # nested: is context nested under a non-sensitive key redacted?
    OUT["j8_nested"] = redact({"order": {"api_key": "x"}})
    # error events: is ErrorEvent payload redacted?
    OUT["j8_error_branch_redacted"] = "ErrorEvent -> event.error, no _safe()"
    # does on_action_execute / on_guard_evaluated leak?
    OUT["j8_hooks_without_safe"] = [
        "on_event_received(ErrorEvent/DoneEvent/AfterEvent .data)",
    ]
    # DoneEvent data carries a service result -- is it redacted?
    logs = []

    class _H(logging.Handler):
        def emit(self, rec):
            logs.append(rec.getMessage())

    lg = logging.getLogger("src.xstate_statemachine.plugins")
    lg.setLevel(logging.INFO)
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
                services={"svc": lambda i, c, e: {"api_key": "SECRET123"}}
            ),
        )
    )
    i.use(LoggingInspector())
    i.start()
    time.sleep(0.05)
    i.tick()
    i.stop()
    lg.removeHandler(h)
    OUT["j8_secret_in_logs"] = any("SECRET123" in m for m in logs)
    OUT["j8_log_sample"] = [m for m in logs if "SECRET123" in m][:2]


# --- J-9: on_plugin_error semantics ---------------------------------------
def j9_plugin_error() -> None:
    class Bad(PluginBase):
        def on_transition(self, i, f, t, tr):
            raise ValueError("bad hook")

    class Watch(PluginBase):
        def __init__(self):
            self.calls = []

        def on_plugin_error(self, i, plugin, hook, error):
            self.calls.append((type(plugin).__name__, hook, repr(error)))

    class BadWatcher(PluginBase):
        """A watcher whose own on_plugin_error raises."""

        def on_plugin_error(self, i, plugin, hook, error):
            raise RuntimeError("watcher exploded")

    cfg = {"id": "p", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
    w = Watch()
    i = SyncInterpreter(create_machine(cfg))
    i.use(Bad())
    i.use(w)
    i.use(BadWatcher())
    logging.disable(logging.CRITICAL)
    i.start()
    i.send("GO")
    logging.disable(logging.NOTSET)
    OUT["j9_watch_calls"] = w.calls
    OUT["j9_last_plugin_error"] = str(i.last_plugin_error)
    OUT["j9_status"] = i.status
    i.stop()

    # async def hook -- reported?
    class AsyncHook(PluginBase):
        async def on_transition(self, i, f, t, tr):  # type: ignore[override]
            pass

    j = SyncInterpreter(create_machine(cfg))
    j.use(AsyncHook())
    logging.disable(logging.CRITICAL)
    j.start()
    j.send("GO")
    logging.disable(logging.NOTSET)
    OUT["j9_asyncdef_reported"] = str(j.last_plugin_error)
    j.stop()


# --- J-10: exit-window snapshot content (was "ok" in p1) ------------------
def j10_exit_window_content() -> None:
    cfg = {
        "id": "ex2",
        "initial": "a",
        "states": {
            "a": {
                "initial": "a1",
                "states": {"a1": {"exit": ["probe"]}},
                "on": {"GO": "b"},
            },
            "b": {},
        },
    }
    got = {}

    def probe(i, c, e, a):
        try:
            got["snap"] = i.get_persisted_snapshot()
        except SnapshotMidStepError:
            got["refused"] = True

    i = SyncInterpreter(
        create_machine(cfg, logic=MachineLogic(actions={"probe": probe}))
    ).start()
    i.send("GO")
    if "snap" in got:
        OUT["j10_exit_snapshot_state_ids"] = got["snap"]["state_ids"]
        OUT["j10_exit_snapshot_config"] = got["snap"]["configuration"]
        try:
            r = SyncInterpreter.from_snapshot(
                json.dumps(got["snap"], default=str),
                create_machine(
                    cfg, logic=MachineLogic(actions={"probe": probe})
                ),
            )
            OUT["j10_restored_value"] = r.value
            OUT["j10_restored_status"] = r.status
        except Exception as exc:  # noqa: BLE001
            OUT["j10_restore_error"] = f"{type(exc).__name__}: {exc}"
    else:
        OUT["j10_exit"] = "refused"
    i.stop()


async def main() -> None:
    await j4_spawned_task()
    await j4b_call_soon()
    await j4c_threadsafe()
    await j4d_nested()
    await j5_slow_sync_service()
    j6_long_legit_settle()
    j6b_two_sends_same_drain()
    j7_restart_timers_simclock()
    j7b_restore_no_flags()
    j8_redaction()
    j9_plugin_error()
    j10_exit_window_content()
    print(json.dumps(OUT, indent=2, default=str))


if __name__ == "__main__":
    logging.getLogger("src.xstate_statemachine.base_interpreter").setLevel(
        logging.CRITICAL
    )
    asyncio.run(main())
