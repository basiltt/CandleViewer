"""SEMANTICS @ 19cb1f1 -- concurrency attacks on the round-9 machinery.

C1  100 machines each running a `raise(delay=1ms)` self-ping-pong (#206):
    every machine must trip, and all must trip at the SAME lap, both kinds.
C2  200 concurrent `rollback + onDone` storms (#207): the
    `on_invocation_stranded` hook fires EXACTLY ONCE per stranded invoke,
    with the correct `(state_id, invoke_id)`, and `RunawayChainError.stranded`
    carries the same ids.
C3  External delayed sends at ~5k/s during self-generated chains: ZERO
    external events dropped as `chain_budget` (#192 x #206 interaction).
C4  Hook ordering: `on_event_dropped` for the cut completion must precede
    `on_invocation_stranded` for the invoke it stranded.

Standalone: stdlib + xstate_statemachine only. Both service kinds.
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
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.plugins import PluginBase

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
        rec: Dict[str, Any] = {"id": a["id"], "title": a["title"]}
        try:
            fn = a["fn"]
            res = asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
            rec["detail"] = res
            rec["status"] = "PASS" if res.get("ok") else "FAIL"
        except Exception as exc:  # noqa: BLE001
            rec["status"] = "ERROR"
            rec["detail"] = {
                "exc": f"{type(exc).__name__}: {exc}",
                "tb": traceback.format_exc()[-1500:],
            }
        npass += rec["status"] == "PASS"
        out.append(rec)
        print(f"[{rec['status']:5}] {rec['id']:4} {a['title'][:92]}")
        if rec["status"] != "PASS":
            print("        -> " + json.dumps(rec["detail"], default=str)[:1400])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


class Obs(PluginBase):
    """Records drops and stranded reports in arrival order."""

    def __init__(self) -> None:
        self.seq: List[Any] = []
        self.drops: List[Any] = []
        self.stranded: List[Any] = []

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.drops.append((getattr(e, "type", None), r))
        self.seq.append(("drop", getattr(e, "type", None), r))

    def on_invocation_stranded(self, i, sid, iid, err):  # noqa: ANN001
        self.stranded.append((sid, iid))
        self.seq.append(("stranded", sid, iid))


# =========================================================================
# C1 -- 100 machines x delayed self-ping-pong: same trip lap (#206)
# =========================================================================
PING = {
    "id": "pp",
    "initial": "a",
    "maxIterations": 10,
    "states": {
        "a": {"entry": "bounce", "on": {"P": "b"}},
        "b": {"entry": "bounce", "on": {"P": "a"}},
    },
}


@attack("C1", "100 machines x `raise(delay=1ms)` self-ping-pong: EVERY "
              "machine trips and all trip at the SAME lap, both kinds")
async def c1() -> Dict[str, Any]:
    cells = {}
    for kind in ("plain", "async"):
        counters: List[Dict[str, int]] = []
        obs: List[Obs] = []
        machines = []
        for _ in range(100):
            n = {"v": 0}
            counters.append(n)

            def bounce(i, c, e, a, _n=n):  # noqa: ANN001
                _n["v"] += 1
                if _n["v"] < 200:
                    i.send("P", delay=1)

            async def bounce_a(i, c, e, a, _n=n):  # noqa: ANN001
                _n["v"] += 1
                if _n["v"] < 200:
                    i.send("P", delay=1)

            lg = MachineLogic(
                actions={"bounce": bounce_a if kind == "async" else bounce}
            )
            o = Obs()
            obs.append(o)
            machines.append(
                Interpreter(
                    create_machine(copy.deepcopy(PING), logic=lg)
                ).use(o)
            )
        await asyncio.gather(*(m.start() for m in machines))
        await asyncio.sleep(1.2)
        laps = sorted({n["v"] for n in counters})
        tripped = sum(
            1
            for i, m in enumerate(machines)
            if m.last_error is not None
            or any(r == "chain_budget" for _, r in obs[i].drops)
        )
        await asyncio.gather(*(m.stop() for m in machines))
        cells[kind] = {
            "distinct_laps": laps,
            "tripped": tripped,
            "bounded": max(n["v"] for n in counters) < 200,
        }
    ok = all(
        len(c["distinct_laps"]) == 1 and c["tripped"] == 100 and c["bounded"]
        for c in cells.values()
    ) and (
        cells["plain"]["distinct_laps"] == cells["async"]["distinct_laps"]
    )
    return {"ok": ok, "cells": cells}


# =========================================================================
# C2 -- 200 concurrent rollback+onDone storms: stranded hook exactly once
# =========================================================================
STORM = {
    "id": "r",
    "initial": "w",
    "maxIterations": 6,
    "states": {
        "w": {"on": {"GO": "a"}},
        "a": {"invoke": {"src": "svc", "id": "sa", "onDone": "b"}},
        "b": {"invoke": {"src": "svc", "id": "sb", "onDone": "a"}},
    },
}


@attack("C2", "200 concurrent rollback+onDone storms: on_invocation_stranded "
              "fires EXACTLY ONCE with correct ids; err.stranded agrees")
async def c2() -> Dict[str, Any]:
    cells = {}
    for kind in ("plain", "async"):
        def svc(i, c, e):  # noqa: ANN001
            return 1

        async def svca(i, c, e):  # noqa: ANN001
            await asyncio.sleep(0)
            return 1

        lg = MachineLogic(services={"svc": svca if kind == "async" else svc})
        obs = [Obs() for _ in range(200)]
        ms = [
            Interpreter(
                create_machine(copy.deepcopy(STORM), logic=lg)
            ).use(obs[i])
            for i in range(200)
        ]
        await asyncio.gather(*(m.start() for m in ms))
        await asyncio.gather(*(m.send("GO") for m in ms))
        await asyncio.sleep(2.0)
        counts = [len(o.stranded) for o in obs]
        bad_ids = [
            o.stranded
            for o in obs
            if any(
                sid not in ("r.a", "r.b") or iid not in ("sa", "sb")
                for sid, iid in o.stranded
            )
        ]
        agree = 0
        for i, m in enumerate(ms):
            e = m.last_error
            hook = tuple(iid for _, iid in obs[i].stranded)
            if tuple(getattr(e, "stranded", ()) or ()) == hook:
                agree += 1
        dormant_without_hook = sum(
            1
            for i, m in enumerate(ms)
            if m.has_dormant_invocations and not obs[i].stranded
        )
        await asyncio.gather(*(m.stop() for m in ms))
        cells[kind] = {
            "hook_count_distribution": sorted(set(counts)),
            "machines_with_exactly_one": counts.count(1),
            "wrong_ids": len(bad_ids),
            "err_stranded_agrees": agree,
            "dormant_without_hook": dormant_without_hook,
        }
    ok = all(
        c["machines_with_exactly_one"] == 200
        and c["wrong_ids"] == 0
        and c["err_stranded_agrees"] == 200
        and c["dormant_without_hook"] == 0
        for c in cells.values()
    )
    return {"ok": ok, "cells": cells}


# =========================================================================
# C3 -- external delayed sends at ~5k/s during a self-generated chain
# =========================================================================
EXTM = {
    "id": "x",
    "initial": "a",
    "maxIterations": 10,
    "states": {
        "a": {
            "entry": "bounce",
            "on": {"P": "b", "EXT": {"actions": "count"}},
        },
        "b": {
            "entry": "bounce",
            "on": {"P": "a", "EXT": {"actions": "count"}},
        },
    },
}


@attack("C3", "5,000 EXTERNAL delayed sends during a live self-generated "
              "delayed chain: ZERO external dropped, both kinds")
async def c3() -> Dict[str, Any]:
    cells = {}
    for kind in ("plain", "async"):
        n = {"v": 0}
        seen = {"v": 0}

        def bounce(i, c, e, a):  # noqa: ANN001
            n["v"] += 1
            if n["v"] < 500:
                i.send("P", delay=1)

        async def bounce_a(i, c, e, a):  # noqa: ANN001
            n["v"] += 1
            if n["v"] < 500:
                i.send("P", delay=1)

        def count(i, c, e, a):  # noqa: ANN001
            seen["v"] += 1

        lg = MachineLogic(
            actions={
                "bounce": bounce_a if kind == "async" else bounce,
                "count": count,
            }
        )
        o = Obs()
        it = await Interpreter(
            create_machine(copy.deepcopy(EXTM), logic=lg)
        ).use(o).start()
        t0 = time.perf_counter()
        N = 5000
        for _ in range(N):
            # EXTERNAL: issued from outside any action, with a delay.
            it.send("EXT", delay=1)
        for _ in range(N):
            await asyncio.sleep(0)
        rate = N / max(time.perf_counter() - t0, 1e-9)
        await asyncio.sleep(1.2)
        ext_dropped = [t for t, r in o.drops if t == "EXT"]
        await it.stop()
        cells[kind] = {
            "sent": N,
            "issue_rate_per_s": round(rate),
            "actions_fired": seen["v"],
            "EXTERNAL_dropped": len(ext_dropped),
            "drop_reasons": sorted({r for t, r in o.drops if t == "EXT"}),
            "self_chain_laps": n["v"],
            "self_shed": sum(1 for t, r in o.drops if t != "EXT"),
        }
    ok = all(
        c["EXTERNAL_dropped"] == 0 and c["actions_fired"] == c["sent"]
        for c in cells.values()
    )
    return {"ok": ok, "cells": cells}


# =========================================================================
# C4 -- hook ordering: drop-of-completion precedes stranded report
# =========================================================================
@attack("C4", "Ordering: on_event_dropped(chain_budget) for the cut "
              "completion precedes on_invocation_stranded for that invoke, "
              "both kinds and both engines")
async def c4() -> Dict[str, Any]:
    cells = {}
    for kind in ("plain", "async"):
        def svc(i, c, e):  # noqa: ANN001
            return 1

        async def svca(i, c, e):  # noqa: ANN001
            await asyncio.sleep(0)
            return 1

        lg = MachineLogic(services={"svc": svca if kind == "async" else svc})
        o = Obs()
        it = await Interpreter(
            create_machine(copy.deepcopy(STORM), logic=lg)
        ).use(o).start()
        await it.send("GO")
        await asyncio.sleep(1.0)
        await it.stop()
        seq = o.seq
        idx_s = next(
            (i for i, s in enumerate(seq) if s[0] == "stranded"), None
        )
        prior_drop = (
            idx_s is not None
            and any(
                s[0] == "drop" and s[2] == "chain_budget"
                for s in seq[:idx_s]
            )
        )
        cells[f"async_engine/{kind}"] = {
            "tail": seq[-4:],
            "stranded_reported": idx_s is not None,
            "drop_precedes_stranded": prior_drop,
        }
    # SyncInterpreter lane (plain def only -- the sync engine has no
    # coroutine service kind).
    def svc(i, c, e):  # noqa: ANN001
        return 1

    o = Obs()
    s = SyncInterpreter(
        create_machine(
            copy.deepcopy(STORM), logic=MachineLogic(services={"svc": svc})
        )
    ).use(o)
    s.start()
    serr = None
    try:
        s.send("GO")
    except Exception as exc:  # noqa: BLE001
        serr = type(exc).__name__
    idx_s = next((i for i, x in enumerate(o.seq) if x[0] == "stranded"), None)
    cells["sync_engine/plain"] = {
        "tail": o.seq[-4:],
        "raised": serr,
        "stranded_reported": idx_s is not None,
        "drop_precedes_stranded": idx_s is not None
        and any(
            x[0] == "drop" and x[2] == "chain_budget" for x in o.seq[:idx_s]
        ),
        "dormant": s.has_dormant_invocations,
    }
    s.stop()
    ok = all(
        c["stranded_reported"] and c["drop_precedes_stranded"]
        for c in cells.values()
    )
    return {"ok": ok, "cells": cells}


if __name__ == "__main__":
    main("c_concurrency")
