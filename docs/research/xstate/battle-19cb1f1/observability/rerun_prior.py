"""
Re-run of the 5e07ba8 observability track's 9 defects (probe_matrix.py +
probe_matrix2.py) against 3ed3099, adapted where round-4 changed semantics.

Adaptations vs the original scripts:
  - D-observability-3 (deferred replay folded into triggering Receipt): #125
    explicitly makes replay its own macrostep now. Kept the same probe but
    print both receipts' state_ids to see if the fold-in is fixed.
  - No probe took a genuinely mid-macrostep snapshot in the original track
    (all snapshots were taken at quiescence, after send(wait=True) returned),
    so SnapshotMidStepError (#102) does not apply to any of these 9 and no
    adaptation for it was needed here.
  - Everything else runs unmodified logic; only imports/version-agnostic.

Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python rerun_prior.py
"""
import asyncio
import json
import logging

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
    PluginBase,
    QueueOverflowError,
    SnapshotDriftError,
    WrongThreadError,
    UnknownEventError,
)

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
        self.calls = []

    def _rec(self, name, **kw):
        self.calls.append((name, kw))

    def on_event_received(self, interpreter, event):
        self._rec("on_event_received", type=getattr(event, "type", None))

    def on_transition(self, interpreter, source, target, transition):
        self._rec("on_transition")

    def on_guard_error(self, interpreter, guard_name, event, error):
        self._rec("on_guard_error", guard=guard_name, error=repr(error))

    def on_event_dropped(self, interpreter, event, reason):
        self._rec("on_event_dropped", type=getattr(event, "type", None), reason=reason)

    def on_resolve_error(self, interpreter, error, event):
        self._rec("on_resolve_error", error=repr(error))


# D-observability-1/2: guard raise, policies false/true/raise -----------------
def d1_d2_guard_raise(policy):
    def bad_guard(ctx, ev):
        raise ValueError("guard-boom")

    cfg = {
        "id": f"m_guard_{policy}",
        "initial": "a",
        "guardErrorPolicy": policy,
        "states": {"a": {"on": {"GO": {"target": "b", "guard": "bad_guard"}}}, "b": {}},
    }
    try:
        logic = MachineLogic(guards={"bad_guard": bad_guard})
        machine = create_machine(cfg, logic=logic)
        rec = Recorder()
        interp = SyncInterpreter(machine).use(rec).start()
        receipt = interp.send("GO", wait=True)
        print(f"D1/D2 guardErrorPolicy={policy}: receipt(changed={receipt.changed}, "
              f"error={receipt.error!r}), last_transition_ok={interp.last_transition_ok}, "
              f"last_error={interp.last_error!r}, on_guard_error fired={'on_guard_error' in [c[0] for c in rec.calls]}")
    except Exception as e:
        print(f"D1/D2 guardErrorPolicy={policy}: BUILD-TIME EXC {e!r}")


# D-observability-3: deferred replay folded into triggering Receipt? --------
def d3_deferred_replay():
    cfg = {
        "id": "m_defer_replay",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {"a": {"on": {"ARM": "b"}}, "b": {"on": {"LATE": "c"}}, "c": {}},
    }
    machine = create_machine(cfg, logic=MachineLogic())
    interp = SyncInterpreter(machine).start()
    r1 = interp.send("LATE", wait=True)
    r2 = interp.send("ARM", wait=True)
    print(f"D3 deferred replay: r1(LATE, deferred)={getattr(r1,'deferred',None)} state_ids={sorted(r1.state_ids)}, "
          f"r2(ARM) state_ids={sorted(r2.state_ids)}, final={sorted(interp.current_state_ids)}")
    print("  -- interpretation: if r2.state_ids already reflects post-replay state 'c', the fold is unchanged;"
          " #125 promises replay is its own macrostep, i.e. a *separate* on_transition, which we can't see from"
          " Receipt shape alone (see hook order check below).")


# D-observability-4: SyncInterpreter ctor rejects max_queue_size -----------
def d4_sync_ctor_asymmetry():
    cfg = {"id": "m_d4", "initial": "a", "states": {"a": {}}}
    machine = create_machine(cfg, logic=MachineLogic())
    try:
        SyncInterpreter(machine, max_queue_size=1)
        print("D4: no TypeError (CHANGED)")
    except TypeError as e:
        print(f"D4: TypeError as before: {e!r}")


