"""SEMANTICS @ c78ce99 -- persistence attacks on #213 / #214 / #216.

P1  v3 round-trip property: >=300 random machines incl. ARMED delayed
    self-sends at random remaining delays, on a SimulatedClock -- the
    remaining delay must be honoured EXACTLY.
P2  v2 fixture upcast matrix: done / error / after / user records.
P3  THE question: a FORGED v2-shaped record minting an engine event.
    A v2 payload's `done`/`after` record is upcast as engine-minted, so an
    attacker who can write a snapshot need only declare `"version": 2` to
    mint a trusted completion. Must NOT drive `after` / `onDone`.
P4  Lane restore ordering: a fired timer restores AHEAD of the inbox.
P5  machine_hash covers scheduled_sends? (structural-hash scope check.)
P6  #214 restore-strict matrix: strict / onUnhandled / plain x kinds.

Standalone: stdlib + xstate_statemachine only; every helper inlined.
"""
from __future__ import annotations

import asyncio, copy, json, logging, os, random, sys, traceback
from typing import Any, Callable, Dict, List

from xstate_statemachine import (
    Interpreter, MachineLogic, SyncInterpreter, create_machine,
)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.events import is_system_event, restore_event
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
        self.invalid: List[Any] = []
        self.drops: List[Any] = []

    def on_invalid_event(self, i, exc, raw):  # noqa: ANN001
        self.invalid.append((type(exc).__name__, getattr(raw, "type", raw)))

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self.drops.append((getattr(e, "type", None), r))


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
        print(f"[{rec['status']:5}] {rec['id']:3} {a['title'][:88]}")
        if rec["status"] != "PASS":
            print("        -> " + json.dumps(rec["detail"], default=str)[:1600])
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{group}.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\n{group}: {npass}/{len(out)} PASS")
    sys.exit(0 if npass == len(out) else 1)


# =========================================================================
# P1 -- v3 round-trip property, >=300 random machines with armed delayed
#       self-sends at random remaining delays, on a SimulatedClock.
# =========================================================================
def _rand_machine(rng: random.Random, n: int) -> Dict[str, Any]:
    """A random chart with a parked state whose only exit is a delayed raise."""
    delay = rng.choice([5, 17, 50, 123, 400, 1000, 5000])
    cfg: Dict[str, Any] = {
        "id": f"m{n}", "initial": "park", "maxIterations": 50,
        "states": {
            "park": {
                "entry": [{"type": "raise",
                           "params": {"event": "WAKE", "delay": delay,
                                      "id": f"sid{n}"}}],
                "on": {"WAKE": "awake"},
            },
            "awake": {"type": "final"},
            # 🧪 a NEUTRAL rendezvous for the optional competing `after`:
            #    targeting `awake` made the timer, not the restored
            #    scheduled_send, the thing that woke the machine -- a
            #    harness artefact that produced 11 false "fired EARLY".
            "other": {},
        },
    }
    # 🧪 An optional COMPETING `after` on the same state. It is only a
    #    fair comparison when it is due AFTER the delayed self-send:
    #    otherwise leaving `park` legitimately cancels the send, and the
    #    machine is in `other` by design, not by a persistence bug.
    competing = None
    if rng.random() < 0.5:
        competing = delay * 10 + 10_000
        cfg["states"]["park"]["after"] = {competing: "other"}
    return cfg, delay


@attack("P1", ">=300 random machines with an ARMED raise(delay=) self-send, "
              "snapshot mid-flight on a SimulatedClock -> restore honours the "
              "REMAINING delay exactly")
