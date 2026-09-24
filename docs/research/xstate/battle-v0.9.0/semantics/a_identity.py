"""SEMANTICS @ v0.9.0 -- #225 task-identity provenance + #232 RuntimeWarning.

A1  Task-identity matrix: for each shape, is the send treated as INTERNAL
    (self-send, drained in the macrostep) or EXTERNAL (ordinary traffic)?
    shapes: action->send, action->helper-coro->send (same task),
    action->ensure_future(task)->send, action->task->task->send,
    def-service->send, child-action->parent.send, after-handler->send.
A2  #225 headline: a worker spawned from an action that OUTLIVES the action
    must be ordinary external traffic -- with the loop idle the machine must
    still advance (round-11 shape hung).
A3  The hand-out idiom ensure_future(i.send(..., wait=True)) must resolve
    whether or not the spawning action awaits again afterwards.
A4  The genuine in-step await is still refused (ReentrantWaitError).
A5  #232 RuntimeWarning: a def action that drops its wait=True receipt warns;
    ensure_future / add_done_callback / result() / await keep it silent.
A6  #232 under `-W error` inside asyncio: WHERE does it surface?

Standalone: stdlib + xstate_statemachine only, every helper inlined.
"""
from __future__ import annotations

import asyncio
import gc
import json
import logging
import os
import sys
import traceback
import warnings
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import ReentrantWaitError

logging.disable(logging.CRITICAL)
_REG: List[Dict[str, Any]] = []
WATCHDOG = 8.0


def attack(aid: str, title: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "fn": fn})
        return fn

    return deco


# ---------------------------------------------------------------- charts
CFG = {
    "id": "a",
    "initial": "a",
    "maxIterations": 60,
    "states": {"a": {"entry": ["go"], "on": {"P": "b"}}, "b": {}},
}
CFG_AFTER = {
    "id": "aa",
    "initial": "a",
    "maxIterations": 60,
    "states": {
        "a": {"after": {5: "h"}},
        "h": {"entry": ["go"], "on": {"P": "b"}},
        "b": {},
    },
}
CFG_PLAIN = {
    "id": "p",
    "initial": "a",
    "maxIterations": 60,
    "states": {"a": {"on": {"P": "b"}}, "b": {}},
}


def _mk(cfg: Dict[str, Any], **logic: Any) -> Any:
    return create_machine(
        json.loads(json.dumps(cfg)), logic=MachineLogic(**logic)
    )


async def _drive(i: Any, settle: float = 0.25) -> None:
    await asyncio.wait_for(i.start(), WATCHDOG)
    await asyncio.sleep(settle)


async def _kill(i: Any) -> None:
    try:
        await asyncio.wait_for(i.stop(), 3.0)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------- A1
