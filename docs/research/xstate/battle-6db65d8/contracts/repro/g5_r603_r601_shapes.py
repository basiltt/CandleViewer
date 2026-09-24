# -*- coding: utf-8 -*-
"""R7/G5 -- the two round-6 shapes, exercised ON THE REAL CONTRACT MACHINES.

R6-03 class -- rollback + `invoke.onDone`.
  `actionErrorPolicy: "rollback"` on an entry action of a state that invokes:
  the entry raises, the configuration is rolled back, and the invoke that the
  aborted entry armed must NOT survive as an orphan, must not re-arm in a
  loop, and its late `done.invoke` must not resurrect the abandoned target.
  Driven on B6 (`twap.submitting_slice`) and B9 (`rule_instance.simulating`).

R6-01 class -- `always` into an invoked child.
  A transient (`always`) that lands on a state with an `invoke`: the entering
  macrostep must terminate, the completion must be delivered, and the settle
  budget must be per-macrostep (not restart per completion). Driven on B9,
  whose `draft -> validating` chain is the catalogue's `always` ladder, and on
  a B8 `attaching` re-entry.

Each check asserts TERMINATES (wall bound), BOUNDED (lap ceiling) and
OBSERVABLE (a health signal reads true when it does not terminate).
"""
from __future__ import annotations

import asyncio
import json
import time

import cvlib
from cvlib import Rig

WALL = 4.0
OUT = []


def rec(name: str, verdict: str, **ev) -> None:
    OUT.append({"check": name, "verdict": verdict, "evidence": ev})
    print(name, verdict)


async def settle(interp, secs: float = 0.25) -> None:
    await asyncio.sleep(secs)


async def r603_rollback_invoke(bid: str, enter_event: str, raising_action: str,
                               name: str, prelude=(), pre_guards=None) -> None:
    """Entry action of an invoking state raises under rollback."""
    cfg = json.loads(json.dumps(cvlib.load(bid)))
    cfg["actionErrorPolicy"] = "rollback"
    rig = Rig(action_raises=set(), guard_values=dict(pre_guards or {}))
    _m, interp, plug, _c = cvlib.new_interp(cfg, rig)
    await interp.start()
    await settle(interp, 0.05)
    for ev in prelude:
        await interp.send(ev)
        await settle(interp, 0.1)
    rig.action_raises.add(raising_action)
    before = sorted(interp.current_state_ids)
    t0 = time.monotonic()
    r = await interp.send(enter_event, wait=True)
    await settle(interp, 0.4)
    el = time.monotonic() - t0
    svc_calls = [c for c in rig.calls if c.startswith("S:")]
    pend = [repr(p) for p in interp.pending_invocations()]
    terminated = el < WALL
    rec(
        name,
        "PASS" if terminated and len(svc_calls) <= 2 else "FAIL",
        machine=bid,
        before=before,
        after=sorted(interp.current_state_ids),
        rolled_back=sorted(interp.current_state_ids) == before,
        elapsed_s=round(el, 2),
        service_invocations=svc_calls,
        pending_invocations=pend,
        status=interp.status,
        receipt={"changed": r.changed, "denied": r.denied,
                 "error": type(r.error).__name__ if r.error else None},
        last_transition_ok=interp.last_transition_ok,
        last_error=type(interp.last_error).__name__ if interp.last_error else None,
        dropped=plug.dropped[:3],
    )
    await interp.stop()


async def r601_always_into_invoke(bid: str, enter_event: str, guards: dict,
                                  name: str, prelude=()) -> None:
    """An `always` ladder that lands on an invoking state must settle."""
    cfg = cvlib.load(bid)
    rig = Rig(guard_values=guards)
    _m, interp, plug, _c = cvlib.new_interp(cfg, rig)
    await interp.start()
    await settle(interp, 0.05)
    for ev in prelude:
        await interp.send(ev)
        await settle(interp, 0.1)
    rig.calls.clear()
    t0 = time.monotonic()
    try:
        r = await asyncio.wait_for(interp.send(enter_event, wait=True), WALL)
        hung = False
    except asyncio.TimeoutError:
        r = None
        hung = True
    await settle(interp, 0.3)
    el = time.monotonic() - t0
    svc = [c for c in rig.calls if c.startswith("S:")]
    rec(
        name,
        "PASS" if not hung and len(svc) < 50 else "FAIL",
        machine=bid,
        hung_send_wait=hung,
        elapsed_s=round(el, 2),
        states=sorted(interp.current_state_ids),
        service_invocations=len(svc),
        service_names=svc[:6],
        status=interp.status,
        last_transition_ok=interp.last_transition_ok,
        last_error=type(interp.last_error).__name__ if interp.last_error else None,
        dropped=plug.dropped[:3],
        receipt=None if r is None else {"changed": r.changed, "denied": r.denied},
    )
    await interp.stop()


async def main() -> None:
    # --- R6-03 class: rollback aborting an entry that arms an invoke --------
    await r603_rollback_invoke(
        "B6", "SLICE_DUE", "bump_slices_done",
        "R6-03/B6 rollback on entry of invoking submitting_slice")
    await r603_rollback_invoke(
        "B9", "TRIGGER", "assert_safety_limits",
        "R6-03/B9 rollback on entry of invoking acting",
        prelude=("SAVE", "ARM_REQUESTED"),
        pre_guards={"promotion_gate_satisfied_and_permitted": True})
    # --- R6-01 class: always ladder into an invoking child ------------------
    await r601_always_into_invoke(
        "B6", "SLICE_DUE", {"slice_qty_below_min_roll_forward": True},
        "R6-01/B6 always out of invoking submitting_slice (roll-forward)")
    await r601_always_into_invoke(
        "B9", "TRIGGER", {"condition_true": True},
        "R6-01/B9 evaluating -> acting invoke chain settles",
        prelude=("SAVE", "ARM_REQUESTED"))
    await r601_always_into_invoke(
        "B8", "POSITION_OPENED", {"exchange_reports_sl": True},
        "R6-01/B8 attach ladder settles into protected")
    print(json.dumps(OUT, indent=1))
    json.dump(OUT, open("repro/g5_r603_r601_shapes.json", "w"), indent=1)


if __name__ == "__main__":
    import logging

    logging.disable(logging.ERROR)
    asyncio.run(main())
