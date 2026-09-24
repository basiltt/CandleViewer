# -*- coding: utf-8 -*-
"""Verify #129 on main@3ed3099: stop() fires on_event_dropped for every
event it abandons -- BLOCK-parked producers and default drain=False
pending events -- on both engines; drain=True does not fire spurious drops.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.plugins import PluginBase


class _Drops(PluginBase):
    def __init__(self):
        self.dropped = []

    def on_event_dropped(self, i, event, reason):
        self.dropped.append((event.type, reason))


CFG_SLOW = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"X": "a", "SLOW": {"actions": "slow"}}}},
}


async def slow(i, c, e, a):
    await asyncio.sleep(0.3)


def crit_sync_default_stop_drops_pending() -> bool:
    d = _Drops()
    cfg = {"id": "m", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
    i = SyncInterpreter(create_machine(cfg)).use(d)
    i.start()
    # nothing is queued at rest for sync (drains synchronously each send),
    # so simulate pending by directly seeding queue before stop.
    from xstate_statemachine.events import Event

    for n in range(5):
        i._event_queue.append(Event(f"X{n}"))
    i.stop(drain=False)
    ok = [r for _, r in d.dropped] == ["stopped"] * 5
    print(f"  [sync default stop] dropped={d.dropped}")
    return ok


def crit_sync_drain_true_no_spurious_drops() -> bool:
    d = _Drops()
    cfg = {"id": "m", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
    i = SyncInterpreter(create_machine(cfg)).use(d)
    i.start()
    from xstate_statemachine.events import Event

    for n in range(5):
        i._event_queue.append(Event(f"X{n}"))
    i.stop(drain=True)
    ok = d.dropped == []
    print(f"  [sync drain=True] dropped={d.dropped}")
    return ok


async def crit_async_block_stop_fires_drop() -> bool:
    d = _Drops()
    i = Interpreter(
        create_machine(CFG_SLOW, logic=MachineLogic(actions={"slow": slow})),
        overflow_policy="block",
        max_queue_size=1,
    ).use(d)
    await i.start()
    asyncio.ensure_future(i.send("SLOW"))
    await asyncio.sleep(0.02)
    producers = [asyncio.ensure_future(i.send("X", wait=True)) for _ in range(3)]
    await asyncio.sleep(0.02)
    await i.stop()
    results = await asyncio.gather(*producers, return_exceptions=True)
    dropped_x = [r for t, r in d.dropped if t == "X"]
    ok = len(dropped_x) >= 1 and all(r == "stopped" for r in dropped_x)
    print(f"  [async BLOCK stop] dropped={d.dropped} producer_results={results}")
    return ok


async def crit_async_default_stop_drops_pending() -> bool:
    d = _Drops()
    i = Interpreter(
        create_machine(CFG_SLOW, logic=MachineLogic(actions={"slow": slow}))
    ).use(d)
    await i.start()
    asyncio.ensure_future(i.send("SLOW"))
    await asyncio.sleep(0.02)
    for _ in range(4):
        i.send("X")
    await asyncio.sleep(0.01)
    await i.stop()
    dropped = [r for t, r in d.dropped if t == "X"]
    ok = len(dropped) == 4
    print(f"  [async default stop] dropped={d.dropped}")
    return ok


async def crit_async_drain_true_no_spurious_drops() -> bool:
    d = _Drops()
    cfg = {"id": "m", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
    i = Interpreter(create_machine(cfg)).use(d)
    await i.start()
    for _ in range(4):
        i.send("X")
    await i.stop(drain=True)
    ok = d.dropped == []
    print(f"  [async drain=True] dropped={d.dropped}")
    return ok


async def main() -> int:
    r1 = crit_sync_default_stop_drops_pending()
    r2 = crit_sync_drain_true_no_spurious_drops()
    r3 = await crit_async_block_stop_fires_drop()
    r4 = await crit_async_default_stop_drops_pending()
    r5 = await crit_async_drain_true_no_spurious_drops()
    for name, r in [
        ("crit_sync_default_stop_drops_pending", r1),
        ("crit_sync_drain_true_no_spurious_drops", r2),
        ("crit_async_block_stop_fires_drop", r3),
        ("crit_async_default_stop_drops_pending", r4),
        ("crit_async_drain_true_no_spurious_drops", r5),
    ]:
        print(f"{name}: {'PASS' if r else 'FAIL'}")
    ok = r1 and r2 and r3 and r4 and r5
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
