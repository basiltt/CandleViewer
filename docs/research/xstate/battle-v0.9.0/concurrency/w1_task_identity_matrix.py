"""w1 (@v0.9.0) -- STANDALONE. #225 self-send provenance by TASK IDENTITY.

The round-12 fix replaced the inherited ContextVar with `_action_tasks`
keyed by the *running task*. The property under test, stated twice:

  P-ROUTE   A send() issued BY the action's own task while the action runs
            is INTERNAL (drained inside the macrostep). A send() issued by
            any OTHER task -- including a helper the action spawned, which
            under a ContextVar inherited the action's identity -- is
            EXTERNAL and must advance the machine with the loop otherwise
            idle.
  P-GUARD   send(wait=True) awaited by the action's own task, in-step, is
            refused with ReentrantWaitError. Awaited by any other task it
            must RESOLVE, whether or not the spawning action yields again.

Cells (both action kinds where expressible; async engine):
  M1 action_direct_send        action's own task -> internal
  M2 action_helper_awaited     action awaits a helper coro (SAME task)
                               -> still internal (no task boundary crossed)
  M3 action_ensure_future      action spawns task, task sends -> EXTERNAL
  M4 action_task_task          action -> task -> task -> send -> EXTERNAL
  M5 worker_outlives_action    spawned worker sends LONG after the action
                               returned, loop idle -> EXTERNAL, advances
  M6 def_service_send          a `def` action/service under the executor
                               sends -> which lane?  (thread, not task)
  M7 child_action_parent_send  child's action sends to PARENT -> external
                               w.r.t. the parent
  M8 after_handler_send        handler reached from an `after` event
  M9 spawner_keeps_awaiting    #225's regression shape: action hands out
                               ensure_future(send(wait=True)) then AWAITS
                               AGAIN afterwards -> receipt must resolve

Every cell has a 25 s watchdog; a HANG is a defect (that is what #225
exists to prevent). Exit 1 == defect.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import warnings
from typing import Any, Dict, List

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import ReentrantWaitError

WATCHDOG = 25.0
ROWS: List[Dict[str, Any]] = []
FAILS: List[str] = []
HERE = os.path.dirname(os.path.abspath(__file__))


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])),
            **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(HERE, name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def record(cell: str, kind: str, **kw: Any) -> None:
    ROWS.append({"cell": cell, "kind": kind, **kw})


def cfg(mid: str) -> Dict[str, Any]:
    """idle --GO--> done.  `boom` runs on entry to idle."""
    return {
        "id": mid,
        "initial": "idle",
        "context": {"n": 0},
        "states": {
            "idle": {"entry": ["boom"], "on": {"GO": "done"}},
            "done": {"entry": ["tick"]},
        },
    }


def cfg_after(mid: str) -> Dict[str, Any]:
    return {
        "id": mid,
        "initial": "wait",
        "context": {"n": 0},
        "states": {
            "wait": {"after": {"10": "hot"}},
            "hot": {"entry": ["boom"], "on": {"GO": "done"}},
            "done": {"entry": ["tick"]},
        },
    }


def mk_logic(boom_async=None, boom_sync=None):
    """Build logic; exactly one of boom_async / boom_sync is given."""
    if boom_sync is not None:
        def _boom(i, ctx, e, ad):  # noqa: ANN001
            boom_sync(i, ctx, e, ad)

        def _tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"boom": _boom, "tick": _tick})

    async def _aboom(i, ctx, e, ad):  # noqa: ANN001
        await boom_async(i, ctx, e, ad)

    async def _atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"boom": _aboom, "tick": _atick})


async def drive(mid: str, logic: MachineLogic, *, after: bool = False,
                settle: float = 0.30):
    """start() then let the loop idle; return (interp, states, n)."""
    m = create_machine(cfg_after(mid) if after else cfg(mid), logic=logic)
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(settle)
    st = sorted(i.current_state_ids)
    n = i.context.get("n", 0)
    await i.stop()
    return i, st, n


def landed(states: List[str]) -> bool:
    return any(s.endswith(".done") for s in states)


# 🧭 ORACLE. Two independent observables per cell:
#   advance  -- with the loop otherwise idle, does the machine reach
#               `.done`?  Under the #225 bug a helper task's plain send()
#               landed in the internal queue and never drained: no.
#   identity -- does send(..., wait=True) issued from that same task raise
#               ReentrantWaitError?  RAISED == "the library thinks this
#               task IS the action" (internal identity); RESOLVED ==
#               external.  This is the direct read of `_action_tasks`.
# Expected identity per cell is asserted against the changelog's claim.


async def cell_M1_action_direct_send() -> None:
    """The action's OWN task sends. Identity: INTERNAL (guard refuses)."""
    seen: List[str] = []

    async def boom(i, ctx, e, ad):  # noqa: ANN001
        i.send("GO")                       # plain: internal lane
        try:
            await i.send("GO", wait=True)  # same task, in-step
            seen.append("RESOLVED")
        except ReentrantWaitError:
            seen.append("ReentrantWaitError")

    _, st, n = await drive("w1m1", mk_logic(boom_async=boom))
    ok = seen == ["ReentrantWaitError"] and landed(st)
    if not ok:
        FAILS.append(f"M1: expected internal identity + advance, got "
                     f"{seen} {st}")
    record("M1_action_direct_send", "async def", identity=seen,
           expected_identity="INTERNAL", states=st, n=n, advanced=landed(st),
           ok=ok)


