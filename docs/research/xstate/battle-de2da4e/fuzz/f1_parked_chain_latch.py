"""F1 -- #221 parked scheduled_sends across restore->persist->restore->start
chains, and #222 chain-trip latch across a snapshot.

A: >=300 property cases. A machine arms 1..3 delayed self-sends, is
   snapshotted, then the blob is passed through N (1..4) restore->re-persist
   hops WITHOUT start() (the journal-compaction shape #221 fixes), and only
   the final blob is started on a SimulatedClock. Properties:
     R1 every hop preserves the record set exactly (type + remaining_ms,
        verbatim -- no time charged)
     R2 the final start() fires every event EXACTLY ONCE
     R3 at exactly the original remaining delay
     R4 a hop that also *starts* consumes the parked records (no double-arm)
B: chain-trip latch across a snapshot: does chain_trips / last_chain_error
   survive get_persisted_snapshot -> from_snapshot? (report, not assume)

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import logging
import os
import random
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SimulatedClock,
    create_machine,
)

N = int(os.environ.get("N_CASES", "320"))
SEED = int(os.environ.get("SEED", "20260923"))
DEFECTS = []


async def _advance(clk, ms):
    if ms <= 0:
        await asyncio.sleep(0)
        return
    # 🕰️ SimulatedClock.increment returns an awaitable wrapper in a loop.
    r = clk.increment(ms)
    if r is not None and hasattr(r, "__await__"):
        await r
    for _ in range(5):
        await asyncio.sleep(0)


def mark(i, c, e, a=None):
    c.setdefault("seen", []).append([e.type, i.clock.now()])


async def mark_async(i, c, e, a=None):
    c.setdefault("seen", []).append([e.type, i.clock.now()])


def logic(kind):
    return MachineLogic(
        actions={"mark": mark if kind == "def" else mark_async}
    )


def gen(idx, rnd):
    n = rnd.randint(1, 3)
    entry, live = [], []
    for k in range(n):
        d = rnd.choice([1, 7, 40, 250, 1000, 60000])
        entry.append(
            {
                "type": "raise",
                "params": {"event": f"P{k}", "delay": d, "id": f"s{k}"},
            }
        )
        live.append((f"P{k}", float(d)))
    cfg = {
        "id": f"f1_{idx}",
        "initial": "armed",
        "context": {"seen": []},
        "states": {
            "armed": {
                "entry": entry,
                "on": {f"P{k}": {"actions": ["mark"]} for k in range(n)},
            }
        },
    }
    return cfg, live


async def case(idx, rnd, kind):
    cfg, live = gen(idx, rnd)
    m = create_machine(cfg, logic=logic(kind))
    it = Interpreter(m, clock=SimulatedClock())
    await it.start()
    await asyncio.sleep(0)
    blob = it.get_snapshot()
    await it.stop()
    base = sorted(
        (r["type"], round(float(r["remaining_ms"]), 6))
        for r in (json.loads(blob).get("scheduled_sends") or [])
    )
    tag = f"[{idx}/{kind}]"
    want = sorted((t, float(d)) for t, d in live)
    if base != want:
        DEFECTS.append(f"R0 {tag} initial records {base} != {want}")
        return

    hops = rnd.randint(1, 4)
    for h in range(hops):
        r = Interpreter.from_snapshot(blob, m, clock=SimulatedClock())
        blob = r.get_snapshot()  # NO start()
        got = sorted(
            (rc["type"], round(float(rc["remaining_ms"]), 6))
            for rc in (json.loads(blob).get("scheduled_sends") or [])
        )
        if got != base:
            DEFECTS.append(f"R1 {tag} hop{h}: {got} != {base}")
            return

    final = Interpreter.from_snapshot(blob, m, clock=SimulatedClock())
    await final.start()
    await asyncio.sleep(0)
    await _advance(final.clock, max(d for _, d in live) + 5.0)
    seen = final.context.get("seen") or []
    counts = {}
    firsts = {}
    for t, when in seen:
        counts[t] = counts.get(t, 0) + 1
        firsts.setdefault(t, when * 1000.0)
    for t, d in live:
        if counts.get(t, 0) != 1:
            DEFECTS.append(
                f"R2 {tag} {t} fired {counts.get(t, 0)}x after {hops} "
                f"restore->persist hops (expected exactly 1)"
            )
        elif abs(firsts[t] - d) > 1.5:
            DEFECTS.append(
                f"R3 {tag} {t} fired at {firsts[t]:.3f}ms, expected {d}ms"
            )
    # R4: a started interpreter must not re-emit parked records
    left = json.loads(final.get_snapshot()).get("scheduled_sends") or []
    if len(left) > len(live):
        DEFECTS.append(
            f"R4 {tag} after start+fire, scheduled_sends={len(left)} "
            f"> armed {len(live)} -- parked records not consumed"
        )
    await final.stop()


TRIP_CFG = {
    "id": "trip",
    "initial": "a",
    "states": {
        "a": {
            "entry": [{"type": "raise", "params": {"event": "GO"}}],
            "on": {
                "GO": {"actions": [{"type": "raise",
                                    "params": {"event": "GO"}}]},
                "BENIGN": {"actions": ["noop"]},
            },
        }
    },
}


def noop(i, c, e, a=None):
    c["n"] = c.get("n", 0) + 1


async def part_b(kind):
    lg = MachineLogic(actions={"noop": noop})
    m = create_machine(json.loads(json.dumps(TRIP_CFG)), logic=lg)
    it = Interpreter(m)
    await it.start()
    await asyncio.sleep(0.2)
    t0, e0 = it.chain_trips, type(it.last_chain_error).__name__
    await it.send("BENIGN")
    await asyncio.sleep(0.05)
    t1, e1 = it.chain_trips, type(it.last_chain_error).__name__
    blob = it.get_snapshot()
    snap = json.loads(blob)
    persisted = [k for k in snap if "chain" in k.lower()]
    await it.stop()
    r = Interpreter.from_snapshot(blob, m)
    t2, e2 = r.chain_trips, type(r.last_chain_error).__name__
    it.clear_chain_error() if False else None
    print(f"  B/{kind}: trips@trip={t0} err={e0} | after BENIGN trips={t1} "
          f"err={e1} | snapshot keys w/ 'chain'={persisted} | "
          f"restored trips={t2} err={e2}")
    if t1 != t0 or e1 == "NoneType":
        DEFECTS.append(f"B/{kind}: latch erased by a benign event "
                       f"({t0},{e0}) -> ({t1},{e1})")
    return (t0, e0, t1, e1, persisted, t2, e2)


async def main():
    print(f"F1 -- #221 parked-record chains ({N} cases x 2 kinds) "
          f"+ #222 latch across snapshot, seed={SEED}")
    rnd = random.Random(SEED)
    for kind in ("def", "async def"):
        r2 = random.Random(SEED)
        for i in range(N):
            await case(i, r2, kind)
        print(f"  A/{kind:9s} {N} cases done, defects so far = {len(DEFECTS)}")
    print("\nB -- chain-trip latch across a snapshot")
    for kind in ("def", "async def"):
        await part_b(kind)
    print(f"\nDEFECTS = {len(DEFECTS)}")
    for d in DEFECTS[:25]:
        print("   -", d)
    raise SystemExit(1 if DEFECTS else 0)


asyncio.run(main())
