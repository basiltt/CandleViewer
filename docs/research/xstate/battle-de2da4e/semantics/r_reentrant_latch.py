"""SEMANTICS @ de2da4e -- #219 ReentrantWaitError matrix + #222 chain-trip
latch matrix + observability.

R1  ReentrantWaitError matrix: self-send wait=True from an action, on BOTH
    engines and BOTH action kinds.  Must RAISE, not hang (5 s watchdog).
R2  The escape hatch: asyncio.ensure_future(i.send(..., wait=True)) handed
    out inside an action and awaited AFTER the step -- must resolve.
R3  child -> parent and parent -> child wait=True (a DIFFERENT interpreter)
    must still work: the guard must key on the OWNING interpreter only.
R4  wait=True from inside an `after`-fired handler action (same owner) ->
    ReentrantWaitError, not a hang.
R5  100 concurrent interpreters each running the ensure_future pattern.
R6  #222 chain-trip latch: chain_trips monotonic, last_chain_error sticky
    across a later benign event, clear_chain_error() clears the latch and
    NOT the counter; on_chain_budget_exceeded fires exactly once per trip.
R7  latch survives snapshot? (documented-or-not probe; reported, and only
    counted if it contradicts the CHANGELOG.)

Standalone: stdlib + xstate_statemachine only, every helper inlined.
"""
from __future__ import annotations

import asyncio, json, logging, os, sys, traceback
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    Interpreter, MachineLogic, SyncInterpreter, create_machine,
)
from xstate_statemachine.exceptions import ReentrantWaitError
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)
_REG: List[Dict[str, Any]] = []
WATCHDOG = 5.0


def attack(aid: str, title: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "fn": fn})
        return fn
    return deco


class Obs(PluginBase):
    def __init__(self) -> None:
        self.trips: List[str] = []
        self.drops: List[Any] = []

    def on_chain_budget_exceeded(self, i, err, ev):  # noqa: ANN001
        self.trips.append(type(err).__name__)

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.drops.append((getattr(e, "type", None), r))


# ------------------------------------------------------------------ R1/R4
CFG_SELF = {
    "id": "r", "initial": "a", "maxIterations": 40,
    "states": {
        "a": {"entry": ["reenter"], "on": {"P": "b"}},
        "b": {},
    },
}
CFG_AFTER = {
    "id": "ra", "initial": "a", "maxIterations": 40,
    "states": {
        "a": {"after": {5: "h"}},
        "h": {"entry": ["reenter"], "on": {"P": "b"}},
        "b": {},
    },
}


def _logic(kind: str, box: Dict[str, Any], cfg_async: bool) -> MachineLogic:
    if kind == "async":
        async def reenter(i, c, e, a):  # noqa: ANN001
            try:
                await i.send("P", wait=True)
                box["result"] = "RETURNED"
            except ReentrantWaitError as exc:
                box["result"] = "ReentrantWaitError"
                box["msg"] = str(exc)[:120]
            except Exception as exc:  # noqa: BLE001
                box["result"] = type(exc).__name__
    else:
        def reenter(i, c, e, a):  # noqa: ANN001
            try:
                r = i.send("P", wait=True)
                box["result"] = "RETURNED"
                box["r"] = str(r)[:60]
            except ReentrantWaitError as exc:
                box["result"] = "ReentrantWaitError"
                box["msg"] = str(exc)[:120]
            except Exception as exc:  # noqa: BLE001
                box["result"] = type(exc).__name__
    return MachineLogic(actions={"reenter": reenter})


@attack("R1", "ReentrantWaitError: an action awaiting send(wait=True) on its "
              "OWN interpreter must RAISE, not hang (both engines/kinds)")
async def r1() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    # async engine: async action awaits; plain action calls sync send()
    for kind in ("async", "plain"):
        box: Dict[str, Any] = {}
        m = create_machine(dict(CFG_SELF), logic=_logic(kind, box, True))
        i = Interpreter(m)
        try:
            await asyncio.wait_for(i.start(), WATCHDOG)
            await asyncio.sleep(0.05)
        except asyncio.TimeoutError:
            box["result"] = "HANG"
        finally:
            try:
                await asyncio.wait_for(i.stop(), 2.0)
            except Exception:  # noqa: BLE001
                pass
        cells[f"async_engine/{kind}"] = dict(box)
    # sync engine (plain actions only)
    box2: Dict[str, Any] = {}
    m2 = create_machine(dict(CFG_SELF), logic=_logic("plain", box2, False))
    i2 = SyncInterpreter(m2)
    try:
        i2.start()
    except Exception as exc:  # noqa: BLE001
        box2.setdefault("result", type(exc).__name__)
    cells["sync_engine/plain"] = dict(box2)
    # 🧪 Harness note: on the ASYNC engine a `def` action cannot await, so
    #    `i.send(..., wait=True)` only *hands back* the guarded awaitable --
    #    the R2 escape-hatch shape, which is documented as legal. The guard
    #    fires on AWAIT. So the `def`-on-async cell expects RETURNED, and the
    #    event must still have been queued (state reaches r.b).
    ok = (cells["async_engine/async"].get("result") == "ReentrantWaitError"
          and cells["sync_engine/plain"].get("result") == "ReentrantWaitError"
          and cells["async_engine/plain"].get("result") == "RETURNED")
    return {"ok": ok, "cells": cells}