async def cell_M2_action_helper_awaited() -> None:
    """Action awaits a plain helper coroutine -- NO task boundary is
    crossed, so the helper runs ON the action's task. Identity must stay
    INTERNAL: a coroutine is not a task."""
    seen: List[str] = []

    async def helper(i):  # noqa: ANN001
        try:
            await i.send("GO", wait=True)
            seen.append("RESOLVED")
        except ReentrantWaitError:
            seen.append("ReentrantWaitError")

    async def boom(i, ctx, e, ad):  # noqa: ANN001
        await helper(i)

    _, st, n = await drive("w1m2", mk_logic(boom_async=boom))
    ok = seen == ["ReentrantWaitError"]
    if not ok:
        FAILS.append(f"M2: an awaited helper coroutine runs on the action's "
                     f"own task; expected ReentrantWaitError, got {seen}")
    record("M2_action_helper_awaited", "async def", identity=seen,
           expected_identity="INTERNAL", states=st, n=n, advanced=landed(st),
           ok=ok)


async def cell_M3_action_ensure_future(kind: str) -> None:
    """Action spawns a TASK which sends. #225: the task is EXTERNAL.
    Runs on both kinds -- ensure_future needs no await at the issue site."""
    seen: List[str] = []
    done = asyncio.Event()

    async def worker(i):  # noqa: ANN001
        try:
            await i.send("GO", wait=True)
            seen.append("RESOLVED")
        except ReentrantWaitError:
            seen.append("ReentrantWaitError")
        except Exception as exc:  # noqa: BLE001
            seen.append(type(exc).__name__)
        done.set()

    def spawn(i, ctx, e, ad):  # noqa: ANN001
        asyncio.ensure_future(worker(i))

    async def aspawn(i, ctx, e, ad):  # noqa: ANN001
        asyncio.ensure_future(worker(i))

    logic = (mk_logic(boom_sync=spawn) if kind == "def"
             else mk_logic(boom_async=aspawn))
    _, st, n = await drive(f"w1m3{kind[:1]}", logic)
    ok = seen == ["RESOLVED"] and landed(st)
    if not ok:
        FAILS.append(f"M3/{kind}: a spawned task must be EXTERNAL "
                     f"(resolve + advance); got {seen} {st}")
    record("M3_action_ensure_future", kind, identity=seen,
           expected_identity="EXTERNAL", states=st, n=n,
           advanced=landed(st), ok=ok)


