"""
NEW attacks on 19cb1f1's round-9 machinery (#203-#210) for the OBSERVABILITY
track. Standalone: stdlib + xstate_statemachine only. Time-boxed subset
(see battle-19cb1f1/observability.md for reductions taken).

V1: enter+exit in one macrostep via `always` roll-forward -- invoke never
    submitted for a state visited transiently (#204 statesToInvoke).
V2: actionErrorPolicy=rollback cuts a state that had armed an invoke in the
    SAME macrostep -- invoke never submitted (#204, rollback half).
V3: after.* matching -- only an engine-minted _EngineAfter fires an `after`
    transition; a hand-built public AfterEvent does NOT (#203, the fix).
V4: raise(delay=) self-send ping-pong is charged as engine work and trips
    RunawayChainError at (about) the same lap as a zero-delay raise cycle.
V5: rollback+onDone storm strands an invocation at the cut -> on_invocation_
    stranded fires exactly once, RunawayChainError.stranded is populated,
    ERROR log names the state.
V6: lap-parity sweep, rollback+onDone shape, maxIterations in {1..25} both
    engines (sync vs async lap count).
V7: a snapshot taken when an invoke is "armed but settle not yet run" (an
    always-chain mid-microstep before quiescence is unreachable publicly --
    documented as SnapshotMidStepError) -- confirm refusal, not a torn/duped
    invocation on restore.

Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python new_attacks_r9.py
"""
import asyncio
import logging
import time

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
    PluginBase,
    RunawayChainError,
    SnapshotMidStepError,
)
from xstate_statemachine.events import AfterEvent

log_records = []


class CaptureHandler(logging.Handler):
    def emit(self, record):
        log_records.append((record.levelname, record.getMessage()))


lib_logger = logging.getLogger("xstate_statemachine")
lib_logger.setLevel(logging.DEBUG)
lib_logger.addHandler(CaptureHandler())
lib_logger.propagate = False


class Recorder(PluginBase):
    def __init__(self):
        self.stranded = []

    def on_invocation_stranded(self, interpreter, state_id, invoke_id, error):
        self.stranded.append((state_id, invoke_id))


def v1_enter_exit_same_macrostep_always():
    """A state entered then exited within one macrostep via `always` must
    never submit its invoke (#204, roll-FORWARD half)."""
    calls = {"n": 0}

    def svc(interpreter, context, event):
        calls["n"] += 1
        return "ok"

    cfg = {
        "id": "v1",
        "initial": "start",
        "context": {},
        "states": {
            "start": {"on": {"GO": "transient"}},
            "transient": {
                "invoke": {"src": "svc", "onDone": "done_state"},
                "always": {"target": "skip"},
            },
            "skip": {"type": "final"},
            "done_state": {"type": "final"},
        },
    }
    machine = create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
    interp = SyncInterpreter(machine)
    interp.start()
    interp.send("GO")
    print(
        f"V1 enter+exit same macrostep (always roll-forward): "
        f"final_state={sorted(interp.current_state_ids)} "
        f"svc_called={calls['n']} (expect: ['v1.skip'], svc_called=0)"
    )


def v3_after_provenance():
    cfg = {
        "id": "v3",
        "initial": "waiting",
        "context": {},
        "states": {
            "waiting": {"after": {60000: "expired"}, "on": {"WORK": "working"}},
            "working": {"type": "final"},
            "expired": {"type": "final"},
        },
    }
    machine = create_machine(cfg, logic=MachineLogic())
    interp = SyncInterpreter(machine)
    interp.start()
    forged = AfterEvent("after.60000.v3.waiting", None, None)
    interp.send(forged)
    print(
        f"V3 hand-built public AfterEvent sent -> "
        f"state={sorted(interp.current_state_ids)} "
        f"(expect: still ['v3.waiting'], NOT ['v3.expired'] -- #203 fix)"
    )


def v4_delayed_self_send_debt():
    cfg = {
        "id": "v4",
        "initial": "a",
        "maxIterations": 15,
        "context": {},
        "states": {
            "a": {
                "entry": [{"type": "raise", "params": {"event": "GO", "delay": 1}}],
                "on": {"GO": "b"},
            },
            "b": {
                "entry": [{"type": "raise", "params": {"event": "GO", "delay": 1}}],
                "on": {"GO": "a"},
            },
        },
    }
    machine = create_machine(cfg, logic=MachineLogic())

    async def main():
        i = Interpreter(machine)
        await i.start()
        t0 = time.time()
        while i.last_error is None and time.time() - t0 < 10:
            await asyncio.sleep(0.02)
        await i.stop()
        return i.last_error

    err = asyncio.run(main())
    print(
        f"V4 raise(delay=1ms) self-ping-pong (async engine -- SyncInterpreter's "
        f"timer-paced variant has user standing by design, does not trip): "
        f"last_error={err!r} "
        f"(expect: RunawayChainError -- delayed self-send charged as engine work, "
        f"maxIterations=15 bounds it)"
    )