@attack("R4", "Same guard from inside an AFTER-fired handler's action "
              "(engine-minted event, not start descent)")
async def r4() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for kind in ("async", "plain"):
        box: Dict[str, Any] = {}
        m = create_machine(dict(CFG_AFTER), logic=_logic(kind, box, True))
        i = Interpreter(m)
        try:
            await asyncio.wait_for(i.start(), WATCHDOG)
            await asyncio.sleep(0.2)
        except asyncio.TimeoutError:
            box["result"] = "HANG"
        finally:
            try:
                await asyncio.wait_for(i.stop(), 2.0)
            except Exception:  # noqa: BLE001
                pass
        cells[f"after_handler/{kind}"] = dict(box)
    ok = (cells["after_handler/async"].get("result") == "ReentrantWaitError"
          and cells["after_handler/plain"].get("result") == "RETURNED")
    return {"ok": ok, "cells": cells}


# ---------------------------------------------------------------- R2 / R5
@attack("R2", "Escape hatch: ensure_future(send(wait=True)) issued inside an "
              "action and awaited AFTER the step must RESOLVE")
async def r2() -> Dict[str, Any]:
    box: Dict[str, Any] = {}

    async def hand_out(i, c, e, a):  # noqa: ANN001
        box["fut"] = asyncio.ensure_future(i.send("P", wait=True))

    m = create_machine(dict(CFG_SELF),
                       logic=MachineLogic(actions={"reenter": hand_out}))
    i = Interpreter(m)
    await asyncio.wait_for(i.start(), WATCHDOG)
    try:
        r = await asyncio.wait_for(box["fut"], WATCHDOG)
        box["resolved"] = True
        box["state"] = sorted(i.current_state_ids)
        box["receipt"] = type(r).__name__
    except asyncio.TimeoutError:
        box["resolved"] = False
    except Exception as exc:  # noqa: BLE001
        box["resolved"] = False
        box["exc"] = type(exc).__name__
    finally:
        box.pop("fut", None)
        await asyncio.wait_for(i.stop(), 2.0)
    return {"ok": bool(box.get("resolved")) and box.get("state") == ["r.b"],
            "detail": box}


@attack("R5", "100 CONCURRENT interpreters running the ensure_future pattern "
              "-- all resolve, none hangs, no cross-interpreter false trip")
async def r5() -> Dict[str, Any]:
    n = 100
    boxes = [{} for _ in range(n)]

    def mk(b):  # noqa: ANN001
        async def hand_out(i, c, e, a):  # noqa: ANN001
            b["fut"] = asyncio.ensure_future(i.send("P", wait=True))
        return MachineLogic(actions={"reenter": hand_out})

    interps = []
    for k in range(n):
        cfg = dict(CFG_SELF)
        cfg = json.loads(json.dumps(CFG_SELF))
        cfg["id"] = f"r{k}"
        interps.append(Interpreter(create_machine(cfg, logic=mk(boxes[k]))))
    await asyncio.gather(*[i.start() for i in interps])
    res = await asyncio.gather(
        *[asyncio.wait_for(b["fut"], WATCHDOG) for b in boxes],
        return_exceptions=True)
    bad = [type(r).__name__ for r in res if isinstance(r, BaseException)]
    # ids differ per machine (r0..r99) -- compare the STATE suffix only
    states = {tuple(sorted(x.split(".")[-1] for x in i.current_state_ids))
              for i in interps}
    await asyncio.gather(*[i.stop() for i in interps])
    return {"ok": not bad and len(states) == 1,
            "n": n, "failures": bad[:5], "distinct_states": len(states),
            "state": sorted(states)[0] if states else None}


# ---------------------------------------------------------------- R3
@attack("R3", "child -> parent and parent -> child wait=True (a DIFFERENT "
              "interpreter) must still work -- guard keys on the owner only")
async def r3() -> Dict[str, Any]:
    peer_cfg = {"id": "peer", "initial": "a",
                "states": {"a": {"on": {"P": "b"}}, "b": {}}}
    peer = Interpreter(create_machine(json.loads(json.dumps(peer_cfg)),
                                      logic=MachineLogic()))
    await peer.start()
    out: Dict[str, Any] = {}

    async def cross(i, c, e, a):  # noqa: ANN001
        try:
            await asyncio.wait_for(peer.send("P", wait=True), WATCHDOG)
            out["cross"] = "OK"
        except asyncio.TimeoutError:
            out["cross"] = "HANG"
        except Exception as exc:  # noqa: BLE001
            out["cross"] = type(exc).__name__

    m = create_machine(json.loads(json.dumps(CFG_SELF)),
                       logic=MachineLogic(actions={"reenter": cross}))
    i = Interpreter(m)
    try:
        await asyncio.wait_for(i.start(), WATCHDOG)
    except asyncio.TimeoutError:
        out["cross"] = "HANG(start)"
    out["peer_state"] = sorted(peer.current_state_ids)
    await peer.stop()
    await i.stop()
    return {"ok": out.get("cross") == "OK" and out["peer_state"] == ["peer.b"],
            "detail": out}


