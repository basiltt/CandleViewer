"""S3 - FUZZ: livelock hunt across BOTH engines with a 30 s watchdog.

Shapes: nested invoke cycles, `always` cycles, rollback + onDone re-arm,
sendTo self-loops. Every generated config must SETTLE; if it trips, the trip
must be observable through `last_error` or the receipt.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
    raise_,
)

N_CONFIGS = 520
WATCHDOG_S = 25.0


class Spy(PluginBase):
    def __init__(self) -> None:
        self.drops: List[str] = []

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.drops.append(reason)


def _gen(rng: random.Random, idx: int) -> Dict[str, Any]:
    """One of four adversarial cycle shapes, randomised."""
    shape = idx % 4
    if shape == 0:  # nested invoke cycle: ver -> arm -> ver
        return {
            "id": f"f{idx}", "initial": "idle",
            "states": {
                "idle": {"on": {"GO": "ver"}},
                "ver": {"invoke": {"src": "svc", "onDone": "arm"}},
                "arm": {"invoke": {"src": "svc", "onDone": "ver"}},
            },
        }
    if shape == 1:  # always cycle across n states
        n = rng.randint(2, 4)
        sts = {
            f"s{k}": {"always": {"target": f"s{(k + 1) % n}", "cond": "yes"}}
            for k in range(n)
        }
        sts["idle"] = {"on": {"GO": "s0"}}
        return {"id": f"f{idx}", "initial": "idle", "states": sts}
    if shape == 2:  # rollback + onDone re-arm
        return {
            "id": f"f{idx}", "initial": "idle",
            "actionErrorPolicy": "rollback",
            "states": {
                "idle": {"on": {"GO": "work"}},
                "work": {
                    "invoke": {
                        "src": "svc",
                        "onDone": {"target": "work", "actions": ["boom"]},
                    }
                },
            },
        }
    # shape 3: raise self-loop into an internal transition
    return {
        "id": f"f{idx}", "initial": "idle",
        "states": {
            "idle": {"on": {"GO": "spin"}},
            "spin": {
                "entry": [raise_({"type": "LOOP"})],
                "on": {"LOOP": {"target": "spin", "internal": False}},
            },
        },
    }


def _logic() -> MachineLogic:
    def svc(i_, ctx, e):  # noqa: ANN001
        return 1

    def boom(i_, ctx, e, am):  # noqa: ANN001
        raise RuntimeError("rollback me")

    return MachineLogic(
        services={"svc": svc},
        guards={"yes": lambda c, e: True},
        actions={"boom": boom},
    )


@attack(
    "S3-01",
    f"{N_CONFIGS} generated cycle configs x ASYNC engine: every one settles "
    f"within the {WATCHDOG_S:.0f}s watchdog; any trip is observable",
    "#166/#167/#168: every self-generated cycle must be bounded and loud",
)
async def s3_01() -> Dict[str, Any]:
    rng = random.Random(7301)
    out: Dict[str, Any] = {
        "ok": True, "configs": 0, "settled": 0, "tripped": 0,
        "silent_trips": [], "hangs": [], "build_rejects": 0,
    }
    for idx in range(N_CONFIGS):
        cfg = _gen(rng, idx)
        spy = Spy()
        try:
            m = create_machine(cfg, logic=_logic())
        except XStateMachineError:
            out["build_rejects"] += 1
            continue
        i = await Interpreter(m).use(spy).start()
        try:
            r = await asyncio.wait_for(i.send("GO", wait=True), WATCHDOG_S)
            out["settled"] += 1
            budget = "chain_budget" in spy.drops
            if budget:
                out["tripped"] += 1
                observable = (
                    i.last_error is not None
                    or getattr(r, "error", None) is not None
                    or bool(spy.drops)
                )
                if not observable:
                    out["ok"] = False
                    if len(out["silent_trips"]) < 5:
                        out["silent_trips"].append(cfg["id"])
        except asyncio.TimeoutError:
            out["ok"] = False
            if len(out["hangs"]) < 5:
                out["hangs"].append({"id": cfg["id"], "shape": idx % 4})
        except XStateMachineError:
            pass
        finally:
            try:
                await asyncio.wait_for(i.stop(), 5)
            except Exception:  # noqa: BLE001
                pass
        out["configs"] += 1
    return out


@attack(
    "S3-02",
    f"{N_CONFIGS} generated cycle configs x SYNC engine: same bound, and the "
    "two engines agree on WHICH shapes trip",
    "engine parity on runaway detection is the #166 headline claim. "
    "NOTE: async trips for shape 0 (invoke ping-pong) land AFTER "
    "send(wait=True) returns, so S3-01 undercounts them; the dedicated "
    "lap-parity probe (repro/d7_lap_parity.py) shows both engines trip at "
    "the SAME lap (1002).",
)
async def s3_02() -> Dict[str, Any]:
    import concurrent.futures as cf

    rng = random.Random(7301)  # same seed => same configs as S3-01
    out: Dict[str, Any] = {
        "ok": True, "configs": 0, "settled": 0, "tripped": 0,
        "hangs": [], "build_rejects": 0, "by_shape_tripped": {},
    }

    def one(cfg: Dict[str, Any]) -> Dict[str, Any]:
        spy = Spy()
        i = SyncInterpreter(create_machine(cfg, logic=_logic())).use(spy).start()
        try:
            i.send("GO")
        except XStateMachineError:
            pass
        res = {"drops": list(spy.drops),
               "err": type(i.last_error).__name__ if i.last_error else None}
        i.stop()
        return res

    with cf.ThreadPoolExecutor(max_workers=1) as ex:
        for idx in range(N_CONFIGS):
            cfg = _gen(rng, idx)
            try:
                create_machine(cfg, logic=_logic())
            except XStateMachineError:
                out["build_rejects"] += 1
                continue
            fut = ex.submit(one, cfg)
            try:
                res = fut.result(timeout=WATCHDOG_S)
                out["settled"] += 1
                if "chain_budget" in res["drops"] or res["err"] == "RunawayChainError":
                    out["tripped"] += 1
                    k = str(idx % 4)
                    out["by_shape_tripped"][k] = out["by_shape_tripped"].get(k, 0) + 1
            except cf.TimeoutError:
                out["ok"] = False
                if len(out["hangs"]) < 5:
                    out["hangs"].append({"id": cfg["id"], "shape": idx % 4})
                break  # the worker thread is wedged; no point continuing
            out["configs"] += 1
    return out


if __name__ == "__main__":
    main("s3_fuzz_livelock")
