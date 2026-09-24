# -*- coding: utf-8 -*-
"""N4 -- the new restore APIs: restart_timers=, has_dormant_timers,
from_snapshot(clock=)   (#128, #117, #135).

Attacks:
  A. `from_snapshot(clock=SimulatedClock())` -- the D-persistence-1 fix.
     Does virtual time actually drive the restored machine, with no
     private-attribute surgery (`harness.attach_clock`)?
  B. `has_dormant_timers` -- True exactly while an `after` of the restored
     configuration is not armed; False once it is. Also checked in the
     pre-`start()` window (#135) and on a configuration with NO timers
     (must be False, not "unknown").
  C. `restart_timers=True` re-arms from zero. Measured: the deadline must
     fire `delay` after the restore, not at the original absolute time.
  D. `restart_timers` defaults to `restart_services` -- all four
     combinations of the two flags, tabulated.
  E. Parallel regions: a restore of a configuration with timers in TWO
     regions must re-arm BOTH.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock

ONE = {
    "id": "t1",
    "initial": "waiting",
    "context": {"fired": 0},
    "states": {
        "waiting": {"after": {"5000": {"target": "expired",
                                       "actions": ["mark"]}}},
        "expired": {"type": "final"},
    },
}

NOTIMER = {
    "id": "t0",
    "initial": "idle",
    "context": {"fired": 0},
    "states": {"idle": {"on": {"GO": {"target": "done"}}},
               "done": {"type": "final"}},
}

PAR = {
    "id": "tp",
    "initial": "both",
    "context": {"fired": 0, "a": 0, "b": 0},
    "states": {
        "both": {
            "type": "parallel",
            "states": {
                "ra": {"initial": "w",
                       "states": {"w": {"after": {"3000": {"target": "e",
                                                           "actions": ["ma"]}}},
                                  "e": {}}},
                "rb": {"initial": "w",
                       "states": {"w": {"after": {"7000": {"target": "e",
                                                           "actions": ["mb"]}}},
                                  "e": {}}},
            },
        }
    },
}


def mark(i, ctx, e, ad): ctx["fired"] += 1          # noqa: ANN001,E704
def ma(i, ctx, e, ad): ctx["a"] += 1                # noqa: ANN001,E704
def mb(i, ctx, e, ad): ctx["b"] += 1                # noqa: ANN001,E704


def build(cfg):
    return create_machine(cfg, logic=MachineLogic(
        actions={"mark": mark, "ma": ma, "mb": mb}))


async def settle(): await asyncio.sleep(0.03)       # noqa: E704


async def snap_of(cfg, advance_ms=0):
    c = SimulatedClock()
    i = Interpreter(build(cfg), clock=c)
    await i.start()
    await settle()
    if advance_ms:
        await c.increment(advance_ms)
        await settle()
    blob = i.get_snapshot()
    if i.status == "running":
        await i.stop()
    return blob


async def test_a() -> None:
    print("=== A. from_snapshot(clock=) drives virtual time (#117) ===")
    blob = await snap_of(ONE)
    c2 = SimulatedClock()
    i2 = Interpreter.from_snapshot(blob, build(ONE), clock=c2,
                                   restart_timers=True)
    print(f"   i2.clock is our SimulatedClock: {i2.clock is c2}")
    await i2.start()
    await settle()
    await c2.increment(6000)
    await settle()
    print(f"   after +6 s virtual: states={sorted(i2.current_state_ids)} "
          f"fired={i2.context['fired']}")
    ok = i2.clock is c2 and i2.context["fired"] == 1
    print(f"   VERDICT public clock injection works = {ok}")
    if i2.status == "running":
        await i2.stop()


async def test_b() -> None:
    print("\n=== B. has_dormant_timers (#128/#135) ===")
    blob = await snap_of(ONE)
    i2 = Interpreter.from_snapshot(blob, build(ONE), clock=SimulatedClock())
    print(f"   pre-start,  static restore : has_dormant_timers={i2.has_dormant_timers}")
    await i2.start(); await settle()
    print(f"   post-start, static restore : has_dormant_timers={i2.has_dormant_timers}  <- expect True")
    stat = i2.has_dormant_timers
    await i2.stop()

    c3 = SimulatedClock()
    i3 = Interpreter.from_snapshot(blob, build(ONE), clock=c3,
                                   restart_timers=True)
    pre = i3.has_dormant_timers
    await i3.start(); await settle()
    print(f"   pre-start,  restart_timers : has_dormant_timers={pre}")
    print(f"   post-start, restart_timers : has_dormant_timers={i3.has_dormant_timers}  <- expect False")
    rearmed = i3.has_dormant_timers
    if i3.status == "running":
        await i3.stop()

    blob0 = await snap_of(NOTIMER)
    i4 = Interpreter.from_snapshot(blob0, build(NOTIMER),
                                   clock=SimulatedClock())
    await i4.start(); await settle()
    print(f"   machine with NO timers     : has_dormant_timers={i4.has_dormant_timers}  <- expect False")
    notimer = i4.has_dormant_timers
    if i4.status == "running":
        await i4.stop()
    print(f"   VERDICT = {stat is True and rearmed is False and notimer is False}")


async def test_c() -> None:
    print("\n=== C. restart_timers re-arms FROM ZERO, measured (#128) ===")
    # Snapshot 4 s into a 5 s deadline: 1 s remains in the original run.
    blob = await snap_of(ONE, advance_ms=4000)
    c2 = SimulatedClock()
    i2 = Interpreter.from_snapshot(blob, build(ONE), clock=c2,
                                   restart_timers=True)
    await i2.start(); await settle()
    await c2.increment(1500)     # would be enough if the elapsed 4 s carried
    await settle()
    at_1_5 = i2.context["fired"]
    await c2.increment(4000)     # total 5.5 s since restore
    await settle()
    at_5_5 = i2.context["fired"]
    print(f"   +1.5 s after restore: fired={at_1_5}  (0 => re-armed from zero)")
    print(f"   +5.5 s after restore: fired={at_5_5}  (1 => full delay elapsed)")
    print(f"   VERDICT from-zero, as documented = {at_1_5 == 0 and at_5_5 == 1}")
    if i2.status == "running":
        await i2.stop()


async def test_d() -> None:
    print("\n=== D. restart_timers defaults to restart_services (#128) ===")
    blob = await snap_of(ONE)
    rows = []
    for svc in (False, True):
        for tmr in (None, False, True):
            c = SimulatedClock()
            i = Interpreter.from_snapshot(blob, build(ONE), clock=c,
                                          restart_services=svc,
                                          restart_timers=tmr)
            await i.start(); await settle()
            await c.increment(6000); await settle()
            rows.append((svc, tmr, i.context["fired"], i.has_dormant_timers))
            if i.status == "running":
                await i.stop()
    print("   restart_services | restart_timers | fired | dormant_after")
    for svc, tmr, f, d in rows:
        print(f"   {str(svc):<16} | {str(tmr):<14} | {f:<5} | {d}")
    # expectation: fired==1 exactly when effective restart_timers is True
    exp = [(False, None, 0), (False, False, 0), (False, True, 1),
           (True, None, 1), (True, False, 0), (True, True, 1)]
    ok = all(r[2] == e[2] for r, e in zip(rows, exp))
    print(f"   VERDICT default-follows-restart_services = {ok}")


async def test_e() -> None:
    print("\n=== E. both parallel regions' timers re-armed ===")
    blob = await snap_of(PAR)
    c = SimulatedClock()
    i = Interpreter.from_snapshot(blob, build(PAR), clock=c,
                                  restart_timers=True)
    await i.start(); await settle()
    await c.increment(8000); await settle()
    print(f"   states={sorted(i.current_state_ids)} "
          f"a={i.context['a']} b={i.context['b']}")
    ok = i.context["a"] == 1 and i.context["b"] == 1
    print(f"   VERDICT both regions re-armed = {ok}")
    if i.status == "running":
        await i.stop()


async def main() -> None:
    await test_a(); await test_b(); await test_c()
    await test_d(); await test_e()


if __name__ == "__main__":
    asyncio.run(main())
