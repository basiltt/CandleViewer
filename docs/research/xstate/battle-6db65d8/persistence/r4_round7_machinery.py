# -*- coding: utf-8 -*-
"""R4 -- round-7 machinery: child mid-step (#183/#184), children_timeout
(#181) and `_chain_owed` under stop() (#179), on BOTH service kinds.

A. Snapshot the PARENT while an invoked child is inside its own entry
   action. #183 requires: a child stepping on the caller's thread is refused
   instantly with ``SnapshotMidStepError(child=True)``; never a half-applied
   harvest. Measured for a `def` and an `async def` child service, and the
   *latency* of the refusal is recorded (#184 says it must not burn 0.5 s).

B. ``start(children_timeout=)`` with N slow children: `await start()` must
   return inside the bound, not after N x delay, and must log a warning.

C. ``_chain_owed`` under 100 never-completing coroutine services followed by
   ``stop()``: does stop() hang (owed debt never repaid) and is the owed
   bookkeeping released (leak check on the owed set)?

Every service-bearing case runs with ``def`` and ``async def``.
"""
from __future__ import annotations

import asyncio
import gc
import json
import logging
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import SnapshotMidStepError

FAIL: list[str] = []


class WarnCatcher(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.msgs: list[str] = []

    def emit(self, record):  # noqa: ANN001
        self.msgs.append(record.getMessage())


CHILD = {
    "id": "kid",
    "initial": "boot",
    "states": {
        "boot": {"entry": ["slow_entry"], "on": {"PING": "done_"}},
        "done_": {"type": "final"},
    },
}


def parent_spec(n_children: int) -> dict:
    return {
        "id": "par",
        "initial": "up",
        "states": {
            "up": {
                "invoke": [
                    {"id": f"k{i}", "src": "kidsvc"} for i in range(n_children)
                ],
                "on": {"GO": "next"},
            },
            "next": {},
        },
    }


# ---------------------------------------------------------------- A -----
async def probe_a(kind: str) -> None:
    """Snapshot the parent while a CHILD is inside its own entry action."""
    hits = {"refused_child": 0, "refused_root": 0, "accepted": 0, "raw": 0}
    latencies: list[float] = []
    box: dict = {}

    def slow_entry_def(interp, ctx, event, ad):  # noqa: ANN001
        ctx["half"] = "written"
        parent = box.get("parent")
        if parent is not None:
            t0 = time.perf_counter()
            try:
                blob = parent.get_persisted_snapshot()
                hits["accepted"] += 1
                box["blob"] = blob
            except SnapshotMidStepError as exc:
                hits["refused_child" if getattr(exc, "child", False)
                     else "refused_root"] += 1
            except Exception:  # noqa: BLE001
                hits["raw"] += 1
            latencies.append(time.perf_counter() - t0)
        ctx["half"] = "complete"

    async def slow_entry_async(interp, ctx, event, ad):  # noqa: ANN001
        slow_entry_def(interp, ctx, event, ad)
        await asyncio.sleep(0)

    def kidsvc_def(interp, ctx, event):  # noqa: ANN001
        return {"ok": 1}

    async def kidsvc_async(interp, ctx, event):  # noqa: ANN001
        await asyncio.sleep(0.01)
        return {"ok": 1}

    child_m = create_machine(
        json.loads(json.dumps(CHILD)),
        logic=MachineLogic(
            actions={
                "slow_entry": slow_entry_def if kind == "def" else slow_entry_async
            }
        ),
    )
    spec = parent_spec(1)
    spec["states"]["up"]["invoke"][0]["src"] = "kidsvc"
    parent_m = create_machine(
        spec,
        logic=MachineLogic(
            services={"kidsvc": kidsvc_def if kind == "def" else kidsvc_async}
        ),
    )
    p = Interpreter(parent_m, clock=SimulatedClock())
    box["parent"] = p
    await p.start()
    # Now spawn the child machine under the parent explicitly so its entry
    # action runs while the parent is quiescent -- the exact #183 window.
    c = Interpreter(child_m, clock=SimulatedClock())
    p._actors[c.id] = c        # register as a child actor
    c.parent = p
    await c.start()
    await asyncio.sleep(0.05)
    worst = max(latencies) if latencies else 0.0
    print("  A[%-5s] refused(child)=%d refused(root)=%d accepted=%d raw=%d "
          "worst_latency=%.1f ms"
          % (kind, hits["refused_child"], hits["refused_root"],
             hits["accepted"], hits["raw"], worst * 1e3))
    if hits["accepted"]:
        b = box.get("blob") or {}
        ctx = (b.get("actors", {}) or {}).get("kid", {}).get("context", {})
        print("       harvested child context = %r" % (ctx,))
        if ctx.get("half") == "written":
            FAIL.append(f"A[{kind}]: half-applied child context harvested")
    if worst > 0.25:
        FAIL.append(f"A[{kind}]: refusal burned {worst*1e3:.0f} ms (#184)")
    await c.stop()
    await p.stop()


# ---------------------------------------------------------------- B -----
async def probe_b(kind: str, n: int = 50, delay: float = 0.2) -> None:
    """`children_timeout` with N slow CHILD MACHINES: start() must be bounded.

    `children_timeout` bounds `_await_actor_bringups`, which awaits invoked
    child *machines* (a `MachineNode` src), not plain services -- so the
    child here is a real sub-machine whose entry action is slow, which is
    the shape #181 names ("a slow child's `async def` entry action no longer
    holds `await start()` for its whole duration").
    """
    def slow_def(interp, ctx, event, ad):  # noqa: ANN001
        time.sleep(delay)

    async def slow_async(interp, ctx, event, ad):  # noqa: ANN001
        await asyncio.sleep(delay)

    kid = create_machine(
        {"id": "kid", "initial": "s", "states": {"s": {"entry": ["slow"]}}},
        logic=MachineLogic(
            actions={"slow": slow_def if kind == "def" else slow_async}
        ),
    )
    m = create_machine(
        parent_spec(n), logic=MachineLogic(services={"kidsvc": kid})
    )
    cap = WarnCatcher()
    logging.getLogger("xstate_statemachine").addHandler(cap)
    i = Interpreter(m, clock=SimulatedClock())
    t0 = time.perf_counter()
    await i.start(children_timeout=0.3)
    el = time.perf_counter() - t0
    warned = [x for x in cap.msgs if "still" in x and "starting" in x]
    registered = len(getattr(i, "_actors", {}) or {})
    print("  B[%-5s] n=%d delay=%.2fs -> start() took %.2fs, status=%s, "
          "children registered=%d, #181 warnings=%d"
          % (kind, n, delay, el, i.status, registered, len(warned)))
    if warned:
        print("       warning: %s" % warned[0][:120])
    if el > 1.5:
        FAIL.append(f"B[{kind}]: start() took {el:.2f}s despite children_timeout=0.3")
    if el > 0.35 and not warned:
        FAIL.append(f"B[{kind}]: waited {el:.2f}s past the bound with no warning")
    # After the bound, the children must still arrive (#181's promise).
    await asyncio.sleep(delay * 2 + 0.3)
    later = len(getattr(i, "_actors", {}) or {})
    print("       after the bring-ups finish: children registered=%d (want %d)"
          % (later, n))
    if later < n:
        FAIL.append(f"B[{kind}]: only {later}/{n} children ever registered")
    logging.getLogger("xstate_statemachine").removeHandler(cap)
    await i.stop()


# ---------------------------------------------------------------- C -----
async def probe_c(n: int = 100) -> None:
    """`_chain_owed` under N never-completing coroutine services + stop()."""
    started = {"n": 0}

    async def never(interp, ctx, event):  # noqa: ANN001
        started["n"] += 1
        await asyncio.sleep(3600)

    spec = {
        "id": "owe",
        "initial": "work",
        "states": {
            "work": {"invoke": [{"id": f"s{k}", "src": "never"} for k in range(n)]},
        },
    }
    m = create_machine(spec, logic=MachineLogic(services={"never": never}))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start(children_timeout=0.5)
    await asyncio.sleep(0.2)
    owed = getattr(i, "_chain_owed", None)
    print("  C services started=%d  _chain_owed after start=%r"
          % (started["n"], owed))
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(i.stop(), timeout=10)
        el = time.perf_counter() - t0
        print("  C stop() returned in %.2fs, status=%s, _chain_owed=%r"
              % (el, i.status, getattr(i, "_chain_owed", None)))
        if el > 5:
            FAIL.append(f"C: stop() took {el:.1f}s with {n} owed services")
    except asyncio.TimeoutError:
        print("  C stop() HUNG >10s with %d never-completing services" % n)
        FAIL.append("C: stop() hung under _chain_owed debt")
    gc.collect()
    leftover = getattr(i, "_chain_owed", None)
    if isinstance(leftover, int) and leftover != 0:
        print("  C LEAK: _chain_owed left at %d after stop()" % leftover)
        FAIL.append(f"C: _chain_owed leaked at {leftover}")


async def main() -> None:
    print("=== A. snapshot parent while a CHILD is in its entry action (#183/#184)")
    for k in ("def", "async"):
        await probe_a(k)
    print("\n=== B. start(children_timeout=) with 50 slow children (#181)")
    for k in ("def", "async"):
        await probe_b(k)
    print("\n=== C. _chain_owed under 100 never-completing coroutine services (#179)")
    await probe_c()
    print("\nFAILURES:", FAIL if FAIL else "none")
    print("VERDICT:", "FAIL" if FAIL else "PASS")


asyncio.run(main())