# An INTERNAL self-send is drained inside the macrostep: with the event loop
# otherwise idle it still lands. An EXTERNAL send goes through the public
# queue: it lands too, but only after the pump turns. Both land at v0.9.0, so
# we distinguish by the `wait=True` guard, which is the one observable that
# differs: refused => "internal/in-step", resolves => "external".
async def _probe_shape(shape: str) -> Dict[str, Any]:
    box: Dict[str, Any] = {"shape": shape, "verdict": None}

    async def _send_wait(i: Any) -> None:
        try:
            await asyncio.wait_for(i.send("P", wait=True), 3.0)
            box["verdict"] = "EXTERNAL(resolved)"
        except ReentrantWaitError:
            box["verdict"] = "INTERNAL(refused)"
        except asyncio.TimeoutError:
            box["verdict"] = "HANG"
        except Exception as exc:  # noqa: BLE001
            box["verdict"] = f"ERR:{type(exc).__name__}"

    if shape == "action_direct":

        async def go(i, c, e, a):  # noqa: ANN001
            await _send_wait(i)

        i = Interpreter(_mk(CFG, actions={"go": go}))
        await _drive(i)

    elif shape == "action_helper_same_task":

        async def helper(i: Any) -> None:
            await asyncio.sleep(0)
            await _send_wait(i)

        async def go(i, c, e, a):  # noqa: ANN001
            await helper(i)  # awaited inline -> SAME task

        i = Interpreter(_mk(CFG, actions={"go": go}))
        await _drive(i)

    elif shape == "action_spawned_task":
        holder: Dict[str, Any] = {}

        async def worker(i: Any) -> None:
            await asyncio.sleep(0.05)  # outlive the action
            await _send_wait(i)

        async def go(i, c, e, a):  # noqa: ANN001
            holder["t"] = asyncio.ensure_future(worker(i))

        i = Interpreter(_mk(CFG, actions={"go": go}))
        await _drive(i, 0.4)

    elif shape == "action_task_task":
        holder = {}

        async def inner(i: Any) -> None:
            await asyncio.sleep(0.02)
            await _send_wait(i)

        async def outer(i: Any) -> None:
            await asyncio.sleep(0.02)
            holder["u"] = asyncio.ensure_future(inner(i))
            await holder["u"]

        async def go(i, c, e, a):  # noqa: ANN001
            holder["t"] = asyncio.ensure_future(outer(i))

        i = Interpreter(_mk(CFG, actions={"go": go}))
        await _drive(i, 0.5)

    elif shape == "def_service":
        # a `def` (sync) service run on the executor sends back
        def svc(i, c, e):  # noqa: ANN001
            try:
                r = i.send("P")
                box["verdict"] = f"EXTERNAL(def-service:{type(r).__name__})"
            except Exception as exc:  # noqa: BLE001
                box["verdict"] = f"ERR:{type(exc).__name__}"
            return {"done": True}

        cfg = {
            "id": "ds",
            "initial": "a",
            "maxIterations": 60,
            "states": {
                "a": {
                    "invoke": {"id": "s", "src": "svc", "onDone": "d"},
                    "on": {"P": "b"},
                },
                "b": {},
                "d": {},
            },
        }
        i = Interpreter(_mk(cfg, services={"svc": svc}))
        await _drive(i, 0.5)
        box["final"] = list(i.current_state_ids)

    elif shape == "after_handler":

        async def go(i, c, e, a):  # noqa: ANN001
            await _send_wait(i)

        i = Interpreter(_mk(CFG_AFTER, actions={"go": go}))
        await _drive(i, 0.4)

    elif shape == "child_action_to_peer":
        peer = Interpreter(_mk(CFG_PLAIN))
        await peer.start()

        async def go(i, c, e, a):  # noqa: ANN001
            try:
                await asyncio.wait_for(peer.send("P", wait=True), 3.0)
                box["verdict"] = "EXTERNAL(resolved)"
            except ReentrantWaitError:
                box["verdict"] = "INTERNAL(refused)"
            except asyncio.TimeoutError:
                box["verdict"] = "HANG"

        i = Interpreter(_mk(CFG, actions={"go": go}))
        await _drive(i, 0.4)
        box["peer_final"] = list(peer.current_state_ids)
        await _kill(peer)
    else:  # pragma: no cover
        raise AssertionError(shape)

    box["final"] = box.get("final") or list(i.current_state_ids)
    await _kill(i)
    return box


SHAPES = [
    "action_direct",
    "action_helper_same_task",
    "action_spawned_task",
    "action_task_task",
    "def_service",
    "after_handler",
    "child_action_to_peer",
]
EXPECT = {
    "action_direct": "INTERNAL(refused)",
    "action_helper_same_task": "INTERNAL(refused)",
    "action_spawned_task": "EXTERNAL(resolved)",
    "action_task_task": "EXTERNAL(resolved)",
    "after_handler": "INTERNAL(refused)",
    "child_action_to_peer": "EXTERNAL(resolved)",
}


@attack("A1", "task-identity matrix: which shapes are in-step (refused) vs "
              "ordinary external traffic (resolved)")
