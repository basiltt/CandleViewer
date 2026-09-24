"""m2 — new attacks on cec108b, FUZZ track.

A-numbers continue the prior report's scheme.
Each attack prints one line: `NAME  PASS/FAIL  detail`.
"""
from __future__ import annotations
import asyncio, copy, json, logging, os, random, sys, threading, time
logging.disable(logging.CRITICAL)

from xstate_statemachine import (
    create_machine, Interpreter, SyncInterpreter, MachineLogic,
    InvalidEventError, SnapshotCorruptError, SnapshotMidStepError,
    SnapshotSerializationError, RootTargetError, QueueOverflowError,
    XStateMachineError,
)

RESULTS = []


def rec(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"{name:34s} {'PASS' if ok else 'FAIL'}  {detail}", flush=True)


CFG_KEYS = {"guardErrorPolicy", "actionErrorPolicy", "onUnhandled",
            "maxIterations"}


def mk(cfg, actions=None, guards=None, services=None, **kw):
    logic = MachineLogic(actions=actions or {}, guards=guards or {},
                         services=services or {})
    c = copy.deepcopy(cfg)
    for k in list(kw):
        if k in CFG_KEYS:
            c[k] = kw.pop(k)
    return create_machine(c, logic=logic, **kw)


# ---------------------------------------------------------------- B1
def b1_snapshot_mutation_typing(n=5000):
    """5k structural snapshot mutations -> only typed errors."""
    cfg = {"id": "m", "initial": "a", "states": {
        "a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}}}
    it = SyncInterpreter(mk(cfg))
    it.start()
    it.send("GO")
    base = it.get_persisted_snapshot()
    rnd = random.Random(20260919)
    JUNK = [None, 0, 1, -1, 3.5, "", "x" * 80, [], {}, [None], {"k": None},
            True, {"a": [1, {"b": None}]}, float("nan"), "🙂", [[]],
            {"": ""}, ["m.a", None], {"m": []}, {"m": {"x": None}}]
    untyped, typed, accepted = 0, 0, 0
    frames = {}
    keys = list(base.keys())
    for i in range(n):
        blob = copy.deepcopy(base)
        for _ in range(rnd.randint(1, 3)):
            op = rnd.random()
            k = rnd.choice(keys)
            if op < 0.65:
                blob[k] = rnd.choice(JUNK)
            elif op < 0.85:
                blob.pop(k, None)
            else:
                blob["junk_%d" % rnd.randrange(9)] = rnd.choice(JUNK)
        try:
            j = json.dumps(blob, default=str)
            SyncInterpreter.from_snapshot(json.loads(j), mk(cfg))
            accepted += 1
        except XStateMachineError:
            typed += 1
        except Exception as exc:
            untyped += 1
            tb = sys.exc_info()[2]
            while tb.tb_next:
                tb = tb.tb_next
            f = (f"{type(exc).__name__}@"
                 f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:"
                 f"{tb.tb_lineno}")
            frames[f] = frames.get(f, 0) + 1
    rec("B1.snapshot_mutation_typing", untyped == 0,
        f"typed={typed} accepted={accepted} untyped={untyped} "
        f"frames={dict(list(frames.items())[:5])}")


# ---------------------------------------------------------------- B2
def b2_event_type_fuzz(n=3000):
    """Hostile event objects -> InvalidEventError, never untyped."""
    cfg = {"id": "m", "initial": "a", "states": {
        "a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}}}
    rnd = random.Random(7)
    HOSTILE = [None, 0, 1, b"GO", object(), [], {}, {"type": None},
               {"type": 1}, {"type": ""}, {"type": []}, {"type": {}},
               {"type": "GO", 1: "x"}, {1: "GO"}, {"type": "GO" * 9000},
               {"type": "🙂"}, {"type": "done.invoke.x"}, set(),
               ("GO",), 3.5, True, {"type": True},
               {"type": "GO", "data": object()}]
    untyped, typed, ok = 0, 0, 0
    frames = {}
    for strict in (False, True):
        it = SyncInterpreter(mk(cfg))
        it.start()
        for i in range(n // 2):
            ev = copy.copy(rnd.choice(HOSTILE))
            try:
                it.send(ev)
                ok += 1
            except XStateMachineError:
                typed += 1
            except Exception as exc:
                untyped += 1
                tb = sys.exc_info()[2]
                while tb.tb_next:
                    tb = tb.tb_next
                f = (f"{type(exc).__name__}@"
                     f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:"
                     f"{tb.tb_lineno}")
                frames[f] = frames.get(f, 0) + 1
    rec("B2.event_type_fuzz", untyped == 0,
        f"typed={typed} accepted={ok} untyped={untyped} frames={frames}")


# ---------------------------------------------------------------- B3
def b3_guard_error_raise_fallback():
    """#152: guardErrorPolicy=raise cancels only its own candidate."""
    def bad(c, e):
        raise ValueError("guard boom")
    cfg = {"id": "m", "initial": "a", "states": {
        "a": {"invoke": {"id": "i", "src": "svc", "onDone": [
            {"target": "b", "guard": "bad"}, {"target": "c"}]}},
        "b": {}, "c": {}}}
    m = mk(cfg, guards={"bad": bad},
           services={"svc": lambda i, c, e: {"v": 1}},
           guardErrorPolicy="raise")
    it = SyncInterpreter(m)
    try:
        it.start()
        st = sorted(it.current_state_ids)
        rec("B3.guard_raise_fallback", st == ["m.c"],
            f"states={st} ok={getattr(it,'last_transition_ok',None)} "
            f"err={type(getattr(it,'last_error',None)).__name__}")
    except Exception as exc:
        rec("B3.guard_raise_fallback", False,
            f"start raised {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- B4
def b4_receipt_denied_matrix():
    """#153: denied vs unhandled vs deferred."""
    cfg = {"id": "m", "initial": "a", "states": {
        "a": {"on": {"DENY": {"target": "b", "guard": "never"}}}, "b": {}}}
    seen = []
    m = mk(cfg, guards={"never": lambda c, e: False})
    it = SyncInterpreter(m)
    it.on_unhandled_event = lambda *a, **k: seen.append((a, k))
    it.start()
    r1 = it.send("DENY", wait=True)
    r2 = it.send("NOPE", wait=True)
    d1 = getattr(r1, "denied", "MISSING")
    d2 = getattr(r2, "denied", "MISSING")
    rec("B4.receipt_denied", d1 is True and d2 is False,
        f"denied(DENY)={d1} denied(NOPE)={d2} hooks={len(seen)}")


# ---------------------------------------------------------------- B5
def b5_fail_policy_snapshot():
    """#145: actionErrorPolicy=fail -> stopped, config cleared, snapshot?"""
    def boom(i, c, e, a):
        raise RuntimeError("action boom")
    cfg = {"id": "m", "initial": "a", "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["boom"]}}}, "b": {}}}
    it = SyncInterpreter(mk(cfg, actions={"boom": boom},
                            actionErrorPolicy="fail"))
    it.start()
    try:
        it.send("GO")
    except Exception:
        pass
    status, cfgids = it.status, sorted(it.current_state_ids)
    snap_outcome = "?"
    try:
        s = it.get_persisted_snapshot()
        snap_outcome = f"produced status={s.get('status')!r}"
        try:
            SyncInterpreter.from_snapshot(s, mk(cfg, actions={"boom": boom}))
            snap_outcome += " restore=ACCEPTED"
        except XStateMachineError as exc:
            snap_outcome += f" restore={type(exc).__name__}"
        except Exception as exc:
            snap_outcome += f" restore=UNTYPED {type(exc).__name__}"
    except XStateMachineError as exc:
        snap_outcome = f"snapshot refused {type(exc).__name__}"
    except Exception as exc:
        snap_outcome = f"snapshot UNTYPED {type(exc).__name__}"
    ok = status == "stopped" and cfgids == [] and "UNTYPED" not in snap_outcome
    rec("B5.fail_policy_stop_snapshot", ok,
        f"status={status!r} states={cfgids} {snap_outcome}")


# ---------------------------------------------------------------- B6
def b6_root_target_nondowngradable():
    """#147: RootTargetError on every strict_targets setting, 4 sites."""
    sites = {
        "on": {"id": "m", "initial": "a", "states": {
            "a": {"on": {"GO": "#m"}}}},
        "always": {"id": "m", "initial": "a", "states": {
            "a": {"always": "#m"}}},
        "after": {"id": "m", "initial": "a", "states": {
            "a": {"after": {"10": "#m"}}}},
        "onDone": {"id": "m", "initial": "a", "states": {
            "a": {"invoke": {"id": "i", "src": "svc", "onDone": "#m"}}}},
    }
    out = []
    bad = 0
    for st in (True, False):
        for name, cfg in sites.items():
            try:
                mk(cfg, services={"svc": lambda i, c, e: 1},
                   strict_targets=st)
                out.append(f"{name}/st={st}:ACCEPTED")
                bad += 1
            except RootTargetError:
                out.append(f"{name}/st={st}:RootTargetError")
            except Exception as exc:
                out.append(f"{name}/st={st}:{type(exc).__name__}")
                bad += 1
    rec("B6.root_target_nondowngradable", bad == 0, " ".join(out))


def main():
    b1_snapshot_mutation_typing()
    b2_event_type_fuzz()
    b3_guard_error_raise_fallback()
    b4_receipt_denied_matrix()
    b5_fail_policy_snapshot()
    b6_root_target_nondowngradable()
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n==== {len(RESULTS)-len(fails)}/{len(RESULTS)} PASS ====")


if __name__ == "__main__":
    main()
