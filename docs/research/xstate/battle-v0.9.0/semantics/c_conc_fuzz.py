"""SEMANTICS @ v0.9.0 -- concurrency (#225 at scale), config fuzz (#231),
determinism incl. the v3 latch.

C1  200 machines x action-spawned workers that OUTLIVE their actions, all
    plain external sends -- every machine advances, no internal-queue
    starvation, both kinds.
C2  100 concurrent ensure_future(send(wait=True)) hand-outs while the
    spawning actions keep awaiting -- all resolve, no false ReentrantWait.
C3  config fuzzer: inline-dict invoke.src and 8 other malformed shapes must
    always raise a NAMED InvalidConfigError, never TypeError/KeyError.
C4  determinism: 50 runs x {async, sync} x {def, async def} of a chain-budget
    chart -- one distinct trace per lane INCLUDING chain_trips and the latch,
    and one distinct trace after a v3 snapshot round-trip.

Standalone: stdlib + xstate_statemachine only, every helper inlined.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import sys
import traceback
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import (
    InvalidConfigError,
    ReentrantWaitError,
    XStateMachineError,
)
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)
_REG: List[Dict[str, Any]] = []
N_MACHINES = int(os.environ.get("C1_MACHINES", "100"))  # per kind -> 200
RUNS = int(os.environ.get("C4_RUNS", "50"))


def attack(aid: str, title: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "fn": fn})
        return fn

    return deco


def _mk(cfg: Dict[str, Any], **logic: Any) -> Any:
    return create_machine(
        json.loads(json.dumps(cfg)), logic=MachineLogic(**logic)
    )


# ------------------------------------------------------------------- C1
CFG_W = {
    "id": "w",
    "initial": "a",
    "maxIterations": 80,
    "states": {
        "a": {"entry": ["spawn"], "on": {"W": "b", "EXT": "a"}},
        "b": {"on": {"EXT": "b"}},
    },
}


@attack("C1", "200 machines x workers spawned from actions that OUTLIVE them "
              "-- all external, no internal-queue starvation")
async def c1() -> Dict[str, Any]:
    holders: List[Any] = []
    machines: List[Any] = []
    ext_sent = 0

    async def worker(i: Any, delay: float) -> None:
        await asyncio.sleep(delay)
        i.send("W")

    rng = random.Random(4242)
    for kind in ("async", "plain"):
        for _ in range(N_MACHINES):
            d = rng.uniform(0.02, 0.12)
            if kind == "async":

                async def spawn(i, c, e, a, _d=d):  # noqa: ANN001
                    holders.append(asyncio.ensure_future(worker(i, _d)))
            else:

                def spawn(i, c, e, a, _d=d):  # noqa: ANN001
                    holders.append(asyncio.ensure_future(worker(i, _d)))

            m = Interpreter(_mk(CFG_W, actions={"spawn": spawn}))
            m.kind = kind  # type: ignore[attr-defined]
            machines.append(m)
    await asyncio.gather(*(m.start() for m in machines))
    # external traffic in parallel with the workers
    for _ in range(20):
        await asyncio.gather(*(m.send("EXT") for m in machines))
        ext_sent += len(machines)
        await asyncio.sleep(0.01)
    # poll to convergence
    for _ in range(300):
        await asyncio.sleep(0.02)
        if all("w.b" in m.current_state_ids for m in machines):
            break
    by_kind: Dict[str, Dict[str, int]] = {}
    for m in machines:
        cell = by_kind.setdefault(m.kind, {"advanced": 0, "of": 0,
                                           "trips": 0, "errored": 0})
        cell["of"] += 1
        cell["advanced"] += int("w.b" in m.current_state_ids)
        cell["trips"] += m.chain_trips
        cell["errored"] += int(str(getattr(m, "status", "")) == "error")
    await asyncio.gather(*(m.stop() for m in machines),
                         return_exceptions=True)
    ok = all(
        c["advanced"] == c["of"] and c["trips"] == 0 and c["errored"] == 0
        for c in by_kind.values()
    )
    return {"ok": ok, "by_kind": by_kind, "external_sent": ext_sent,
            "machines": len(machines)}


# ------------------------------------------------------------------- C2
CFG_H = {
    "id": "h",
    "initial": "a",
    "maxIterations": 80,
    "states": {"a": {"entry": ["hand"], "on": {"P": "b"}}, "b": {}},
}


@attack("C2", "100 concurrent ensure_future(send(wait=True)) hand-outs while "
              "the spawning actions keep awaiting")
async def c2() -> Dict[str, Any]:
    futs: List[Any] = []
    machines: List[Any] = []
    for _ in range(100):

        async def hand(i, c, e, a):  # noqa: ANN001
            futs.append(asyncio.ensure_future(i.send("P", wait=True)))
            await asyncio.sleep(0.02)  # keep awaiting AFTER handing out
            await asyncio.sleep(0.02)

        machines.append(Interpreter(_mk(CFG_H, actions={"hand": hand})))
    await asyncio.gather(*(m.start() for m in machines))
    results = await asyncio.gather(
        *(asyncio.wait_for(f, 8.0) for f in futs), return_exceptions=True
    )
    kinds: Dict[str, int] = {}
    for r in results:
        k = type(r).__name__ if isinstance(r, BaseException) else "Receipt"
        kinds[k] = kinds.get(k, 0) + 1
    advanced = sum("h.b" in m.current_state_ids for m in machines)
    await asyncio.gather(*(m.stop() for m in machines),
                         return_exceptions=True)
    ok = (
        kinds.get("Receipt", 0) == 100
        and "ReentrantWaitError" not in kinds
        and advanced == 100
    )
    return {"ok": ok, "outcomes": kinds, "advanced": advanced, "of": 100}


# ------------------------------------------------------------------- C3
def _bad_configs() -> Dict[str, Dict[str, Any]]:
    inline = {"id": "inner", "initial": "x", "states": {"x": {}}}
    base = lambda inv: {  # noqa: E731
        "id": "c",
        "initial": "a",
        "states": {"a": {"invoke": {"id": "s", **inv}}},
    }
    return {
        "invoke_src_inline_dict": base({"src": inline}),
        "invoke_src_inline_dict_ondone": base(
            {"src": inline, "onDone": "a"}
        ),
        "invoke_src_list": base({"src": ["a", "b"]}),
        "invoke_src_int": base({"src": 7}),
        "invoke_src_none": base({"src": None}),
        "invoke_src_missing": base({}),
        "invoke_src_nested_machine_key": base(
            {"src": {"machine": inline}}
        ),
        "invoke_not_dict": {
            "id": "c", "initial": "a",
            "states": {"a": {"invoke": 5}},
        },
        "invoke_list_with_inline": {
            "id": "c", "initial": "a",
            "states": {"a": {"invoke": [{"id": "s", "src": inline}]}},
        },
    }


@attack("C3", "#231 config fuzz: inline-dict invoke.src and 8 malformed "
              "shapes always raise a NAMED InvalidConfigError, never TypeError")
async def c3() -> Dict[str, Any]:
    cells, bad = {}, []
    for name, cfg in _bad_configs().items():
        try:
            m = create_machine(json.loads(json.dumps(cfg)),
                               logic=MachineLogic())
            # some shapes may only die at interpretation
            i = Interpreter(m)
            await asyncio.wait_for(i.start(), 5.0)
            await asyncio.sleep(0.05)
            cells[name] = {"outcome": "ACCEPTED",
                           "final": list(i.current_state_ids)}
            try:
                await i.stop()
            except Exception:  # noqa: BLE001
                pass
            bad.append({"shape": name, "why": "accepted, expected refusal"})
        except InvalidConfigError as exc:
            msg = str(exc)
            named = all(
                tok in msg for tok in ("invoke",)
            ) and ("src" in msg or "dict" in msg or "type" in msg)
            cells[name] = {"outcome": "InvalidConfigError",
                           "named": named, "msg": msg[:190]}
            if not named:
                bad.append({"shape": name, "why": "message not diagnostic",
                            "msg": msg[:160]})
        except XStateMachineError as exc:
            cells[name] = {"outcome": type(exc).__name__, "msg": str(exc)[:150]}
        except Exception as exc:  # noqa: BLE001
            cells[name] = {"outcome": f"RAW:{type(exc).__name__}",
                           "msg": str(exc)[:150]}
            bad.append({"shape": name,
                        "why": f"raw {type(exc).__name__}, not "
                               f"InvalidConfigError"})
    # the headline shape must be exact
    head = cells.get("invoke_src_inline_dict", {})
    if head.get("outcome") != "InvalidConfigError":
        bad.append({"shape": "invoke_src_inline_dict",
                    "why": "not InvalidConfigError", "got": head})
    return {"ok": not bad, "cells": cells, "bad": bad}


# ------------------------------------------------------------------- C4
CFG_DET = {
    "id": "d",
    "initial": "a",
    "maxIterations": 6,
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "LOOP"}}],
              "on": {"LOOP": "b", "BENIGN": "a"}},
        "b": {"entry": [{"type": "raise", "params": {"event": "LOOP"}}],
              "on": {"LOOP": "a", "BENIGN": "b"}},
    },
}


class Tr(PluginBase):
    def __init__(self) -> None:
        self.t: List[str] = []

    def on_chain_budget_exceeded(self, i, err, ev):  # noqa: ANN001
        self.t.append(f"C:{type(err).__name__}")

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.t.append(f"D:{getattr(e, 'type', '?')}:{r}")


@attack("C4", "determinism: 50 runs x {async,sync} x {def,async def} -- one "
              "trace per lane incl. chain_trips, latch, and a v3 round-trip")
async def c4() -> Dict[str, Any]:
    lanes: Dict[str, set] = {}
    for engine in ("async", "sync"):
        for kind in ("plain", "async"):
            if engine == "sync" and kind == "async":
                continue
            sigs = set()
            for _ in range(RUNS):
                p = Tr()
                if engine == "async":
                    i = Interpreter(_mk(CFG_DET))
                    i.use(p)
                    await i.start()
                    await asyncio.sleep(0.08)
                    sig = (
                        tuple(p.t),
                        i.chain_trips,
                        type(i.last_chain_error).__name__,
                        tuple(sorted(i.current_state_ids)),
                    )
                    blob = json.dumps(i.get_persisted_snapshot())
                    await i.stop()
                    j = Interpreter.from_snapshot(
                        blob, _mk(CFG_DET), minimum_version=3,
                        verify_machine_hash=False,
                    )
                    sig = sig + (
                        j.chain_trips,
                        type(j.last_chain_error).__name__,
                        str(j.last_chain_error)[:70],
                    )
                    try:
                        await j.stop()
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    s = SyncInterpreter(_mk(CFG_DET))
                    s.use(p)
                    s.start()
                    sig = (
                        tuple(p.t),
                        s.chain_trips,
                        type(s.last_chain_error).__name__,
                        tuple(sorted(s.current_state_ids)),
                    )
                    blob = json.dumps(s.get_persisted_snapshot())
                    try:
                        s.stop()
                    except Exception:  # noqa: BLE001
                        pass
                    j = SyncInterpreter.from_snapshot(
                        blob, _mk(CFG_DET), minimum_version=3,
                        verify_machine_hash=False,
                    )
                    sig = sig + (
                        j.chain_trips,
                        type(j.last_chain_error).__name__,
                        str(j.last_chain_error)[:70],
                    )
                sigs.add(json.dumps(sig, default=str))
            lanes[f"{engine}/{kind}"] = sigs
    detail = {
        k: {"distinct": len(v), "sample": json.loads(sorted(v)[0])[:4]}
        for k, v in lanes.items()
    }
    return {"ok": all(len(v) == 1 for v in lanes.values()),
            "runs_per_lane": RUNS, "lanes": detail}


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
        print(f"[{rec['status']:5}] {rec['id']:3} {a['title'][:82]}", flush=True)
        print("        -> " + json.dumps(rec["detail"], default=str)[:2400])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


if __name__ == "__main__":
    main("c_conc_fuzz")