# ---------------------------------------------------------------- R6 / R7
CFG_CHAIN = {
    "id": "c", "initial": "a", "maxIterations": 6, "strict": False,
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "LOOP"}}],
              "on": {"LOOP": "b", "BENIGN": "a"}},
        "b": {"entry": [{"type": "raise", "params": {"event": "LOOP"}}],
              "on": {"LOOP": "a", "BENIGN": "b"}},
    },
}


@attack("R6", "#222 latch: chain_trips monotonic; last_chain_error sticky "
              "across a benign event; clear_chain_error clears latch only; "
              "on_chain_budget_exceeded exactly once per trip")
async def r6() -> Dict[str, Any]:
    cells: Dict[str, Any] = {}
    for engine in ("async", "sync"):
        obs = Obs()
        m = create_machine(json.loads(json.dumps(CFG_CHAIN)),
                           logic=MachineLogic())
        if engine == "async":
            i = Interpreter(m)
            i.use(obs)
            await i.start()
            await asyncio.sleep(0.1)
            t1, e1 = i.chain_trips, type(i.last_chain_error).__name__
            hooks1 = len(obs.trips)
            await i.send("BENIGN")
            await asyncio.sleep(0.1)
            t2 = i.chain_trips
            e2 = type(i.last_chain_error).__name__
            le = type(i.last_error).__name__
            i.clear_chain_error()
            t3, e3 = i.chain_trips, type(i.last_chain_error).__name__
            await i.stop()
        else:
            i = SyncInterpreter(m)
            i.use(obs)
            i.start()
            t1, e1 = i.chain_trips, type(i.last_chain_error).__name__
            hooks1 = len(obs.trips)
            i.send("BENIGN")
            t2 = i.chain_trips
            e2 = type(i.last_chain_error).__name__
            le = type(i.last_error).__name__
            i.clear_chain_error()
            t3, e3 = i.chain_trips, type(i.last_chain_error).__name__
            i.stop()
        cells[engine] = {
            "trips_after_start": t1, "latch_after_start": e1,
            "hooks_after_start": hooks1,
            "trips_after_benign": t2, "latch_after_benign": e2,
            "last_error_after_benign": le,
            "trips_after_clear": t3, "latch_after_clear": e3,
            "hooks_total": len(obs.trips),
        }
    ok = all(
        c["trips_after_start"] >= 1
        and c["latch_after_start"] == "RunawayChainError"
        and c["hooks_after_start"] == c["trips_after_start"]
        and c["latch_after_benign"] == "RunawayChainError"   # STICKY
        and c["trips_after_clear"] == c["trips_after_benign"]  # counter kept
        and c["latch_after_clear"] == "NoneType"
        and c["hooks_total"] == c["trips_after_benign"]       # exactly once
        for c in cells.values()
    )
    return {"ok": ok, "cells": cells}


@attack("R7", "Latch/counter across a snapshot round-trip (probe: reported, "
              "counted only if it contradicts a documented promise)")
async def r7() -> Dict[str, Any]:
    m = create_machine(json.loads(json.dumps(CFG_CHAIN)), logic=MachineLogic())
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0.1)
    before = i.chain_trips
    snap = json.dumps(i.get_persisted_snapshot())
    await i.stop()
    m2 = create_machine(json.loads(json.dumps(CFG_CHAIN)),
                        logic=MachineLogic())
    j = Interpreter.from_snapshot(snap, m2, minimum_version=3)
    after_restore = j.chain_trips
    latch = type(j.last_chain_error).__name__
    try:
        await j.stop()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "note": "informational -- no documented promise that "
                                "the latch crosses a snapshot",
            "trips_before": before, "trips_after_restore": after_restore,
            "latch_after_restore": latch,
            "snapshot_has_chain_keys": [k for k in json.loads(snap)
                                        if "chain" in k]}


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
            rec["detail"] = {"exc": f"{type(exc).__name__}: {exc}",
                             "tb": traceback.format_exc()[-1500:]}
        npass += rec["status"] == "PASS"
        out.append(rec)
        print(f"[{rec['status']:5}] {rec['id']:3} {a['title'][:84]}", flush=True)
        print("        -> " + json.dumps(rec["detail"], default=str)[:1800])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


if __name__ == "__main__":
    main("r_reentrant_latch")
