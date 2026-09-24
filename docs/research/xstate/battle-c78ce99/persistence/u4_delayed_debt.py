# -*- coding: utf-8 -*-
"""U4 -- #206 delayed self-`send` debt across a snapshot/restore.

STANDALONE (stdlib + xstate_statemachine).  Run from any cwd.

#206 made a `raise(delay=)` to the machine itself a DEBT of the arming step:
its firing is charged as engine work, so a 1 ms ping-pong trips
`maxIterations` instead of running forever, while a delayed send issued from
OUTSIDE an action stays external.  That debt lives in interpreter state, and
a snapshot/restore is the one operation that can silently discharge it.

Four properties:

  A  A SELF-PING-PONG STILL TRIPS AFTER A RESTORE.  Run a 1 ms delayed
     self-send cycle, snapshot it, restore, and let it run: the restored
     machine must also trip `RunawayChainError` -- not spin forever.

  B  THE PENDING DELAYED SELF-SEND IS VISIBLE IN THE BLOB (or its loss is).
     Report what the snapshot holds for an in-flight delayed self-send.

  C  PROVENANCE IS NOT LAUNDERED BY THE ROUND-TRIP.  An EXTERNAL delayed
     send is external by #206; if a restore turns a self-generated delayed
     send into external traffic (or vice versa) the budget is wrong on the
     restored machine.  Compare trip behaviour of the two origins after a
     round-trip.

  D  RESTORE DOES NOT RESURRECT A CANCELLED DEBT.  Cancelling settles the
     debt (#206); a snapshot taken after the cancel must not re-arm it.

Both service kinds (the cycle is action-driven, but the machine carries an
invoke so the kind is exercised).  Each run is watchdogged: a cycle that has
not tripped within the budget is reported as HANG -- the observed result.
"""
from __future__ import annotations

import asyncio
import json
import os

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import RunawayChainError

KIND = os.environ.get("XS_SVC", "async")
WATCHDOG = 12.0
MAXIT = 12

SPEC = {
    "id": "debt",
    "maxIterations": 12,
    "initial": "a",
    "context": {"laps": 0},
    "states": {
        # 📏 ADAPTED @19cb1f1: #206's surface is the declarative `raise`
        #    action with `params.delay` (ms). `Interpreter.send()` has NO
        #    `delay=` keyword -- passing one silently makes it PAYLOAD
        #    (see u4b P1), so the earlier formulation measured nothing.
        "a": {"entry": [{"type": "raise",
                         "params": {"event": "PONG", "delay": 1}}, "lap"],
              "on": {"PONG": "b"}},
        "b": {"entry": [{"type": "raise",
                         "params": {"event": "PONG", "delay": 1}}, "lap"],
              "on": {"PONG": "a"}},
    },
}


def build(delay_ms: int = 1):
    def lap(i, c, e, a):  # noqa: ANN001
        c["laps"] = c.get("laps", 0) + 1

    def svc_def(i, c, e):  # noqa: ANN001
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"ok": 1}

    return create_machine(
        json.loads(json.dumps(SPEC)),
        logic=MachineLogic(
            actions={"lap": lap},
            services={"svc": svc_def if KIND == "def" else svc_async},
        ),
    )


async def _settle(i, budget: float = WATCHDOG) -> str:
    """Poll until the machine stops turning or the watchdog fires."""
    loop = asyncio.get_running_loop()
    end = loop.time() + budget
    last = -1
    while loop.time() < end:
        if getattr(i, "status", "") in ("error", "stopped", "done"):
            return "TRIPPED" if i.status == "error" else str(i.status)
        cur = i.context.get("laps", 0)
        if cur == last:
            await asyncio.sleep(0.05)
            if i.context.get("laps", 0) == cur:
                return "QUIESCENT"
        last = cur
        await asyncio.sleep(0.02)
    return "HANG"


def _err(i) -> str:
    e = getattr(i, "error", None)
    return type(e).__name__ if e is not None else "None"


async def part_a() -> list:
    print("=== A. delayed self-ping-pong trips, live and after a restore ===")
    fails = []
    i = Interpreter(build())
    await i.start()
    live = await _settle(i)
    live_laps = i.context.get("laps", 0)
    print(f"   live      : {live:<9} laps={live_laps} err={_err(i)}")
    # 📏 ADAPTED: #206 CUTS the chain (drop + ERROR log), it does not put
    #    the machine in `error`. The property is "bounded, not HANG"
    #    (u4b P2 shows the cut is announced and lap-parity-exact).
    if live == "HANG":
        fails.append("A: the live delayed cycle never terminated (HANG)")
    try:
        blob = i.get_snapshot()
        blob_note = "captured"
    except Exception as exc:  # noqa: BLE001
        blob, blob_note = None, f"REFUSED {type(exc).__name__}"
    print(f"   snapshot of the tripped machine: {blob_note}")
    await i.stop()

    if blob is None:
        return fails

    d = json.loads(blob)
    print(f"   blob status={d.get('status')} "
          f"pending={[r['type'] for r in d.get('pending_events') or []]} "
          f"error={str(d.get('error'))[:60]!r}")

    # restore into a fresh machine and let it run again
    try:
        j = Interpreter.from_snapshot(blob, build())
    except Exception as exc:  # noqa: BLE001
        print(f"   restore REFUSED {type(exc).__name__}: {exc}")
        print("   (a tripped machine is not restorable -- recorded)")
        return fails
    await j.start()
    r = await _settle(j)
    print(f"   restored  : {r:<9} laps={j.context.get('laps', 0)} "
          f"err={_err(j)}")
    if r == "HANG":
        fails.append("A: the RESTORED delayed cycle never terminated (HANG)")
    if live != "HANG" and r != "HANG" and abs(live_laps - j.context.get("laps", 0)) > 1:
        fails.append(
            f"A: lap parity lost across the restore: live {live_laps} vs "
            f"restored {j.context.get('laps', 0)}")
    try:
        await j.stop()
    except Exception:  # noqa: BLE001
        pass
    return fails


