"""
Observability battle-track probe matrix for xstate-statemachine @ 5e07ba8.

Runs each failure mode against both engines where applicable, using a
recording PluginBase subclass that timestamps every hook call (monotonic
counter), and prints: which hooks fired, in what order, exactly once?,
receipt contents, last_transition_ok/last_error, and log records captured
via a logging.Handler attached to the library logger.

Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python probe_matrix.py
"""
import asyncio
import logging
import sys

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
    PluginBase,
    Event,
    OverflowPolicy,
    RunawayChainError,
    QueueOverflowError,
    StateNotFoundError,
    UnknownEventError,
    InvalidEventPayloadError,
    SnapshotDriftError,
    WrongThreadError,
)

log_records = []


class CaptureHandler(logging.Handler):
    def emit(self, record):
        log_records.append((record.levelname, record.getMessage()))


lib_logger = logging.getLogger("xstate_statemachine")
lib_logger.setLevel(logging.DEBUG)
lib_logger.addHandler(CaptureHandler())
lib_logger.propagate = False  # keep stray tracebacks off stdout for readability


class Recorder(PluginBase):
    def __init__(self):
        self.calls = []
        self._seq = 0

    def _rec(self, name, **kw):
        self._seq += 1
        self.calls.append((self._seq, name, kw))

    def on_interpreter_start(self, interpreter):
        self._rec("on_interpreter_start")

    def on_interpreter_stop(self, interpreter):
        self._rec("on_interpreter_stop")

    def on_event_received(self, interpreter, event):
        self._rec("on_event_received", type=getattr(event, "type", None))

    def on_transition(self, interpreter, source, target, transition):
        self._rec("on_transition", source=sorted(s.id for s in source) if hasattr(source, "__iter__") else None)

    def on_action_execute(self, interpreter, action):
        self._rec("on_action_execute", action=action.type)

    def on_action_error(self, interpreter, action, error):
        self._rec("on_action_error", action=action.type, error=repr(error))

    def on_transition_failed(self, interpreter, transition, failed_actions):
        self._rec("on_transition_failed", n=len(failed_actions))

    def on_guard_error(self, interpreter, guard_name, event, error):
        self._rec("on_guard_error", guard=guard_name, error=repr(error))

    def on_unhandled_event(self, interpreter, event, active_state_ids, disposition):
        self._rec("on_unhandled_event", type=event.type, disposition=disposition)

    def on_event_dropped(self, interpreter, event, reason):
        self._rec("on_event_dropped", type=getattr(event, "type", None), reason=reason)

    def on_error(self, interpreter, error):
        self._rec("on_error", error=repr(error))

    def on_done(self, interpreter, output):
        self._rec("on_done", output=output)

    def on_guard_evaluated(self, interpreter, guard_name, event, result):
        self._rec("on_guard_evaluated", guard=guard_name, result=result)

    def on_service_start(self, interpreter, invocation):
        self._rec("on_service_start", id=invocation.id)

    def on_service_done(self, interpreter, invocation, result):
        self._rec("on_service_done", id=invocation.id, result=result)

    def on_service_error(self, interpreter, invocation, error):
        self._rec("on_service_error", id=invocation.id, error=repr(error))


def dump(title, rec, extra=None):
    print(f"\n=== {title} ===")
    for seq, name, kw in rec.calls:
        print(f"  {seq:>3} {name} {kw}")
    if extra:
        for k, v in extra.items():
            print(f"  -- {k}: {v}")
    from collections import Counter
    counts = Counter(name for _, name, _ in rec.calls)
    dupes = {k: v for k, v in counts.items() if v > 1}
    if dupes:
        print(f"  !! fired more than once: {dupes}")


# ---------------------------------------------------------------------------
# 1. Action raise under each actionErrorPolicy (sync engine)
# ---------------------------------------------------------------------------
def probe_action_raise(policy):
    def boom(interp, ctx, ev, ad):
        raise ValueError("boom")

    cfg = {
        "id": f"m_action_{policy}",
        "initial": "a",
        "actionErrorPolicy": policy,
        "states": {
            "a": {"on": {"GO": {"target": "b", "actions": ["boom"]}}},
            "b": {},
        },
    }
    logic = MachineLogic(actions={"boom": boom})
    machine = create_machine(cfg, logic=logic)
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()
    log_records.clear()
    receipt = interp.send("GO", wait=True)
    dump(
        f"action raise / policy={policy}",
        rec,
        {
            "receipt": receipt,
            "last_transition_ok": interp.last_transition_ok,
            "last_error": interp.last_error,
            "status": interp.status,
            "logs": [l for l in log_records if "boom" in l[1] or "Action" in l[1] or "action" in l[1]],
        },
    )


