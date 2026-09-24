"""B. onUnhandled = "defer" — adversarial probe (#28).

B1  3 deferred + a live event: replay order and position vs live traffic
B2  still-unhandled events are re-deferred, not dropped
B3  DEFER_MAX overflow: which event is lost, and is it reported?
B4  the defer buffer survives snapshot -> from_snapshot -> replay
B5  LC-03 end to end: FILL arrives during a submit invoke, handler armed by
    the invoke's onDone -- is the fill applied?
B6  deferred events and a transition that changes state but does NOT arm a
    handler: no infinite replay loop
B7  sync/async engine parity on replay ORDER
B8  does a deferred event replay when the state change came from an
    `after` timer (not a send)?
B9  system events (done./after./xstate.) are never deferred
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Probe  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)
P = Probe("B — onUnhandled defer")


class UnhandledWatcher(PluginBase):
    def __init__(self):
        self.events = []

    def on_unhandled_event(self, interp, event, active, disposition):
        self.events.append((event.type, disposition))


# --------------------------------------------------------------------- B1/B7
ORDER_CFG = {
    "id": "d",
    "initial": "closed",
    "onUnhandled": "defer",
    "context": {"log": []},
    "states": {
        "closed": {"on": {"OPEN": "open"}},
        "open": {
            "on": {
                "A": {"actions": ["log"]},
                "B": {"actions": ["log"]},
                "C": {"actions": ["log"]},
                "LIVE": {"actions": ["log"]},
            }
        },
    },
}


def _log(i, c, e, a):
    c["log"].append(e.type)


async def b1():
    m = create_machine(ORDER_CFG, logic=MachineLogic(actions={"log": _log}))
    i = await Interpreter(m).start()
    await i.send("A")
    await i.send("B")
    await i.send("C")
    await asyncio.sleep(0.02)
    deferred = i.deferred_count
    await i.send("OPEN")
    await i.send("LIVE")
    await asyncio.sleep(0.05)
    log = list(i.context["log"])
    await i.stop()
    return (
        log == ["A", "B", "C", "LIVE"],
        f"deferred_before_open={deferred} log={log} (want A,B,C then LIVE)",
    )


def b7_sync():
    m = create_machine(ORDER_CFG, logic=MachineLogic(actions={"log": _log}))
    i = SyncInterpreter(m).start()
    i.send("A")
    i.send("B")
    i.send("C")
    deferred = i.deferred_count
    i.send("OPEN")
    i.send("LIVE")
    return list(i.context["log"]), deferred


async def b7():
    m = create_machine(ORDER_CFG, logic=MachineLogic(actions={"log": _log}))
    i = await Interpreter(m).start()
    for ev in ("A", "B", "C"):
        await i.send(ev)
    await asyncio.sleep(0.02)
    await i.send("OPEN")
    await i.send("LIVE")
    await asyncio.sleep(0.05)
    alog = list(i.context["log"])
    await i.stop()
    slog, _ = b7_sync()
    return alog == slog, f"async={alog} sync={slog}"


# ------------------------------------------------------------------------ B2
PARTIAL_CFG = {
    "id": "p",
    "initial": "s0",
    "onUnhandled": "defer",
    "context": {"log": []},
    "states": {
        "s0": {"on": {"STEP": "s1"}},
        "s1": {"on": {"A": {"actions": ["log"]}, "STEP": "s2"}},
        "s2": {"on": {"B": {"actions": ["log"]}}},
    },
}


async def b2():
    m = create_machine(PARTIAL_CFG, logic=MachineLogic(actions={"log": _log}))
    i = await Interpreter(m).start()
    await i.send("A")
    await i.send("B")
    await asyncio.sleep(0.02)
    await i.send("STEP")  # -> s1, only A is handled
    await asyncio.sleep(0.05)
    mid_log, mid_def = list(i.context["log"]), i.deferred_count
    await i.send("STEP")  # -> s2, B should now replay
    await asyncio.sleep(0.05)
    end_log, end_def = list(i.context["log"]), i.deferred_count
    await i.stop()
    return (
        mid_log == ["A"] and end_log == ["A", "B"] and end_def == 0,
        f"after s1: log={mid_log} held={mid_def}; after s2: log={end_log} held={end_def}",
    )


# ------------------------------------------------------------------------ B3
async def b3():
    w = UnhandledWatcher()
    m = create_machine(ORDER_CFG, logic=MachineLogic(actions={"log": _log}))
    i = await Interpreter(m).start()
    i.use(w)
    n = Interpreter.DEFER_MAX + 5
    for k in range(n):
        await i.send("A", seq=k)
    await asyncio.sleep(0.3)
    held = i.deferred_count
    dropped = [e for e in w.events if e[1] == "dropped"]
    await i.send("OPEN")
    await asyncio.sleep(1.0)
    log = list(i.context["log"])
    await i.stop()
    return (
        held == Interpreter.DEFER_MAX and len(dropped) == 5 and len(log) == Interpreter.DEFER_MAX,
        f"sent={n} held={held} dropped_reported={len(dropped)} replayed={len(log)} "
        f"DEFER_MAX={Interpreter.DEFER_MAX}",
    )


# ------------------------------------------------------------------------ B4
async def b4():
    m = create_machine(ORDER_CFG, logic=MachineLogic(actions={"log": _log}))
    i = await Interpreter(m).start()
    for ev in ("A", "B", "C"):
        await i.send(ev)
    await asyncio.sleep(0.03)
    held_before = i.deferred_count
    snap = i.get_snapshot()
    await i.stop()

    m2 = create_machine(ORDER_CFG, logic=MachineLogic(actions={"log": _log}))
    j = Interpreter.from_snapshot(snap, m2)
    await j.start()
    held_after = j.deferred_count
    await j.send("OPEN")
    await asyncio.sleep(0.08)
    log = list(j.context["log"])
    await j.stop()
    return (
        held_before == 3 and held_after == 3 and log == ["A", "B", "C"],
        f"held_before={held_before} held_after_restore={held_after} replayed={log}",
    )


# ------------------------------------------------------------------- B5 LC-03
LC03_CFG = {
    "id": "oms",
    "initial": "idle",
    "onUnhandled": "defer",
    "context": {"filled": 0, "log": []},
    "states": {
        "idle": {"on": {"SUBMIT": "submitting"}},
        "submitting": {
            "invoke": {"id": "sub", "src": "submit", "onDone": {"target": "working"}},
        },
        "working": {"on": {"FILL": {"actions": ["fill"]}}},
    },
}


async def b5():
    async def submit(i, c, e):
        await asyncio.sleep(0.06)
        return {"ok": True}

    def fill(i, c, e, a):
        c["filled"] += e.data.get("qty", 0) if hasattr(e, "data") else 0
        c["filled"] += getattr(e, "payload", {}).get("qty", 0) if hasattr(e, "payload") else 0
        c["log"].append("FILL")

    m = create_machine(
        LC03_CFG,
        logic=MachineLogic(actions={"fill": fill}, services={"submit": submit}),
    )
    i = await Interpreter(m).start()
    await i.send("SUBMIT")
    await asyncio.sleep(0.01)
    # 🎯 The fill races in while we are still inside the invoke.
    await i.send("FILL", qty=100)
    await asyncio.sleep(0.02)
    held_mid = i.deferred_count
    await asyncio.sleep(0.2)
    log, st = list(i.context["log"]), set(i.current_state_ids)
    await i.stop()
    return (
        log == ["FILL"],
        f"held_during_invoke={held_mid} log={log} states={st}",
    )


# ------------------------------------------------------------------------ B6
LOOP_CFG = {
    "id": "lp",
    "initial": "s0",
    "onUnhandled": "defer",
    "context": {},
    "states": {
        "s0": {"on": {"STEP": "s1"}},
        "s1": {"on": {"STEP": "s0"}},
    },
}


async def b6():
    m = create_machine(LOOP_CFG, logic=MachineLogic())
    i = await Interpreter(m).start()
    await i.send("NEVER_HANDLED")
    await asyncio.sleep(0.02)
    t0 = asyncio.get_running_loop().time()
    await i.send("STEP")
    await asyncio.sleep(0.05)
    elapsed = asyncio.get_running_loop().time() - t0
    held, st = i.deferred_count, set(i.current_state_ids)
    await i.stop()
    return (
        held == 1 and elapsed < 1.0,
        f"held={held} states={st} elapsed={elapsed:.3f}s (no spin)",
    )


# ------------------------------------------------------------------ B8 after
AFTER_CFG = {
    "id": "af",
    "initial": "closed",
    "onUnhandled": "defer",
    "context": {"log": []},
    "states": {
        "closed": {"after": {40: "open"}},
        "open": {"on": {"A": {"actions": ["log"]}}},
    },
}


async def b8():
    m = create_machine(AFTER_CFG, logic=MachineLogic(actions={"log": _log}))
    i = await Interpreter(m).start()
    await i.send("A")
    await asyncio.sleep(0.02)
    held = i.deferred_count
    await asyncio.sleep(0.25)
    log, st = list(i.context["log"]), set(i.current_state_ids)
    await i.stop()
    return log == ["A"], f"held_before_timer={held} log={log} states={st}"


# ------------------------------------------------------------------------ B9
async def b9():
    w = UnhandledWatcher()
    m = create_machine(AFTER_CFG, logic=MachineLogic(actions={"log": _log}))
    i = await Interpreter(m).start()
    i.use(w)
    await asyncio.sleep(0.25)
    held = i.deferred_count
    sysev = [e for e in w.events if e[0].startswith(("after.", "done.", "xstate."))]
    await i.stop()
    return held == 0 and not sysev, f"held={held} system_events_reported={sysev}"


async def main():
    cases = [
        ("B1", "replay order ahead of live traffic", b1),
        ("B2", "still-unhandled are re-deferred", b2),
        ("B3", "DEFER_MAX overflow behaviour", b3),
        ("B4", "buffer survives snapshot/restore", b4),
        ("B5", "LC-03 fill-during-submit e2e", b5),
        ("B6", "no replay spin on a dead-end move", b6),
        ("B7", "sync/async replay-order parity", b7),
        ("B8", "replay after an `after` timer move", b8),
        ("B9", "system events never deferred", b9),
    ]
    for pid, title, fn in cases:
        try:
            ok, d = await fn()
            P.check(pid, title, ok, d)
        except Exception as exc:  # noqa: BLE001
            P.record_exc(pid, title, exc)
    P.report()


if __name__ == "__main__":
    asyncio.run(main())