async def a1() -> Dict[str, Any]:
    cells, bad = {}, []
    for s in SHAPES:
        try:
            r = await asyncio.wait_for(_probe_shape(s), 25.0)
        except asyncio.TimeoutError:
            r = {"shape": s, "verdict": "HANG"}
        cells[s] = r
        exp = EXPECT.get(s)
        if exp and r.get("verdict") != exp:
            bad.append({"shape": s, "expected": exp, "got": r.get("verdict")})
        if r.get("verdict") == "HANG":
            bad.append({"shape": s, "expected": "no hang", "got": "HANG"})
    return {"ok": not bad, "cells": cells, "bad": bad}


# ------------------------------------------------------------------- A2
@attack("A2", "#225: a worker spawned from an action OUTLIVING it is external "
              "-- machine advances with the loop idle (200x, both kinds)")
async def a2() -> Dict[str, Any]:
    res: Dict[str, Any] = {}
    for kind in ("async", "plain"):
        advanced, holders = 0, []
        N = 100
        for _ in range(N):
            async def worker(i: Any) -> None:
                await asyncio.sleep(0.01)
                i.send("P")  # plain send, no wait

            if kind == "async":

                async def go(i, c, e, a):  # noqa: ANN001
                    holders.append(asyncio.ensure_future(worker(i)))
            else:

                def go(i, c, e, a):  # noqa: ANN001
                    holders.append(asyncio.ensure_future(worker(i)))

            i = Interpreter(_mk(CFG, actions={"go": go}))
            await asyncio.wait_for(i.start(), WATCHDOG)
            # poll to convergence, loop otherwise idle
            for _ in range(200):
                await asyncio.sleep(0.01)
                if "a.b" in i.current_state_ids:
                    break
            advanced += int("a.b" in i.current_state_ids)
            await _kill(i)
        res[kind] = {"advanced": advanced, "of": N}
    ok = all(v["advanced"] == v["of"] for v in res.values())
    return {"ok": ok, "by_kind": res}


# ------------------------------------------------------------------- A3
@attack("A3", "#225: ensure_future(send(wait=True)) hand-out resolves whether "
              "or not the spawning action awaits afterwards")
async def a3() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for yields in (False, True):
        box: Dict[str, Any] = {}

        async def go(i, c, e, a):  # noqa: ANN001
            box["fut"] = asyncio.ensure_future(i.send("P", wait=True))
            if yields:
                await asyncio.sleep(0.02)  # the action awaits AFTER handing out

        i = Interpreter(_mk(CFG, actions={"go": go}))
        await _drive(i, 0.1)
        try:
            r = await asyncio.wait_for(box["fut"], 3.0)
            box["result"] = f"OK:{type(r).__name__}"
        except ReentrantWaitError as exc:
            box["result"] = f"ReentrantWaitError:{str(exc)[:80]}"
        except asyncio.TimeoutError:
            box["result"] = "HANG"
        box["final"] = list(i.current_state_ids)
        box.pop("fut", None)
        await _kill(i)
        cells[f"action_yields_after={yields}"] = box
    ok = all(
        c["result"].startswith("OK") and "a.b" in c["final"]
        for c in cells.values()
    )
    return {"ok": ok, "cells": cells}


# ------------------------------------------------------------------- A4
@attack("A4", "the genuine in-step await is STILL refused (both engines)")
async def a4() -> Dict[str, Any]:
    box: Dict[str, Any] = {}

    async def go(i, c, e, a):  # noqa: ANN001
        try:
            await i.send("P", wait=True)
            box["async_engine"] = "RETURNED"
        except ReentrantWaitError:
            box["async_engine"] = "ReentrantWaitError"

    i = Interpreter(_mk(CFG, actions={"go": go}))
    await _drive(i, 0.15)
    await _kill(i)

    def go_s(i, c, e, a):  # noqa: ANN001
        try:
            i.send("P", wait=True)
            box["sync_engine"] = "RETURNED"
        except ReentrantWaitError:
            box["sync_engine"] = "ReentrantWaitError"

    s = SyncInterpreter(_mk(CFG, actions={"go": go_s}))
    s.start()
    try:
        s.stop()
    except Exception:  # noqa: BLE001
        pass
    ok = (
        box.get("async_engine") == "ReentrantWaitError"
        and box.get("sync_engine") == "ReentrantWaitError"
    )
    return {"ok": ok, "cells": box}


