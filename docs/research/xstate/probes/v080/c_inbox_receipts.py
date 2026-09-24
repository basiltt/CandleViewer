"""C. Bounded inbox overflow policies + send(wait=, priority=) receipts (#38, #39).

C1  RAISE: QueueOverflowError at the call site once full; depth observable
C2  DROP_NEWEST: warns, fires on_event_dropped, machine keeps running
C3  BLOCK: producer suspends, no loss
C4  BLOCK issued from inside an ACTION does not self-deadlock
C5  priority=True is exempt from the bound
C6  wait=True: does the receipt await the FULL macrostep incl. actions?
    (action mutates context with an await inside -- receipt must see it)
C7  wait=True receipt.changed False for an unhandled event
C8  wait=True receipt.error carries the action failure under "continue"
C9  wait=True receipt.error under "rollback"
C10 priority reorders: a priority send jumps a backlog
C11 wait=True on a stopped interpreter -- does it hang or raise?
C12 receipt for an event that triggers a state change via `always`
C13 overflow accounting: does queue_depth ever exceed max_queue_size?
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
    OverflowPolicy,
    PluginBase,
    QueueOverflowError,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)
P = Probe("C — bounded inbox & receipts")


class DropWatcher(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, interp, event, *a, **k):
        self.dropped.append(event.type)


SLOW_CFG = {
    "id": "q",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"TICK": {"actions": ["slow"]}}}},
}


async def _slow(i, c, e, a):
    await asyncio.sleep(0.02)
    c["n"] += 1


def mk_slow():
    return create_machine(SLOW_CFG, logic=MachineLogic(actions={"slow": _slow}))


# ------------------------------------------------------------------- C1 RAISE
async def c1():
    i = Interpreter(mk_slow(), max_queue_size=5, overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    sent, err = 0, None
    try:
        for _ in range(50):
            await i.send("TICK")
            sent += 1
    except QueueOverflowError as exc:
        err = exc
    depth = i.queue_depth
    await i.stop()
    return (
        err is not None and sent <= 7,
        f"accepted={sent} before {type(err).__name__ if err else None}; depth_at_raise={depth}",
    )


# ------------------------------------------------------------- C2 DROP_NEWEST
async def c2():
    w = DropWatcher()
    i = Interpreter(
        mk_slow(), max_queue_size=5, overflow_policy=OverflowPolicy.DROP_NEWEST
    )
    await i.start()
    i.use(w)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(50):
            await i.send("TICK")
        nwarn = len(caught)
    await asyncio.sleep(0.5)
    status, processed = i.status, i.context["n"]
    await i.stop()
    return (
        len(w.dropped) > 0 and status == "running",
        f"dropped_hook={len(w.dropped)} warnings={nwarn} processed={processed} status={status}",
    )


# ------------------------------------------------------------------- C3 BLOCK
async def c3():
    i = Interpreter(mk_slow(), max_queue_size=5, overflow_policy=OverflowPolicy.BLOCK)
    await i.start()
    t0 = asyncio.get_running_loop().time()
    for _ in range(20):
        await i.send("TICK")
    elapsed = asyncio.get_running_loop().time() - t0
    await asyncio.sleep(0.6)
    n = i.context["n"]
    await i.stop()
    return (
        n == 20 and elapsed > 0.1,
        f"processed={n}/20 producer_blocked_for={elapsed:.3f}s (backpressure works if >0.1s and n==20)",
    )


# ----------------------------------------------- C4 BLOCK send from an action
SELFSEND_CFG = {
    "id": "ss",
    "initial": "a",
    "context": {"n": 0, "done": False},
    "states": {
        "a": {"on": {"GO": {"actions": ["selfsend"]}, "ECHO": {"actions": ["mark"]}}}
    },
}


async def c4():
    holder = {}

    async def selfsend(i, c, e, a):
        for _ in range(12):  # well past the bound of 3
            await i.send("ECHO")

    def mark(i, c, e, a):
        c["n"] += 1

    m = create_machine(
        SELFSEND_CFG, logic=MachineLogic(actions={"selfsend": selfsend, "mark": mark})
    )
    i = Interpreter(m, max_queue_size=3, overflow_policy=OverflowPolicy.BLOCK)
    await i.start()
    holder["i"] = i
    try:
        await asyncio.wait_for(i.send("GO"), timeout=2.0)
        await asyncio.sleep(0.4)
        deadlocked = False
    except asyncio.TimeoutError:
        deadlocked = True
    n, status = i.context["n"], i.status
    try:
        await asyncio.wait_for(i.stop(), timeout=2.0)
    except asyncio.TimeoutError:
        pass
    return (
        not deadlocked and n == 12,
        f"deadlocked={deadlocked} echoes_processed={n}/12 status={status}",
    )


# --------------------------------------------------- C5 priority exempt/bound
async def c5():
    i = Interpreter(mk_slow(), max_queue_size=3, overflow_policy=OverflowPolicy.RAISE)
    await i.start()
    err = None
    try:
        for _ in range(30):
            await i.send("TICK", priority=True, wait=False)
    except Exception as exc:  # noqa: BLE001
        err = exc
    await asyncio.sleep(1.0)
    n = i.context["n"]
    await i.stop()
    return err is None, f"error={type(err).__name__ if err else None} processed={n}/30"


# ------------------------------------------ C6 wait= awaits the full macrostep
AWAITED_CFG = {
    "id": "w",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["slow_bump"]}}}, "b": {}},
}


async def c6():
    async def slow_bump(i, c, e, a):
        await asyncio.sleep(0.05)
        c["n"] = 99

    m = create_machine(AWAITED_CFG, logic=MachineLogic(actions={"slow_bump": slow_bump}))
    i = await Interpreter(m).start()
    r = await i.send("GO", wait=True)
    n_at_receipt = i.context["n"]
    ids = set(r.state_ids)
    await i.stop()
    return (
        n_at_receipt == 99 and r.changed and "w.b" in ids,
        f"ctx_at_receipt={n_at_receipt} receipt.changed={r.changed} state_ids={ids}",
    )


# --------------------------------------------------- C7 unhandled -> changed?
async def c7():
    m = create_machine(AWAITED_CFG, logic=MachineLogic(actions={"slow_bump": _slow}))
    i = await Interpreter(m).start()
    r = await i.send("NOPE", wait=True)
    await i.stop()
    return (
        r.changed is False and r.error is None,
        f"changed={r.changed} error={r.error} state_ids={set(r.state_ids)}",
    )


# ---------------------------------------------------- C8/C9 receipt.error
ERR_CFG = {
    "id": "er",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["boom"]}}}, "b": {}},
}


def _boom(i, c, e, a):
    raise RuntimeError("kaboom")


async def _receipt_under(policy):
    cfg = dict(ERR_CFG)
    cfg["actionErrorPolicy"] = policy
    m = create_machine(cfg, logic=MachineLogic(actions={"boom": _boom}))
    i = await Interpreter(m).start()
    r = await i.send("GO", wait=True)
    st = set(i.current_state_ids)
    await i.stop()
    return r, st


async def c8():
    r, st = await _receipt_under("continue")
    return (
        r.error is not None,
        f'policy=continue: error={type(r.error).__name__ if r.error else None} changed={r.changed} states={st}',
    )


async def c9():
    r, st = await _receipt_under("rollback")
    return (
        r.error is not None and r.changed is False,
        f'policy=rollback: error={type(r.error).__name__ if r.error else None} changed={r.changed} states={st}',
    )


# ------------------------------------------------------ C10 priority reorders
ORDER_CFG = {
    "id": "o",
    "initial": "a",
    "context": {"log": []},
    "states": {
        "a": {"on": {"BULK": {"actions": ["slowlog"]}, "URGENT": {"actions": ["log"]}}}
    },
}


async def c10():
    async def slowlog(i, c, e, a):
        await asyncio.sleep(0.01)
        c["log"].append("B")

    def log(i, c, e, a):
        c["log"].append("U")

    m = create_machine(
        ORDER_CFG, logic=MachineLogic(actions={"slowlog": slowlog, "log": log})
    )
    i = await Interpreter(m).start()
    for _ in range(20):
        await i.send("BULK")
    await i.send("URGENT", priority=True, wait=False)
    await asyncio.sleep(0.6)
    log_s = "".join(i.context["log"])
    pos = log_s.index("U")
    await i.stop()
    return pos < 5, f"urgent landed at index {pos} of {len(log_s)}: {log_s[:12]}..."


# ---------------------------------------------- C11 wait on stopped machine
async def c11():
    m = create_machine(AWAITED_CFG, logic=MachineLogic(actions={"slow_bump": _slow}))
    i = await Interpreter(m).start()
    await i.stop()
    try:
        r = await asyncio.wait_for(i.send("GO", wait=True), timeout=1.5)
        return True, f"resolved to {r} (no hang)"
    except asyncio.TimeoutError:
        return False, "HUNG: receipt never resolved on a stopped interpreter"
    except Exception as exc:  # noqa: BLE001
        return True, f"raised {type(exc).__name__}: {exc}"


# ----------------------------------------------------- C12 receipt vs always
ALWAYS_CFG = {
    "id": "al",
    "initial": "a",
    "context": {"go": False},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["setgo"]}}},
        "b": {"always": [{"target": "c", "guard": "is_go"}]},
        "c": {},
    },
}


async def c12():
    def setgo(i, c, e, a):
        c["go"] = True

    m = create_machine(
        ALWAYS_CFG,
        logic=MachineLogic(actions={"setgo": setgo}, guards={"is_go": lambda c, e: c["go"]}),
    )
    i = await Interpreter(m).start()
    r = await i.send("GO", wait=True)
    ids = set(r.state_ids)
    await i.stop()
    return "al.c" in ids, f"receipt.state_ids={ids} (want the SETTLED state al.c)"


# --------------------------------------------------- C13 depth never exceeds
async def c13():
    i = Interpreter(mk_slow(), max_queue_size=5, overflow_policy=OverflowPolicy.DROP_NEWEST)
    await i.start()
    peak = 0
    for _ in range(60):
        await i.send("TICK")
        peak = max(peak, i.queue_depth)
    await i.stop()
    return peak <= 5, f"peak queue_depth={peak} with max_queue_size=5"


async def main():
    cases = [
        ("C1", "RAISE overflow policy", c1),
        ("C2", "DROP_NEWEST policy + hook", c2),
        ("C3", "BLOCK backpressure, no loss", c3),
        ("C4", "BLOCK from an action: no deadlock", c4),
        ("C5", "priority exempt from the bound", c5),
        ("C6", "wait= awaits the full macrostep", c6),
        ("C7", "receipt.changed on unhandled", c7),
        ("C8", 'receipt.error under "continue"', c8),
        ("C9", 'receipt.error under "rollback"', c9),
        ("C10", "priority jumps a backlog", c10),
        ("C11", "wait= on a stopped interpreter", c11),
        ("C12", "receipt reports the settled state", c12),
        ("C13", "queue_depth respects the bound", c13),
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