async def cell_M4_action_task_task() -> None:
    """action -> task -> task -> send. Two boundaries; still EXTERNAL.
    Under a ContextVar the identity was inherited at EVERY hop."""
    seen: List[str] = []

    async def inner(i):  # noqa: ANN001
        try:
            await i.send("GO", wait=True)
            seen.append("RESOLVED")
        except ReentrantWaitError:
            seen.append("ReentrantWaitError")

    async def outer(i):  # noqa: ANN001
        t = asyncio.ensure_future(inner(i))
        await t

    async def boom(i, ctx, e, ad):  # noqa: ANN001
        asyncio.ensure_future(outer(i))

    _, st, n = await drive("w1m4", mk_logic(boom_async=boom))
    ok = seen == ["RESOLVED"] and landed(st)
    if not ok:
        FAILS.append(f"M4: grandchild task must be EXTERNAL; got {seen} {st}")
    record("M4_action_task_task", "async def", identity=seen,
           expected_identity="EXTERNAL", states=st, n=n,
           advanced=landed(st), ok=ok)


async def cell_M5_worker_outlives_action() -> None:
    """The worker sleeps well past the action's return, THEN sends a PLAIN
    event with the loop idle. This is the exact #225 starvation shape: an
    internal-lane routing here means the event is never drained."""
    async def worker(i):  # noqa: ANN001
        await asyncio.sleep(0.25)
        i.send("GO")            # plain send, long after the action ended

    async def boom(i, ctx, e, ad):  # noqa: ANN001
        asyncio.ensure_future(worker(i))

    _, st, n = await drive("w1m5", mk_logic(boom_async=boom), settle=0.80)
    ok = landed(st) and n == 1
    if not ok:
        FAILS.append(f"M5: a worker outliving its action sent a plain event "
                     f"with the loop idle and the machine did not advance: "
                     f"{st} n={n}")
    record("M5_worker_outlives_action", "async def",
           expected_identity="EXTERNAL", states=st, n=n,
           advanced=landed(st), ok=ok)


async def cell_M6_def_action_send() -> None:
    """A plain `def` action sends. It runs under the executor -- a THREAD,
    not a task -- so `asyncio.current_task()` there is not the action's
    task. Recorded as OBSERVED: the library may run `def` actions inline
    on the loop thread (then internal) or off-thread (then external).
    Either is defensible; what is NOT is losing the event."""
    def boom(i, ctx, e, ad):  # noqa: ANN001
        i.send("GO")

    _, st, n = await drive("w1m6", mk_logic(boom_sync=boom), settle=0.60)
    ok = landed(st) and n == 1
    if not ok:
        FAILS.append(f"M6: a plain send() from a `def` action was lost in "
                     f"either lane: {st} n={n}")
    record("M6_def_action_send", "def",
           expected_identity="EITHER (must not be lost)", states=st, n=n,
           advanced=landed(st), ok=ok)


async def cell_M7_child_to_parent(kind: str) -> None:
    """A child interpreter's action sends to the PARENT. The parent's
    `_action_tasks` must not contain the child's action task, so this is
    EXTERNAL w.r.t. the parent and its wait=True must resolve."""
    seen: List[str] = []
    parent_m = create_machine(cfg_plainish("w1m7p"), logic=MachineLogic(
        actions={"tick": (lambda i, c, e, a: c.__setitem__(
            "n", c.get("n", 0) + 1))}))
    parent = Interpreter(parent_m)
    await parent.start()

    async def aboom(i, ctx, e, ad):  # noqa: ANN001
        try:
            await parent.send("GO", wait=True)
            seen.append("RESOLVED")
        except ReentrantWaitError:
            seen.append("ReentrantWaitError")

    def sboom(i, ctx, e, ad):  # noqa: ANN001
        parent.send("GO")
        seen.append("PLAIN")

    logic = (mk_logic(boom_sync=sboom) if kind == "def"
             else mk_logic(boom_async=aboom))
    child = Interpreter(create_machine(cfg(f"w1m7c{kind[:1]}"), logic=logic))
    await child.start()
    await asyncio.sleep(0.40)
    pst = sorted(parent.current_state_ids)
    pn = parent.context.get("n", 0)
    await child.stop()
    await parent.stop()
    expect = ["RESOLVED"] if kind == "async def" else ["PLAIN"]
    ok = seen == expect and any(s.endswith(".done") for s in pst) and pn == 1
    if not ok:
        FAILS.append(f"M7/{kind}: child->parent send must be EXTERNAL to the "
                     f"parent; got {seen} parent={pst} n={pn}")
    record("M7_child_action_parent_send", kind, identity=seen,
           expected_identity="EXTERNAL(parent)", parent_states=pst, n=pn,
           advanced=any(s.endswith(".done") for s in pst), ok=ok)


