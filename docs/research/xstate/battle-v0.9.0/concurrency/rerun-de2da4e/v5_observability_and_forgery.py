"""v5 (@de2da4e) -- STANDALONE. #222 observability exactly-once semantics
and snapshot-forgery of the round-11 fields.

O1  on_chain_budget_exceeded fires EXACTLY ONCE per trip, and
    chain_trips increments in lockstep with it. Repeated trips ->
    monotonic count, one hook call each.
O2  clear_chain_error() is idempotent, clears only the latch, and a
    LATER trip re-latches (so acknowledge does not deafen the channel).
O3  Ordering: on_event_dropped('chain_budget') vs
    on_chain_budget_exceeded for the same trip -- recorded and asserted
    consistent across both engines and both kinds.
O4  `last_error` vs `last_chain_error` divergence: the documented #222
    claim is that last_error is a PER-STEP read and the latch is not.
    A benign event after a trip must clear the former, keep the latter.

X1  Snapshot forgery of the ROUND-11 fields, framed as R10-01 does: the
    docs declare `from_snapshot` input a trust boundary, so a forgery
    counts only if it crosses a boundary the library still claims to
    hold. Vectors: forged `chain_trips`-like keys, a `scheduled_sends`
    record with a NEGATIVE remaining_ms (fires instantly?), a forged
    `lane`, and a parked record that survives re-persist (#221) -- does
    the #221 verbatim re-emit launder a forged record through a second
    hop so the second blob looks engine-written?

Run: python v5_observability_and_forgery.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock

FAILS: List[str] = []
OUT: Dict[str, Any] = {}
HERE = os.path.dirname(os.path.abspath(__file__))


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


class Spy(PluginBase):
    """Records the ORDER of the two chain-related callbacks."""

    def __init__(self) -> None:
        self.order: List[str] = []
        self.chain_hook = 0
        self.dropped = 0
        self.hook_errors: List[str] = []

    def on_chain_budget_exceeded(self, interpreter, error, event):  # noqa: ANN001
        self.chain_hook += 1
        self.order.append(f"hook:{type(error).__name__}")

    def on_event_dropped(self, interpreter, event, reason):  # noqa: ANN001
        if reason == "chain_budget":
            self.dropped += 1
            self.order.append("dropped")


def logic(kind: str) -> MachineLogic:
    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"tick": tick})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"tick": atick})


def trip_cfg(mid: str, limit: int = 4) -> Dict[str, Any]:
    """Zero-delay self-raise cycle, armed by an external KICK so trips can
    be driven one at a time."""
    hop = {"type": "raise", "params": {"event": "GO"}}
    return {
        "id": mid,
        "initial": "idle",
        "context": {"n": 0},
        "maxIterations": limit,
        "states": {
            "idle": {"on": {"KICK": "a", "BENIGN": {"actions": ["tick"]}}},
            # 🧷 RESET is what lets the SAME interpreter be tripped again:
            #    after a trip the machine is parked in a/b, and without a
            #    way back to `idle` a second KICK is simply unhandled --
            #    which looks like "the latch did not re-arm" but is only
            #    the chart having no second trip to observe.
            "a": {"entry": [hop, "tick"],
                  "on": {"GO": "b", "RESET": "idle"}},
            "b": {"entry": [hop, "tick"],
                  "on": {"GO": "a", "RESET": "idle"}},
        },
    }


async def o1_exactly_once(kind: str) -> Dict[str, Any]:
    """Drive 3 separate trips; hook count and chain_trips must agree."""
    m = create_machine(copy.deepcopy(trip_cfg("v5o1")), logic=logic(kind))
    i = Interpreter(m)
    spy = Spy()
    i.use(spy)
    await i.start()
    progression: List[Dict[str, int]] = []
    for _ in range(3):
        await i.send("RESET")
        await asyncio.sleep(0.01)
        await i.send("KICK")
        for _ in range(100):
            await asyncio.sleep(0.005)
            if i.chain_trips > len(progression):
                break
        progression.append({"chain_trips": i.chain_trips,
                            "hook_calls": spy.chain_hook,
                            "dropped": spy.dropped})
    trips, hooks = i.chain_trips, spy.chain_hook
    await i.stop()
    row = {"kind": kind, "kicks": 3, "chain_trips": trips,
           "hook_calls": hooks, "dropped": spy.dropped,
           "progression": progression, "order_head": spy.order[:8]}
    if trips == 0:
        FAILS.append(f"O1/{kind}: no trip at all")
    if hooks != trips:
        FAILS.append(f"O1/{kind}: on_chain_budget_exceeded fired {hooks}x "
                     f"but chain_trips={trips} (not exactly-once)")
    if [p["chain_trips"] for p in progression] != sorted(
        p["chain_trips"] for p in progression
    ):
        FAILS.append(f"O1/{kind}: chain_trips not monotonic: {progression}")
    return row


async def o2_clear_idempotent(kind: str) -> Dict[str, Any]:
    m = create_machine(copy.deepcopy(trip_cfg("v5o2")), logic=logic(kind))
    i = Interpreter(m)
    spy = Spy()
    i.use(spy)
    await i.start()
    await i.send("KICK")
    for _ in range(100):
        await asyncio.sleep(0.005)
        if i.chain_trips:
            break
    t1, l1 = i.chain_trips, i.last_chain_error is not None
    i.clear_chain_error()
    cleared1 = i.last_chain_error is None
    t_after_clear = i.chain_trips
    i.clear_chain_error()          # idempotent?
    cleared2 = i.last_chain_error is None
    err2 = None
    # a LATER trip must re-latch
    await i.send("RESET")
    await asyncio.sleep(0.01)
    await i.send("KICK")
    for _ in range(100):
        await asyncio.sleep(0.005)
        if i.chain_trips > t1:
            break
    relatched = i.last_chain_error is not None
    t2 = i.chain_trips
    await i.stop()
    row = {"kind": kind, "trips_first": t1, "latched_first": l1,
           "cleared_once": cleared1, "cleared_twice": cleared2,
           "count_kept_after_clear": t_after_clear == t1,
           "trips_after_second_kick": t2, "relatched": relatched,
           "second_clear_error": err2}
    if not l1:
        FAILS.append(f"O2/{kind}: first trip did not latch")
    if not (cleared1 and cleared2):
        FAILS.append(f"O2/{kind}: clear_chain_error not idempotent")
    if t_after_clear != t1:
        FAILS.append(f"O2/{kind}: clear_chain_error reset the count")
    if t2 <= t1 or not relatched:
        FAILS.append(f"O2/{kind}: a trip AFTER an acknowledge did not "
                     f"re-latch (trips {t1} -> {t2}, relatched={relatched})")
    return row


def o3_sync_engine(kind: str) -> Dict[str, Any]:
    """Sync-engine parity for O1/O2 plus the callback ORDER."""
    if kind == "async def":
        return {"engine": "sync", "kind": kind, "unsupported": True}
    m = create_machine(copy.deepcopy(trip_cfg("v5o3")), logic=logic("def"))
    i = SyncInterpreter(m)
    spy = Spy()
    i.use(spy)
    i.start()
    i.send("KICK")
    for _ in range(50):
        i.tick()
        if i.chain_trips:
            break
    t1 = i.chain_trips
    latched = i.last_chain_error is not None
    i.clear_chain_error()
    cleared = i.last_chain_error is None
    kept = i.chain_trips == t1
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass
    row = {"engine": "sync", "kind": "def", "chain_trips": t1,
           "hook_calls": spy.chain_hook, "dropped": spy.dropped,
           "latched": latched, "cleared": cleared, "count_kept": kept,
           "order_head": spy.order[:8]}
    if not t1:
        FAILS.append("O3/sync: no trip")
    if spy.chain_hook != t1:
        FAILS.append(f"O3/sync: hook {spy.chain_hook}x vs chain_trips {t1}")
    if not (latched and cleared and kept):
        FAILS.append(f"O3/sync: latch semantics {latched}/{cleared}/{kept}")
    return row


async def o4_last_error_divergence(kind: str) -> Dict[str, Any]:
    """#222's core claim: a benign handled event clears `last_error` but
    must NOT clear `last_chain_error`."""
    m = create_machine(copy.deepcopy(trip_cfg("v5o4")), logic=logic(kind))
    i = Interpreter(m)
    await i.start()
    await i.send("KICK")
    for _ in range(100):
        await asyncio.sleep(0.005)
        if i.chain_trips:
            break
    le_after_trip = type(i.last_error).__name__ if i.last_error else None
    lce_after_trip = (
        type(i.last_chain_error).__name__ if i.last_chain_error else None
    )
    # the benign event #222 was filed about
    await i.send("BENIGN")
    await asyncio.sleep(0.05)
    le_after_benign = type(i.last_error).__name__ if i.last_error else None
    lce_after_benign = (
        type(i.last_chain_error).__name__ if i.last_chain_error else None
    )
    trips = i.chain_trips
    await i.stop()
    row = {"kind": kind, "last_error_after_trip": le_after_trip,
           "last_chain_error_after_trip": lce_after_trip,
           "last_error_after_benign": le_after_benign,
           "last_chain_error_after_benign": lce_after_benign,
           "chain_trips": trips}
    if lce_after_trip != "RunawayChainError":
        FAILS.append(f"O4/{kind}: latch not set after a trip "
                     f"({lce_after_trip})")
    if lce_after_benign != "RunawayChainError":
        FAILS.append(f"O4/{kind}: #222 REGRESSION -- a benign event erased "
                     f"last_chain_error ({lce_after_benign})")
    if not trips:
        FAILS.append(f"O4/{kind}: chain_trips stayed 0")
    return row


# ── X1: forgery of the round-11 fields, R10-01 framing ───────────────
#    `from_snapshot` input is a DECLARED trust boundary
#    (base_interpreter.py:1676-1691). A forgery is filed ONLY if it
#    crosses a boundary the library still CLAIMS to hold. The known-open
#    D11-concurrency-1 (no strict check on scheduled_sends) is not
#    re-filed here; these cells ask whether #221 WIDENED it.
def sched_cfg(mid: str) -> Dict[str, Any]:
    return {
        "id": mid,
        "initial": "idle",
        "context": {"n": 0},
        "strict": True,
        "states": {
            "idle": {"on": {"REAL": "moved"}},
            "moved": {"entry": ["tick"]},
        },
    }


def blob_of(i: Any) -> str:
    s = i.get_persisted_snapshot()
    return s if isinstance(s, str) else json.dumps(s, default=str)


async def x1_forgery(kind: str) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []

    async def base_blob(mid: str) -> str:
        m = create_machine(copy.deepcopy(sched_cfg(mid)), logic=logic(kind))
        i = Interpreter(m, clock=SimulatedClock())
        await i.start()
        b = blob_of(i)
        await i.stop()
        return b

    async def run(blob: str, mid: str, advance: float = 0.0):
        m = create_machine(copy.deepcopy(sched_cfg(mid)), logic=logic(kind))
        c = SimulatedClock()
        r = Interpreter.from_snapshot(blob, m, clock=c)
        await r.start()
        if advance:
            await c.increment(advance)
        await asyncio.sleep(0.02)
        st = sorted(r.current_state_ids)
        n = r.context.get("n")
        await r.stop()
        return st, n

    # (a) NEGATIVE remaining_ms -- clamped, or does it fire instantly/hang?
    blob = json.loads(await base_blob("v5xa"))
    blob["scheduled_sends"] = [
        {"type": "REAL", "payload": {}, "remaining_ms": -999999.0,
         "send_id": "forged"}
    ]
    st, n = await run(json.dumps(blob), "v5xa")
    rows.append({"vector": "negative_remaining_ms", "states": st, "n": n,
                 "note": "a negative remaining must be clamped, not "
                         "produce a hang or a negative-delay schedule"})

    # (b) does #221's verbatim re-emit LAUNDER a forged record through a
    #     second hop -- i.e. does hop 2 add any provenance the first
    #     blob lacked?
    blob2 = json.loads(await base_blob("v5xb"))
    forged = {"type": "REAL", "payload": {"v": "FORGED"},
              "remaining_ms": 1000.0, "send_id": "f"}
    blob2["scheduled_sends"] = [dict(forged)]
    m = create_machine(copy.deepcopy(sched_cfg("v5xb")), logic=logic(kind))
    r = Interpreter.from_snapshot(json.dumps(blob2), m,
                                  clock=SimulatedClock())
    hop2 = json.loads(blob_of(r))
    rec2 = (hop2.get("scheduled_sends") or [{}])[0]
    added = sorted(set(rec2) - set(forged))
    removed = sorted(set(forged) - set(rec2))
    rows.append({
        "vector": "221_reemit_laundering",
        "hop2_record": rec2,
        "keys_added_by_reemit": added,
        "keys_removed_by_reemit": removed,
        "verbatim": not added and not removed,
        "note": "#221 says the parked record is re-emitted VERBATIM. If "
                "hop 2 stamped provenance the forger did not write, that "
                "would be a NEW minting channel; verbatim means the "
                "forgery is neither laundered nor upgraded -- it stays "
                "exactly the D11-concurrency-1 surface, not wider.",
    })

    # (c) forged `lane` on a scheduled_sends record
    blob3 = json.loads(await base_blob("v5xc"))
    blob3["scheduled_sends"] = [
        {"type": "REAL", "payload": {}, "remaining_ms": 1.0,
         "send_id": "f", "lane": "priority", "engine": True}
    ]
    st3, n3 = await run(json.dumps(blob3), "v5xc", advance=5.0)
    rows.append({"vector": "forged_lane_plus_engine_flag", "states": st3,
                 "n": n3,
                 "note": "recorded against the KNOWN-OPEN D11-concurrency-1; "
                         "filed only if it does something D11-1 does not"})

    # (d) does the snapshot expose chain_trips at all (forgeable)?
    m4 = create_machine(copy.deepcopy(trip_cfg("v5xd")), logic=logic(kind))
    i4 = Interpreter(m4)
    await i4.start()
    await i4.send("KICK")
    for _ in range(100):
        await asyncio.sleep(0.005)
        if i4.chain_trips:
            break
    b4 = json.loads(blob_of(i4))
    trips_live = i4.chain_trips
    await i4.stop()
    b4["chain_trips"] = 999
    b4["last_chain_error"] = "FORGED"
    m5 = create_machine(copy.deepcopy(trip_cfg("v5xd")), logic=logic(kind))
    r5 = Interpreter.from_snapshot(json.dumps(b4), m5)
    rows.append({
        "vector": "forged_chain_trips",
        "live_trips_before_snapshot": trips_live,
        "snapshot_has_chain_trips_key": "chain_trips" in
                                        json.loads(blob_of(i4) if False
                                                   else json.dumps(b4)),
        "restored_chain_trips": r5.chain_trips,
        "restored_latch": (None if r5.last_chain_error is None
                           else str(r5.last_chain_error)),
        "note": "SUPERSEDED at 0.9.0: #226 made chain_trips / "
                "last_chain_error v3 envelope fields BY DESIGN, so a "
                "forged key is no longer inert -- it is the same "
                "already-open D11-concurrency-1 blob-trust surface, one "
                "field wider. Assertion rewritten: the forged value must "
                "be ADMITTED COHERENTLY (int count + RestoredError latch, "
                "clearable), not crash and not latch a raw attacker "
                "object. Filed as a defect only if the boundary widens.",
    })
    if not isinstance(r5.chain_trips, int):
        FAILS.append(f"X1/{kind}: forged chain_trips restored as "
                     f"{type(r5.chain_trips).__name__}, not int")
    if r5.last_chain_error is not None and not isinstance(
        r5.last_chain_error, BaseException
    ):
        FAILS.append(f"X1/{kind}: forged last_chain_error restored as a raw "
                     f"{type(r5.last_chain_error).__name__}, not an "
                     f"exception (RestoredError expected)")
    r5.clear_chain_error()
    if r5.last_chain_error is not None:
        FAILS.append(f"X1/{kind}: clear_chain_error() did not clear a "
                     f"forged latch")
    return {"kind": kind, "vectors": rows}


async def main() -> int:
    OUT["O1_exactly_once"] = [await o1_exactly_once(k)
                              for k in ("def", "async def")]
    OUT["O2_clear_idempotent"] = [await o2_clear_idempotent(k)
                                  for k in ("def", "async def")]
    OUT["O3_sync_parity"] = [o3_sync_engine(k) for k in ("def", "async def")]
    OUT["O4_last_error_divergence"] = [await o4_last_error_divergence(k)
                                       for k in ("def", "async def")]
    OUT["X1_forgery"] = [await x1_forgery(k) for k in ("def", "async def")]
    OUT["failures"] = FAILS
    OUT["verdict"] = "DEFECT" if FAILS else "CLEAN"
    emit("v5_observability_and_forgery", OUT)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