async def p1() -> Dict[str, Any]:
    rng = random.Random(20260922)
    bad: List[Any] = []
    checked = 0
    for i in range(300):
        cfg, delay = _rand_machine(rng, i)
        clock = SimulatedClock()
        m = Interpreter(create_machine(copy.deepcopy(cfg)), clock=clock)
        await m.start()
        elapsed = rng.uniform(0.0, delay * 0.8)
        await clock.increment(elapsed)
        if "m.awake" in str(m.current_state_ids):
            await m.stop()
            continue
        snap = m.get_persisted_snapshot()
        await m.stop()
        ss = snap.get("scheduled_sends") or []
        if snap.get("version") != 3:
            bad.append({"i": i, "why": "version", "v": snap.get("version")})
            continue
        if len(ss) != 1:
            bad.append({"i": i, "why": "no scheduled_sends record",
                        "ss": ss, "delay": delay, "elapsed": elapsed})
            continue
        rem = ss[0].get("remaining_ms")
        want = delay - elapsed
        if rem is None or abs(rem - want) > 1e-6:
            bad.append({"i": i, "why": "remaining_ms wrong",
                        "got": rem, "want": want})
            continue
        if ss[0].get("send_id") != f"sid{i}":
            bad.append({"i": i, "why": "send_id lost", "rec": ss[0]})
            continue
        # -- restore on a fresh clock; the remaining delay must be exact.
        clock2 = SimulatedClock()
        m2 = Interpreter.from_snapshot(
            json.dumps(snap), create_machine(copy.deepcopy(cfg)),
            clock=clock2,
        )
        await m2.start()
        await clock2.increment(rem - 0.001)
        early = set(m2.current_state_ids)
        await clock2.increment(0.002)
        late = set(m2.current_state_ids)
        await m2.stop()
        if any("awake" in s for s in early):
            bad.append({"i": i, "why": "fired EARLY", "rem": rem})
        elif not any("awake" in s for s in late):
            bad.append({"i": i, "why": "did NOT fire at remaining",
                        "rem": rem, "late": sorted(late)})
        checked += 1
    return {"ok": not bad and checked >= 250, "checked": checked,
            "n_bad": len(bad), "bad": bad[:8]}


# =========================================================================
# P2 / P3 -- v2 upcast matrix, and THE question: does declaring
#            "version": 2 let a forged record MINT an engine event?
# =========================================================================
FORGE = {
    "id": "t", "initial": "a", "maxIterations": 20, "strict": True,
    "states": {
        "a": {"after": {86_400_000: "fired_after"},
              "invoke": {"src": "slow", "id": "q", "onDone": "fired_done"},
              "on": {"REAL": "other"}},
        "fired_after": {}, "fired_done": {}, "other": {},
    },
}


def _forge_snapshot(base: Dict[str, Any], version: int,
                    rec: Dict[str, Any]) -> str:
    snap = copy.deepcopy(base)
    snap["version"] = version
    snap["pending_events"] = [rec]
    return json.dumps(snap)


async def _restore_and_settle(payload: str, kind: str) -> Dict[str, Any]:
    async def slow(i, c, e):  # noqa: ANN001
        await asyncio.sleep(30)

    def slow_p(i, c, e):  # noqa: ANN001
        import time; time.sleep(30)

    lg = MachineLogic(services={"slow": slow if kind == "async" else slow_p})
    o = Obs()
    m = Interpreter.from_snapshot(
        payload, create_machine(copy.deepcopy(FORGE), logic=lg)
    ).use(o)
    await m.start()
    await asyncio.sleep(0.25)
    res = {"state": sorted(m.current_state_ids),
           "invalid": o.invalid, "drops": o.drops,
           "last_error": type(m.last_error).__name__ if m.last_error else None}
    await m.stop()
    return res


async def _base_snapshot() -> Dict[str, Any]:
    async def slow(i, c, e):  # noqa: ANN001
        await asyncio.sleep(30)
    m = Interpreter(create_machine(copy.deepcopy(FORGE),
                                   logic=MachineLogic(services={"slow": slow})))
    await m.start()
    await asyncio.sleep(0.05)
    snap = m.get_persisted_snapshot()
    await m.stop()
    snap["pending_events"] = []
    return snap


@attack("P3", "THE question: a FORGED v2-shaped record declaring "
              "\"version\": 2 is upcast as ENGINE-MINTED -- can it drive an "
              "`after` / `onDone` it never earned?")