def v5_stranded_invocation_hook():
    rec = Recorder()

    def boom(*a):
        raise RuntimeError("entry failed")

    cfg = {
        "id": "v5",
        "actionErrorPolicy": "rollback",
        "initial": "idle",
        "maxIterations": 10,
        "states": {
            "idle": {"on": {"GO": "starting"}},
            "starting": {
                "invoke": {"id": "sub", "src": "svc", "onDone": "recording"}
            },
            "recording": {"entry": ["boom"]},
        },
    }
    machine = create_machine(
        cfg, logic=MachineLogic(actions={"boom": boom}, services={"svc": lambda i, c, e: 1})
    )
    interp = SyncInterpreter(machine).use(rec)
    interp.start()
    interp.send("GO", wait=True)
    err = interp.last_error
    stranded_attr = getattr(err, "stranded", None) if err else None
    error_logs = [m for lvl, m in log_records if lvl == "ERROR" and "cut by the chain budget" in m]
    print(
        f"V5 rollback/cut-onDone-storm stranded hook: "
        f"last_error={type(err).__name__ if err else None} "
        f"err.stranded={stranded_attr} plugin_hook_calls={rec.stranded} "
        f"error_log_named_state={bool(error_logs)} "
        f"(expect: RunawayChainError with .stranded=('sub',), "
        f"on_invocation_stranded fired once w/ ('spin.starting','sub'), ERROR log)"
    )


def v6_lap_parity_sweep():
    def make(engine_cls, limit):
        calls = {"n": 0}

        def svc(interpreter, context, event):
            calls["n"] += 1
            return "ok"

        cfg = {
            "id": f"v6_{engine_cls.__name__}_{limit}",
            "initial": "spin",
            "context": {},
            "maxIterations": limit,
            "states": {"spin": {"invoke": {"src": "svc", "onDone": "spin"}}},
        }
        machine = create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
        return engine_cls(machine), calls

    mismatches = []
    for limit in range(1, 16):
        interp_s, calls_s = make(SyncInterpreter, limit)
        interp_s.start()
        t0 = time.time()
        while interp_s.last_error is None and time.time() - t0 < 2:
            interp_s.tick()
        laps_sync = calls_s["n"]

        async def run_async():
            interp_a, calls_a = make(Interpreter, limit)
            await interp_a.start()
            t0 = time.time()
            while interp_a.last_error is None and time.time() - t0 < 2:
                await asyncio.sleep(0.001)
            return calls_a["n"]

        laps_async = asyncio.run(run_async())
        if laps_sync != laps_async:
            mismatches.append((limit, laps_sync, laps_async))
    print(
        f"V6 lap-parity sweep limits 1-15 (invoke.onDone loop, reduced from 1-25 "
        f"per time budget): "
        f"mismatches={mismatches} (expect: [] -- all three lanes agree per #209)"
    )


def v7_snapshot_mid_macrostep_invoke_arming():
    class SnapProbe(PluginBase):
        def __init__(self):
            self.result = None

        def on_transition(self, interpreter, from_state, to_state, event):
            if self.result is None:
                try:
                    interpreter.get_persisted_snapshot()
                    self.result = "ok(no error)"
                except SnapshotMidStepError as e:
                    self.result = f"refused: {e}"

    def svc(interpreter, context, event):
        return "ok"

    cfg = {
        "id": "v7",
        "initial": "start",
        "context": {},
        "states": {
            "start": {"on": {"GO": "spin"}},
            "spin": {"invoke": {"src": "svc", "onDone": "done"}},
            "done": {"type": "final"},
        },
    }
    machine = create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
    probe = SnapProbe()
    interp = SyncInterpreter(machine).use(probe)
    interp.start()
    interp.send("GO")
    print(
        f"V7 snapshot attempt mid on_transition (invoke arming in-flight): "
        f"result={probe.result} (expect: refused with SnapshotMidStepError, "
        f"never a torn/duplicated invocation)"
    )


if __name__ == "__main__":
    v1_enter_exit_same_macrostep_always()
    v3_after_provenance()
    v4_delayed_self_send_debt()
    v5_stranded_invocation_hook()
    v6_lap_parity_sweep()
    v7_snapshot_mid_macrostep_invoke_arming()
    print("DONE")