# ---------------------------------------------------------------------------
# 2. Guard raise under each guardErrorPolicy
# ---------------------------------------------------------------------------
def probe_guard_raise(policy):
    def bad_guard(ctx, ev):
        raise ValueError("guard-boom")

    cfg = {
        "id": f"m_guard_{policy}",
        "initial": "a",
        "guardErrorPolicy": policy,
        "states": {
            "a": {"on": {"GO": {"target": "b", "guard": "bad_guard"}}},
            "b": {},
        },
    }
    logic = MachineLogic(guards={"bad_guard": bad_guard})
    machine = create_machine(cfg, logic=logic)
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()
    log_records.clear()
    receipt = interp.send("GO", wait=True)
    dump(
        f"guard raise / policy={policy}",
        rec,
        {
            "receipt": receipt,
            "last_transition_ok": interp.last_transition_ok,
            "last_error": interp.last_error,
            "status": interp.status,
        },
    )


# ---------------------------------------------------------------------------
# 3. Unhandled event under each onUnhandled policy
# ---------------------------------------------------------------------------
def probe_unhandled(policy):
    cfg = {
        "id": f"m_unhandled_{policy}",
        "initial": "a",
        "onUnhandled": policy,
        "states": {"a": {}},
    }
    machine = create_machine(cfg, logic=MachineLogic())
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()
    receipt = None
    err = None
    try:
        receipt = interp.send("TYPO", wait=True)
    except Exception as e:
        err = repr(e)
    dump(
        f"unhandled event / onUnhandled={policy}",
        rec,
        {
            "receipt": receipt,
            "send_raised": err,
            "status": interp.status,
            "deferred_count": interp.deferred_count,
        },
    )


# ---------------------------------------------------------------------------
# 4. Deferred replay
# ---------------------------------------------------------------------------
def probe_deferred_replay():
    cfg = {
        "id": "m_defer_replay",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {
            "a": {"on": {"ARM": "b"}},
            "b": {"on": {"LATE": "c"}},
            "c": {},
        },
    }
    machine = create_machine(cfg, logic=MachineLogic())
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()
    r1 = interp.send("LATE", wait=True)  # deferred in state a
    r2 = interp.send("ARM", wait=True)  # a->b, should trigger replay of LATE
    dump(
        "deferred replay",
        rec,
        {
            "receipt_LATE_initial": r1,
            "receipt_ARM": r2,
            "final_state": interp.current_state_ids,
            "deferred_count_after": interp.deferred_count,
        },
    )


# ---------------------------------------------------------------------------
# 5. Inbox overflow, each policy
# ---------------------------------------------------------------------------
def probe_overflow(policy):
    # NOTE: max_queue_size/overflow_policy are Interpreter (async)-only
    # constructor params; SyncInterpreter drains synchronously inside
    # send() so there is no queue to overflow on that engine. Covered by
    # probe_overflow_async below on both RAISE and DROP_NEWEST.
    pass


