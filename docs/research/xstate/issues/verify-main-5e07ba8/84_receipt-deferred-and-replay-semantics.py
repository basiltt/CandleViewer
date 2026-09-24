"""Verify issue #84 on main @ 5e07ba8.

CHANGELOG [Unreleased] claim: "Receipt.deferred (#84): an event held by
onUnhandled: 'defer' resolved changed=False, error=None -- indistinguishable
from a correct no-op. The receipt now says deferred=True."

Beyond the acceptance criteria, this also documents what happens when the
deferred event is later replayed: does a second receipt/notification exist
for the caller who originally awaited the (now known-stale) receipt, or is
the original receipt object itself ever mutated/resolved a second time?
"""

import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine


CFG = {
    "id": "gate",
    "initial": "closed",
    "onUnhandled": "defer",
    "context": {"filled": 0},
    "states": {
        "closed": {"on": {"OPEN": "open"}},
        "open": {"on": {"FILL": {"target": "filled", "actions": ["mark"]}}},
        "filled": {},
    },
}


def mark(i, ctx, event, action):
    ctx["filled"] += 1


async def crit_1_2_3() -> dict:
    """1: receipt distinguishes deferred from processed no-op.
    2: on replay, the caller can learn the eventual outcome.
    3: onUnhandled error/ignore receipts unchanged (spot-checked via a
       genuinely-processed no-op having deferred=False)."""
    i = await Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"mark": mark}))
    ).start()

    receipt = await i.send("FILL", wait=True)  # no FILL handler in 'closed'
    at_defer_time = {
        "deferred": receipt.deferred,
        "changed": receipt.changed,
        "error": receipt.error,
        "state": i.value,
    }

    receipt_open = await i.send("OPEN", wait=True)  # replay happens here
    await asyncio.sleep(0.02)

    after_replay = {
        "state": i.value,
        "context_filled": i.context["filled"],
        # Is the ORIGINAL receipt object ever mutated after replay?
        "original_receipt_still_deferred": receipt.deferred,
        "original_receipt_changed_field": receipt.changed,
        # Does OPEN's own receipt (a distinct send) report the replay's
        # effect, or only its own (targetless from 'closed'->'open') step?
        "open_receipt_deferred": receipt_open.deferred,
        "open_receipt_changed": receipt_open.changed,
    }

    await i.stop()
    return {"at_defer_time": at_defer_time, "after_replay": after_replay}


def crit_sync() -> dict:
    i = SyncInterpreter(
        create_machine(CFG, logic=MachineLogic(actions={"mark": mark}))
    )
    i.start()
    r = i.send("FILL", wait=True)
    d1 = r.deferred
    r2 = i.send("OPEN", wait=True)
    out = {"fill_deferred": d1, "open_deferred": r2.deferred, "state": i.value}
    i.stop()
    return out


def crit_correct_noop_not_deferred() -> dict:
    cfg = {"id": "n", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
    i = SyncInterpreter(create_machine(cfg))
    i.start()
    r = i.send("NOPE", wait=True)  # genuinely unhandled, no defer policy
    out = {"deferred": r.deferred, "changed": r.changed}
    i.stop()
    return out


def main() -> int:
    res = asyncio.run(crit_1_2_3())
    sync = crit_sync()
    noop = crit_correct_noop_not_deferred()

    print("Async at defer time:", res["at_defer_time"])
    print("Async after replay :", res["after_replay"])
    print("Sync                :", sync)
    print("Correct no-op (not deferred):", noop)

    d = res["at_defer_time"]
    a = res["after_replay"]

    ok = (
        d["deferred"] is True
        and d["changed"] is False
        and d["error"] is None
        and d["state"] == "closed"
        and a["state"] == "filled"
        and a["context_filled"] == 1
        # documented finding: the ORIGINAL receipt is a point-in-time
        # snapshot and is never retroactively mutated/re-resolved by the
        # later replay -- there is no second notification against it.
        and a["original_receipt_still_deferred"] is True
        and a["original_receipt_changed_field"] is False
        # OPEN's own receipt reflects only OPEN's own transition, not FILL's
        and a["open_receipt_deferred"] is False
        and sync["fill_deferred"] is True
        and sync["open_deferred"] is False
        and sync["state"] == "filled"
        and noop["deferred"] is False
        and noop["changed"] is False
    )
    print("RESULT:", "PASS" if ok else "FAIL")
    print(
        "NOTE: no second receipt/notification is delivered for the FILL send "
        "when it is later replayed by OPEN; the caller who awaited FILL's "
        "receipt must separately await/observe OPEN (or poll state) to learn "
        "the eventual outcome -- criterion 2 is satisfied via i.value / a "
        "second wait=True send on the event that triggers replay, not via "
        "the original receipt resolving a second time."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
