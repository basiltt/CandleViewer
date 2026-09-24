# -*- coding: utf-8 -*-
"""R6-01 -- async Interpreter livelock: `always` descending into a child that
carries a COMPLETED `invoke`.

`await send("GO", wait=True)` never resolves; status stays "running", .error is
None, and one core is pegged. SyncInterpreter on the identical machine trips
RunawayChainError and returns.

Library only, no project machinery. cec108b (unreleased 0.8.1), Python 3.13.

Exit code 1 == the livelock was observed (watchdog fired).
"""
import asyncio
import copy
import logging
import threading
import time

logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)

WATCHDOG = 5.0

CFG = {
    "id": "m",
    "initial": "a",
    "on": {"GO": {"target": "#m.a", "internal": True}},
    "states": {
        "a": {
            "initial": "a",
            "always": {"target": "#m.a.a", "guard": "g"},
            "states": {"a": {"invoke": {"id": "i", "src": "svc"}}},
        },
    },
}


def svc(interp, ctx, evt):
    return {"ok": 1}


def build(sync):
    return create_machine(
        copy.deepcopy(CFG),
        logic=MachineLogic(
            actions={},
            guards={"g": lambda c, e: True},
            services={"svc": svc},
        ),
    )


async def async_probe():
    it = Interpreter(build(False), strict=False)
    await asyncio.wait_for(it.start(), timeout=WATCHDOG)
    await asyncio.sleep(0.05)         # let the first invoke complete
    task = asyncio.ensure_future(it.send("GO", wait=True))
    done, _ = await asyncio.wait({task}, timeout=WATCHDOG)
    if done:
        print("async : send resolved -> %r" % (task.result(),))
        hung = False
    else:
        print("async : HANG -- no receipt after %.1fs  status=%s  error=%r"
              % (WATCHDOG, it.status, it.error))
        task.cancel()
        hung = True
    await it.stop()
    return hung


def sync_probe():
    it = SyncInterpreter(build(True), strict=False)
    box = {}

    def run():
        try:
            it.start()
            box["r"] = it.send("GO", wait=True)
        except BaseException as exc:      # noqa: BLE001
            box["exc"] = exc

    th = threading.Thread(target=run, daemon=True)
    t0 = time.monotonic()
    th.start()
    th.join(WATCHDOG)
    if th.is_alive():
        print("sync  : HANG after %.1fs" % WATCHDOG)
        return True
    dt = time.monotonic() - t0
    r = box.get("r")
    print("sync  : returned in %.2fs  ok=%s  err=%s"
          % (dt, getattr(it, "last_transition_ok", None),
             type(r.error).__name__ if r is not None and r.error else
             type(box.get("exc")).__name__ if box.get("exc") else None))
    return False


def main():
    sync_hung = sync_probe()
    async_hung = asyncio.run(async_probe())
    print()
    if async_hung and not sync_hung:
        print("REPRODUCED: async livelocks where sync terminates.")
        return 1
    print("NOT reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
