"""R4-06 / R4-07 / R4-11 — refined fresh-process re-reproductions.

Public API only; no library source modified.
"""
import asyncio
import json
import logging

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

logging.disable(logging.CRITICAL)


def _snap(interp):
    raw = interp.get_persisted_snapshot()
    return json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw


# ---------------- R4-06: external events charged to the chain budget
async def r4_06(burst):
    cfg = {
        "id": "m",
        "initial": "a",
        "context": {"n": 0},
        "states": {
            "a": {"on": {"T": {"actions": ["inc"]}, "SLOW": {"actions": ["slow"]}}}
        },
    }

    def inc(i, c, e, a):
        c["n"] += 1

    async def slow(i, c, e, a):
        await asyncio.sleep(0.4)

    dropped = []

    class P:
        def on_event_dropped(self, i, ev, reason):
            dropped.append(reason)

        def __getattr__(self, n):
            return lambda *a, **k: None

    i = Interpreter(
        create_machine(cfg, logic=MachineLogic(actions={"inc": inc, "slow": slow}))
    )
    i.use(P())
    await i.start()
    await i.send("SLOW")
    await asyncio.sleep(0.02)
    for _ in range(burst):
        await i.send("T")
    await asyncio.sleep(2.0)  # fixed settle window, not a queue_depth poll
    n = i.context["n"]
    ok = i.last_transition_ok
    await i.stop()
    return {
        "burst": burst,
        "applied": n,
        "lost": burst - n,
        "dropped_reasons": dropped[:5],
        "n_dropped": len(dropped),
        "last_transition_ok": ok,
        "REPRO": burst - n > 0,
    }


# ---------------- R4-07: Receipt.deferred false positives + id-set growth
def r4_07(n):
    # `GO` is handled in `a` only; in `b` it is unhandled and therefore DEFERRED.
    cfg = {
        "id": "m",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"BACK": "a"}}},
    }
    s = SyncInterpreter(create_machine(cfg, logic=MachineLogic())).start()
    false_pos = 0
    checked = 0
    for _ in range(n):
        r = s.send("GO", wait=True)  # a -> b : genuinely handled
        if r is not None:
            checked += 1
            if getattr(r, "deferred", False) and r.changed:
                false_pos += 1
        s.send("BACK")  # fire-and-forget, back to `a`
    leaked = len(getattr(s, "_deferred_this_step", ()))
    return {
        "iterations": n,
        "receipts_checked": checked,
        "false_positives_deferred_and_changed": false_pos,
        "leaked_ids_in__deferred_this_step": leaked,
        "deferred_count": getattr(s, "deferred_count", None),
        "REPRO": false_pos > 0 or leaked > 0,
    }


def r4_07_leak(n):
    """Fire-and-forget defers: no receipt path, so ids are never discarded."""
    cfg = {
        "id": "m",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {"a": {"on": {"LATER": "b"}}, "b": {}},
    }
    s = SyncInterpreter(create_machine(cfg, logic=MachineLogic())).start()
    for _ in range(n):
        s.send("NOPE")  # never handled anywhere -> deferred, no receipt
    return {
        "sent": n,
        "leaked_ids_in__deferred_this_step": len(getattr(s, "_deferred_this_step", ())),
        "deferred_count": getattr(s, "deferred_count", None),
    }


# ---------------- R4-11: priority lane never persisted
async def r4_11_prestart():
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"on": {"A": {}, "B": {}, "URGENT": {}}}},
    }
    i = Interpreter(create_machine(cfg, logic=MachineLogic()))
    # queue before start(): nothing can be consumed, so the snapshot must hold all three
    await i.send("A")
    await i.send("B")
    await i.send("URGENT", priority=True)
    snap = _snap(i)
    names = [p.get("type") for p in snap.get("pending_events", [])]
    return {
        "status": i.status,
        "queue_depth": i.queue_depth,
        "pending_events_property": [getattr(e, "type", e) for e in i.pending_events],
        "drain_pending": [getattr(e, "type", e) for e in await i.drain_pending()],
        "snapshot_pending": names,
        "REPRO": "A" in names and "B" in names and "URGENT" not in names,
    }


async def main():
    out = {
        "R4-06": await r4_06(1500),
        "R4-06_control_burst_999": await r4_06(999),
        "R4-07": r4_07(3000),
        "R4-07_leak": r4_07_leak(5000),
        "R4-11": await r4_11_prestart(),
    }
    print(json.dumps(out, indent=1, default=str))


asyncio.run(main())
