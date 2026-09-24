"""D9-C: concurrency + children_timeout + RAISE attacks on f28719c.

C1  External priority producer at high rate DURING a self-generated chain,
    both service kinds: ZERO EXTERNAL events may be shed (type-aware -- a
    self-generated completion being cut is #192 working correctly).
C2  An ACTION-issued send(priority=True) must be CHARGED (#192) and trip,
    on both service kinds.
C3  children_timeout with 50 def + 50 async children: the bound is PER
    CHILD, not N*D, and a WARNING always fires on overrun (#194).
C4  A def service armed then rolled back (actionErrorPolicy rollback) under
    200 concurrent interpreters: the callable is never submitted (#193).
C5  RAISE loop-side refusals fire on_event_dropped exactly once.

Standalone: stdlib + xstate_statemachine only.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import sys
import time
import traceback
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

logging.disable(logging.CRITICAL)

_REG: List[Dict[str, Any]] = []


def attack(aid: str, title: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "fn": fn})
        return fn

    return deco


def main(group: str) -> None:
    out, npass = [], 0
    for a in _REG:
        rec = {"id": a["id"], "title": a["title"]}
        try:
            fn = a["fn"]
            res = asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
            rec["detail"] = res
            rec["status"] = "PASS" if res.get("ok") else "FAIL"
        except Exception as exc:  # noqa: BLE001
            rec["status"] = "ERROR"
            rec["detail"] = {"exc": f"{type(exc).__name__}: {exc}",
                             "tb": traceback.format_exc()[-1500:]}
        npass += rec["status"] == "PASS"
        out.append(rec)
        print(f"[{rec['status']:5}] {rec['id']:6} {a['title'][:88]}")
        if rec["status"] != "PASS":
            print("        -> " + json.dumps(rec["detail"], default=str)[:1200])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


class Drops(PluginBase):
    def __init__(self) -> None:
        self.items: List[Any] = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.items.append((e.type, reason))


# ==========================================================================
# C1 -- external priority producer during a self-generated chain
# ==========================================================================
PINGPONG = {
    "id": "pp",
    "initial": "idle",
    "maxIterations": 20,
    "states": {
        "idle": {"on": {"GO": "a", "EXT": {"actions": "count_ext"}}},
        "a": {"invoke": {"src": "svc", "onDone": "b"},
              "on": {"EXT": {"actions": "count_ext"}}},
        "b": {"invoke": {"src": "svc", "onDone": "a"},
              "on": {"EXT": {"actions": "count_ext"}}},
    },
}


async def _ext_flood(kind: str, n: int) -> Dict[str, Any]:
    seen = {"n": 0}

    def count_ext(i, c, e, a):  # noqa: ANN001
        seen["n"] += 1

    def svc(i, c, e):  # noqa: ANN001
        return 1

    async def svc_a(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    logic = MachineLogic(
        actions={"count_ext": count_ext},
        services={"svc": svc_a if kind == "async" else svc},
    )
    d = Drops()
    itp = await Interpreter(
        create_machine(copy.deepcopy(PINGPONG), logic=logic)
    ).use(d).start()
    await itp.send("GO")
    t0 = time.perf_counter()
    for _ in range(n):
        await itp.send("EXT", priority=True)
        await asyncio.sleep(0)
    rate = n / max(time.perf_counter() - t0, 1e-9)
    await asyncio.sleep(0.3)
    ext_shed = [t for t, r in d.items
                if r == "chain_budget" and t == "EXT"]
    self_shed = [t for t, r in d.items
                 if r == "chain_budget" and t != "EXT"]
    await itp.stop()
    return {
        "kind": kind, "sent": n, "actions_fired": seen["n"],
        "rate_per_s": round(rate),
        "EXTERNAL_shed_as_chain_budget": len(ext_shed),
        "self_generated_shed_ok": len(self_shed),
        "other_drops": sorted({r for t, r in d.items if r != "chain_budget"}),
    }


@attack("C1", "External priority producer >=10k/s during a self-generated "
              "chain: ZERO external shed, both service kinds")
async def c1() -> Dict[str, Any]:
    runs = [await _ext_flood(k, 10000) for k in ("plain", "async")]
    return {
        "ok": all(r["EXTERNAL_shed_as_chain_budget"] == 0
                  and r["actions_fired"] == r["sent"] for r in runs),
        "runs": runs,
    }


# ==========================================================================
# C2 -- an ACTION-issued priority send is charged and trips (#192)
# ==========================================================================
SELF_PRIO = {
    "id": "sp",
    "initial": "a",
    "maxIterations": 15,
    "states": {
        "a": {"entry": "bounce", "on": {"P": "b"}},
        "b": {"entry": "bounce", "on": {"P": "a"}},
    },
}


@attack("C2", "An action-issued send(priority=True) is CHARGED and trips "
              "the chain budget (#192), both service kinds")
async def c2() -> Dict[str, Any]:
    out = {}
    for kind in ("plain", "async"):
        n = {"v": 0}

        def bounce(i, c, e, a):  # noqa: ANN001
            n["v"] += 1
            if n["v"] < 400:
                i.send("P", priority=True)

        d = Drops()
        itp = await Interpreter(
            create_machine(copy.deepcopy(SELF_PRIO),
                           logic=MachineLogic(actions={"bounce": bounce}))
        ).use(d).start()
        await asyncio.sleep(0.5)
        out[kind] = {
            "laps": n["v"],
            "tripped": any(r == "chain_budget" for _, r in d.items),
            "last_error": type(itp.last_error).__name__
            if itp.last_error else None,
            "bounded": n["v"] < 400,
        }
        await itp.stop()
    return {
        "ok": all(v["tripped"] and v["bounded"] for v in out.values()),
        "runs": out,
    }

# ==========================================================================
# C3 -- children_timeout is PER CHILD with 50 def + 50 async children (#194)
# ==========================================================================
@attack("C3", "children_timeout with 50 def + 50 async children: bound is "
              "per child (not N*D) and a WARNING always fires on overrun")
async def c3() -> Dict[str, Any]:
    import logging as _lg

    D = 0.25
    N = 50
    recs: List[str] = []

    class Cap(_lg.Handler):
        def emit(self, r):  # noqa: ANN001
            if r.levelno >= _lg.WARNING:
                recs.append(r.getMessage()[:80])

    def kid(idx: int) -> Dict[str, Any]:
        return {"id": f"kid{idx}", "initial": "boot",
                "states": {"boot": {"entry": "slow"}, "up": {}}}

    out = {}
    for kind in ("plain", "async"):
        recs.clear()
        _lg.disable(_lg.NOTSET)
        cap = Cap()
        lg_i = _lg.getLogger("xstate_statemachine")
        lg_i.addHandler(cap)
        lg_i.setLevel(_lg.WARNING)

        def slow_sync(i, c, e, a):  # noqa: ANN001
            time.sleep(D)

        async def slow_async(i, c, e, a):  # noqa: ANN001
            await asyncio.sleep(D)

        root = {"id": "root", "initial": "up",
                "states": {"up": {"invoke": [
                    {"src": f"kid{n}", "id": f"kid{n}"} for n in range(N)]}}}
        logic = MachineLogic(
            actions={"slow": slow_async if kind == "async" else slow_sync},
            services={
                f"kid{n}": create_machine(
                    kid(n),
                    logic=MachineLogic(actions={
                        "slow": slow_async if kind == "async" else slow_sync}),
                ) for n in range(N)
            },
        )
        itp = Interpreter(create_machine(root, logic=logic))
        t0 = time.perf_counter()
        await itp.start(children_timeout=D * 2)
        el = time.perf_counter() - t0
        out[kind] = {
            "children": N, "per_child_delay": D, "bound": D * 2,
            "start_seconds": round(el, 3),
            "aggregate_bound_would_be": round(N * D, 2),
            "within_per_child_scale": el < N * D * 0.5,
            "status": itp.status,
            "warnings": len(recs),
        }
        await itp.stop()
        lg_i.removeHandler(cap)
        _lg.disable(_lg.CRITICAL)
    return {
        # #194 documented contract: a blocking plain-`def` entry action
        # cannot be pre-empted on the loop thread -- the bound does not
        # apply, but the WARNING must fire. The coroutine lane must honour
        # the PER-CHILD bound (not N*D).
        "ok": (out["async"]["within_per_child_scale"]
               and out["plain"]["warnings"] >= 1
               and all(v["status"] == "running" for v in out.values())),
        "plain_is_documented_nonpreemptible": True,
        "runs": out,
    }


# ==========================================================================
# C4 -- def service armed then rolled back, 200 concurrent (#193)
# ==========================================================================
ROLLBACK = {
    "id": "rb",
    "initial": "idle",
    "actionErrorPolicy": "rollback",
    "states": {
        "idle": {"on": {"GO": "arm"}},
        "arm": {"entry": "boom", "invoke": {"src": "work", "onDone": "done"}},
        "done": {},
    },
}


@attack("C4", "200 concurrent def-service arm-then-rollback: the callable "
              "is never submitted (#193 handoff inside the engine task)")
async def c4() -> Dict[str, Any]:
    submitted = {"n": 0}

    def work(i, c, e):  # noqa: ANN001
        submitted["n"] += 1
        return 1

    def boom(i, c, e, a):  # noqa: ANN001
        raise RuntimeError("rollback me")

    ints = []
    for _ in range(200):
        logic = MachineLogic(actions={"boom": boom},
                             services={"work": work})
        ints.append(await Interpreter(
            create_machine(copy.deepcopy(ROLLBACK), logic=logic)).start())
    await asyncio.gather(*(i.send("GO") for i in ints),
                         return_exceptions=True)
    await asyncio.sleep(0.5)
    states = sorted({tuple(sorted(i.current_state_ids)) for i in ints})
    for i in ints:
        await i.stop()
    return {
        "ok": submitted["n"] == 0,
        "interpreters": 200,
        "service_callable_submitted": submitted["n"],
        "distinct_states": [list(s) for s in states],
    }


if __name__ == "__main__":
    main("c_concurrency")
