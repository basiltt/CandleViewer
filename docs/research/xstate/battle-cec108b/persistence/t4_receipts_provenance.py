# -*- coding: utf-8 -*-
"""T4 - receipts at crash, and v1 provenance laundering.

P11: an event STILL IN THE INBOX when the process dies -- what does its
     `wait=True` awaiter get?
P12: a v1 (0.8.0) snapshot holding a USER event whose name matches an engine
     shape restores as a SYSTEM event, laundering provenance and undoing the
     #79 fix across a version upgrade.
P13: does a restored, never-processed event still resolve a NEW receipt?
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.events import restore_event

import order_machine
from harness import attach_clock


async def p11_receipt_in_inbox() -> None:
    """Freeze the run loop so the event cannot be processed, then crash."""
    gate = asyncio.Event()

    async def gated(interp, ctx, event):  # noqa: ANN001
        await gate.wait()
        return {"ack": 1}

    i = await Interpreter(
        order_machine.build(ack=gated), clock=SimulatedClock()
    ).start()
    await asyncio.sleep(0.02)
    await i.send("SUBMIT", qty=1)
    await asyncio.sleep(0.03)  # parked inside the gated invoke
    # RISK_OK is now accepted onto the inbox and cannot be drained.
    task = asyncio.ensure_future(i.send("RISK_OK", wait=True))
    await asyncio.sleep(0.05)
    blob = i.get_snapshot()
    persisted = [r["type"] for r in json.loads(blob)["pending_events"]]
    print(f"P11 in-inbox at snapshot: {persisted}")
    await i.stop()  # crash surrogate
    try:
        r = await asyncio.wait_for(task, timeout=1.5)
        print(f"P11 awaiter RESOLVED: {r}")
    except asyncio.TimeoutError:
        print("P11 awaiter HUNG: never resolved, never raised  <-- DEFECT")
    except Exception as e:  # noqa: BLE001
        print(f"P11 awaiter RAISED {type(e).__name__}: {e}")
    gate.set()

    # and after the restore -- is the event replayed?
    i2 = Interpreter.from_snapshot(blob, order_machine.build(ack=gated))
    attach_clock(i2, SimulatedClock())
    await i2.start()
    await asyncio.sleep(0.08)
    print(f"P11 restored: states={sorted(i2.current_state_ids)} "
          f"risk={i2.context['risk']} pending={[e.type for e in i2.pending_events]}")
    print("     -> the event IS replayed, but NO receipt is handed to anyone: "
          "the original awaiter's future died with the process.")
    await i2.stop()


async def p12_v1_provenance_laundering() -> None:
    """0.8.0 (v1) snapshot -> 0.8.1 restore: user events become system."""
    i = await Interpreter(
        order_machine.build(on_unhandled="error"), clock=SimulatedClock()
    ).start()
    await asyncio.sleep(0.02)
    blob = json.loads(i.get_snapshot())
    await i.stop()

    # A v1 blob as 0.8.0 would have written it: no `kind`, no `version` bump.
    v1 = {k: v for k, v in blob.items() if k != "machine_hash"}
    v1["version"] = 1
    for name in ("done.review", "after.hours", "xstate.custom", "PLAIN"):
        rec = {"type": name, "payload": {}}
        ev = restore_event(rec)
        print(f"P12 v1 record {name!r} -> {type(ev).__name__} "
              f"system={ev.system}"
              + ("   <-- USER EVENT LAUNDERED TO SYSTEM" if ev.system
                 and not name.startswith("xstate.") else ""))

    # end-to-end: does the laundered event escape `onUnhandled: "error"`?
    v1["pending_events"] = [{"type": "done.review", "payload": {}}]
    i2 = Interpreter.from_snapshot(
        json.dumps(v1),
        order_machine.build(on_unhandled="error"),
        verify_machine_hash=False,
    )
    attach_clock(i2, SimulatedClock())
    await i2.start()
    await asyncio.sleep(0.08)
    print(f"P12 end-to-end: status={i2.status} error={i2.error} "
          f"(a LIVE `done.review` would have errored the machine)")
    await i2.stop()

    # control: the same name sent live to the same machine
    i3 = await Interpreter(
        order_machine.build(on_unhandled="error"), clock=SimulatedClock()
    ).start()
    await asyncio.sleep(0.02)
    try:
        await i3.send("done.review")
    except Exception as e:  # noqa: BLE001
        print(f"P12 control send raised {type(e).__name__}")
    await asyncio.sleep(0.05)
    print(f"P12 control (live send): status={i3.status} error={i3.error}")
    await i3.stop()


async def main() -> None:
    print("=== P11 receipt for an event still in the inbox ===")
    await p11_receipt_in_inbox()
    print("\n=== P12 v1 provenance laundering ===")
    await p12_v1_provenance_laundering()


if __name__ == "__main__":
    asyncio.run(main())
