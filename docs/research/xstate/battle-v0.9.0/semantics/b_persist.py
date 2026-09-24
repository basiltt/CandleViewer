"""SEMANTICS @ v0.9.0 -- persistence: #226 latch round-trip, #227 strict on
restored scheduled_sends, #230 from_snapshot(plugins=), #233 sync priority.

B1  v3 latch round-trip: chain_trips monotonic across N restarts, the
    RestoredError message intact and byte-stable; clear_chain_error() still
    clears only the latch; old (v3-without-chain-keys) blobs upcast to 0/None.
B2  #227 property, 300 cases: a strict machine restored with a mix of
    declared / undeclared records across BOTH lanes (pending_events and
    scheduled_sends) -- refusals are reported, armed count is right, and the
    machine is CONSISTENT afterwards (starts, advances, no armed residue).
B3  #230: from_snapshot(plugins=) receives every restore-time hook exactly
    once -- on_invalid_event fires for the refused records, and not twice.
B4  #233: a `lane: "priority"` record restores at the HEAD of the sync
    engine's single queue, matching the async engine's ordering.
B5  security/trust boundary: forge chain_trips / last_chain_error in a v3
    blob (framing probe -- only filed if a boundary is crossed), and try to
    bypass `strict` through the scheduled_sends lane.

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
from xstate_statemachine.exceptions import RestoredError
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)
_REG: List[Dict[str, Any]] = []


def attack(aid: str, title: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        _REG.append({"id": aid, "title": title, "fn": fn})
        return fn

    return deco


class Obs(PluginBase):
    def __init__(self) -> None:
        self.invalid: List[str] = []
        self.trips: List[str] = []
        self.events: List[str] = []

    def on_invalid_event(self, i, exc, event=None, **kw):  # noqa: ANN001
        self.invalid.append(
            f"{type(exc).__name__}:{getattr(event, 'type', event)}"
        )

    def on_chain_budget_exceeded(self, i, err, ev):  # noqa: ANN001
        self.trips.append(type(err).__name__)

    def on_event_received(self, i, event):  # noqa: ANN001
        self.events.append(getattr(event, "type", "?"))


def _mk(cfg: Dict[str, Any], **logic: Any) -> Any:
    return create_machine(
        json.loads(json.dumps(cfg)), logic=MachineLogic(**logic)
    )


# --------------------------------------------------------------- charts
CFG_CHAIN = {
    "id": "ch",
    "initial": "a",
    "maxIterations": 6,
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "T"}}],
              "on": {"T": "b"}},
        "b": {"entry": [{"type": "raise", "params": {"event": "T"}}],
              "on": {"T": "a"}},
    },
}
# same state ids, no chain: restoring here mints no NEW trip
CFG_IDLE = {
    "id": "ch",
    "initial": "a",
    "maxIterations": 6,
    "states": {"a": {"on": {"T": "b"}}, "b": {"on": {"T": "a"}}},
}


# ------------------------------------------------------------------- B1
@attack("B1", "#226: chain_trips monotonic across N restarts, RestoredError "
              "message intact, clear clears only the latch, legacy upcast")
async def b1() -> Dict[str, Any]:
    i = Interpreter(_mk(CFG_CHAIN))
    await i.start()
    await asyncio.sleep(0.15)
    first_trips = i.chain_trips
    first_msg = str(i.last_chain_error)
    snap = json.dumps(i.get_persisted_snapshot())
    await i.stop()

    blob = json.loads(snap)
    keys_present = {
        k: blob.get(k) for k in ("chain_trips", "last_chain_error")
    }

    hops: List[Dict[str, Any]] = []
    cur = snap
    for n in range(5):
        # restore into an IDLE chart so no new trip is minted by the restart
        j = Interpreter.from_snapshot(cur, _mk(CFG_IDLE), minimum_version=3,
                                      verify_machine_hash=False)
        hops.append(
            {
                "hop": n,
                "trips": j.chain_trips,
                "latch_type": type(j.last_chain_error).__name__,
                "latch_msg": str(j.last_chain_error)[:90],
            }
        )
        cur = json.dumps(j.get_persisted_snapshot())
        try:
            await j.stop()
        except Exception:  # noqa: BLE001
            pass

    monotonic = all(h["trips"] == first_trips for h in hops)
    msg_stable = len({h["latch_msg"] for h in hops}) == 1
    typed = all(h["latch_type"] == "RestoredError" for h in hops)
    msg_intact = all(
        first_msg[:60] in h["latch_msg"] or h["latch_msg"] in first_msg
        for h in hops
    )

    # clear_chain_error on a restored latch: clears latch, keeps counter
    k = Interpreter.from_snapshot(snap, _mk(CFG_IDLE), minimum_version=3,
                                  verify_machine_hash=False)
    k.clear_chain_error()
    cleared = {"latch": k.last_chain_error, "trips": k.chain_trips}
    try:
        await k.stop()
    except Exception:  # noqa: BLE001
        pass

    # a legacy v3 blob with the keys ABSENT must upcast to 0 / None
    legacy = json.loads(snap)
    legacy.pop("chain_trips", None)
    legacy.pop("last_chain_error", None)
    g = Interpreter.from_snapshot(json.dumps(legacy), _mk(CFG_IDLE),
                                  minimum_version=3,
                                  verify_machine_hash=False)
    legacy_cell = {"trips": g.chain_trips, "latch": g.last_chain_error}
    try:
        await g.stop()
    except Exception:  # noqa: BLE001
        pass

    # a NEW trip after a restore must be previous + 1
    h = Interpreter.from_snapshot(snap, _mk(CFG_CHAIN), minimum_version=3,
                                  verify_machine_hash=False)
    await h.start()
    await asyncio.sleep(0.05)
    # a restore is STATIC (no entry re-run), so drive a fresh chain by hand
    await h.send("T")
    await asyncio.sleep(0.15)
    after_new = h.chain_trips
    await h.stop()

    ok = (
        first_trips >= 1
        and monotonic
        and msg_stable
        and typed
        and msg_intact
        and cleared["latch"] is None
        and cleared["trips"] == first_trips
        and legacy_cell == {"trips": 0, "latch": None}
        and after_new == first_trips + 1
    )
    return {
        "ok": ok,
        "first_trips": first_trips,
        "first_msg": first_msg[:90],
        "snapshot_keys": keys_present,
        "hops": hops,
        "monotonic": monotonic,
        "msg_stable": msg_stable,
        "restored_type_is_RestoredError": typed,
        "after_clear": {"latch": str(cleared["latch"]),
                        "trips": cleared["trips"]},
        "legacy_upcast": {"trips": legacy_cell["trips"],
                          "latch": str(legacy_cell["latch"])},
        "trips_after_new_trip": after_new,
    }


# ------------------------------------------------------------------- B2
CFG_STRICT = {
    "id": "st",
    "initial": "a",
    "strict": True,
    "maxIterations": 40,
    "states": {"a": {"on": {"KNOWN": "b", "TICK": "a"}}, "b": {}},
}


def _blob_with(records_pending: List[Dict[str, Any]],
               records_sched: List[Dict[str, Any]],
               base: Dict[str, Any]) -> str:
    b = json.loads(json.dumps(base))
    b["pending_events"] = records_pending
    b["scheduled_sends"] = records_sched
    return json.dumps(b)


@attack("B2", "#227 property (300 cases): strict refusal on BOTH restore "
              "lanes leaves a consistent machine; armed count is right")
async def b2() -> Dict[str, Any]:
    base_i = Interpreter(_mk(CFG_STRICT))
    await base_i.start()
    base = base_i.get_persisted_snapshot()
    await base_i.stop()

    rng = random.Random(9090)
    DECL = ["KNOWN", "TICK"]
    UNDECL = ["NOPE", "GHOST", "XX"]
    bad: List[Dict[str, Any]] = []
    N = 300
    stats = {"refused": 0, "armed": 0, "cases": 0}
    for case in range(N):
        n_p = rng.randint(0, 3)
        n_s = rng.randint(0, 3)
        pend, sched = [], []
        exp_refuse = 0
        for _ in range(n_p):
            declared = rng.random() < 0.5
            t = rng.choice(DECL if declared else UNDECL)
            pend.append({"type": t, "payload": {}, "version": 3})
            exp_refuse += int(not declared)
        exp_armed = 0
        for k in range(n_s):
            declared = rng.random() < 0.5
            t = rng.choice(DECL if declared else UNDECL)
            sched.append(
                {
                    "type": t,
                    "payload": {},
                    "version": 3,
                    "remaining_ms": float(rng.randint(1, 20)),
                    "send_id": f"s{case}_{k}",
                }
            )
            exp_refuse += int(not declared)
            exp_armed += int(declared)
        obs = Obs()
        blob = _blob_with(pend, sched, base)
        try:
            j = Interpreter.from_snapshot(
                blob, _mk(CFG_STRICT), minimum_version=3,
                verify_machine_hash=False, plugins=[obs],
            )
        except Exception as exc:  # noqa: BLE001
            bad.append({"case": case, "why": f"restore raised "
                                             f"{type(exc).__name__}: {exc}"})
            continue
        try:
            await asyncio.wait_for(j.start(), 5.0)
            await asyncio.sleep(0.06)
        except Exception as exc:  # noqa: BLE001
            bad.append({"case": case, "why": f"start raised "
                                             f"{type(exc).__name__}"})
            try:
                await j.stop()
            except Exception:  # noqa: BLE001
                pass
            continue
        n_ref = len(obs.invalid)
        armed_left = len(getattr(j, "_armed_self_sends", {}) or {})
        parked = len(getattr(j, "_restored_self_sends", []) or [])
        # consistency: machine alive, no undeclared type ever transitioned,
        # every refusal reported, no residue
        alive = str(getattr(j, "status", "")) in ("running", "done")
        saw_undecl = [e for e in obs.events if e in UNDECL]
        if n_ref != exp_refuse:
            bad.append({"case": case, "why": "refusal count",
                        "exp": exp_refuse, "got": n_ref,
                        "invalid": obs.invalid})
        if saw_undecl:
            bad.append({"case": case, "why": "undeclared transitioned",
                        "got": saw_undecl})
        if not alive:
            bad.append({"case": case, "why": "machine not alive",
                        "status": str(j.status)})
        if armed_left or parked:
            bad.append({"case": case, "why": "armed residue",
                        "armed": armed_left, "parked": parked})
        stats["refused"] += n_ref
        stats["armed"] += exp_armed
        stats["cases"] += 1
        try:
            await j.stop()
        except Exception:  # noqa: BLE001
            pass
    return {"ok": not bad, "cases": N, "stats": stats,
            "bad_n": len(bad), "bad": bad[:6]}


# ------------------------------------------------------------------- B3
@attack("B3", "#230: from_snapshot(plugins=) gets every restore-time hook "
              "EXACTLY once (and .use() after restore gets zero)")
async def b3() -> Dict[str, Any]:
    base_i = Interpreter(_mk(CFG_STRICT))
    await base_i.start()
    base = base_i.get_persisted_snapshot()
    await base_i.stop()
    blob = _blob_with(
        [{"type": "NOPE", "payload": {}, "version": 3}],
        [{"type": "GHOST", "payload": {}, "version": 3,
          "remaining_ms": 5.0, "send_id": "g1"}],
        base,
    )
    # via plugins=
    p = Obs()
    j = Interpreter.from_snapshot(blob, _mk(CFG_STRICT), minimum_version=3,
                                  verify_machine_hash=False, plugins=[p])
    at_restore = list(p.invalid)
    await j.start()
    await asyncio.sleep(0.06)
    after_start = list(p.invalid)
    await j.stop()

    # duplicate registration: plugins= AND .use() -- must not double-fire
    p2 = Obs()
    j2 = Interpreter.from_snapshot(blob, _mk(CFG_STRICT), minimum_version=3,
                                   verify_machine_hash=False, plugins=[p2])
    n_after_restore = len(p2.invalid)
    await j2.start()
    await asyncio.sleep(0.06)
    n2 = len(p2.invalid)
    await j2.stop()

    # via .use() AFTER restore (the pre-#230 route): must MISS the pending one
    p3 = Obs()
    j3 = Interpreter.from_snapshot(blob, _mk(CFG_STRICT), minimum_version=3,
                                   verify_machine_hash=False)
    j3.use(p3)
    late_at_restore = list(p3.invalid)
    await j3.start()
    await asyncio.sleep(0.06)
    late_after_start = list(p3.invalid)
    await j3.stop()

    ok = (
        at_restore == ["UnknownEventError:NOPE"]
        and after_start == ["UnknownEventError:NOPE",
                            "UnknownEventError:GHOST"]
        and n_after_restore == 1
        and n2 == 2
        and late_at_restore == []
        and late_after_start == ["UnknownEventError:GHOST"]
    )
    return {
        "ok": ok,
        "plugins_kwarg": {"at_restore": at_restore,
                          "after_start": after_start},
        "late_use": {"at_restore": late_at_restore,
                     "after_start": late_after_start},
        "exactly_once": {"restore_lane": n_after_restore, "both_lanes": n2},
    }


# ------------------------------------------------------------------- B4
CFG_LANES = {
    "id": "ln",
    "initial": "a",
    "maxIterations": 60,
    "states": {
        "a": {"on": {"X": "a", "Y": "a", "Z": "a"}},
    },
}


@attack("B4", "#233: a lane:'priority' record restores at the HEAD of the "
              "sync engine's queue -- same order the async engine gives")
async def b4() -> Dict[str, Any]:
    seen_async: List[str] = []
    seen_sync: List[str] = []

    base_i = Interpreter(_mk(CFG_LANES))
    await base_i.start()
    base = base_i.get_persisted_snapshot()
    await base_i.stop()

    recs = [
        {"type": "X", "payload": {}, "version": 3, "lane": "inbox"},
        {"type": "Y", "payload": {}, "version": 3, "lane": "inbox"},
        {"type": "Z", "payload": {}, "version": 3, "lane": "priority"},
    ]
    blob = _blob_with(recs, [], base)

    class Rec(PluginBase):
        def __init__(self, sink: List[str]) -> None:
            self.sink = sink

        def on_event_received(self, i, event):  # noqa: ANN001
            self.sink.append(getattr(event, "type", "?"))

    j = Interpreter.from_snapshot(blob, _mk(CFG_LANES), minimum_version=3,
                                  verify_machine_hash=False,
                                  plugins=[Rec(seen_async)])
    await j.start()
    await asyncio.sleep(0.15)
    await j.stop()

    s = SyncInterpreter.from_snapshot(blob, _mk(CFG_LANES), minimum_version=3,
                                      verify_machine_hash=False,
                                      plugins=[Rec(seen_sync)])
    s.start()
    try:
        s.stop()
    except Exception:  # noqa: BLE001
        pass

    a_order = [e for e in seen_async if e in ("X", "Y", "Z")]
    s_order = [e for e in seen_sync if e in ("X", "Y", "Z")]
    return {
        "ok": a_order == ["Z", "X", "Y"] and s_order == a_order,
        "async_order": a_order,
        "sync_order": s_order,
        "expected": ["Z", "X", "Y"],
    }


# ------------------------------------------------------------------- B5
@attack("B5", "trust boundary: forged chain_trips / last_chain_error in a v3 "
              "blob, and strict bypass via the scheduled_sends lane")
async def b5() -> Dict[str, Any]:
    base_i = Interpreter(_mk(CFG_IDLE))
    await base_i.start()
    base = base_i.get_persisted_snapshot()
    await base_i.stop()

    forged = json.loads(json.dumps(base))
    forged["chain_trips"] = 999999
    forged["last_chain_error"] = "TOTALLY FORGED"
    j = Interpreter.from_snapshot(json.dumps(forged), _mk(CFG_IDLE),
                                  minimum_version=3,
                                  verify_machine_hash=False)
    forged_cell = {
        "trips": j.chain_trips,
        "latch_type": type(j.last_chain_error).__name__,
        "latch_msg": str(j.last_chain_error)[:60],
    }
    await j.stop()

    # can a forged latch make anything FATAL / change control flow?
    k = Interpreter.from_snapshot(json.dumps(forged), _mk(CFG_IDLE),
                                  minimum_version=3,
                                  verify_machine_hash=False)
    await k.start()
    await asyncio.sleep(0.05)
    await k.send("T")
    await asyncio.sleep(0.05)
    still_running = str(k.status)
    final = list(k.current_state_ids)
    await k.stop()

    # strict bypass attempts through the scheduled lane
    b_i = Interpreter(_mk(CFG_STRICT))
    await b_i.start()
    sbase = b_i.get_persisted_snapshot()
    await b_i.stop()
    attempts: Dict[str, Any] = {}
    variants = {
        "plain_undeclared": {"type": "NOPE", "payload": {}, "version": 3,
                             "remaining_ms": 2.0},
        "engine_flagged": {"type": "NOPE", "payload": {}, "version": 3,
                           "engine": True, "remaining_ms": 2.0},
        "done_shape": {"type": "done.invoke.ghost", "payload": {},
                       "version": 3, "remaining_ms": 2.0},
        "v2_upcast": {"type": "NOPE", "payload": {}, "version": 2,
                      "remaining_ms": 2.0},
    }
    for name, rec in variants.items():
        obs = Obs()
        try:
            m = Interpreter.from_snapshot(
                _blob_with([], [rec], sbase), _mk(CFG_STRICT),
                minimum_version=0, verify_machine_hash=False, plugins=[obs],
            )
            await m.start()
            await asyncio.sleep(0.06)
            attempts[name] = {
                "refused": bool(obs.invalid),
                "invalid": obs.invalid,
                "transitions": obs.events,
                "final": list(m.current_state_ids),
            }
            await m.stop()
        except Exception as exc:  # noqa: BLE001
            attempts[name] = {"exc": f"{type(exc).__name__}: {exc}"[:120]}

    return {
        "ok": True,  # framing probe; verdict written in the report
        "forged_latch": forged_cell,
        "forged_does_not_break_flow": {"status": still_running,
                                       "final": final},
        "strict_bypass_attempts": attempts,
        "note": "a party with full blob control is inside the documented "
                "trust boundary (from_snapshot docstring #205); filed only "
                "if a non-blob-controlling party can cross it",
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
        print("        -> " + json.dumps(rec["detail"], default=str)[:2400])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


if __name__ == "__main__":
    main("b_persist")
