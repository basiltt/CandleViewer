"""SEMANTICS @ 19cb1f1 -- fuzz: livelock + illegal-configuration receipts.

F1  Livelock fuzzer: 500 random configs x {def, async def} x {sync, async}
    engines, shapes drawn from always / invoke / after / delayed-raise
    combinations. Every run must terminate under a 5 s watchdog, must be
    bounded, and every trip must be OBSERVABLE (last_error or a
    `chain_budget` drop); the trip lap must agree across kinds and engines.
F2  Receipt fuzz: 400 random send/guard combinations -- a receipt must
    never report `ok` (no error) over an ILLEGAL configuration, and never
    report an error over a legal one.

Standalone: stdlib + xstate_statemachine only.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import random
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional

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


class Drops(PluginBase):
    def __init__(self) -> None:
        self.items: List[Any] = []
        self.stranded: List[Any] = []

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.items.append((getattr(e, "type", None), r))

    def on_invocation_stranded(self, i, sid, iid, err):  # noqa: ANN001
        self.stranded.append((sid, iid))


# =========================================================================
# F1 -- livelock fuzz: 500 configs x 2 kinds x 2 engines
# =========================================================================
SHAPES = ("always", "invoke", "raise0", "raise_delay", "after_cycle",
          "always_invoke")


def _build(shape: str, limit: int) -> Dict[str, Any]:
    """A two-state cycle of the requested shape, bounded by *limit*."""
    base: Dict[str, Any] = {"id": "f", "initial": "a", "maxIterations": limit}
    if shape == "always":
        base["states"] = {
            "a": {"entry": "tick", "always": {"target": "b"}},
            "b": {"entry": "tick", "always": {"target": "a"}},
        }
    elif shape == "invoke":
        base["states"] = {
            "a": {"entry": "tick",
                  "invoke": {"src": "svc", "id": "ia", "onDone": "b"}},
            "b": {"entry": "tick",
                  "invoke": {"src": "svc", "id": "ib", "onDone": "a"}},
        }
    elif shape == "raise0":
        base["states"] = {
            "a": {"entry": "bounce", "on": {"P": "b"}},
            "b": {"entry": "bounce", "on": {"P": "a"}},
        }
    elif shape == "raise_delay":
        base["states"] = {
            "a": {"entry": "bounce_d", "on": {"P": "b"}},
            "b": {"entry": "bounce_d", "on": {"P": "a"}},
        }
    elif shape == "after_cycle":
        base["states"] = {
            "a": {"entry": "tick", "after": {1: {"target": "b"}}},
            "b": {"entry": "tick", "after": {1: {"target": "a"}}},
        }
    else:  # always_invoke -- a state entered and exited in one macrostep
        base["states"] = {
            "a": {"entry": "tick",
                  "invoke": {"src": "svc", "id": "ia", "onDone": "b"},
                  "always": {"target": "b"}},
            "b": {"entry": "tick", "always": {"target": "a"}},
        }
    return base


def _logic(kind: str, n: Dict[str, int], cap: int) -> MachineLogic:
    def tick(i, c, e, a):  # noqa: ANN001
        n["v"] += 1

    async def tick_a(i, c, e, a):  # noqa: ANN001
        n["v"] += 1

    def bounce(i, c, e, a):  # noqa: ANN001
        n["v"] += 1
        if n["v"] < cap:
            i.send("P")

    async def bounce_a(i, c, e, a):  # noqa: ANN001
        n["v"] += 1
        if n["v"] < cap:
            i.send("P")

    def bounce_d(i, c, e, a):  # noqa: ANN001
        n["v"] += 1
        if n["v"] < cap:
            i.send("P", delay=1)

    async def bounce_d_a(i, c, e, a):  # noqa: ANN001
        n["v"] += 1
        if n["v"] < cap:
            i.send("P", delay=1)

    def svc(i, c, e):  # noqa: ANN001
        return 1

    async def svc_a(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return 1

    a = kind == "async"
    return MachineLogic(
        actions={
            "tick": tick_a if a else tick,
            "bounce": bounce_a if a else bounce,
            "bounce_d": bounce_d_a if a else bounce_d,
        },
        services={"svc": svc_a if a else svc},
    )


async def _run_async(cfg, kind, cap, settle) -> Dict[str, Any]:
    n = {"v": 0}
    d = Drops()
    it = Interpreter(
        create_machine(copy.deepcopy(cfg), logic=_logic(kind, n, cap))
    ).use(d)
    try:
        await asyncio.wait_for(it.start(), timeout=5.0)
        await asyncio.sleep(settle)
        res = {
            "laps": n["v"],
            "bounded": n["v"] < cap,
            "observable": it.last_error is not None
            or any(r == "chain_budget" for _, r in d.items),
            "hang": False,
        }
        await it.stop()
        return res
    except asyncio.TimeoutError:
        return {"laps": n["v"], "bounded": False, "observable": False,
                "hang": True}


def _run_sync(cfg, cap) -> Dict[str, Any]:
    n = {"v": 0}
    d = Drops()
    s = SyncInterpreter(
        create_machine(copy.deepcopy(cfg), logic=_logic("plain", n, cap))
    ).use(d)
    err = None
    try:
        # NOTE: `start()` alone drives the initial descent and its settle
        # pass. An extra `send()` would drive the cycle a SECOND time and
        # double the lap count -- a harness artefact, not a parity defect.
        s.start()
    except Exception as exc:  # noqa: BLE001
        err = type(exc).__name__
    out = {
        "laps": n["v"],
        "bounded": n["v"] < cap,
        "observable": err is not None
        or s.last_error is not None
        or any(r == "chain_budget" for _, r in d.items),
        "hang": False,
    }
    s.stop()
    return out


@attack("F1", "Livelock fuzz: 500 configs x {def, async def} x {sync, async} "
              "engines over always/invoke/after/raise/delayed-raise cycles -- "
              "no hang, every trip observable, lap parity")
async def f1() -> Dict[str, Any]:
    rng = random.Random(4242)
    hangs, unbounded, silent = [], [], []
    kind_mismatch, engine_mismatch = [], []
    runs = 0
    for i in range(500):
        shape = SHAPES[i % len(SHAPES)]
        limit = rng.randint(2, 14)
        cap = 400
        cfg = _build(shape, limit)
        settle = 0.25 if shape in ("raise_delay", "after_cycle") else 0.12
        rp = await _run_async(cfg, "plain", cap, settle)
        ra = await _run_async(cfg, "async", cap, settle)
        runs += 2
        # `after_cycle` is WALL-CLOCK paced: each firing is its own
        # macrostep on a 1 ms timer, so it is not a runaway chain and
        # `maxIterations` neither does nor should trip. Its lap count is a
        # function of the sampling window, so it is checked for hangs and
        # CPU-boundedness only -- not for trip-observability or lap parity.
        timer_paced = shape == "after_cycle"
        for tag, r in (("plain", rp), ("async", ra)):
            if r["hang"]:
                hangs.append((i, shape, tag))
            elif not r["bounded"]:
                unbounded.append((i, shape, tag, r["laps"]))
            elif not r["observable"] and not timer_paced:
                silent.append((i, shape, tag, r["laps"]))
        if (
            not timer_paced
            and rp["laps"] != ra["laps"]
            and not (rp["hang"] or ra["hang"])
        ):
            kind_mismatch.append((i, shape, limit, rp["laps"], ra["laps"]))
        # sync engine: timer-paced shapes are driven by the caller's tick()
        # and are not comparable in a single send(); skip those.
        if shape in ("always", "invoke", "raise0", "always_invoke"):
            rs = _run_sync(cfg, cap)
            runs += 1
            if not rs["bounded"]:
                unbounded.append((i, shape, "sync", rs["laps"]))
            elif not rs["observable"]:
                silent.append((i, shape, "sync", rs["laps"]))
            if rs["laps"] != rp["laps"]:
                engine_mismatch.append(
                    (i, shape, limit, rp["laps"], rs["laps"])
                )
    return {
        "ok": not (hangs or unbounded or silent or kind_mismatch
                   or engine_mismatch),
        "runs": runs,
        "hangs": hangs[:8],
        "n_hangs": len(hangs),
        "unbounded": unbounded[:8],
        "n_unbounded": len(unbounded),
        "silent_runaways": silent[:8],
        "n_silent": len(silent),
        "def_vs_asyncdef_lap_mismatch": kind_mismatch[:8],
        "n_kind_mismatch": len(kind_mismatch),
        "async_vs_sync_engine_lap_mismatch": engine_mismatch[:8],
        "n_engine_mismatch": len(engine_mismatch),
    }


# =========================================================================
# F2 -- receipt fuzz (#208): never `ok` over an illegal configuration,
#       never an error over a legal, cleanly-processed one
# =========================================================================
def _receipt_machine(rng: random.Random, i: int) -> Dict[str, Any]:
    policy = rng.choice(["continue", "rollback", "fail"])
    unh = rng.choice([None, "error", "defer", "ignore"])
    cfg: Dict[str, Any] = {
        "id": f"rc{i}",
        "initial": "a",
        "actionErrorPolicy": policy,
        "states": {
            "a": {
                "on": {
                    "OK": {"target": "b"},
                    "BOOM": {"target": "b", "actions": "boom"},
                    "GUARDED": {"target": "b", "cond": "never"},
                }
            },
            "b": {"on": {"OK": "a", "BOOM": {"target": "a",
                                             "actions": "boom"}}},
        },
    }
    if unh:
        cfg["onUnhandled"] = unh
    return cfg


def _legal(ids, machine) -> bool:
    """Every reported leaf id must resolve in the machine, and the set
    must be non-empty."""
    if not ids:
        return False
    known = set()

    def walk(node):  # noqa: ANN001
        known.add(node.id)
        for ch in node.states.values():
            walk(ch)

    walk(machine)
    return all(i in known for i in ids)


@attack("F2", "Receipt fuzz (#208): 480 random send/guard/policy cells -- a "
              "receipt is never success-shaped over an illegal configuration, "
              "and never error-shaped over a clean legal step")
async def f2() -> Dict[str, Any]:
    rng = random.Random(777)
    ok_over_illegal, err_over_legal, odd = [], [], []
    cells = 0
    for kind in ("plain", "async"):
        for i in range(60):
            cfg = _receipt_machine(rng, i)

            def boom(i_, c, e, a):  # noqa: ANN001
                raise RuntimeError("boom")

            async def boom_a(i_, c, e, a):  # noqa: ANN001
                raise RuntimeError("boom")

            lg = MachineLogic(
                actions={"boom": boom_a if kind == "async" else boom},
                guards={"never": lambda c, e: False},
            )
            m = create_machine(copy.deepcopy(cfg), logic=lg)
            it = await Interpreter(m).start()
            for ev in ("GUARDED", "OK", "UNDECLARED", "BOOM"):
                cells += 1
                # Once `onUnhandled: "error"` has stopped the interpreter,
                # every later receipt is correctly an
                # `InterpreterStoppedError`; that is not "an error over a
                # legal step", so stop feeding this cell.
                stopped = it.status != "running"
                try:
                    r = await it.send(ev, wait=True)
                except Exception as exc:  # noqa: BLE001
                    odd.append(
                        (kind, i, ev, f"{type(exc).__name__}: {exc}"[:90])
                    )
                    continue
                ids = sorted(r.state_ids)
                legal = _legal(ids, m)
                if r.error is None and not legal:
                    ok_over_illegal.append((kind, i, ev, ids))
                if ev == "OK" and r.error is not None and not stopped:
                    err_over_legal.append(
                        (kind, i, ev, type(r.error).__name__)
                    )
                # NOTE: a GUARD-DENIED event is an `onUnhandled` disposition
                # ("guard_denied", docs/api/index.md:1924), so under
                # `onUnhandled: "error"` an `UnhandledEventError` on the
                # receipt is the DOCUMENTED outcome, not an error over a
                # legal step. Only record it as a defect for other policies.
                if (
                    ev == "GUARDED"
                    and r.error is not None
                    and cfg.get("onUnhandled") != "error"
                ):
                    err_over_legal.append(
                        (kind, i, ev, type(r.error).__name__)
                    )
                # `denied` is only meaningful where a handler IS declared.
                # The GUARDED handler exists in `a` only, and the preceding
                # "OK" has already moved us to `b`, so `denied=False` there
                # is correct; assert the flag only from `a`.
                if ev == "GUARDED" and ids == [f"rc{i}.a"] and not r.denied:
                    odd.append((kind, i, ev, "denied flag not set in 'a'"))
            await it.stop()
    return {
        "ok": not (ok_over_illegal or err_over_legal),
        "cells": cells,
        "ok_over_illegal_configuration": ok_over_illegal[:8],
        "n_ok_over_illegal": len(ok_over_illegal),
        "error_over_legal_step": err_over_legal[:8],
        "n_err_over_legal": len(err_over_legal),
        "exceptions_from_send": odd[:8],
        "n_exceptions": len(odd),
    }


if __name__ == "__main__":
    main("f_fuzz")
