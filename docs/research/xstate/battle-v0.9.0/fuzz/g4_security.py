"""G4 -- v0.9.0 security / trust-boundary probes on the NEW v3 fields.

Framing (R10-01 / R12-02 precedent): a snapshot is TRUSTED INPUT. A finding
counts only if the forgery reaches an outcome an equivalent HONEST write of
`configuration` / `context` could NOT reach -- i.e. the boundary is crossed,
not merely exercised. Every cell runs a CONTROL first.

S1 forge `chain_trips` / `last_chain_error` in a v3 blob.
S2 forge `chain_trips` to a huge value -- does it disable the budget, or
   make a later genuine trip non-monotonic?
S3 bypass attempts on the #227 strict check of restored `scheduled_sends`:
     s3a undeclared type
     s3b undeclared type + engine-ish name (done.invoke.*)
     s3c `lane: "priority"` smuggled onto a scheduled_sends record
     s3d schema-violating payload on a DECLARED type
   Control: does an honest `pending_events` write reach the same place?

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import asyncio
import json
import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)

DEFECTS = []
NOTES = []

TRIP = {
    "id": "sec",
    "initial": "a",
    "states": {
        "a": {
            "entry": [{"type": "raise", "params": {"event": "GO"}}],
            "on": {
                "GO": {
                    "actions": [{"type": "raise", "params": {"event": "GO"}}]
                },
                "BENIGN": {"actions": []},
            },
        }
    },
}

QUIET = {
    "id": "sec2",
    "strict": True,
    "initial": "a",
    "context": {"seen": []},
    "states": {"a": {"on": {"D0": {"actions": ["mark"]}}}},
}


def mark(i, c, e, a=None):
    c.setdefault("seen", []).append(e.type)


class Spy(PluginBase):
    def __init__(self):
        self.invalid = []

    def on_invalid_event(self, interpreter, error, event=None):
        self.invalid.append(
            (type(error).__name__, getattr(event, "type", None))
        )


async def blob_of(cfg, logic=None, settle=0.0):
    m = create_machine(json.loads(json.dumps(cfg)), logic=logic or MachineLogic())
    it = Interpreter(m)
    await it.start()
    if settle:
        await asyncio.sleep(settle)
    b = it.get_snapshot()
    await it.stop()
    return m, json.loads(b)


async def s1_s2():
    print("S1/S2 -- forged chain_trips / last_chain_error in a v3 blob")
    m, clean = await blob_of(TRIP, settle=0.25)
    print(
        f"  CONTROL untouched blob: chain_trips={clean.get('chain_trips')} "
        f"last_chain_error={str(clean.get('last_chain_error'))[:40]!r}"
    )
    # S1: erase the latch
    forged = dict(clean)
    forged["chain_trips"] = 0
    forged["last_chain_error"] = None
    r = Interpreter.from_snapshot(json.dumps(forged), m)
    print(
        f"  S1 erased latch          -> trips={r.chain_trips} "
        f"err={type(r.last_chain_error).__name__}"
    )
    NOTES.append(
        f"S1 a writer that controls the blob can erase the #226 latch "
        f"(trips {clean.get('chain_trips')} -> {r.chain_trips}). Inside the "
        f"documented trust boundary: the same writer can rewrite "
        f"`configuration`/`context` wholesale. NOT a defect."
    )
    # S2: inflate it
    forged2 = dict(clean)
    forged2["chain_trips"] = 10**9
    forged2["last_chain_error"] = "ATTACKER TEXT"
    r2 = Interpreter.from_snapshot(json.dumps(forged2), m)
    t_before = r2.chain_trips
    await r2.start()
    # 🔁 A STATIC restore does not re-run entry, so nothing trips by itself.
    #    Drive a genuine new trip with an explicit send -- the control below
    #    pins that this is what an untouched blob does too.
    await r2.send("GO")
    await asyncio.sleep(0.3)
    t_after = r2.chain_trips
    print(
        f"  S2 inflated latch        -> restored={t_before} after a genuine "
        f"re-trip={t_after} monotonic={t_after >= t_before} "
        f"msg={str(r2.last_chain_error)[:30]!r}"
    )
    await r2.stop()
    if t_after < t_before:
        DEFECTS.append(
            f"S2: a forged chain_trips made the counter NON-monotonic "
            f"({t_before} -> {t_after}) -- #226 claims monotonic across "
            f"restarts"
        )
    # does a huge count disable the budget?
    if t_after != t_before + 1:
        DEFECTS.append(
            f"S2: after restoring chain_trips={t_before}, a genuine new trip "
            f"left the counter at {t_after} (expected {t_before + 1}) -- an "
            f"inflated latch disturbs later trip accounting"
        )
    # CONTROL: the same drive on an UNTOUCHED blob
    rc = Interpreter.from_snapshot(json.dumps(clean), m)
    c_before = rc.chain_trips
    await rc.start()
    await rc.send("GO")
    await asyncio.sleep(0.3)
    print(
        f"  CONTROL honest restore   -> {c_before} -> {rc.chain_trips} "
        f"(forged path: {t_before} -> {t_after})"
    )
    await rc.stop()


async def s3():
    print("\nS3 -- bypass attempts on the #227 strict check (restored lanes)")
    lg = MachineLogic(actions={"mark": mark})
    m, clean = await blob_of(QUIET, lg)

    cases = [
        ("s3a undeclared in scheduled_sends", "scheduled_sends",
         {"type": "ZZ", "payload": {}, "remaining_ms": 1.0}),
        ("s3b engine-ish name in scheduled_sends", "scheduled_sends",
         {"type": "done.invoke.ghost", "payload": {"filled": 9}, "remaining_ms": 1.0}),
        ("s3c lane:priority on scheduled_sends", "scheduled_sends",
         {"type": "ZZ", "payload": {}, "remaining_ms": 1.0, "lane": "priority"}),
        ("s3d engine flag forged on scheduled_sends", "scheduled_sends",
         {"type": "done.invoke.ghost", "payload": {}, "remaining_ms": 1.0,
          "engine": True}),
        ("CONTROL undeclared in pending_events", "pending_events",
         {"type": "ZZ", "payload": {}}),
        ("CONTROL declared in scheduled_sends", "scheduled_sends",
         {"type": "D0", "payload": {}, "remaining_ms": 1.0}),
    ]
    for label, lane, rec in cases:
        blob = json.loads(json.dumps(clean))
        blob[lane] = [rec]
        spy = Spy()
        try:
            r = Interpreter.from_snapshot(
                json.dumps(blob), m, plugins=[spy]
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:42s} -> RESTORE RAISED {type(exc).__name__}")
            continue
        await r.start()
        await asyncio.sleep(0.05)
        seen = r.context.get("seen") or []
        delivered = rec["type"] in seen
        print(
            f"  {label:42s} -> delivered={delivered} seen={seen} "
            f"on_invalid_event={spy.invalid} "
            f"last_error={type(r.last_error).__name__}"
        )
        await r.stop()
        if label.startswith("CONTROL declared"):
            if not delivered:
                DEFECTS.append(f"{label}: a DECLARED restored send was dropped")
            continue
        if delivered:
            DEFECTS.append(
                f"{label}: an undeclared/forged record was DELIVERED on a "
                f"strict machine -- #227 bypassed"
            )
        elif not spy.invalid:
            DEFECTS.append(
                f"{label}: refused SILENTLY -- no on_invalid_event (#227 "
                f"promises the refusal is reported)"
            )


async def main():
    print("G4 -- v0.9.0 trust-boundary probes on the new v3 fields\n")
    await s1_s2()
    await s3()
    print(f"\nDEFECTS = {len(DEFECTS)}")
    for d in DEFECTS:
        print("   -", d)
    print(f"\nNOTES (trust-boundary, not defects) = {len(NOTES)}")
    for n in NOTES:
        print("   *", n)
    return 1 if DEFECTS else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
