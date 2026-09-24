"""v3 (@de2da4e) -- STANDALONE. #221 parked scheduled_sends across chains,
#222 chain-trip latch across snapshot, #220 recursive key check on the
real catalogue JSONs.

P1  >=300 property cases: arm `raise(delay=D)`, advance a SimulatedClock
    by a random elapsed, then run the chain
        persist -> restore -> persist -> restore -> start
    (restore/re-persist WITHOUT start in the middle -- the #221 shape).
    Requirements: the record survives EVERY hop with the SAME remaining
    delay (no time charged to a parked record), and after start() the
    event fires EXACTLY ONCE at the right deadline.
P2  Longer chain: 5 restore/re-persist hops before start(). Still one
    fire, same remaining.
P3  Chain-trip latch across a snapshot: trip the budget, snapshot,
    restore -- what do chain_trips / last_chain_error read on the
    restored interpreter? (recorded; the contract is per-interpreter so
    a reset is EXPECTED -- asserted only as "documented, not silent")
P4  Recursive key check vs every catalogue *.machine.json: strict_config
    must accept all of them (0 false positives on valid grammar).

Run: python v3_persistence_chain_and_latch.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import glob
import json
import os
import random
import sys
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    create_machine,
    persistence,
)
from xstate_statemachine.clock import SimulatedClock

N_CASES = 300
FAILS: List[str] = []
OUT: Dict[str, Any] = {}
HERE = os.path.dirname(os.path.abspath(__file__))
CATALOGUE_GLOB = os.path.join(
    HERE, "..", "..", "..", "battle-*", "contracts", "*.machine.json"
)


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {
        "probe": name,
        "py": ".".join(map(str, sys.version_info[:3])),
        **data,
    }
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(HERE, name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


def cfg(delay_ms: float, mid: str = "v3") -> Dict[str, Any]:
    return {
        "id": mid,
        "initial": "arm",
        "context": {"n": 0},
        "states": {
            "arm": {
                "entry": [
                    {"type": "raise",
                     "params": {"event": "PING", "delay": delay_ms,
                                "id": "hb"}}
                ],
                "on": {"PING": "fired"},
            },
            "fired": {"entry": ["tick"], "type": "final"},
        },
    }


def logic(kind: str) -> MachineLogic:
    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"tick": tick})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"tick": atick})


def sched(blob: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(blob.get("scheduled_sends") or [])


def blob_of(interp: Any) -> str:
    snap = interp.get_persisted_snapshot()
    return snap if isinstance(snap, str) else json.dumps(snap, default=str)


async def hop(blob: str, delay_ms: float, kind: str, mid: str) -> str:
    """One restore -> re-persist hop with NO start() in between (#221)."""
    m = create_machine(copy.deepcopy(cfg(delay_ms, mid)), logic=logic(kind))
    r = Interpreter.from_snapshot(blob, m, clock=SimulatedClock())
    return blob_of(r)


async def p1_case(delay_ms: float, elapsed_ms: float, kind: str,
                  hops: int, mid: str) -> Dict[str, Any]:
    c = SimulatedClock()
    m = create_machine(copy.deepcopy(cfg(delay_ms, mid)), logic=logic(kind))
    i = Interpreter(m, clock=c)
    await i.start()
    if elapsed_ms:
        await c.increment(elapsed_ms)
    blob = blob_of(i)
    await i.stop()
    first = sched(json.loads(blob))
    out: Dict[str, Any] = {
        "delay_ms": delay_ms, "elapsed_ms": elapsed_ms, "kind": kind,
        "hops": hops, "first_records": len(first),
        "first_remaining": first[0].get("remaining_ms") if first else None,
    }
    if len(first) != 1:
        out["fail"] = f"{len(first)} records after arm (want 1)"
        return out

    remainings = [first[0].get("remaining_ms")]
    for h in range(hops):
        blob = await hop(blob, delay_ms, kind, mid)
        recs = sched(json.loads(blob))
        if len(recs) != 1:
            out["fail"] = f"hop {h + 1}: {len(recs)} records (want 1)"
            out["remainings"] = remainings
            return out
        remainings.append(recs[0].get("remaining_ms"))
    out["remainings"] = remainings
    # 🧷 A parked record binds no clock, so no time may be charged to it.
    if len({round(float(r), 6) for r in remainings}) != 1:
        out["fail"] = f"remaining_ms drifted across parked hops: {remainings}"
        return out

    # final hop: restore and START -- must fire exactly once, on time
    remaining = float(remainings[-1])
    c2 = SimulatedClock()
    m2 = create_machine(copy.deepcopy(cfg(delay_ms, mid)), logic=logic(kind))
    r = Interpreter.from_snapshot(blob, m2, clock=c2)
    await r.start()
    await c2.increment(max(remaining - 1, 0))
    out["fired_early"] = f"{mid}.fired" in r.current_state_ids
    await c2.increment(2)
    out["fired_on_time"] = f"{mid}.fired" in r.current_state_ids
    out["n"] = r.context.get("n")
    await r.stop()
    if out["fired_early"]:
        out["fail"] = "fired before the persisted remaining delay"
    elif not out["fired_on_time"]:
        out["fail"] = "did not fire at the persisted remaining delay"
    elif out["n"] != 1:
        out["fail"] = f"fired {out['n']} times (want exactly 1)"
    return out


async def p1_property() -> Dict[str, Any]:
    rnd = random.Random(31337)
    fails: List[Dict[str, Any]] = []
    cases = 0
    for k in range(N_CASES):
        kind = "def" if k % 2 == 0 else "async def"
        delay = rnd.choice([50, 100, 250, 500, 1000, 2500, 5000, 60000])
        elapsed = round(rnd.uniform(0, delay * 0.9), 2)
        hops = rnd.choice([1, 2, 3])
        row = await p1_case(delay, elapsed, kind, hops, f"v3p{k}")
        cases += 1
        if "fail" in row:
            fails.append(row)
    out = {"cases": cases, "failures": len(fails), "sample": fails[:5]}
    if fails:
        FAILS.append(f"P1: {len(fails)}/{cases} property cases failed")
    return out


async def p2_long_chain() -> Dict[str, Any]:
    rows = []
    for kind in ("def", "async def"):
        row = await p1_case(1000, 250, kind, 5, f"v3q{kind[:3]}")
        rows.append(row)
        if "fail" in row:
            FAILS.append(f"P2/{kind}: {row['fail']}")
    return {"hops": 5, "rows": rows}


def trip_cfg(mid: str) -> Dict[str, Any]:
    """A zero-delay self-raise cycle -- guaranteed chain-budget trip."""
    return {
        "id": mid,
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": 5,
        "states": {
            "a": {
                "entry": [{"type": "raise", "params": {"event": "GO"}}],
                "on": {"GO": "b"},
            },
            "b": {
                "entry": [{"type": "raise", "params": {"event": "GO"}}],
                "on": {"GO": "a"},
            },
        },
    }


async def p3_latch_across_snapshot(kind: str) -> Dict[str, Any]:
    """#222: chain_trips / last_chain_error, and what a snapshot carries."""
    m = create_machine(copy.deepcopy(trip_cfg("v3t")), logic=logic(kind))
    i = Interpreter(m)
    await i.start()
    for _ in range(100):
        if getattr(i, "chain_trips", 0):
            break
        await asyncio.sleep(0.01)
    trips = getattr(i, "chain_trips", None)
    latched = i.last_chain_error
    # a benign event must NOT erase the latch (that is the whole of #222)
    await i.send("GO")
    await asyncio.sleep(0.05)
    latched_after_benign = i.last_chain_error
    last_error_after_benign = i.last_error
    blob = blob_of(i)
    blob_keys = sorted(json.loads(blob).keys())
    await i.stop()

    m2 = create_machine(copy.deepcopy(trip_cfg("v3t")), logic=logic(kind))
    r = Interpreter.from_snapshot(blob, m2)
    restored_trips = getattr(r, "chain_trips", None)
    restored_latch = r.last_chain_error

    # clear_chain_error semantics: clears the latch, keeps the count
    i2_trips_before = trips
    m3 = create_machine(copy.deepcopy(trip_cfg("v3u")), logic=logic(kind))
    i3 = Interpreter(m3)
    await i3.start()
    for _ in range(100):
        if getattr(i3, "chain_trips", 0):
            break
        await asyncio.sleep(0.01)
    t_before = i3.chain_trips
    i3.clear_chain_error()
    cleared = i3.last_chain_error
    t_after = i3.chain_trips
    await i3.stop()

    row = {
        "kind": kind,
        "chain_trips": trips,
        "latched_type": type(latched).__name__ if latched else None,
        "latch_survives_benign_event": latched_after_benign is not None,
        "last_error_after_benign": (
            None if last_error_after_benign is None
            else type(last_error_after_benign).__name__
        ),
        "snapshot_keys": blob_keys,
        "snapshot_carries_chain_trips": "chain_trips" in blob_keys,
        "restored_chain_trips": restored_trips,
        "restored_latch": (
            type(restored_latch).__name__ if restored_latch else None
        ),
        "clear_chain_error_clears_latch": cleared is None,
        "clear_chain_error_keeps_count": t_after == t_before and t_after > 0,
        "note": "a restored interpreter is a NEW object; a reset count is "
                "expected. Recorded to show it is not silently non-zero.",
    }
    if not trips:
        FAILS.append(f"P3/{kind}: budget never tripped (chain_trips={trips})")
    if not row["latch_survives_benign_event"]:
        FAILS.append(f"P3/{kind}: #222 latch erased by a benign event")
    if not row["clear_chain_error_clears_latch"]:
        FAILS.append(f"P3/{kind}: clear_chain_error() did not clear the latch")
    if not row["clear_chain_error_keeps_count"]:
        FAILS.append(f"P3/{kind}: clear_chain_error() reset chain_trips")
    return row


def p4_catalogue() -> Dict[str, Any]:
    """#220 must not FALSE-POSITIVE on valid grammar. Every catalogue
    chart is hand-written valid XState-subset JSON: strict_config must
    accept all of them."""
    files = sorted(glob.glob(CATALOGUE_GLOB))
    rejected: List[Dict[str, str]] = []
    built = 0
    unbuildable: List[Dict[str, str]] = []
    for f in files:
        try:
            raw = json.load(open(f, encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            unbuildable.append({"file": os.path.basename(f),
                                "error": f"unreadable: {exc}"})
            continue
        try:
            create_machine(copy.deepcopy(raw), logic=MachineLogic(),
                           strict_config=True)
            built += 1
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "unknown config key" in msg:
                rejected.append({"file": os.path.basename(f), "error": msg[:300]})
            else:
                # not a key-check finding (missing logic, unresolved target,
                # ...) -- out of scope for THIS assertion, recorded only
                unbuildable.append({"file": os.path.basename(f),
                                    "error": type(exc).__name__ + ": " + msg[:160]})
    out = {
        "files": len(files),
        "built_clean_under_strict_config": built,
        "false_positive_key_rejections": len(rejected),
        "false_positive_sample": rejected[:5],
        "other_build_errors": len(unbuildable),
        "other_sample": unbuildable[:5],
    }
    if rejected:
        FAILS.append(
            f"P4: recursive key check FALSE-POSITIVES on {len(rejected)} "
            f"valid catalogue charts"
        )
    if not files:
        FAILS.append("P4: no catalogue *.machine.json found -- probe is vacuous")
    return out


async def main() -> int:
    OUT["P1_chain_property"] = await p1_property()
    OUT["P2_long_chain"] = await p2_long_chain()
    OUT["P3_chain_latch"] = [await p3_latch_across_snapshot(k)
                             for k in ("def", "async def")]
    OUT["P4_catalogue_false_positives"] = p4_catalogue()
    OUT["failures"] = FAILS
    OUT["verdict"] = "DEFECT" if FAILS else "CLEAN"
    emit("v3_persistence_chain_and_latch", OUT)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
