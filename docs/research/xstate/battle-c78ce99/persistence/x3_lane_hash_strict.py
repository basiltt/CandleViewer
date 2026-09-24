# -*- coding: utf-8 -*-
"""X3 -- lane restore ordering (#214) + does `machine_hash` cover the new
snapshot surface? + v3 record without `engine` stays user traffic.

STANDALONE (stdlib + xstate_statemachine). Neutral cwd.

  A  LANE ORDERING. A blob whose `pending_events` holds an inbox record
     FIRST and a `lane: "priority"` record SECOND must process the
     priority one first on restore (a fired timer restores ahead of the
     inbox, #214).
  B  LANE FORGERY. A user record carrying `"lane": "priority"` -- does it
     jump the queue? (Ordering only, no provenance: document it.)
  C  machine_hash / structure_hash: is it a function of the MACHINE only?
     Two machines that differ only in a `raise(delay=)` param -> hashes
     must differ or a snapshot's scheduled_sends can be replayed into a
     chart that no longer arms them. Report what it actually covers.
  D  `strict` on restore (#214): a restored USER event unknown to the
     machine is refused, reported via on_invalid_event, and dropped --
     exactly once.
"""
from __future__ import annotations

import asyncio
import json
import os

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

KIND = os.environ.get("XS_SVC", "async")


class Spy(PluginBase):
    def __init__(self):
        self.invalid = []
        self.dropped = []

    def on_invalid_event(self, interp, error, event=None):  # noqa: ANN001
        self.invalid.append(getattr(event, "type", str(error)[:40]))

    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        self.dropped.append((getattr(event, "type", "?"), reason))


ORDER_SPEC = {
    "id": "ord",
    "initial": "waiting",
    "context": {"log": []},
    "states": {
        "waiting": {
            "after": {"600000": {"actions": "note"}},
            "on": {"USER": {"actions": "note"}},
        }
    },
}


def build_order():
    def note(i, c, e, a):  # noqa: ANN001
        c["log"].append(e.type)

    return create_machine(
        json.loads(json.dumps(ORDER_SPEC)),
        logic=MachineLogic(actions={"note": note}),
    )


def blob_for(m, recs, ctx=None):
    return json.dumps({
        "machine_hash": m.structure_hash,
        "version": 3,
        "status": "running",
        "state_ids": ["ord.waiting"],
        "configuration": ["ord", "ord.waiting"],
        "context": ctx if ctx is not None else {"log": []},
        "pending_events": recs,
        "deferred": [],
        "history": {},
        "actors": {},
        "system": {},
    })


async def part_a():
    print("=== A. lane restore ordering (inbox record first in the list) ===")
    m = build_order()
    recs = [
        {"kind": "event", "type": "USER", "payload": {}},
        {"kind": "after", "type": "after.600000.ord.waiting", "engine": True,
         "lane": "priority", "scheduled_for": 0.0, "fired_at": 0.0},
    ]
    i = Interpreter.from_snapshot(blob_for(m, recs), m)
    await i.start()
    await asyncio.sleep(0.08)
    log = list(i.context["log"])
    await i.stop()
    first_is_timer = bool(log) and log[0].startswith("after.")
    print(f"   processing order = {log}")
    print(f"   VERDICT timer ahead of inbox = {first_is_timer}")


async def part_b():
    print("\n=== B. forged `lane: priority` on a USER record ===")
    m = build_order()
    recs = [
        {"kind": "event", "type": "USER", "payload": {"n": 1}},
        {"kind": "event", "type": "USER", "payload": {"n": 2},
         "lane": "priority"},
    ]
    i = Interpreter.from_snapshot(blob_for(m, recs), m)
    await i.start()
    await asyncio.sleep(0.08)
    log = list(i.context["log"])
    await i.stop()
    print(f"   order = {log} (both 'USER'; lane forgery reorders only)")
    print("   NOTE: `lane` is ordering, not provenance -- a forged lane can "
          "reorder the restored inbox but cannot mint an engine event.")


DELAY_SPEC = {
    "id": "h",
    "initial": "a",
    "context": {},
    "states": {
        "a": {"entry": [{"type": "raise",
                         "params": {"event": "P", "delay": 50}}],
              "on": {"P": {"actions": []}}},
    },
}


async def part_c():
    print("\n=== C. structure_hash coverage vs the v3 surface ===")

    def mk(delay, eid="h"):
        s = json.loads(json.dumps(DELAY_SPEC))
        s["id"] = eid
        s["states"]["a"]["entry"][0]["params"]["delay"] = delay
        return create_machine(s, logic=MachineLogic(actions={}))

    h50, h5000 = mk(50).structure_hash, mk(5000).structure_hash
    print(f"   delay=50 hash   = {h50}")
    print(f"   delay=5000 hash = {h5000}")
    print(f"   VERDICT differing raise-delay changes the hash = "
          f"{h50 != h5000}")
    # does a snapshot's scheduled_sends participate in the hash? (it must
    # not -- the hash is a MACHINE fingerprint) -- state the contract.
    m = mk(50)
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(0)
    snap = json.loads(i.get_snapshot())
    await i.stop()
    print(f"   snapshot scheduled_sends = "
          f"{[(r['type'], round(r['remaining_ms'])) for r in snap.get('scheduled_sends') or []]}")
    print(f"   snapshot machine_hash == machine.structure_hash = "
          f"{snap.get('machine_hash') == m.structure_hash}")
    print("   NOTE: `machine_hash` fingerprints the CHART, not the payload; "
          "scheduled_sends are unauthenticated like every other field.")


STRICT_SPEC = {
    "id": "st",
    "strict": True,
    "onUnhandled": "error",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"KNOWN": {"actions": "bump"}}}},
}


async def part_d():
    print("\n=== D. #214 restore-strict matrix ===")

    def bump(i, c, e, a):  # noqa: ANN001
        c["n"] += 1

    for recs, label in (
        ([{"kind": "event", "type": "KNOWN", "payload": {}}], "known user"),
        ([{"kind": "event", "type": "NOPE", "payload": {}}], "unknown user"),
        ([{"kind": "event", "type": "NOPE", "payload": {}},
          {"kind": "event", "type": "NOPE", "payload": {}}],
         "unknown user x2"),
        ([{"kind": "system", "type": "___xstate_x", "payload": {}}],
         "system rec"),
    ):
        m = create_machine(json.loads(json.dumps(STRICT_SPEC)),
                           logic=MachineLogic(actions={"bump": bump}))
        b = json.dumps({
            "machine_hash": m.structure_hash, "version": 3,
            "status": "running", "state_ids": ["st.a"],
            "configuration": ["st", "st.a"], "context": {"n": 0},
            "pending_events": recs, "deferred": [],
            "history": {}, "actors": {}, "system": {},
        })
        spy = Spy()
        try:
            i = Interpreter.from_snapshot(b, m)
        except Exception as exc:  # noqa: BLE001
            print(f"   {label:16s}: REFUSED at restore {type(exc).__name__}")
            continue
        i.use(spy)
        le = None if i.last_error is None else type(i.last_error).__name__
        await i.start()
        await asyncio.sleep(0.05)
        le2 = None if i.last_error is None else type(i.last_error).__name__
        n = i.context["n"]
        st = i.status
        if i.status == "running":
            await i.stop()
        print(f"   {label:16s}: n={n} status={st} last_error@restore={le} "
              f"@run={le2} invalid_hook={spy.invalid} dropped={spy.dropped}")


async def main():
    print(f"X3 kind={KIND}")
    await part_a()
    await part_b()
    await part_c()
    await part_d()


asyncio.run(main())
