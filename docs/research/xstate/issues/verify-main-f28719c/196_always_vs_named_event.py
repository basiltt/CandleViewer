"""Verify #196 on f28719c: eventless (`always`) transitions never compete for
a NAMED event; they are selected only in the eventless settle pass (SCXML
3.13). Also: SyncInterpreter reaps an invoked child on exit/stop (leak fix).

Matrix: {def, async def} service x {Interpreter, SyncInterpreter}.
Direct correctness check (not a load/fuzz probe): a spinning `always` at a
deeper state must never consume a *named* external event nor block its own
handler's actions from running; last_error should reflect a genuine settle
trip only when the always is truly unguarded-runaway, and applied count for
external sends must be deterministic (all-or-explicit-drop, never silent).
"""
from __future__ import annotations

import asyncio
import json
import time

from xstate_statemachine import Interpreter, SyncInterpreter, MachineLogic, create_machine

FAIL: list[str] = []
ROWS: list[dict] = []

# invoke -> onDone -> re-enter cycle WITH an always that keeps re-entering
# the same invoking child region (documented runaway shape per #196 report).
CFG = {
    "id": "m196", "initial": "a", "maxIterations": 50, "context": {"ext": 0},
    "on": {"EXT": {"actions": ["extbump"]}},
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {
            "always": {"target": "b2"},
            "initial": "b2",
            "states": {"b2": {"invoke": {"id": "s", "src": "svc", "onDone": {"target": "#m196.a"}}}},
        },
    },
}


def extbump(i, c, e, a):
    c["ext"] = c.get("ext", 0) + 1


async def async_svc(i, c, e):
    await asyncio.sleep(0)
    return {"ok": 1}


def def_svc(i, c, e):
    return {"ok": 1}


async def async_cell(kind: str, n: int = 200):
    svc = def_svc if kind == "def" else async_svc
    it = Interpreter(create_machine(json.loads(json.dumps(CFG)),
                                     logic=MachineLogic(services={"svc": svc}, actions={"extbump": extbump})))
    await asyncio.wait_for(it.start(), 10)
    for _ in range(n):
        await it.send("GO")
        it.send("EXT", priority=True)
        await asyncio.sleep(0)
    # #196: the reporter's own withdrawn claim was "permanent starvation" --
    # refuted because a long-enough settle drains the queues. We give it a
    # generous settle window and check the queues actually drain (not just
    # a fixed sleep), rather than asserting applied==sent immediately.
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if it._event_queue.qsize() == 0 and len(it._priority_queue) == 0:
            break
        await asyncio.sleep(0.2)
    applied = (it.context or {}).get("ext", 0)
    err = type(it.last_error).__name__ if it.last_error else None
    inbox_left = it._event_queue.qsize()
    prio_left = len(it._priority_queue)
    row = {"engine": "async", "service": kind, "sent": n, "applied": applied,
           "status": it.status, "last_error": err, "inbox_left": inbox_left, "priority_left": prio_left}
    ROWS.append(row)
    drained = inbox_left == 0 and prio_left == 0
    if applied != n and err is None and drained:
        FAIL.append(f"async/{kind}: EXT applied {applied}/{n} but queues drained and last_error is None (silent drop)")
    if not drained:
        FAIL.append(f"async/{kind}: queues never drained within 15s (inbox={inbox_left}, priority={prio_left}) -- permanent starvation")
    await asyncio.wait_for(it.stop(), 10)


def sync_cell(n: int = 200):
    it = SyncInterpreter(create_machine(json.loads(json.dumps(CFG)),
                                         logic=MachineLogic(services={"svc": def_svc}, actions={"extbump": extbump})))
    it.start()
    for _ in range(n):
        try:
            it.send("GO")
            it.send("EXT", priority=True)
        except Exception:
            pass
    applied = (it.context or {}).get("ext", 0)
    err = type(it.last_error).__name__ if it.last_error else None
    ROWS.append({"engine": "sync", "service": "def", "sent": n, "applied": applied,
                 "status": it.status, "last_error": err})
    if applied != n and err is None:
        FAIL.append(f"sync/def: EXT applied {applied}/{n} but last_error is None (silent starvation)")
    it.stop()


async def leak_check():
    """SyncInterpreter reaps invoked children on exit/stop (#196 side fix)."""
    import threading
    before = threading.active_count()
    it = SyncInterpreter(create_machine(json.loads(json.dumps(CFG)),
                                         logic=MachineLogic(services={"svc": def_svc}, actions={"extbump": extbump})))
    it.start()
    for _ in range(50):
        it.send("GO")
    it.stop()
    time.sleep(0.3)
    after = threading.active_count()
    ROWS.append({"case": "sync-child-thread-leak", "threads_before": before, "threads_after": after})
    if after > before + 2:  # small slack
        FAIL.append(f"sync engine leaked threads across re-entry cycle+stop: before={before} after={after}")


async def main() -> int:
    for kind in ("def", "async"):
        await async_cell(kind)
    sync_cell()
    await leak_check()
    print(json.dumps({"rows": ROWS, "failures": FAIL}, indent=2, default=str))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