def cfg_plainish(mid: str) -> Dict[str, Any]:
    return {
        "id": mid,
        "initial": "idle",
        "context": {"n": 0},
        "states": {"idle": {"on": {"GO": "done"}},
                   "done": {"entry": ["tick"]}},
    }


async def cell_M8_after_handler_send() -> None:
    """The action is reached from an `after`-fired event, i.e. the run loop
    entered it from a timer callback rather than from start(). The task
    recorded in `_action_tasks` must still be the one running the action."""
    seen: List[str] = []

    async def boom(i, ctx, e, ad):  # noqa: ANN001
        try:
            await i.send("GO", wait=True)
            seen.append("RESOLVED")
        except ReentrantWaitError:
            seen.append("ReentrantWaitError")

    _, st, n = await drive("w1m8", mk_logic(boom_async=boom), after=True,
                           settle=0.50)
    ok = seen == ["ReentrantWaitError"]
    if not ok:
        FAILS.append(f"M8: an `after`-reached action is still the action; "
                     f"expected ReentrantWaitError, got {seen}")
    record("M8_after_handler_send", "async def", identity=seen,
           expected_identity="INTERNAL", states=st, n=n,
           advanced=landed(st), ok=ok)


async def cell_M9_spawner_keeps_awaiting() -> None:
    """#225's named regression: the action hands the receipt out with
    ensure_future and THEN AWAITS AGAIN. Under the ContextVar the later
    yield made the handed-out receipt flip to a refusal. It must resolve."""
    seen: List[str] = []
    box: Dict[str, Any] = {}

    async def boom(i, ctx, e, ad):  # noqa: ANN001
        box["t"] = asyncio.ensure_future(i.send("GO", wait=True))
        await asyncio.sleep(0.05)   # the action yields again -- the trap
        await asyncio.sleep(0.05)

    _, st, n = await drive("w1m9", mk_logic(boom_async=boom), settle=0.60)
    t = box.get("t")
    try:
        await asyncio.wait_for(t, 5.0)
        seen.append("RESOLVED")
    except ReentrantWaitError:
        seen.append("ReentrantWaitError")
    except asyncio.TimeoutError:
        seen.append("HANG")
    except Exception as exc:  # noqa: BLE001
        seen.append(type(exc).__name__)
    ok = seen == ["RESOLVED"] and landed(st)
    if not ok:
        FAILS.append(f"M9: a handed-out receipt must resolve even when the "
                     f"spawning action yields again; got {seen} {st}")
    record("M9_spawner_keeps_awaiting", "async def", identity=seen,
           expected_identity="EXTERNAL", states=st, n=n,
           advanced=landed(st), ok=ok)


async def main() -> int:
    warnings.simplefilter("always")
    cells = [
        ("M1", cell_M1_action_direct_send()),
        ("M2", cell_M2_action_helper_awaited()),
        ("M3/def", cell_M3_action_ensure_future("def")),
        ("M3/async def", cell_M3_action_ensure_future("async def")),
        ("M4", cell_M4_action_task_task()),
        ("M5", cell_M5_worker_outlives_action()),
        ("M6", cell_M6_def_action_send()),
        ("M7/def", cell_M7_child_to_parent("def")),
        ("M7/async def", cell_M7_child_to_parent("async def")),
        ("M8", cell_M8_after_handler_send()),
        ("M9", cell_M9_spawner_keeps_awaiting()),
    ]
    for name, coro in cells:
        try:
            await asyncio.wait_for(coro, WATCHDOG)
        except asyncio.TimeoutError:
            FAILS.append(f"{name}: HANG (> {WATCHDOG}s watchdog)")
            record(name, "?", hung=True, ok=False)
        except Exception as exc:  # noqa: BLE001
            FAILS.append(f"{name}: raised {type(exc).__name__}: {exc}")
            record(name, "?", error=f"{type(exc).__name__}: {exc}", ok=False)
    emit("w1_task_identity_matrix", {
        "cells": ROWS,
        "failures": FAILS,
        "verdict": "CLEAN" if not FAILS else "DEFECT",
    })
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
