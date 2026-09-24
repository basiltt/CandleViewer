"""E. Injectable clock + timer lane (#48, #49, #50).

E1  SimulatedClock: a 30 s `after` fires in virtual time, ~0 wall clock
E2  determinism: two identical virtual runs produce identical traces
E3  virtual-time ORDERING of several timers with close deadlines
E4  starvation: a 40 ms `after` under a 2k-event burst -- measured lateness
E5  AfterEvent carries scheduled_for / fired_at / lateness_ms
E6  SyncInterpreter spawns NO OS thread per timer (thread count is flat)
E7  SyncInterpreter.tick() delivers a due deadline with no send()
    (see e7_sync_timer_in_loop.py -- this passes only OFF an asyncio loop)
E8  invoked children inherit the parent's clock
E9  SimulatedClock + delayed sendTo (`after`-style delayed send)
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Probe  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SimulatedClock,
    SyncInterpreter,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)
P = Probe("E — clock injection & timer lane")


async def _advance(clock, seconds: float) -> None:
    """Advance a SimulatedClock by *seconds*.

    `increment()` takes MILLISECONDS and, inside a running loop, returns a
    `_MustAwait` wrapper that is neither a coroutine nor a future -- so an
    `iscoroutine` guard skips the await and no timer fires. Always await
    whatever is returned.
    """
    result = clock.increment(seconds * 1000.0)
    if result is not None:
        await result

LONG_CFG = {
    "id": "lg",
    "initial": "wait",
    "context": {"log": []},
    "states": {
        "wait": {"after": {30000: {"target": "fired", "actions": ["note"]}}},
        "fired": {},
    },
}


def _note(i, c, e, a):
    c["log"].append(("fired", getattr(e, "lateness_ms", None)))


async def e1():
    clock = SimulatedClock()
    m = create_machine(LONG_CFG, logic=MachineLogic(actions={"note": _note}))
    i = Interpreter(m, clock=clock)
    await i.start()
    t0 = time.perf_counter()
    await _advance(clock, 31.0)
    wall = time.perf_counter() - t0
    st = set(i.current_state_ids)
    await i.stop()
    return (
        st == {"lg.fired"} and wall < 1.0,
        f"states={st} wall_clock={wall:.4f}s for a 30s timer",
    )


MULTI_CFG = {
    "id": "mt",
    "initial": "a",
    "context": {"log": []},
    "states": {
        "a": {"after": {100: {"target": "b", "actions": ["n1"]}}},
        "b": {"after": {50: {"target": "c", "actions": ["n2"]}}},
        "c": {"after": {10: {"target": "d", "actions": ["n3"]}}},
        "d": {},
    },
}


async def _virtual_trace():
    clock = SimulatedClock()
    log = []
    m = create_machine(
        MULTI_CFG,
        logic=MachineLogic(
            actions={
                "n1": lambda i, c, e, a: log.append("n1"),
                "n2": lambda i, c, e, a: log.append("n2"),
                "n3": lambda i, c, e, a: log.append("n3"),
            }
        ),
    )
    i = Interpreter(m, clock=clock)
    await i.start()
    for _ in range(20):
        await _advance(clock, 20.0)
    st = set(i.current_state_ids)
    await i.stop()
    return log, st


async def e2():
    a, sa = await _virtual_trace()
    b, sb = await _virtual_trace()
    return a == b and sa == sb, f"run1={a}{sorted(sa)} run2={b}{sorted(sb)}"


async def e3():
    log, st = await _virtual_trace()
    return log == ["n1", "n2", "n3"] and st == {"mt.d"}, f"order={log} final={st}"


BURST_CFG = {
    "id": "bs",
    "initial": "run",
    "context": {"n": 0, "late": None},
    "states": {
        "run": {
            "after": {40: {"target": "late", "actions": ["record"]}},
            "on": {"NOISE": {"actions": ["bump"]}},
        },
        "late": {"on": {"NOISE": {"actions": ["bump"]}}},
    },
}


async def e4():
    def record(i, c, e, a):
        c["late"] = getattr(e, "lateness_ms", None)

    def bump(i, c, e, a):
        c["n"] += 1

    m = create_machine(
        BURST_CFG, logic=MachineLogic(actions={"record": record, "bump": bump})
    )
    i = await Interpreter(m).start()
    t0 = time.perf_counter()
    for _ in range(2000):
        await i.send("NOISE")
    await asyncio.sleep(0.5)
    fired_late = i.context["late"]
    processed, st = i.context["n"], set(i.current_state_ids)
    elapsed = time.perf_counter() - t0
    await i.stop()
    return (
        st == {"bs.late"} and (fired_late is None or fired_late < 250),
        f"2000-event burst in {elapsed:.3f}s; timer lateness_ms={fired_late}; "
        f"processed={processed}; final={st}",
    )


async def e5():
    seen = {}

    def record(i, c, e, a):
        seen["scheduled_for"] = getattr(e, "scheduled_for", "MISSING")
        seen["fired_at"] = getattr(e, "fired_at", "MISSING")
        seen["lateness_ms"] = getattr(e, "lateness_ms", "MISSING")

    m = create_machine(
        BURST_CFG, logic=MachineLogic(actions={"record": record, "bump": lambda *a: None})
    )
    i = await Interpreter(m).start()
    await asyncio.sleep(0.25)
    await i.stop()
    ok = all(v not in (None, "MISSING") for v in seen.values()) and seen
    return bool(ok), f"AfterEvent fields={seen}"


SYNC_TIMER_CFG = {
    "id": "sy",
    "initial": "a",
    "context": {"log": []},
    "states": {
        "a": {"after": {40: {"target": "b", "actions": ["note"]}}},
        "b": {"on": {"PING": {"actions": ["note"]}}},
    },
}


def e6():
    before = threading.active_count()
    machines = []
    for _ in range(25):
        m = create_machine(SYNC_TIMER_CFG, logic=MachineLogic(actions={"note": _note}))
        machines.append(SyncInterpreter(m).start())
    peak = threading.active_count()
    for i in machines:
        i.stop()
    return (
        peak - before <= 2,
        f"threads before={before} after 25 sync machines with timers={peak} (delta={peak - before})",
    )


def e7():
    m = create_machine(SYNC_TIMER_CFG, logic=MachineLogic(actions={"note": _note}))
    i = SyncInterpreter(m).start()
    st_before = set(i.current_state_ids)
    time.sleep(0.08)
    i.tick()
    st_after = set(i.current_state_ids)
    i.stop()
    return (
        st_before == {"sy.a"} and st_after == {"sy.b"},
        f"before tick()={st_before} after tick()={st_after} (no send() used)",
    )


PARENT_CLOCK = {
    "id": "pc",
    "initial": "up",
    "context": {},
    "states": {"up": {"invoke": {"id": "kid", "src": "kidm"}}},
}
KID_CLOCK = {
    "id": "kidm",
    "initial": "w",
    "context": {},
    "states": {"w": {"after": {20000: "f"}}, "f": {"type": "final"}},
}


async def e8():
    clock = SimulatedClock()
    kid = create_machine(KID_CLOCK, logic=MachineLogic())
    m = create_machine(PARENT_CLOCK, logic=MachineLogic(services={"kidm": kid}))
    i = Interpreter(m, clock=clock)
    await i.start()
    await asyncio.sleep(0.05)
    # 🔑 Grab the child BEFORE advancing: reaching a final state now tears
    #    the actor down (#57), so `_actors` is empty by the time we look.
    #    Actor ids are namespaced `parent:key`, not the bare invoke id.
    child = i._actors.get("pc:kid") or i._actors.get("kid")
    shares_clock = child is not None and child.clock is clock
    t0 = time.perf_counter()
    await _advance(clock, 21.0)
    await asyncio.sleep(0.05)
    wall = time.perf_counter() - t0
    child_state = set(child.current_state_ids) if child else "NO-CHILD"
    child_status = child.status if child else "?"
    await i.stop()
    return (
        wall < 1.0 and shares_clock and child_status in ("done", "stopped"),
        f"child.clock is parent's={shares_clock} child state={child_state} "
        f"status={child_status} wall={wall:.4f}s for the child's 20s timer",
    )


DELAYED_SEND_CFG = {
    "id": "ds",
    "initial": "a",
    "context": {"log": []},
    "states": {
        "a": {
            # 📮 A DELAYED SELF-SEND. `sendTo` cannot address the machine
            #    itself by its own id (it resolves actors, not self), so the
            #    self-directed spelling is `raise` with a `delay`.
            "entry": [
                {
                    "type": "raise",
                    "params": {"event": {"type": "LATER"}, "delay": 15000},
                }
            ],
            "on": {"LATER": {"target": "b", "actions": ["note"]}},
        },
        "b": {},
    },
}


async def e9():
    clock = SimulatedClock()
    m = create_machine(DELAYED_SEND_CFG, logic=MachineLogic(actions={"note": _note}))
    i = Interpreter(m, clock=clock)
    await i.start()
    t0 = time.perf_counter()
    await _advance(clock, 16.0)
    await asyncio.sleep(0.05)
    wall = time.perf_counter() - t0
    st = set(i.current_state_ids)
    await i.stop()
    return (
        st == {"ds.b"} and wall < 1.0,
        f"states={st} wall={wall:.4f}s for a 15s delayed send",
    )


async def main():
    for pid, title, fn in [
        ("E1", "SimulatedClock: 30s in ~0 wall", e1),
        ("E2", "virtual-time determinism", e2),
        ("E3", "virtual-time timer ordering", e3),
        ("E4", "no starvation under 2k-event burst", e4),
        ("E5", "AfterEvent lateness fields", e5),
        ("E8", "children inherit the clock", e8),
        ("E9", "delayed sendTo under virtual time", e9),
    ]:
        try:
            ok, d = await fn()
            P.check(pid, title, ok, d)
        except Exception as exc:  # noqa: BLE001
            P.record_exc(pid, title, exc)
    for pid, title, fn in [
        ("E6", "sync engine: no thread per timer", e6),
        ("E7", "sync tick() delivers a deadline", e7),
    ]:
        try:
            ok, d = fn()
            P.check(pid, title, ok, d)
        except Exception as exc:  # noqa: BLE001
            P.record_exc(pid, title, exc)
    P.report()


if __name__ == "__main__":
    asyncio.run(main())