# D-observability-5: StateNotFound -> hook or just Receipt/log? -----------
def d5_state_not_found():
    cfg = {"id": "m_snf", "initial": "a", "states": {"a": {"on": {"GO": "does.not.exist"}}}}
    machine = create_machine(cfg, logic=MachineLogic(), strict_targets=False)
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()
    receipt = interp.send("GO", wait=True)
    print(f"D5 StateNotFound: receipt.error={receipt.error!r}, last_error={interp.last_error!r}, "
          f"status={interp.status}, hooks={[c[0] for c in rec.calls]}")


# D-observability-6: .use() vs .plugins= wrap parity (refuted last round) --
def d6_use_vs_setter_parity():
    class Buggy(PluginBase):
        def on_transition(self, interpreter, source, target, transition):
            raise RuntimeError("buggy plugin")

    cfg = {"id": "m_d6", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
    m1 = create_machine(cfg, logic=MachineLogic())
    i1 = SyncInterpreter(m1).use(Buggy()).start()
    r1 = i1.send("GO", wait=True)

    m2 = create_machine({**cfg, "id": "m_d6b"}, logic=MachineLogic())
    i2 = SyncInterpreter(m2)
    i2.plugins = [Buggy()]
    i2.start()
    r2 = i2.send("GO", wait=True)
    print(f"D6 .use() receipt(changed={r1.changed}, error={r1.error!r}); "
          f".plugins= receipt(changed={r2.changed}, error={r2.error!r}) -- "
          f"{'identical (still refuted)' if (r1.changed, r1.error) == (r2.changed, r2.error) else 'DIFFERS (regression?)'}")


# D-observability-7: has_dormant_invocations only clears on start() --------
async def d7_dormant_invoke_flag():
    async def slow_service(interp, ctx, ev):
        await asyncio.sleep(100)

    cfg = {"id": "m_d7", "initial": "a", "states": {"a": {"invoke": {"src": "slow_service", "id": "svc"}}}}
    logic = MachineLogic(services={"slow_service": slow_service})
    machine = create_machine(cfg, logic=logic)
    interp = Interpreter(machine)
    await interp.start()
    snap = json.dumps(interp.get_persisted_snapshot())
    await interp.stop()
    restored = Interpreter.from_snapshot(snap, machine, restart_services=True)
    print(f"D7: before .start() has_dormant_invocations={restored.has_dormant_invocations}, status={restored.status}")
    await restored.start()
    print(f"    after  .start() has_dormant_invocations={restored.has_dormant_invocations}")
    await restored.stop()


# D-observability-8: stop() default drops pending queue silently ----------
async def d8_stop_drops_pending():
    cfg = {"id": "m_d8", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
    machine = create_machine(cfg, logic=MachineLogic())
    interp = Interpreter(machine)
    await interp.start()
    for i in range(5):
        interp.send(f"X{i}", wait=False)
    before = len(interp.pending_events)
    log_records.clear()
    await interp.stop()
    dropped_hooks = [c for c in [] ]  # no recorder plugged for this specific run; see note
    print(f"D8: pending_events before stop={before}, status after stop={interp.status}; "
          f"(no on_event_dropped hook exists for this path per prior finding -- re-checking with a plugin below)")

    rec = Recorder()
    machine2 = create_machine({**cfg, "id": "m_d8b"}, logic=MachineLogic())
    interp2 = Interpreter(machine2).use(rec)
    await interp2.start()
    for i in range(5):
        interp2.send(f"X{i}", wait=False)
    await interp2.stop()
    dropped = [c for c in rec.calls if c[0] == "on_event_dropped"]
    print(f"D8b: on_event_dropped fired {len(dropped)} times for {before} abandoned events -- "
          f"{'FIXED (signal now exists)' if dropped else 'STILL-PRESENT (silent drop)'}")


# D-observability-9: no to_dict/to_json/config re-export ------------------
def d9_no_config_reexport():
    cfg = {"id": "m_d9", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {"type": "final"}}}
    machine = create_machine(cfg, logic=MachineLogic())
    has = hasattr(machine, "to_dict") or hasattr(machine, "to_json") or hasattr(machine, "config")
    print(f"D9: to_dict/to_json/config present={has} (to_mermaid={hasattr(machine,'to_mermaid')}, "
          f"to_plantuml={hasattr(machine,'to_plantuml')})")


if __name__ == "__main__":
    for p in ("false", "true", "raise"):
        d1_d2_guard_raise(p)
    d3_deferred_replay()
    d4_sync_ctor_asymmetry()
    d5_state_not_found()
    d6_use_vs_setter_parity()
    asyncio.run(d7_dormant_invoke_flag())
    asyncio.run(d8_stop_drops_pending())
    d9_no_config_reexport()
    print("DONE")
