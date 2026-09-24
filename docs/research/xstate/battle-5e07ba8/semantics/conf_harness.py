"""Dual-engine SCXML / XState-v5 conformance harness.

Every case is registered with @case(id, title, spec, expected) and receives a
`Rig` that hides the async/sync engine difference behind one small API:

    rig.boot(cfg, logic)    -> start an interpreter
    await rig.send("E")     -> send and settle
    rig.ids()               -> sorted leaf state ids
    rig.ctx()               -> context dict

The SAME case body runs twice: once on `Interpreter` (async) and once on
`SyncInterpreter`. Results are recorded per engine, so a divergence between
the two engines is visible as ASYNC=PASS / SYNC=FAIL on one row.

Cases that are inherently async-only (async services, real timers) declare
`engines=("async",)`; sync-only cases declare `engines=("sync",)`.

Output: results/<name>.json plus a printed table.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

SETTLE = 0.06

_REGISTRY: List[Dict[str, Any]] = []
RESULTS: List[Dict[str, Any]] = []


def case(
    cid: str,
    title: str,
    spec: str,
    expected: Any,
    *,
    engines: Sequence[str] = ("async", "sync"),
) -> Callable:
    """Registers a conformance case.

    Args:
        cid: Case id, e.g. "S-01".
        title: One-line description.
        spec: Citation of the normative source for `expected`.
        expected: Expected observed value (any JSON-able), or a dict keyed by
            engine name when the two engines legitimately differ.
        engines: Which engines to run on.
    """

    def deco(fn: Callable) -> Callable:
        _REGISTRY.append(
            {
                "id": cid,
                "title": title,
                "spec": spec,
                "expected": expected,
                "engines": tuple(engines),
                "fn": fn,
            }
        )
        return fn

    return deco


def _norm(v: Any) -> Any:
    if isinstance(v, (set, frozenset)):
        return sorted(_norm(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    return v


class Rig:
    """Engine-agnostic driver for one case run."""

    def __init__(self, engine: str) -> None:
        self.engine = engine
        self.interp: Any = None
        self.log: List[str] = []

    # -- construction ------------------------------------------------------
    def machine(self, cfg: Dict[str, Any], logic: MachineLogic) -> Any:
        return create_machine(cfg, logic=logic)

    async def boot(
        self, cfg: Dict[str, Any], logic: MachineLogic, **kw: Any
    ) -> Any:
        m = create_machine(cfg, logic=logic)
        return await self.boot_machine(m, **kw)

    async def boot_machine(self, m: Any, **kw: Any) -> Any:
        if self.engine == "async":
            self.interp = await Interpreter(m, **kw).start()
        else:
            self.interp = SyncInterpreter(m, **kw).start()
        await self.settle()
        return self.interp

    # -- driving -----------------------------------------------------------
    async def send(self, ev: Any, **payload: Any) -> Any:
        if self.engine == "async":
            r = await self.interp.send(ev, **payload)
        else:
            r = self.interp.send(ev, **payload)
        await self.settle()
        return r

    async def send_wait(self, ev: Any, **payload: Any) -> Any:
        if self.engine == "async":
            r = await self.interp.send(ev, wait=True, **payload)
        else:
            r = self.interp.send(ev, wait=True, **payload)
        await self.settle()
        return r

    async def settle(self, n: float = SETTLE) -> None:
        if self.engine == "async":
            await asyncio.sleep(n)
        else:
            # Sync engine answers inline; give real timers a chance and pump.
            await asyncio.sleep(0)
            if self.interp is not None and self.interp.status == "running":
                self.interp.tick()

    async def sleep(self, n: float) -> None:
        """Real-time wait, then pump the sync engine's timer lane."""
        await asyncio.sleep(n)
        if self.engine == "sync":
            if self.interp is not None and self.interp.status == "running":
                self.interp.tick()

    async def stop(self) -> None:
        if self.interp is None:
            return
        try:
            if self.engine == "async":
                await self.interp.stop()
            else:
                self.interp.stop()
        except Exception:  # noqa: BLE001
            pass

    # -- observation -------------------------------------------------------
    def ids(self) -> List[str]:
        return sorted(self.interp.current_state_ids)

    def leaves(self) -> List[str]:
        """State ids with the machine-id prefix stripped, for readability."""
        root = self.interp.machine.id + "."
        return sorted(
            s[len(root) :] if s.startswith(root) else s
            for s in self.interp.current_state_ids
        )

    def ctx(self) -> Dict[str, Any]:
        return dict(self.interp.context)

    def rec(self, name: str) -> Callable:
        def fn(i: Any, c: Any, e: Any, a: Any) -> None:
            self.log.append(name)

        return fn

    def recorders(self, *names: str) -> Dict[str, Callable]:
        return {n: self.rec(n) for n in names}


async def _run_one(rec: Dict[str, Any], engine: str) -> Dict[str, Any]:
    exp = rec["expected"]
    if isinstance(exp, dict) and set(exp) <= {"async", "sync"} and exp:
        exp = exp[engine]
    out: Dict[str, Any] = {
        "id": rec["id"],
        "engine": engine,
        "title": rec["title"],
        "spec": rec["spec"],
        "expected": _norm(exp),
    }
    rig = Rig(engine)
    try:
        res = rec["fn"](rig)
        if inspect.isawaitable(res):
            res = await asyncio.wait_for(res, timeout=25)
        obs = _norm(res)
        out["observed"] = obs
        out["status"] = "PASS" if obs == out["expected"] else "FAIL"
    except Exception as exc:  # noqa: BLE001
        out["observed"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc()[-1500:]
        out["status"] = "ERROR"
    finally:
        await rig.stop()
    return out


def run_all(name: str, only: Optional[str] = None) -> None:
    async def _main() -> None:
        for rec in _REGISTRY:
            if only and not rec["id"].startswith(only):
                continue
            for eng in rec["engines"]:
                RESULTS.append(await _run_one(rec, eng))

    asyncio.run(_main())
    here = os.path.dirname(os.path.abspath(__file__))
    rdir = os.path.join(here, "results")
    os.makedirs(rdir, exist_ok=True)
    with open(
        os.path.join(rdir, f"{name}.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(RESULTS, f, indent=2, default=str)

    for r in RESULTS:
        print(f"[{r['status']:5}] {r['id']:7} {r['engine']:5} {r['title']}")
        if r["status"] != "PASS":
            print(f"          spec    : {r['spec']}")
            print(
                f"          expected: {json.dumps(r['expected'], default=str)}"
            )
            print(
                f"          observed: {json.dumps(r['observed'], default=str)}"
            )
    n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
    print(f"\n{name}: {n_pass}/{len(RESULTS)} PASS")
    sys.stdout.flush()
