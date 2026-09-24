"""Standalone repro for R8-05: forged DoneEvent/AfterEvent, in-process and via
restore_event(), drive a real onDone. Exits 1 while present, 0 once fixed."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.events import AfterEvent, DoneEvent, restore_event, is_system_event

FAIL: list[str] = []

SPEC = {
    "id": "sec",
    "initial": "a",
    "strict": True,
    "onUnhandled": "error",
    "states": {
        "a": {
            "invoke": [{"id": "k", "src": "svc", "onDone": {"target": "done_", "actions": ["stash"]}}],
        },
        "done_": {},
    },
}


def build(kind: str):
    def svc_def(i, c, e):  # noqa: ANN001
        import time
        time.sleep(30)  # never completes within this probe's lifetime

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(30)

    def stash(i, c, e, a):  # noqa: ANN001
        c["got"] = getattr(e, "data", None)

    return create_machine(
        json.loads(json.dumps(SPEC)),
        logic=MachineLogic(
            services={"svc": svc_def if kind == "def" else svc_async},
            actions={"stash": stash},
        ),
    )


async def check1() -> None:
    """Hand-built DoneEvent is exempt from strict/onUnhandled; async drives onDone."""
    for kind in ("def", "async"):
        i = Interpreter(build(kind), clock=SimulatedClock())
        await i.start(children_timeout=0.2)
        await asyncio.sleep(0.02)
        before = sorted(i.current_state_ids)
        forged = DoneEvent(type="done.invoke.k", data={"forged": True}, src="k")
        # As in check2: #195 makes `strict` refuse a user-built engine event by
        # raising. Swallowing that raise and then scoring "still running" as
        # `exempt from strict` inverts the result -- the refusal is exactly the
        # protection this repro was written to demand.
        refused = None
        try:
            await i.send(forged)
        except Exception as e:
            refused = type(e).__name__
        await asyncio.sleep(0.05)
        after = sorted(i.current_state_ids)
        moved = after != before
        print(
            f"  [check1/{kind:<5}] before={before} after={after} "
            f"status={i.status} refused={refused}"
        )
        if moved:
            FAIL.append(f"check1/{kind}: forged DoneEvent drove onDone ({before}->{after})")
        elif refused is None and i.status == "running":
            FAIL.append(f"check1/{kind}: forged DoneEvent exempt from strict/onUnhandled")
        await i.stop()
    d, a = DoneEvent(type="done.invoke.k", data={}, src="k"), AfterEvent(type="after.1.x")
    if is_system_event(d) or is_system_event(a):
        print("  [check1/surface] DoneEvent/AfterEvent pass isinstance-only is_system_event()")

async def check2() -> None:
    """restore_event() on an attacker record yields a trusted DoneEvent."""
    rec = {"kind": "done", "type": "done.invoke.k", "data": {"forged": True, "px": 9e9}, "src": "k"}
    ev = restore_event(rec)
    print(f"  [check2] restored={ev!r} is_system_event={is_system_event(ev)}")
    for kind in ("def", "async"):
        i = Interpreter(build(kind))
        await i.start(children_timeout=0.5)
        await asyncio.sleep(0.05)
        before = sorted(i.current_state_ids)
        # #195 (landed at f28719c) makes `strict` REFUSE a user-built engine
        # event by raising UnknownEventError. That raise IS the protection
        # working -- it must be caught and scored as a PASS, not allowed to
        # escape as an uncaught traceback. Before this fix the send simply
        # succeeded and drove the forged onDone.
        refused = None
        try:
            await i.send(ev)
        except Exception as e:
            refused = type(e).__name__
        await asyncio.sleep(0.2)
        after = sorted(i.current_state_ids)
        got = i.context.get("got")
        print(
            f"  [check2/{kind:<5}] before={before} after={after} "
            f"ctx.got={got} refused={refused}"
        )
        if after != before:
            FAIL.append(f"check2/{kind}: snapshot-forged DoneEvent drove onDone, ctx.got={got}")
        await i.stop()

async def main() -> None:
    print("EXPECTED: forged DoneEvent/AfterEvent are rejected by strict/onUnhandled\n"
          "and never drive a real onDone transition.\nOBSERVED:")
    await check1()
    await check2()
    print("\nFAILURES:", FAIL if FAIL else "none")
    if FAIL:
        print("VERDICT: FAIL (defect present)")
        sys.exit(1)
    print("VERDICT: PASS (defect fixed)")
    sys.exit(0)


def _watchdog(timeout: float = 60.0) -> None:
    def _kill():
        print("WATCHDOG: repro hung; aborting", file=sys.stderr)
        os._exit(2)
    t = threading.Timer(timeout, _kill)
    t.daemon = True
    t.start()



if __name__ == "__main__":
    _watchdog(60.0)
    asyncio.run(main())
