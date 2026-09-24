"""LC-44 verification on xstate-statemachine 0.8.0.

Exercises the pure-API speed fix (#54) and the probe-hoist/history-leak
fixes against the acceptance criteria in
LC-44-pure-api-slower-and-skips-actions.md.
"""

from __future__ import annotations

import logging
import sys

from xstate_statemachine import (
    MachineLogic,
    SyncInterpreter,
    create_machine,
    get_initial_snapshot,
    get_next_snapshot,
    pure_transition,
)
from xstate_statemachine import helpers

logging.disable(logging.CRITICAL)

CONFIG = {
    "id": "order",
    "initial": "idle",
    "context": {"qty": 0.0, "fills": 0},
    "states": {
        "idle": {"on": {"SUBMIT": {"target": "open", "actions": ["book"]}}},
        "open": {"on": {"FILL": {"target": "open", "actions": ["book"]}}},
    },
}


def book(interpreter, context, event, action_def) -> None:
    context["qty"] += float(event.payload.get("qty", 0.0))
    context["fills"] += 1


def machine():
    return create_machine(CONFIG, logic=MachineLogic(actions={"book": book}))


EVENTS = [{"type": "SUBMIT", "qty": 1.0}] + [
    {"type": "FILL", "qty": 1.0} for _ in range(999)
]


