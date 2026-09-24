# -*- coding: utf-8 -*-
"""U3 -- #204 `statesToInvoke` across a snapshot: does a restore arm the
invoke EXACTLY ONCE?

STANDALONE (stdlib + xstate_statemachine).  Run from any cwd.

#204 moved invoke arming out of state entry and into the settle pass: a
state is *recorded* on entry and its service is submitted only once the
eventless (`always`) transitions have settled and the state is still active.
That creates a new, previously non-existent window -- **entered, recorded,
not yet armed** -- and persistence must not be able to observe or duplicate
it.  Three properties:

  A  ARM-ONCE ACROSS RESTORE.  Snapshot a machine that is parked in an
     invoking state, restore with `restart_services=True`, and count the
     TOTAL number of service calls that the restored machine makes.  It must
     be exactly 1 -- not 0 (the pending record was lost) and not 2 (armed
     once by the restore path and once by the settle pass).

  B  THE ROLL-FORWARD STATE IS NEVER PERSISTED AS INVOKING.  A state entered
     and exited within one macrostep by an `always` never submits its
     service (#204).  A snapshot taken after that macrostep must not name it
     in `pending_invocations()` / must not resurrect its service on restore.

  C  SNAPSHOT INSIDE THE WINDOW.  Take the snapshot from `on_transition`,
     i.e. the first window the library accepts, on a machine whose target
     has both an `always` and an `invoke`.  Same arm-once criterion.

Both service kinds; call counts are kept in a module-level list so a restore
into a FRESH machine object still shares the counter.
"""
from __future__ import annotations

import asyncio
import json
import os

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

KIND = os.environ.get("XS_SVC", "async")

# 📏 ADAPTED @19cb1f1 for the `def` lane. A plain-`def` service is the
#    documented uninterruptible kind: the entering step AWAITS it (#193,
#    Production Characteristics §2), so the machine can never be observed
#    "parked in an invoking state" on the `def` lane -- an attempt to
#    snapshot during the hold is refused `SnapshotMidStepError` because the
#    step has not settled. The `def` lane therefore runs with hold=0 and the
#    arm-once criterion becomes "the completed state restores WITHOUT
#    re-arming" (expected calls 0), which is the same property observed on
#    the other side of the same window.
HOLD = 5.0 if KIND != "def" else 0.0
EXPECT_A = 1 if KIND != "def" else 0

CALLS: list[str] = []

# --- A: plain invoking state ------------------------------------------------
SPEC_A = {
    "id": "arm",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "working"}},
        "working": {
            "invoke": [{"id": "k", "src": "svc",
                        "onDone": {"target": "done_", "actions": ["mark"]}}],
        },
        "done_": {"type": "final"},
    },
}

# --- B: always rolls the invoking state forward in ONE macrostep ------------
SPEC_B = {
    "id": "fwd",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "transient"}},
        # entered and exited in the same macrostep: #204 says its service is
        # never submitted.
        "transient": {
            "always": [{"target": "settled"}],
            "invoke": [{"id": "ghost", "src": "svc",
                        "onDone": {"target": "settled"}}],
        },
        "settled": {"on": {"AGAIN": "transient"}},
    },
}

# --- C: target has BOTH an always-guard and an invoke -----------------------
SPEC_C = {
    "id": "both",
    "initial": "idle",
    "context": {"n": 0, "pass": False},
    "states": {
        "idle": {"on": {"GO": "working"}},
        "working": {
            "always": [{"target": "shortcut", "guard": "isPass"}],
            "invoke": [{"id": "k", "src": "svc",
                        "onDone": {"target": "done_", "actions": ["mark"]}}],
        },
        "shortcut": {"type": "final"},
        "done_": {"type": "final"},
    },
}


def _logic(hold: float):
    def mark(i, c, e, a):  # noqa: ANN001
        c["n"] = c.get("n", 0) + 1

    def is_pass(c, e):  # noqa: ANN001
        return bool(c.get("pass"))

    def svc_def(i, c, e):  # noqa: ANN001
        CALLS.append("def")
        import time
        time.sleep(hold)
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        CALLS.append("async")
        await asyncio.sleep(hold)
        return {"ok": 1}

    return MachineLogic(
        actions={"mark": mark},
        guards={"isPass": is_pass},
        services={"svc": svc_def if KIND == "def" else svc_async},
    )


def build(spec, hold: float = 0.0):
    return create_machine(json.loads(json.dumps(spec)), logic=_logic(hold))