# ------------------------------------------------------------------- A5
def _collect_warnings(fn: Callable[[], Any]) -> List[str]:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        fn()
        gc.collect()
        gc.collect()
    return [f"{c.category.__name__}: {str(c.message)[:120]}" for c in w]


@attack("A5", "#232: a def action that DROPS its wait=True receipt warns; "
              "ensure_future/callback/result/await keep it silent")
async def a5() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for use in ("drop", "ensure_future", "add_done_callback", "await_it"):
        holder: List[Any] = []

        def go(i, c, e, a):  # noqa: ANN001
            r = i.send("P", wait=True)
            if use == "ensure_future":
                holder.append(asyncio.ensure_future(r))
            elif use == "add_done_callback":
                try:
                    r.add_done_callback(lambda _f: None)
                    holder.append(r)
                except Exception as exc:  # noqa: BLE001
                    holder.append(f"ERR:{type(exc).__name__}")
            elif use == "await_it":
                holder.append(asyncio.ensure_future(_await(r)))
            # "drop": r goes out of scope unused

        async def _await(r: Any) -> Any:
            try:
                return await r
            except Exception:  # noqa: BLE001
                return None

        got: List[str] = []
        i = Interpreter(_mk(CFG, actions={"go": go}))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await _drive(i, 0.15)
            holder.clear()
            gc.collect()
            gc.collect()
            await asyncio.sleep(0.05)
            gc.collect()
            got = [
                f"{c.category.__name__}: {str(c.message)[:110]}"
                for c in w
                if c.category is RuntimeWarning
            ]
        cells[use] = {"runtime_warnings": got, "n": len(got)}
        await _kill(i)
    ok = cells["drop"]["n"] >= 1 and all(
        cells[k]["n"] == 0
        for k in ("ensure_future", "add_done_callback", "await_it")
    )
    return {"ok": ok, "cells": cells}


# ------------------------------------------------------------------- A6
@attack("A6", "#232 under -W error inside asyncio: where does the warning "
              "surface, and does it damage the machine?")
async def a6() -> Dict[str, Any]:
    def go(i, c, e, a):  # noqa: ANN001
        i.send("P", wait=True)  # dropped on purpose

    i = Interpreter(_mk(CFG, actions={"go": go}))
    raised: List[str] = []
    loop = asyncio.get_running_loop()
    heard: List[str] = []
    old = loop.get_exception_handler()
    loop.set_exception_handler(
        lambda lp, ctx: heard.append(str(ctx.get("message"))[:120])
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        try:
            await _drive(i, 0.2)
        except RuntimeWarning as exc:
            raised.append(f"from start(): {str(exc)[:110]}")
        except Exception as exc:  # noqa: BLE001
            raised.append(f"{type(exc).__name__}: {str(exc)[:110]}")
        gc.collect()
        await asyncio.sleep(0.05)
        gc.collect()
    final = list(i.current_state_ids)
    status = getattr(i, "status", None)
    await _kill(i)
    loop.set_exception_handler(old)
    return {
        "ok": True,  # observational
        "raised_to_caller": raised,
        "loop_exception_handler": heard[:3],
        "final": final,
        "status": str(status),
        "note": "machine must not be damaged by the warning",
        "machine_intact": "a.b" in final or "a.a" in final,
    }


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
        print("        -> " + json.dumps(rec["detail"], default=str)[:2200])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


if __name__ == "__main__":
    main("a_identity")