async def probe_overflow_async(policy):
    cfg = {"id": f"m_overflow_async_{policy.name}", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
    machine = create_machine(cfg, logic=MachineLogic())
    rec = Recorder()
    interp = Interpreter(machine, max_queue_size=1, overflow_policy=policy).use(rec)
    await interp.start()
    results = []
    for i in range(4):
        try:
            r = interp.send(f"X{i}")
            results.append(("queued", i))
        except QueueOverflowError as e:
            results.append(("raised", repr(e)))
    await asyncio.sleep(0.05)
    dump(
        f"inbox overflow (async engine) / policy={policy}",
        rec,
        {"results": results, "queue_depth": interp.queue_depth},
    )
    await interp.stop()


# ---------------------------------------------------------------------------
# 6. Chain (runaway) budget trip
# ---------------------------------------------------------------------------
def probe_chain_budget():
    def rechain(interp, ctx, ev, ad):
        interp.send("LOOP")

    cfg = {
        "id": "m_chain",
        "initial": "a",
        "maxIterations": 5,
        "states": {"a": {"on": {"LOOP": {"target": "a", "actions": ["rechain"]}}}},
    }
    logic = MachineLogic(actions={"rechain": rechain})
    machine = create_machine(cfg, logic=logic)
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()
    receipt = interp.send("LOOP", wait=True)
    dump(
        "chain (runaway) budget trip",
        rec,
        {
            "receipt": receipt,
            "last_transition_ok": interp.last_transition_ok,
            "last_error": interp.last_error,
            "status": interp.status,
        },
    )


# ---------------------------------------------------------------------------
# 7/8. invoke error / child failure (escalate too), async engine
# ---------------------------------------------------------------------------
async def probe_invoke_error(with_onerror):
    async def failing_service(interp, ctx, ev):
        raise RuntimeError("svc-fail")

    on = {"onError": "err"} if with_onerror else {}
    cfg = {
        "id": f"m_invoke_err_{with_onerror}",
        "initial": "a",
        "states": {
            "a": {
                "invoke": {"src": "failing_service", "id": "svc", **on},
            },
            "err": {},
        },
    }
    logic = MachineLogic(services={"failing_service": failing_service})
    machine = create_machine(cfg, logic=logic)
    rec = Recorder()
    interp = Interpreter(machine).use(rec)
    await interp.start()
    await asyncio.sleep(0.05)
    dump(
        f"invoke error / onError_declared={with_onerror}",
        rec,
        {"status": interp.status, "error": interp.error},
    )
    if interp.status == "running":
        await interp.stop()


async def probe_escalate():
    def esc(interp, ctx, ev, ad):
        raise RuntimeError("will be escalated")

    child_cfg = {
        "id": "child",
        "initial": "c",
        "states": {"c": {"entry": ["blow"]}},
        "actionErrorPolicy": "fail",
    }

    def blow(interp, ctx, ev, ad):
        raise RuntimeError("child-blew-up")

    child_logic = MachineLogic(actions={"blow": blow})
    child_machine = create_machine(child_cfg, logic=child_logic)

    parent_cfg = {
        "id": "parent_escalate",
        "initial": "p",
        "states": {
            "p": {
                "invoke": {"src": "child_machine", "id": "kid", "onError": "handled"},
            },
            "handled": {},
        },
    }
    parent_logic = MachineLogic(services={"child_machine": child_machine})
    parent_machine = create_machine(parent_cfg, logic=parent_logic)
    rec = Recorder()
    interp = Interpreter(parent_machine).use(rec)
    await interp.start()
    await asyncio.sleep(0.05)
    dump("child machine failure -> ErrorEvent -> onError (parity check #99)", rec, {"status": interp.status})
    if interp.status == "running":
        await interp.stop()


# ---------------------------------------------------------------------------
# 9. StateNotFound under strict_targets=False
# ---------------------------------------------------------------------------
def probe_state_not_found():
    cfg = {
        "id": "m_snf",
        "initial": "a",
        "states": {"a": {"on": {"GO": "does.not.exist"}}},
    }
    machine = create_machine(cfg, logic=MachineLogic(), strict_targets=False)
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()
    receipt = interp.send("GO", wait=True)
    dump(
        "StateNotFound under strict_targets=False",
        rec,
        {
            "receipt": receipt,
            "last_transition_ok": interp.last_transition_ok,
            "last_error": interp.last_error,
            "status": interp.status,
        },
    )


# ---------------------------------------------------------------------------
# 10. strict violation (UnknownEventError at call site)
# ---------------------------------------------------------------------------
def probe_strict_violation():
    cfg = {"id": "m_strict", "initial": "a", "strict": True, "states": {"a": {"on": {"KNOWN": "a"}}}}
    machine = create_machine(cfg, logic=MachineLogic())
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()
    try:
        interp.send("KNOWN_TYPO")
        result = "no exception (BUG if strict)"
    except UnknownEventError as e:
        result = repr(e)
    dump("strict violation", rec, {"send_result": result})


# ---------------------------------------------------------------------------
# 11. wrong thread
# ---------------------------------------------------------------------------
async def probe_wrong_thread():
    import threading

    cfg = {"id": "m_thread", "initial": "a", "states": {"a": {}}}
    machine = create_machine(cfg, logic=MachineLogic())
    interp = Interpreter(machine)
    await interp.start()
    result = {}

    def other_thread():
        try:
            interp.send("X")
            result["outcome"] = "no exception (BUG)"
        except WrongThreadError as e:
            result["outcome"] = repr(e)

    t = threading.Thread(target=other_thread)
    t.start()
    t.join()
    dump("wrong thread", Recorder(), {"result": result})
    await interp.stop()


if __name__ == "__main__":
    for p in ("continue", "rollback", "fail"):
        probe_action_raise(p)
    for p in ("false", "true", "raise"):
        probe_guard_raise(p)
    for p in ("ignore", "defer", "error"):
        probe_unhandled(p)
    probe_deferred_replay()
    probe_overflow(OverflowPolicy.DROP_NEWEST)
    probe_overflow(OverflowPolicy.RAISE)
    asyncio.run(probe_overflow_async(OverflowPolicy.DROP_NEWEST))
    asyncio.run(probe_overflow_async(OverflowPolicy.RAISE))
    probe_chain_budget()
    asyncio.run(probe_invoke_error(True))
    asyncio.run(probe_invoke_error(False))
    asyncio.run(probe_escalate())
    probe_state_not_found()
    probe_strict_violation()
    asyncio.run(probe_wrong_thread())
    print("\nDONE")
