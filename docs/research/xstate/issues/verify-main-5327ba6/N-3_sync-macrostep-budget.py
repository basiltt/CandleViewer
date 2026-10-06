"""
Verification script for gh#77 / LC N-3 on xstate-statemachine main @ 5327ba6.

Acceptance criteria (from gh#77):
  A. repro/N-03_sync-macrostep-budget-clears-queue.py exits 0.
  B. send_events(["T"] * 5000) on the sync engine processes all 5000.
  C. A genuine runaway (an `always` self-loop with a guard that never
     settles) still trips the guard, and does so by RAISING rather than
     by clearing.
  D. Sync and async engines produce byte-identical action traces for a
     2000-event batch.

Also verifies the "need" specifics:
  - send_events(["T"]*1501) processes all 1501.
  - budget only self-generated work, per chain: 3000 independent one-deep
    raises all delivered.
  - a self-feeding loop is still broken, with only the generated tail
    discarded (not the caller's events).
  - engine-parity test exists in tests/.

Exits 0 only if ALL criteria pass.
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import asyncio
import os
import subprocess
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

REPRO = (
    str(_REPO / 'docs/research/xstate/issues/new-0.8.0/repro/N-03_sync-macrostep-budget-clears-queue.py')
)
LIB_ROOT = str(_XS)


def check(label, cond, observed, expected):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}: OBSERVED={observed!r} EXPECTED={expected!r}")
    return cond


def crit_a():
    proc = subprocess.run([sys.executable, REPRO], capture_output=True, text=True)
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr)
    return check("A: original repro exits 0", proc.returncode == 0, proc.returncode, 0)


def make_bump_cfg():
    return {
        "id": "bud",
        "initial": "a",
        "context": {"seen": 0},
        "states": {
            "a": {
                "on": {
                    "T": {"target": "a", "actions": ["bump"], "reenter": True}
                }
            }
        },
    }


def bump(interp, ctx, event, action):
    ctx["seen"] = ctx.get("seen", 0) + 1


def crit_b_5000():
    i = SyncInterpreter(
        create_machine(make_bump_cfg(), logic=MachineLogic(actions={"bump": bump}))
    )
    i.start()
    i.send_events(["T"] * 5000)
    ok = i.context["seen"] == 5000 and i.queue_depth == 0
    return check(
        "B: send_events(['T']*5000) processes all 5000",
        ok,
        (i.context["seen"], i.queue_depth),
        (5000, 0),
    )


def crit_need_1501():
    i = SyncInterpreter(
        create_machine(make_bump_cfg(), logic=MachineLogic(actions={"bump": bump}))
    )
    i.start()
    i.send_events(["T"] * 1501)
    ok = i.context["seen"] == 1501 and i.queue_depth == 0
    return check(
        "need: send_events(['T']*1501) processes all 1501",
        ok,
        (i.context["seen"], i.queue_depth),
        (1501, 0),
    )


def crit_need_3000_independent_raises():
    # A raise built into the config -- one-deep, not self-feeding: each
    # external "T" triggers a single "R" raise via an action that calls
    # interp.send("R"); R just bumps context and terminates the chain.
    cfg = {
        "id": "raisy",
        "initial": "a",
        "context": {"seen": 0, "raised": 0},
        "states": {
            "a": {
                "on": {
                    "T": {"actions": ["bump_and_raise_once"]},
                    "R": {"actions": ["bump_raised"]},
                }
            }
        },
    }

    def bump_and_raise_once(interp, ctx, event, action):
        ctx["seen"] = ctx.get("seen", 0) + 1
        interp.send("R")

    def bump_raised(interp, ctx, event, action):
        ctx["raised"] = ctx.get("raised", 0) + 1

    i = SyncInterpreter(
        create_machine(
            cfg,
            logic=MachineLogic(
                actions={
                    "bump_and_raise_once": bump_and_raise_once,
                    "bump_raised": bump_raised,
                }
            ),
        )
    )
    i.start()
    i.send_events(["T"] * 3000)
    ok = i.context["seen"] == 3000 and i.context["raised"] == 3000
    return check(
        "need: 3000 independent one-deep raises all delivered",
        ok,
        (i.context["seen"], i.context["raised"]),
        (3000, 3000),
    )


def crit_c_runaway_raises():
    # Genuine self-feeding chain: T re-raises T forever (guarded off after
    # a huge count so the test itself terminates, but the guard should
    # trip well before that and RAISE rather than silently clear).
    cfg = {
        "id": "loopy",
        "initial": "a",
        "context": {"n": 0},
        "states": {"a": {"on": {"T": {"actions": ["loop"]}}}},
    }

    def loop(interp, ctx, event, action):
        ctx["n"] = ctx.get("n", 0) + 1
        if ctx["n"] < 1_000_000:
            interp.send("T")

    i = SyncInterpreter(
        create_machine(cfg, logic=MachineLogic(actions={"loop": loop}))
    )
    i.start()
    raised = False
    err = None
    try:
        i.send("T")
    except Exception as e:  # noqa: BLE001
        raised = True
        err = e
    # The runaway guard trips (n is nowhere near 1,000,000; send() returns),
    # but per the actual implementation it trips by DROPPING the
    # self-generated tail and logging ERROR -- it does NOT raise an
    # exception to the caller. This diverges from the acceptance criterion
    # text ("does so by raising"); documented as a residual gap.
    bounded = i.context.get("n", 0) < 1_000_000 and i.status == "running"
    ok = raised  # acceptance criterion literally requires raising
    print(
        f"    (info) guard did trip and bound the loop: n={i.context.get('n')}, "
        f"status={i.status}, but no exception was raised (raised={raised})"
    )
    return check(
        "C: genuine runaway raise-loop trips the guard by RAISING",
        ok,
        (raised, type(err).__name__ if err else None, i.context.get("n"), bounded),
        (True, "<some exception>", "<< 1_000_000", True),
    )


def ctx_trip_reasonable(i):
    return i.context.get("n", 0) < 1_000_000


def crit_d_trace_parity(n=2000):
    trace_sync = []
    trace_async = []

    cfg = make_bump_cfg()

    def bump_trace(trace):
        def _bump(interp, ctx, event, action):
            ctx["seen"] = ctx.get("seen", 0) + 1
            trace.append(ctx["seen"])

        return _bump

    i_sync = SyncInterpreter(
        create_machine(cfg, logic=MachineLogic(actions={"bump": bump_trace(trace_sync)}))
    )
    i_sync.start()
    i_sync.send_events(["T"] * n)

    async def run_async():
        i_async = Interpreter(
            create_machine(
                cfg, logic=MachineLogic(actions={"bump": bump_trace(trace_async)})
            )
        )
        await i_async.start()
        await i_async.send_events(["T"] * n)
        await asyncio.wait_for(i_async.stop(drain=True), timeout=30.0)
        return i_async

    asyncio.run(run_async())

    ok = trace_sync == trace_async and len(trace_sync) == n
    return check(
        f"D: sync/async byte-identical action traces for {n}-event batch",
        ok,
        (len(trace_sync), len(trace_async), trace_sync == trace_async),
        (n, n, True),
    )


def crit_parity_test_exists():
    hits = []
    for root, _, files in os.walk(os.path.join(LIB_ROOT, "tests")):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        content = fh.read()
                except Exception:
                    continue
                if "parity" in content.lower() and (
                    "sync" in content.lower() and "budget" in content.lower()
                    or "max_iterations" in content.lower()
                ):
                    hits.append(os.path.relpath(path, LIB_ROOT))
    ok = len(hits) > 0
    return check(
        "engine-parity test exists in tests/",
        ok,
        hits,
        "at least one match",
    )


def main():
    results = []
    results.append(crit_a())
    results.append(crit_b_5000())
    results.append(crit_need_1501())
    results.append(crit_need_3000_independent_raises())
    results.append(crit_c_runaway_raises())
    results.append(crit_d_trace_parity())
    results.append(crit_parity_test_exists())
    print()
    print("ALL PASS" if all(results) else "SOME FAILED")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
