"""Minimal, self-contained repros for every defect the FUZZ track filed.

Run:  python repros.py
Exit code is the number of defects that still reproduce.

Each repro prints OBSERVED vs EXPECTED and a one-line verdict. Nothing here
imports the fuzzers; these are the shrunk cases, hand-checked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)

RESULTS = []


def report(did, title, observed, expected, reproduced):
    RESULTS.append((did, reproduced))
    mark = "REPRODUCED" if reproduced else "not reproduced"
    print(f"\n--- {did}: {title}")
    print(f"    observed: {observed}")
    print(f"    expected: {expected}")
    print(f"    => {mark}")


LOGIC = MachineLogic(
    actions={"noop": lambda i, c, e, a: None},
    guards={"g_true": lambda c, e: True, "g_false": lambda c, e: False},
    services={"svc_ok": lambda i, c, e: {"ok": 1}},
)


async def _svc_ok(i, c, e):
    return {"ok": 1}


ASYNC_LOGIC = MachineLogic(
    actions={"noop": lambda i, c, e, a: None},
    guards={"g_true": lambda c, e: True, "g_false": lambda c, e: False},
    services={"svc_ok": _svc_ok},
)


# -----------------------------------------------------------------------------
# D-fuzz-1: start() never terminates; the inbox grows without bound
# -----------------------------------------------------------------------------
def d1():
    cfg = {
        "id": "m",
        "type": "parallel",
        "states": {
            "A": {
                "initial": "a1",
                "states": {
                    "a1": {
                        "invoke": {
                            "id": "inv",
                            "src": "svc_ok",
                            "onDone": "#m.A.a1",
                        }
                    }
                },
            },
            "B": {
                "initial": "b1",
                "states": {"b1": {"always": "#m.A.a1"}},
            },
        },
    }
    interp = SyncInterpreter(create_machine(cfg, logic=LOGIC))
    t = threading.Thread(target=interp.start, daemon=True)
    t.start()
    t.join(6.0)
    alive = t.is_alive()
    qlen = len(interp._event_queue)
    report(
        "D-fuzz-1",
        "SyncInterpreter.start() does not terminate; inbox grows unbounded",
        f"start() still running after 6 s: {alive}; inbox len={qlen}",
        "start() returns; inbox bounded by maxIterations",
        alive and qlen > 10000,
    )


# -----------------------------------------------------------------------------
# D-fuzz-2: an `always` targeting the machine root empties the configuration
# -----------------------------------------------------------------------------
def d2():
    cfg = {"id": "m", "initial": "a", "states": {"a": {"always": "#m"}}}
    i = SyncInterpreter(create_machine(cfg, logic=LOGIC))
    i.start()
    sync_ids = sorted(i.current_state_ids)

    async def go():
        a = Interpreter(create_machine(cfg, logic=ASYNC_LOGIC))
        await a.start()
        out = (sorted(a.current_state_ids), a.status)
        await a.stop()
        return out

    async_ids, async_status = asyncio.run(go())
    snap = i.get_persisted_snapshot()
    report(
        "D-fuzz-2",
        "`always` targeting the machine root empties the configuration, "
        "status stays 'running'",
        f"sync states={sync_ids} status={i.status} value={i.value!r}; "
        f"async states={async_ids} status={async_status}; "
        f"snapshot state_ids={snap['state_ids']}",
        "a non-empty atomic configuration, or a typed build/runtime error",
        sync_ids == [] and async_ids == [] and i.status == "running",
    )


# -----------------------------------------------------------------------------
# D-fuzz-3: sync send() to a non-running machine is silent; async is observable
# -----------------------------------------------------------------------------
class Watch(PluginBase):
    def __init__(self):
        self.ev, self.un, self.dr = [], [], []

    def on_event_received(self, i, e):
        self.ev.append(e.type)

    def on_unhandled_event(self, i, e, *a, **k):
        self.un.append(e.type)

    def on_event_dropped(self, i, e, reason=None, *a, **k):
        self.dr.append((e.type, reason))


def d3():
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}},
    }
    w = Watch()
    i = SyncInterpreter(create_machine(cfg, logic=LOGIC))
    i.use(w)
    i.start()
    i.stop()
    i.send("GO")
    sync_hooks = (w.ev, w.un, w.dr)

    async def go():
        w2 = Watch()
        a = Interpreter(create_machine(cfg, logic=ASYNC_LOGIC))
        a.use(w2)
        await a.start()
        await a.stop()
        await a.send("GO")
        await asyncio.sleep(0.05)
        return (w2.ev, w2.un, w2.dr)

    async_hooks = asyncio.run(go())
    silent = sync_hooks == ([], [], []) and async_hooks[2] != []
    report(
        "D-fuzz-3",
        "send() to a stopped/done SyncInterpreter returns normally and fires "
        "NO hook; the async engine fires on_event_dropped(reason='not_running')",
        f"sync hooks={sync_hooks}; async hooks={async_hooks}",
        "both engines observe the drop (parity), or both raise "
        "InterpreterStoppedError",
        silent,
    )


# -----------------------------------------------------------------------------
# D-fuzz-4: a dict event with a non-string `type` raises a bare Python error
# -----------------------------------------------------------------------------
def d4():
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}},
    }
    out = []
    for strict in (False, True):
        i = SyncInterpreter(create_machine(cfg, logic=LOGIC), strict=strict)
        i.start()
        for ev in ({"type": None}, {"type": 123}):
            try:
                i.send(ev)
                out.append((strict, ev, "accepted"))
            except XStateMachineError as exc:
                out.append((strict, ev, f"typed {type(exc).__name__}"))
            except Exception as exc:  # noqa: BLE001
                out.append((strict, ev, f"UNTYPED {type(exc).__name__}"))
    untyped = [o for o in out if "UNTYPED" in o[2]]
    report(
        "D-fuzz-4",
        "send({'type': None}) raises AttributeError/TypeError from library "
        "internals instead of a typed XStateMachineError",
        "; ".join(f"strict={s} {e} -> {r}" for s, e, r in out),
        "InvalidEventPayloadError (or any XStateMachineError) on every path",
        len(untyped) == 4,
    )


# -----------------------------------------------------------------------------
# D-fuzz-5: non-event objects raise a bare TypeError from send()
# -----------------------------------------------------------------------------
def d5():
    cfg = {"id": "m", "initial": "a", "states": {"a": {}}}
    i = SyncInterpreter(create_machine(cfg, logic=LOGIC))
    i.start()
    kinds = []
    for ev in (None, 123, b"B", ["GO"], object()):
        try:
            i.send(ev)
            kinds.append((type(ev).__name__, "accepted"))
        except XStateMachineError as exc:
            kinds.append((type(ev).__name__, f"typed {type(exc).__name__}"))
        except TypeError:
            kinds.append((type(ev).__name__, "bare TypeError"))
    bare = [k for k in kinds if k[1] == "bare TypeError"]
    report(
        "D-fuzz-5",
        "send() raises a bare TypeError for an unsupported event object; "
        "`except XStateMachineError` does not catch it",
        "; ".join(f"{t} -> {r}" for t, r in kinds),
        "a typed XStateMachineError subclass, per the documented catch-all",
        len(bare) == 5,
    )


# -----------------------------------------------------------------------------
# D-fuzz-6: from_snapshot raises bare KeyError/AttributeError/TypeError
# -----------------------------------------------------------------------------
def d6():
    import copy

    cfg = {
        "id": "m",
        "initial": "a",
        "context": {"n": 0},
        "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}},
    }
    machine = create_machine(cfg, logic=LOGIC)
    i = SyncInterpreter(machine)
    i.start()
    snap = i.get_persisted_snapshot()

    cases = {
        "pending_events=[{}]": {"pending_events": [{}]},
        "pending_events=[null]": {"pending_events": [None]},
        'pending_events=["GO"]': {"pending_events": ["GO"]},
        "deferred=[{}]": {"deferred": [{}]},
        "history={'m': null}": {"history": {"m": None}},
        "configuration=5": {"configuration": 5},
        'state_ids=[["m.a"]]': {"configuration": None, "state_ids": [["m.a"]]},
        "actors={'a': null}": {"actors": {"a": None}},
    }
    out = []
    for name, mut in cases.items():
        s = copy.deepcopy(snap)
        s.update(mut)
        try:
            SyncInterpreter.from_snapshot(
                json.dumps(s, default=str), machine, verify_machine_hash=False
            )
            out.append((name, "restored"))
        except XStateMachineError as exc:
            out.append((name, f"typed {type(exc).__name__}"))
        except Exception as exc:  # noqa: BLE001
            out.append((name, f"UNTYPED {type(exc).__name__}"))
    untyped = [o for o in out if "UNTYPED" in o[1]]
    report(
        "D-fuzz-6",
        "from_snapshot() raises bare KeyError / AttributeError / TypeError on "
        "a corrupted blob",
        "; ".join(f"{n} -> {r}" for n, r in out),
        "every corrupted blob raises an XStateMachineError subclass",
        len(untyped) >= 6,
    )


# -----------------------------------------------------------------------------
# D-fuzz-7: from_snapshot silently loads garbage (empty configuration, bogus
#           status, non-mapping context)
# -----------------------------------------------------------------------------
def d7():
    import copy

    cfg = {
        "id": "m",
        "initial": "a",
        "context": {"n": 0},
        "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}},
    }
    machine = create_machine(cfg, logic=LOGIC)
    i = SyncInterpreter(machine)
    i.start()
    snap = i.get_persisted_snapshot()

    out = []
    for name, mut in {
        "configuration=[] ": {"configuration": [], "state_ids": []},
        'configuration=["m"]': {"configuration": ["m"], "state_ids": []},
        'status="zzz"': {"status": "zzz"},
        "status=5": {"status": 5},
        "status=['running']": {"status": ["running"]},
        "context=42": {"context": 42},
    }.items():
        s = copy.deepcopy(snap)
        s.update(mut)
        r = SyncInterpreter.from_snapshot(
            json.dumps(s, default=str), machine, verify_machine_hash=False
        )
        out.append(
            (
                name,
                f"status={r.status!r} ({type(r.status).__name__}) "
                f"states={sorted(r.current_state_ids)} context={r.context!r}",
            )
        )
    bad = [
        o
        for o in out
        if "states=[]" in o[1] or "'zzz'" in o[1] or "(list)" in o[1]
    ]
    report(
        "D-fuzz-7",
        "from_snapshot() accepts a blob whose configuration is empty, whose "
        "status is an undocumented value of any TYPE, or whose context is "
        "not a mapping",
        "; ".join(f"{n} -> {r}" for n, r in out),
        "SnapshotDriftError / InvalidConfigError for each",
        len(bad) >= 4,
    )


# -----------------------------------------------------------------------------
# NOT-A-DEFECT check: an unimplemented action name.
# `create_machine()` accepts it (no build-time check), but the failure at run
# time is a typed ImplementationMissingError on both the entry path and the
# transition path. Loud, typed, catchable -- so this is NOT filed as a defect;
# it is kept here as the evidence for that call.
# -----------------------------------------------------------------------------
def d8():
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {
            "a": {"on": {"GO": {"target": "#m.b", "actions": "no_such"}}},
            "b": {},
        },
    }
    built = False
    try:
        machine = create_machine(cfg, logic=LOGIC)
        built = True
    except XStateMachineError as exc:
        print(f"\n--- (not a defect) build rejected: {type(exc).__name__}")
        return
    i = SyncInterpreter(machine)
    i.start()
    try:
        i.send("GO")
        outcome = "send() returned normally (SILENT)"
    except XStateMachineError as exc:
        outcome = f"typed {type(exc).__name__} (loud, catchable)"
    except Exception as exc:  # noqa: BLE001
        outcome = f"UNTYPED {type(exc).__name__}"
    print(
        f"\n--- (not a defect) unimplemented action: built={built}; "
        f"runtime -> {outcome}"
    )


# -----------------------------------------------------------------------------
# D-fuzz-9: a self-referential config dict is a RecursionError, not a typed one
# -----------------------------------------------------------------------------
def d9():
    a: dict = {"initial": "x", "states": {}}
    a["states"]["x"] = a  # aliased cycle
    cfg = {"id": "m", "initial": "a", "states": {"a": a}}
    try:
        create_machine(cfg, logic=LOGIC)
        outcome = "built (!)"
        ok = True
    except XStateMachineError as exc:
        outcome = f"typed {type(exc).__name__}"
        ok = False
    except RecursionError:
        outcome = "RecursionError"
        ok = True
    report(
        "D-fuzz-8",
        "a config dict containing itself blows the Python stack instead of "
        "raising InvalidConfigError",
        outcome,
        "InvalidConfigError naming the cyclic state",
        outcome == "RecursionError",
    )


# -----------------------------------------------------------------------------
# D-fuzz-9: a runaway-chain trip leaves the LIVE machine structurally corrupt
#           (an active leaf whose ancestors are inactive), reported as healthy,
#           and a save/restore round-trip silently rewrites the configuration.
# -----------------------------------------------------------------------------
def d10():
    cfg = {
        "id": "m",
        "initial": "b",
        "maxIterations": 1,
        "always": {"target": "#m.b", "guard": "g_true"},
        "states": {
            "b": {
                "type": "parallel",
                "states": {
                    "a": {
                        "initial": "a",
                        "always": {"target": "#m", "guard": "g_true"},
                        "states": {"a": {}},
                    },
                    "b": {
                        "initial": "a",
                        "invoke": {
                            "id": "v",
                            "src": "svc_ok",
                            "onDone": "#m.b",
                            "onError": "#m.b",
                        },
                        "states": {"a": {}},
                    },
                },
            }
        },
    }
    machine = create_machine(cfg, logic=LOGIC)
    i = SyncInterpreter(machine)
    i.start()
    active = {n.id for n in i._active_state_nodes}
    orphans = sorted(
        n.id
        for n in i._active_state_nodes
        if n.parent is not None and n.parent not in i._active_state_nodes
    )
    s1 = i.get_persisted_snapshot()
    r = SyncInterpreter.from_snapshot(
        json.dumps(s1, default=str), machine
    )
    s2 = r.get_persisted_snapshot()
    report(
        "D-fuzz-9",
        "a runaway-chain trip leaves an active leaf whose ancestors are "
        "INACTIVE; the machine reports healthy, and save->restore->save "
        "silently rewrites the configuration",
        f"live active={sorted(active)} orphans={orphans} "
        f"value={i.value!r} status={i.status} "
        f"last_transition_ok={i.last_transition_ok} "
        f"last_error={type(i.last_error).__name__}; "
        f"save1 configuration={s1['configuration']}; "
        f"save2 configuration={s2['configuration']}",
        "no orphan active node; a trip is reported via last_error; "
        "save->restore->save is stable",
        bool(orphans) and s1["configuration"] != s2["configuration"],
    )


def main() -> int:
    for fn in (d1, d2, d3, d4, d5, d6, d7, d8, d9, d10):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"\n!!! {fn.__name__} harness error: {type(exc).__name__}: {exc}")
    n = sum(1 for _, r in RESULTS if r)
    print(f"\n==== {n}/{len(RESULTS)} defects reproduce on this build ====")
    for did, r in RESULTS:
        print(f"  {did}: {'REPRODUCED' if r else 'no'}")
    return n


if __name__ == "__main__":
    raise SystemExit(main())