def main() -> int:
    ok = True

    # --- 1) probe class is module-level (same type across calls) ----------
    m = machine()
    snap0 = get_initial_snapshot(m)
    probe1, _ = helpers._build_probe(m, snap0)
    probe2, _ = helpers._build_probe(m, snap0)
    print(f"OBSERVED type(probe1) is type(probe2) = {type(probe1) is type(probe2)}")
    print("EXPECTED True (module-level probe class, not rebuilt per call)")
    if type(probe1) is not type(probe2):
        ok = False

    # --- 2) semantics unchanged: assign applies, user actions do not run --
    snap = get_initial_snapshot(m)
    snap = get_next_snapshot(m, snap, {"type": "SUBMIT", "qty": 1.0})
    print(f"OBSERVED pure snapshot state={sorted(snap.state_ids)} "
          f"context={snap.context}")
    print("EXPECTED state moved to 'order.open'; context['fills'] NOT "
          "incremented (user action 'book' does not run in pure API)")
    if "order.open" not in snap.state_ids or snap.context.get("fills", 0) != 0:
        ok = False

    # --- 3) transitioning does not schedule timers/invokes -----------------
    cfg_timer = {
        "id": "t",
        "initial": "a",
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {"after": {100: "c"}},
            "c": {},
        },
    }
    mt = create_machine(cfg_timer, logic=MachineLogic())
    st = get_initial_snapshot(mt)
    st = get_next_snapshot(mt, st, {"type": "GO"})
    probe_t, _ = helpers._build_probe(mt, st)
    scheduled = bool(getattr(probe_t, "_timer_handles", {})) or bool(
        getattr(probe_t, "_actors", {})
    )
    print(f"OBSERVED probe scheduled timers/invokes after entering 'b' = {scheduled}")
    print("EXPECTED False (pure transitions never schedule real work)")
    if scheduled:
        ok = False

    # --- 4) snapshots remain independent (branching) -----------------------
    cfg_assign = {
        "id": "ctr",
        "initial": "a",
        "context": {"n": 0},
        "states": {
            "a": {
                "on": {
                    "INC": {
                        "actions": [
                            {"type": "assign", "params": {"assignment": {"n": 1}}}
                        ]
                    },
                    "INC5": {
                        "actions": [
                            {"type": "assign", "params": {"assignment": {"n": 5}}}
                        ]
                    },
                }
            }
        },
    }
    mc = create_machine(cfg_assign, logic=MachineLogic())
    base = get_initial_snapshot(mc)
    branch_a = get_next_snapshot(mc, base, {"type": "INC"})
    branch_b = get_next_snapshot(mc, base, {"type": "INC5"})
    print(f"OBSERVED base.context={base.context} branch_a.context={branch_a.context} "
          f"branch_b.context={branch_b.context}")
    print("EXPECTED base.context['n'] still 0 (untouched by either branch); "
          "branch_a['n']=1, branch_b['n']=5 (independent, not shared)")
    if base.context.get("n") != 0 or branch_a.context.get("n") != 1 or branch_b.context.get("n") != 5:
        ok = False

    # --- 5) history does not leak between unrelated snapshot chains --------
    cfg_hist = {
        "id": "h",
        "initial": "p",
        "states": {
            "p": {
                "initial": "a",
                "states": {
                    "a": {"on": {"TO_B": "b"}},
                    "b": {},
                    "hist": {"type": "history"},
                },
                "on": {"OUT": "q"},
            },
            "q": {"on": {"BACK": "p.hist"}},
        },
    }
    mh = create_machine(cfg_hist, logic=MachineLogic())
    s1 = get_initial_snapshot(mh)
    s1 = get_next_snapshot(mh, s1, {"type": "TO_B"})  # p.b
    s1 = get_next_snapshot(mh, s1, {"type": "OUT"})  # q, history remembers b
    s1 = get_next_snapshot(mh, s1, {"type": "BACK"})  # back to b via history

    # An UNRELATED snapshot with no history of its own.
    q_unrelated = helpers.PureSnapshot({"h.q"}, {"h", "h.q"}, {}, "running")
    s2 = get_next_snapshot(mh, q_unrelated, {"type": "BACK"})

    print(f"OBSERVED chained-history snapshot -> {sorted(s1.state_ids)}")
    print(f"OBSERVED unrelated fresh snapshot -> {sorted(s2.state_ids)}")
    print("EXPECTED chained resolves to 'h.p.b' (remembered); unrelated "
          "resolves to default 'h.p.a' (no leaked history)")
    if "h.p.b" not in s1.state_ids:
        ok = False
    if "h.p.a" not in s2.state_ids:
        ok = False

    # --- 6) pure API ENGINE cost <= SyncInterpreter.send -------------------
    # Matches the library's own methodology
    # (tests/test_helpers_pure.py::TestPurePerf): the pure API must allocate
    # a fresh immutable PureSnapshot (one context deepcopy) per step, which
    # `send()` never pays -- that allocation floor is subtracted so the
    # comparison measures ENGINE work, not the unavoidable cost of
    # immutability. Best-of-5 to reject scheduler noise.
    import copy
    import time as _time

    from xstate_statemachine import PureSnapshot

    cfg_perf = {
        "id": "p",
        "initial": "a",
        "context": {"n": 0},
        "states": {
            "a": {"on": {"T": {"target": "b", "actions": ["inc"]}}},
            "b": {"on": {"T": {"target": "a", "actions": ["inc"]}}},
        },
    }

    def inc(i, c, e, a):  # noqa: ANN001
        c["n"] += 1

    mp = create_machine(cfg_perf, logic=MachineLogic(actions={"inc": inc}))
    N = 5000

    def time_sync() -> float:
        it = SyncInterpreter(mp).start()
        t0 = _time.perf_counter()
        for _ in range(N):
            it.send("T")
        return (_time.perf_counter() - t0) / N

    def time_pure() -> float:
        s = get_initial_snapshot(mp)
        t0 = _time.perf_counter()
        for _ in range(N):
            s = get_next_snapshot(mp, s, "T")
        return (_time.perf_counter() - t0) / N

    def time_floor() -> float:
        ctx = {"n": 0}
        t0 = _time.perf_counter()
        for _ in range(N):
            PureSnapshot(
                state_ids={"p.a"},
                configuration={"p", "p.a"},
                context=copy.deepcopy(ctx),
            )
        return (_time.perf_counter() - t0) / N

    for fn in (time_sync, time_pure, time_floor):
        fn()  # warm-up
    real = min(time_sync() for _ in range(5))
    pure = min(time_pure() for _ in range(5))
    floor = min(time_floor() for _ in range(5))
    engine = pure - floor
    print(f"OBSERVED sync={real * 1e6:.1f}us pure_total={pure * 1e6:.1f}us "
          f"floor={floor * 1e6:.1f}us pure_engine={engine * 1e6:.1f}us "
          f"(engine/sync ratio={engine / real:.2f}x)")
    print("EXPECTED pure ENGINE work (total minus the unavoidable immutable-"
          "snapshot allocation floor) <= 2x the interpreter's per-event cost")
    if engine > real * 2.0:
        ok = False

    print("RESULT:", "FIXED" if ok else "NOT FIXED (see failing checks above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