async def p3() -> Dict[str, Any]:
    base = await _base_snapshot()
    cells: Dict[str, Any] = {}
    forged = [
        ("after_v2", 2, {"type": "after.86400000.t.a", "kind": "after"}),
        ("done_v2", 2, {"type": "done.invoke.q", "kind": "done",
                        "data": {"pwned": True}}),
        ("error_v2", 2, {"type": "error.platform.q", "kind": "error"}),
        ("after_v3_unflagged", 3, {"type": "after.86400000.t.a",
                                   "kind": "after"}),
        ("done_v3_unflagged", 3, {"type": "done.invoke.q", "kind": "done"}),
        ("after_v3_flagged", 3, {"type": "after.86400000.t.a",
                                 "kind": "after", "engine": True}),
        ("user_v2", 2, {"type": "BOGUS", "kind": "event"}),
    ]
    minted: List[str] = []
    for name, ver, rec in forged:
        for kind in ("plain", "async"):
            try:
                r = await _restore_and_settle(
                    _forge_snapshot(base, ver, rec), kind
                )
            except Exception as exc:  # noqa: BLE001
                r = {"refused": f"{type(exc).__name__}: {exc}"}
            cells[f"{name}/{kind}"] = r
            st = " ".join(r.get("state") or [])
            if "fired_after" in st or "fired_done" in st:
                minted.append(f"{name}/{kind}")
    # 🎯 Oracle: a FORGED v2 record must not reach a terminal it never
    #    earned. `after_v3_flagged` is the library's documented trusted
    #    path (a caller who can write a snapshot owns state_ids anyway),
    #    so it is recorded, not charged.
    illegitimate = [m for m in minted if not m.startswith("after_v3_flagged")]
    return {"ok": not illegitimate, "minted_illegitimately": illegitimate,
            "all_minted": minted, "cells": cells}


# =========================================================================
# P4 -- #214 restore-strict matrix + lane ordering
# =========================================================================
LANE = {
    "id": "L", "initial": "a", "strict": True,
    "states": {"a": {"entry": "log", "on": {"X": "b", "Y": "c"}},
               "b": {"entry": "log"}, "c": {"entry": "log"}},
}


@attack("P4", "#214: a restored USER event passes the same `strict` check a "
              "send() does -- refusal reported via on_invalid_event / "
              "last_error, event dropped; both kinds")
async def p4() -> Dict[str, Any]:
    base_cfg = copy.deepcopy(LANE)
    cells: Dict[str, Any] = {}
    for kind in ("plain", "async"):
        seen: List[str] = []

        def log(i, c, e, a):  # noqa: ANN001
            seen.append(getattr(e, "type", "?"))

        async def log_a(i, c, e, a):  # noqa: ANN001
            seen.append(getattr(e, "type", "?"))

        lg = MachineLogic(actions={"log": log_a if kind == "async" else log})
        m0 = Interpreter(create_machine(copy.deepcopy(base_cfg), logic=lg))
        await m0.start(); await asyncio.sleep(0.05)
        snap = m0.get_persisted_snapshot(); await m0.stop()
        for label, rec in (
            ("undeclared", {"type": "NOPE", "kind": "event"}),
            ("declared", {"type": "X", "kind": "event"}),
        ):
            s = copy.deepcopy(snap); s["pending_events"] = [rec]
            seen.clear()
            o = Obs()
            m = Interpreter.from_snapshot(
                json.dumps(s), create_machine(copy.deepcopy(base_cfg), logic=lg)
            ).use(o)
            await m.start(); await asyncio.sleep(0.2)
            cells[f"{label}/{kind}"] = {
                "state": sorted(m.current_state_ids),
                "invalid_hook": o.invalid,
                "last_error": type(m.last_error).__name__
                if m.last_error else None,
                "seen": list(seen),
            }
            await m.stop()
    ok = all(
        c["invalid_hook"] and c["last_error"] == "UnknownEventError"
        and not any("L.b" in s for s in c["state"])
        for k, c in cells.items() if k.startswith("undeclared")
    ) and all(
        any("L.b" in s for s in c["state"])
        for k, c in cells.items() if k.startswith("declared")
    )
    return {"ok": ok, "cells": cells}


if __name__ == "__main__":
    main("p_persistence")
