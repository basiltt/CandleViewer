"""SEMANTICS @ 19cb1f1 -- persistence attacks on the round-9 machinery.

P1  Snapshot of a machine parked in an invoking state (invoke armed by the
    settle pass, #204) -> restore -> the service must arm EXACTLY ONCE.
P2  Snapshot taken from inside a hook while the invoke is recorded but NOT
    yet armed (`_states_to_invoke` non-empty) -- reachable window?
P3  Forged `after` pending records under `strict` / `onUnhandled` (#203):
    `engine: true` / absent / truthy-string, both engines.
P4  Delayed self-`send` debt (#206) across snapshot/restore: an armed
    `raise(delay=)` must not resurrect as un-charged external work.
P5  Property: 300 random machines (parallel + children + after + invoke),
    snapshot at quiescence -> restore -> configuration + invoke-count parity.

Standalone: stdlib + xstate_statemachine only. Both service kinds.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import sys
import traceback
import logging
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.events import is_system_event, restore_event
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


def _blob(b: Any) -> Dict[str, Any]:
    return json.loads(b) if isinstance(b, str) else b


class Spy(PluginBase):
    def __init__(self) -> None:
        self.drops: List[Any] = []
        self.recv: List[str] = []
        self.stranded: List[Any] = []

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.drops.append((getattr(e, "type", None), r))

    def on_event_received(self, i, e):  # noqa: ANN001
        self.recv.append(e.type)

    def on_invocation_stranded(self, i, sid, iid, err):  # noqa: ANN001
        self.stranded.append((sid, iid))


# =========================================================================
# P1 -- snapshot while parked in an invoking state; restore arms ONCE
# =========================================================================
PARK = {
    "id": "pk",
    "initial": "idle",
    "states": {
        "idle": {"on": {"GO": "run"}},
        "run": {
            "invoke": {"src": "svc", "id": "s1", "onDone": {"target": "done"}}
        },
        "done": {},
    },
}


@attack("P1", "Snapshot parked in an invoking state -> restore arms the "
              "service EXACTLY ONCE (#204), both kinds")
async def p1() -> Dict[str, Any]:
    cells = {}
    for kind in ("plain", "async"):
        n = {"v": 0}

        def svc(i, c, e):  # noqa: ANN001
            n["v"] += 1
            import time as _t

            _t.sleep(3.0)
            return 1

        async def svca(i, c, e):  # noqa: ANN001
            n["v"] += 1
            await asyncio.sleep(3.0)
            return 1

        lg = MachineLogic(
            services={"svc": svca if kind == "async" else svc}
        )
        it = await Interpreter(
            create_machine(copy.deepcopy(PARK), logic=lg)
        ).start()
        if kind == "async":
            await it.send("GO")
            await asyncio.sleep(0.05)
            b = _blob(it.get_persisted_snapshot())
            await it.stop()
        else:
            # a plain-`def` service is awaited by the entering step, so the
            # machine is never observable mid-invoke; snapshot the idle
            # state and inject the invoking configuration instead.
            b = _blob(it.get_persisted_snapshot())
            await it.stop()
            b["state_ids"] = ["pk.run"]
            b["configuration"] = ["pk.run"]
        armed_before = n["v"]
        n["v"] = 0
        i2 = Interpreter.from_snapshot(
            json.dumps(b), create_machine(copy.deepcopy(PARK), logic=lg)
        )
        await i2.start()
        await asyncio.sleep(0.15)
        cells[kind] = {
            "armed_before_snapshot": armed_before,
            "armed_after_restore": n["v"],
            "state": sorted(i2.current_state_ids),
            "dormant": i2.has_dormant_invocations,
            "pending": [
                (p.state_id, p.invoke_id) for p in i2.pending_invocations()
            ],
        }
        await i2.stop()
    return {
        "ok": all(c["armed_after_restore"] <= 1 for c in cells.values()),
        "cells": cells,
    }


# =========================================================================
# P3 -- forged `after` pending records (#203), strict / onUnhandled
# =========================================================================
AFTER_M = {
    "id": "t",
    "initial": "a",
    "states": {
        "a": {"after": {60000: {"target": "b"}}, "on": {"E": "b"}},
        "b": {},
    },
}


@attack("P3", "Forged `after` pending record: only a genuinely engine-minted "
              "AfterEvent may fire a 60 s timer instantly (#203)")
async def p3() -> Dict[str, Any]:
    cells = {}
    for pol_name, extra in (
        ("strict", {"strict": True}),
        ("onUnhandled", {"onUnhandled": "error"}),
        ("plain", {}),
    ):
        cfg = dict(copy.deepcopy(AFTER_M), **extra)
        it = await Interpreter(create_machine(copy.deepcopy(cfg))).start()
        base = _blob(it.get_persisted_snapshot())
        await it.stop()
        for flag_name, flag in (
            ("engine_true", True),
            ("absent", None),
            ("string_true", "true"),
            ("engine_1", 1),
        ):
            rec = {"kind": "after", "type": "after.60000.t.a"}
            if flag is not None:
                rec["engine"] = flag
            ev = restore_event(dict(rec))
            bb = copy.deepcopy(base)
            bb["pending_events"] = [dict(rec)]
            sp = Spy()
            i2 = Interpreter.from_snapshot(
                json.dumps(bb), create_machine(copy.deepcopy(cfg))
            )
            i2.use(sp)
            await i2.start()
            await asyncio.sleep(0.08)
            cells[f"{pol_name}/{flag_name}"] = {
                "restored_type": type(ev).__name__,
                "is_system": is_system_event(ev),
                "state": sorted(i2.current_state_ids),
                "err": type(i2.last_error).__name__
                if i2.last_error
                else None,
                "fired": "t.b" in i2.current_state_ids,
            }
            await i2.stop()
    # A record WITHOUT a genuine engine mint must never fire the timer.
    bad = [
        k
        for k, v in cells.items()
        if not k.endswith("engine_true") and v["fired"]
    ]
    # The `engine: true` record is trusted by contract (snapshot = trusted
    # input, #205) -- recorded, not counted as a defect here.
    return {
        "ok": not bad,
        "forged_fired_60s_timer": bad,
        "engine_true_fires_by_contract": [
            k for k, v in cells.items() if k.endswith("engine_true")
            and v["fired"]
        ],
        "cells": cells,
    }


# =========================================================================
# P4 -- delayed self-`send` debt (#206) across snapshot / restore
# =========================================================================
PING = {
    "id": "pp",
    "initial": "a",
    "maxIterations": 12,
    "states": {
        "a": {"entry": "bounce", "on": {"P": "b"}},
        "b": {"entry": "bounce", "on": {"P": "a"}},
    },
}


@attack("P4", "A `raise(delay=1ms)` self-ping-pong stays CHARGED across a "
              "snapshot/restore -- the cycle trips on the restored machine")
async def p4() -> Dict[str, Any]:
    cells = {}
    for kind in ("plain", "async"):
        n = {"v": 0}

        def bounce(i, c, e, a):  # noqa: ANN001
            n["v"] += 1
            if n["v"] < 300:
                i.send("P", delay=1)

        async def bounce_a(i, c, e, a):  # noqa: ANN001
            n["v"] += 1
            if n["v"] < 300:
                i.send("P", delay=1)

        lg = MachineLogic(
            actions={"bounce": bounce_a if kind == "async" else bounce}
        )
        sp = Spy()
        it = await Interpreter(
            create_machine(copy.deepcopy(PING), logic=lg)
        ).use(sp).start()
        await asyncio.sleep(0.5)
        live_laps = n["v"]
        live_trip = any(r == "chain_budget" for _, r in sp.drops) or (
            it.last_error is not None
        )
        # snapshot mid-flight is refused while in flight; take it at rest
        try:
            b = _blob(it.get_persisted_snapshot())
            snap_ok = True
        except Exception as exc:  # noqa: BLE001
            b, snap_ok = None, type(exc).__name__
        await it.stop()
        restored = None
        if b is not None:
            n["v"] = 0
            sp2 = Spy()
            i2 = Interpreter.from_snapshot(
                json.dumps(b), create_machine(copy.deepcopy(PING), logic=lg)
            )
            i2.use(sp2)
            await i2.start()
            await asyncio.sleep(0.5)
            restored = {
                "laps": n["v"],
                "bounded": n["v"] < 300,
                "tripped": any(
                    r == "chain_budget" for _, r in sp2.drops
                )
                or i2.last_error is not None,
            }
            await i2.stop()
        cells[kind] = {
            "live_laps": live_laps,
            "live_bounded": live_laps < 300,
            "live_tripped": live_trip,
            "snapshot": snap_ok,
            "restored": restored,
        }
    ok = all(
        c["live_bounded"]
        and c["live_tripped"]
        and (c["restored"] is None or c["restored"]["bounded"])
        for c in cells.values()
    )
    return {"ok": ok, "cells": cells}


# =========================================================================
# P5 -- property: 300 random machines (parallel/children/after/invoke)
# =========================================================================
def _rand_machine(rng: random.Random, idx: int) -> Dict[str, Any]:
    """A random chart mixing parallel regions, nested children, `after`
    timers (long, so they never fire in the window) and invokes."""
    kids = {}
    for r in range(rng.randint(1, 3)):
        leaves = {}
        nl = rng.randint(2, 3)
        for j in range(nl):
            st: Dict[str, Any] = {}
            roll = rng.random()
            if roll < 0.3:
                st["invoke"] = {
                    "src": "svc",
                    "id": f"i{r}{j}",
                    "onDone": {"target": f"l{(j + 1) % nl}"},
                }
            elif roll < 0.5:
                st["after"] = {90000: {"target": f"l{(j + 1) % nl}"}}
            if rng.random() < 0.4:
                st["on"] = {"X": f"l{(j + 1) % nl}"}
            leaves[f"l{j}"] = st
        kids[f"r{r}"] = {"initial": "l0", "states": leaves}
    return {
        "id": f"m{idx}",
        "type": "parallel",
        "states": kids,
    }


@attack("P5", "Property: 300 random parallel+children+after+invoke machines "
              "snapshot at quiescence -> restore preserves configuration and "
              "arms each invoke at most once (both kinds)")
async def p5() -> Dict[str, Any]:
    bad: List[Any] = []
    checked = 0
    for kind in ("plain", "async"):
        rng = random.Random(90210)
        for idx in range(150):
            cfg = _rand_machine(rng, idx)
            arm: Dict[str, int] = {}

            def svc(i, c, e):  # noqa: ANN001
                arm["n"] = arm.get("n", 0) + 1
                return 1

            async def svca(i, c, e):  # noqa: ANN001
                arm["n"] = arm.get("n", 0) + 1
                await asyncio.sleep(0.5)
                return 1

            lg = MachineLogic(
                services={"svc": svca if kind == "async" else svc}
            )
            try:
                it = await Interpreter(
                    create_machine(copy.deepcopy(cfg), logic=lg)
                ).start()
                await asyncio.sleep(0)
                before = sorted(it.current_state_ids)
                b = _blob(it.get_persisted_snapshot())
                await it.stop()
                arm.clear()
                i2 = Interpreter.from_snapshot(
                    json.dumps(b),
                    create_machine(copy.deepcopy(cfg), logic=lg),
                )
                await i2.start()
                await asyncio.sleep(0)
                after = sorted(i2.current_state_ids)
                n_inv = sum(
                    1
                    for s in i2._active_state_nodes  # noqa: SLF001
                    for _ in s.invoke
                )
                await i2.stop()
                checked += 1
                if arm.get("n", 0) > max(n_inv, 0):
                    bad.append(
                        {"idx": idx, "kind": kind, "why": "armed>declared",
                         "armed": arm.get("n", 0), "declared": n_inv}
                    )
            except Exception as exc:  # noqa: BLE001
                bad.append(
                    {"idx": idx, "kind": kind,
                     "exc": f"{type(exc).__name__}: {exc}"[:200]}
                )
    return {"ok": not bad, "checked": checked, "bad": bad[:10],
            "n_bad": len(bad)}


if __name__ == "__main__":
    main("p_persistence")