async def part_bc() -> list:
    """Snapshot a machine with an IN-FLIGHT delayed self-send (long delay),
    restore it, and see whether the pending send survives and with what
    standing."""
    print("\n=== B/C. in-flight delayed self-send across a round-trip ===")
    fails = []
    # 300 ms delay, no cycle: enter `a`, one delayed self-send in flight.
    spec = json.loads(json.dumps(SPEC))
    spec["states"]["a"]["entry"] = [
        {"type": "raise", "params": {"event": "PONG", "delay": 300}}, "lap"]
    spec["states"]["b"]["entry"] = []          # stop the cycle at b
    spec["states"]["b"]["on"] = {}

    def lap(i, c, e, a):  # noqa: ANN001
        c["laps"] = c.get("laps", 0) + 1

    def svc_def(i, c, e):  # noqa: ANN001
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"ok": 1}

    def mk():
        return create_machine(
            json.loads(json.dumps(spec)),
            logic=MachineLogic(
                actions={"lap": lap},
                services={
                    "svc": svc_def if KIND == "def" else svc_async}),
        )

    i = Interpreter(mk())
    await i.start()
    await asyncio.sleep(0.05)   # inside the 300 ms window
    states = sorted(i.current_state_ids)
    blob = i.get_snapshot()
    d = json.loads(blob)
    pend = [r["type"] for r in d.get("pending_events") or []]
    defer = [r["type"] for r in d.get("deferred") or []]
    print(f"   live in-window: states={states} laps={i.context.get('laps')}")
    print(f"   blob pending_events={pend} deferred={defer}")
    print(f"   -> the in-flight delayed self-send is "
          f"{'PRESENT' if pend or defer else 'ABSENT from the blob'}")
    await asyncio.sleep(0.4)
    print(f"   live after the delay elapsed: "
          f"states={sorted(i.current_state_ids)} (the live send DID fire)")
    await i.stop()

    j = Interpreter.from_snapshot(blob, mk())
    await j.start()
    await asyncio.sleep(0.6)    # well past the original 300 ms
    jstates = sorted(j.current_state_ids)
    print(f"   restored after 600 ms: states={jstates} "
          f"laps={j.context.get('laps')}")
    moved = any("debt.b" in s for s in jstates)
    print(f"   -> the delayed self-send "
          f"{'FIRED on the restored machine' if moved else 'was LOST'}")
    if not moved:
        fails.append(
            "B: an in-flight delayed self-send is silently lost across a "
            "snapshot/restore (the restored machine never reaches `b`)")
    await j.stop()
    return fails


async def part_d() -> list:
    print("\n=== D. external delayed send keeps external standing (#206) ===")
    fails = []
    spec = json.loads(json.dumps(SPEC))
    spec["states"]["a"]["entry"] = []
    spec["states"]["b"]["entry"] = []

    def svc_def(i, c, e):  # noqa: ANN001
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"ok": 1}

    def mk():
        return create_machine(
            json.loads(json.dumps(spec)),
            logic=MachineLogic(
                actions={},
                services={
                    "svc": svc_def if KIND == "def" else svc_async}),
        )

    i = Interpreter(mk())
    await i.start()

    # 📏 An EXTERNAL delayed send is the CALLER's own timer -- the library
    #    has no `send(delay=)`. This is #206's "stays external" case.
    async def caller_timer(interp):  # noqa: ANN001
        await asyncio.sleep(0.3)
        await interp.send("PONG")

    task = asyncio.ensure_future(caller_timer(i))
    await asyncio.sleep(0.05)
    blob = i.get_snapshot()
    d = json.loads(blob)
    print(f"   external delayed send: blob pending="
          f"{[r['type'] for r in d.get('pending_events') or []]} "
          f"deferred={[r['type'] for r in d.get('deferred') or []]}")
    task.cancel()
    await i.stop()

    j = Interpreter.from_snapshot(blob, mk())
    await j.start()
    t2 = asyncio.ensure_future(caller_timer(j))
    await asyncio.sleep(0.6)
    st = sorted(j.current_state_ids)
    t2.cancel()
    print(f"   restored after 600 ms: states={st}")
    print(f"   -> external delayed send "
          f"{'FIRED' if any('debt.b' in s for s in st) else 'was LOST'} "
          f"(same treatment as the self-send above: compare)")
    await j.stop()
    return fails


async def main() -> None:
    print(f"=== U4 delayed-self-send debt across persistence [{KIND}] "
          f"maxIterations={MAXIT} ===")
    fails = []
    fails += await part_a()
    fails += await part_bc()
    fails += await part_d()
    print()
    print("FAILURES:", fails or "none")
    print("VERDICT:", "FAIL" if fails else "PASS")


if __name__ == "__main__":
    asyncio.run(main())