class Snap(PluginBase):
    """Captures the blob from the first accepted `on_transition`."""

    def __init__(self, want: str) -> None:
        self.want = want
        self.blob = None

    def on_transition(self, interp, frm, to, t):  # noqa: ANN001
        if self.blob is not None:
            return
        if any(self.want in n.id for n in to):
            try:
                self.blob = interp.get_snapshot()
            except Exception as exc:  # noqa: BLE001
                self.blob = f"__REFUSED__{type(exc).__name__}"


def _dormant(i) -> tuple:
    has = getattr(i, "has_dormant_invocations", None)
    pend = getattr(i, "pending_invocations", None)
    return (
        has if not callable(has) else has(),
        list(pend()) if callable(pend) else None,
    )


async def part_a() -> list:
    print("=== A. arm-exactly-once across a restore (parked in `working`) ===")
    fails = []
    CALLS.clear()
    i = Interpreter(build(SPEC_A, hold=HOLD))
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.05)
    live_calls = len(CALLS)
    print(f"   live: states={sorted(i.current_state_ids)} calls={live_calls}")
    blob = i.get_snapshot()
    await i.stop()

    CALLS.clear()
    j = Interpreter.from_snapshot(blob, build(SPEC_A, hold=0.0),
                                  restart_services=True)
    print(f"   pre-start  dormant={_dormant(j)}")
    await j.start()
    await asyncio.sleep(0.2)
    n = len(CALLS)
    print(f"   restored: states={sorted(j.current_state_ids)} "
          f"service calls on the RESTORED machine = {n}  "
          f"(must be exactly {EXPECT_A})")
    if n != EXPECT_A:
        fails.append(
            f"A: restored machine armed the invoke {n}x, "
            f"expected {EXPECT_A}")
    await j.stop()
    return fails


async def part_b() -> list:
    print("\n=== B. roll-forward state must never persist as invoking ===")
    fails = []
    CALLS.clear()
    i = Interpreter(build(SPEC_B, hold=0.0))
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.1)
    live = len(CALLS)
    states = sorted(i.current_state_ids)
    print(f"   live after GO: states={states} ghost-service calls={live} "
          f"(#204: must be 0)")
    if live != 0:
        fails.append(f"B: the rolled-forward invoke ran {live}x live")
    blob = i.get_snapshot()
    d = json.loads(blob)
    print(f"   snapshot actors={d.get('actors')} "
          f"state_ids={d.get('state_ids')}")
    if any("transient" in s for s in d.get("state_ids") or []):
        fails.append("B: snapshot persists the transient state as active")
    await i.stop()

    CALLS.clear()
    j = Interpreter.from_snapshot(blob, build(SPEC_B, hold=0.0),
                                  restart_services=True)
    await j.start()
    await asyncio.sleep(0.15)
    n = len(CALLS)
    print(f"   restored: states={sorted(j.current_state_ids)} "
          f"ghost-service calls={n}  (must be 0)")
    if n != 0:
        fails.append(f"B: restore resurrected the never-armed service ({n}x)")
    await j.stop()
    return fails


async def part_c() -> list:
    print("\n=== C. snapshot from on_transition into a state with "
          "always+invoke ===")
    fails = []
    CALLS.clear()
    p = Snap("working")
    i = Interpreter(build(SPEC_C, hold=HOLD))
    i.use(p)
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0.05)
    print(f"   live: states={sorted(i.current_state_ids)} calls={len(CALLS)}")
    print(f"   on_transition blob: "
          f"{'REFUSED ' + p.blob[11:] if isinstance(p.blob, str) and p.blob.startswith('__REFUSED__') else 'accepted'}")
    blob = p.blob if not (isinstance(p.blob, str)
                          and p.blob.startswith("__REFUSED__")) else None
    if blob is None:
        blob = i.get_snapshot()
        print("   (fell back to a quiescent snapshot)")
    await i.stop()

    CALLS.clear()
    j = Interpreter.from_snapshot(blob, build(SPEC_C, hold=0.0),
                                  restart_services=True)
    await j.start()
    await asyncio.sleep(0.2)
    n = len(CALLS)
    print(f"   restored: states={sorted(j.current_state_ids)} "
          f"calls={n}  (must be exactly {EXPECT_A})")
    if n != EXPECT_A:
        fails.append(
            f"C: restored machine armed the invoke {n}x, "
            f"expected {EXPECT_A}")
    await j.stop()
    return fails


async def main() -> None:
    print(f"=== U3 statesToInvoke across persistence [{KIND}] ===")
    fails = []
    fails += await part_a()
    fails += await part_b()
    fails += await part_c()
    print()
    print("FAILURES:", fails or "none")
    print("VERDICT:", "FAIL" if fails else "PASS")


if __name__ == "__main__":
    asyncio.run(main())
