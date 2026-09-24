# -*- coding: utf-8 -*-
"""U5 -- #207 `on_invocation_stranded` under a rollback+onDone storm, with a
chaos snapshot/restore in the middle.

STANDALONE (stdlib + xstate_statemachine).  Run from any cwd.

#207 made a chain cut that strands an invocation observable: the hook
`on_invocation_stranded(interpreter, state_id, invoke_id, error)` fires, an
ERROR log names the state, `RunawayChainError.stranded` carries the invoke
ids, and `has_dormant_invocations` / `pending_invocations()` answer on
demand.  This track's question is what persistence does to that signal.

  A  EXACTLY-ONCE AND CORRECT IDS across N concurrent storms.  Every
     stranded state must be reported once, with the state id and invoke id
     the chart declares -- no duplicates, no invented ids, no misses.

  B  THE STRANDED STATE IS PERSISTED HONESTLY.  A snapshot taken after the
     cut must name the invoking state in `state_ids` AND report it through
     `pending_invocations()`, so a wrapper can tell "stranded" from
     "waiting on a slow service" from the blob alone.

  C  A RESTORE OF A STRANDED MACHINE IS NOT SILENTLY STRANDED AGAIN.
     Restore with `restart_services=True`: the dormant invocation must be
     re-armed (the whole point of the flag), not left dormant forever.

  D  ORDERING vs `on_event_dropped`.  Both fire for the same cut; record
     the relative order so a wrapper's correlation logic can rely on it.

Both service kinds.  N storms run concurrently on the same loop.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

KIND = os.environ.get("XS_SVC", "async")

# rollback + onDone: the entry action fails, the step is rolled back, the
# invoke is re-armed by the next lap, and the cycle is cut at maxIterations
# with the service in flight -- #207's shape.
# 📏 the #207 shape: the invoke's `onDone` targets a state whose ENTRY
#    fails, so `actionErrorPolicy: rollback` unwinds back into the invoking
#    state, which re-arms -- a cycle that ends parked in `starting` with
#    nothing running. `maxIterations` is left DEFAULT here (the library pins
#    the plateau at limit+2); a low limit is exercised in the storm.
SPEC = {
    "id": "st",
    "maxIterations": 10,
    "actionErrorPolicy": "rollback",
    "initial": "idle",
    "states": {
        "idle": {"on": {"GO": "starting"}},
        "starting": {
            "invoke": {"id": "k", "src": "svc", "onDone": "recording"},
        },
        "recording": {"entry": ["boom"]},
    },
}


def build(hold: float):
    def boom(i, c, e, a):  # noqa: ANN001
        raise RuntimeError("entry failed -> rollback")

    def svc_def(i, c, e):  # noqa: ANN001
        import time
        time.sleep(hold)
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(hold)
        return {"ok": 1}

    return create_machine(
        json.loads(json.dumps(SPEC)),
        logic=MachineLogic(
            actions={"boom": boom},
            services={"svc": svc_def if KIND == "def" else svc_async},
        ),
    )


class Watch(PluginBase):
    def __init__(self) -> None:
        self.stranded = []          # (state_id, invoke_id)
        self.dropped = []
        self.order = []             # interleaved hook names

    def on_invocation_stranded(self, interp, state_id, invoke_id, error):  # noqa: ANN001,E501
        self.stranded.append((state_id, invoke_id))
        self.order.append("stranded")

    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        self.dropped.append((getattr(event, "type", "?"), str(reason)))
        self.order.append("dropped")


def _pend(i):
    p = getattr(i, "pending_invocations", None)
    try:
        return [(x.state_id, x.invoke_id) for x in p()] if callable(p) else None
    except Exception:  # noqa: BLE001
        return None


async def storm(idx: int, hold: float) -> tuple:
    w = Watch()
    i = Interpreter(build(hold))
    i.use(w)
    await i.start()
    try:
        await i.send("GO")
    except Exception:  # noqa: BLE001
        pass
    # let the cycle run to its cut
    for _ in range(120):
        await asyncio.sleep(0.01)
        if w.stranded or w.dropped:
            break
    await asyncio.sleep(0.05)
    states = sorted(i.current_state_ids)
    dormant = getattr(i, "has_dormant_invocations", None)
    dormant = dormant() if callable(dormant) else dormant
    pend = _pend(i)
    try:
        blob = i.get_snapshot()
    except Exception as exc:  # noqa: BLE001
        blob = f"__REFUSED__{type(exc).__name__}"
    try:
        await i.stop()
    except Exception:  # noqa: BLE001
        pass
    return w, states, dormant, pend, blob


async def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    # 📏 the service must COMPLETE for the rollback cycle to turn, so the
    #    hold is 0 on both lanes; the `def` lane additionally blocks the
    #    loop per call, so N concurrent storms serialise there.
    hold = 0.0
    print(f"=== U5 stranded-invocation hook under {n} concurrent "
          f"rollback+onDone storms [{KIND}] hold={hold} ===")

    logbuf = io.StringIO()
    handler = logging.StreamHandler(logbuf)
    handler.setLevel(logging.ERROR)
    logging.getLogger("xstate_statemachine").addHandler(handler)

    res = await asyncio.gather(*[storm(k, hold) for k in range(n)])

    logging.getLogger("xstate_statemachine").removeHandler(handler)

    fails = []
    n_stranded = sum(len(w.stranded) for w, *_ in res)
    n_dropped = sum(len(w.dropped) for w, *_ in res)
    machines_with = sum(1 for w, *_ in res if w.stranded)
    dup = [w.stranded for w, *_ in res if len(w.stranded) != len(set(w.stranded))]
    bad_ids = sorted({
        p for w, *_ in res for p in w.stranded
        if p != ("st.starting", "k")})
    print(f"   machines that reported a strand : {machines_with}/{n}")
    print(f"   total on_invocation_stranded    : {n_stranded}")
    print(f"   total on_event_dropped          : {n_dropped}")
    print(f"   duplicate reports within one machine: {len(dup)} (must be 0)")
    print(f"   wrong ids reported              : {bad_ids or 'none'} "
          f"(expected ('st.starting','k'))")
    if dup:
        fails.append(f"A: {len(dup)} machines reported a strand more than once")
    if bad_ids:
        fails.append(f"A: wrong state/invoke ids reported: {bad_ids}")

    # ordering
    orders = {tuple(w.order[:2]) for w, *_ in res if len(w.order) >= 2}
    print(f"   hook order (first two)          : "
          f"{sorted(orders) or 'n/a'}")

    # B: read side
    sample = res[0]
    w, states, dormant, pend, blob = sample
    print(f"\n   sample machine: states={states} "
          f"has_dormant_invocations={dormant} pending_invocations={pend}")
    refused = isinstance(blob, str) and blob.startswith("__REFUSED__")
    print(f"   snapshot after the cut          : "
          f"{'REFUSED ' + blob[11:] if refused else 'accepted'}")
    if not refused:
        d = json.loads(blob)
        print(f"   blob state_ids={d.get('state_ids')} "
              f"actors={list((d.get('actors') or {}).keys())} "
              f"status={d.get('status')}")
        if machines_with and not d.get("state_ids"):
            fails.append("B: a stranded machine persists an empty state_ids")

        # C: restore with restart_services
        calls = []

        def mk():
            def boom(i, c, e, a):  # noqa: ANN001
                pass

            def svc_def(i, c, e):  # noqa: ANN001
                calls.append(1)
                return {"ok": 1}

            async def svc_async(i, c, e):  # noqa: ANN001
                calls.append(1)
                await asyncio.sleep(0)
                return {"ok": 1}

            return create_machine(
                json.loads(json.dumps(SPEC)),
                logic=MachineLogic(
                    actions={"boom": boom},
                    services={
                        "svc": svc_def if KIND == "def" else svc_async}),
            )

        j = Interpreter.from_snapshot(blob, mk(), restart_services=True)
        pre = _pend(j)
        await j.start()
        await asyncio.sleep(0.2)
        post_dormant = getattr(j, "has_dormant_invocations", None)
        post_dormant = post_dormant() if callable(post_dormant) else post_dormant
        print(f"\n   restored: pre-start pending={pre} "
              f"service calls={len(calls)} still_dormant={post_dormant}")
        if states and any("starting" in s for s in states) and not calls:
            fails.append(
                "C: restart_services=True did NOT re-arm the stranded "
                "invocation (0 service calls)")
        try:
            await j.stop()
        except Exception:  # noqa: BLE001
            pass

    logtxt = logbuf.getvalue()
    hits = [l for l in logtxt.splitlines() if "strand" in l.lower()]
    print(f"\n   ERROR-log lines mentioning 'strand': {len(hits)}")
    if hits:
        print(f"     e.g. {hits[0][:140]}")
    if machines_with and not hits:
        fails.append("D: no ERROR log named the stranded state (#207)")

    print()
    print("FAILURES:", fails or "none")
    print("VERDICT:", "FAIL" if fails else "PASS")


if __name__ == "__main__":
    asyncio.run(main())
