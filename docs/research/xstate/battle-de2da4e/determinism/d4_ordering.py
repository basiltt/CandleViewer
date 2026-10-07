"""D4 -- total ordering rules: one lane against another, both engines.

For each pair of delivery lanes we construct a machine where two events are
made ready at the same decision point and record which one the engine processes
first. Every case is run REPEATS times so instability is visible.

Lanes under test
  EXT      ordinary `send()` -> external inbox
  PRIO     `send(priority=True)` / `send_priority()` -> priority lane
  INT      `raise` built-in -> SCXML internal queue (#36)
  SELFSEND an action calling `interp.send()` on itself (#90 reroute)
  AFTER    an `after` timer fired by the clock -> timer priority lane (#48)
  DONE     an invoke completion (`done.invoke.*`)
  DEFER    an event replayed out of the `onUnhandled: "defer"` buffer

Output: a rules table plus a stability verdict per case.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(
    0, "<workspace>/_ref/xstate-statemachine/src"
)
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

REPEATS = 15
CASES = []


def case(cid, desc):
    def deco(fn):
        CASES.append((cid, desc, fn))
        return fn

    return deco


def mk(cfg, actions=None, services=None, guards=None):
    return create_machine(
        cfg,
        logic=MachineLogic(
            actions=actions or {}, services=services or {}, guards=guards or {}
        ),
    )


# -----------------------------------------------------------------------------
# helper machine: every event just appends its type to `order`
# -----------------------------------------------------------------------------
def recorder_cfg(events, extra=None, **kw):
    on = {e: {"actions": ["rec"]} for e in events}
    if extra:
        on.update(extra)
    cfg = {
        "id": "o",
        "initial": "s",
        "context": {},
        "states": {"s": dict(on=on, **(kw.get("state") or {}))},
    }
    if "onUnhandled" in kw:
        cfg["onUnhandled"] = kw["onUnhandled"]
    return cfg


# =============================================================================
# C1  EXT vs PRIO -- an idle-queued external event vs a later priority send
# =============================================================================
@case("C1", "EXT queued first vs PRIO sent second (async)")
async def c1():
    order = []
    cfg = recorder_cfg(["A", "B", "SLOW"])
    cfg["states"]["s"]["on"]["SLOW"] = {"actions": ["slow"]}

    async def slow(i, c, e, a):
        for _ in range(50):
            await asyncio.sleep(0)

    def rec(i, c, e, a):
        order.append(e.type)

    interp = Interpreter(
        mk(cfg, actions={"rec": rec, "slow": slow}), clock=SimulatedClock()
    )
    await interp.start()
    await interp.send("SLOW")  # occupies the loop
    await asyncio.sleep(0)
    await interp.send("A")  # external inbox
    interp.send_priority("B")  # priority lane
    for _ in range(3000):
        await asyncio.sleep(0)
    await interp.stop()
    return order


# =============================================================================
# C2  INT (raise) vs EXT -- SCXML internal queue drains first (#36)
# =============================================================================
@case("C2", "INT (raise) vs EXT already in the inbox (async)")
async def c2():
    order = []
    cfg = {
        "id": "o",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "GO": {
                        "target": "t",
                        "actions": [{"type": "raise", "params": {"event": "R"}}],
                    },
                    "R": {"actions": ["rec"]},
                    "EXT": {"actions": ["rec"]},
                }
            },
            "t": {"on": {"R": {"actions": ["rec"]}, "EXT": {"actions": ["rec"]}}},
        },
    }

    def rec(i, c, e, a):
        order.append(e.type)

    interp = Interpreter(mk(cfg, actions={"rec": rec}), clock=SimulatedClock())
    await interp.start()
    await interp.send("EXT")  # queued while idle, BEFORE the raise exists
    await interp.send("GO")
    for _ in range(3000):
        await asyncio.sleep(0)
    await interp.stop()
    return order


@case("C2s", "INT (raise) vs EXT already in the inbox (sync)")
def c2s():
    order = []
    cfg = {
        "id": "o",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "GO": {
                        "target": "t",
                        "actions": [{"type": "raise", "params": {"event": "R"}}],
                    },
                    "R": {"actions": ["rec"]},
                    "EXT": {"actions": ["rec"]},
                }
            },
            "t": {"on": {"R": {"actions": ["rec"]}, "EXT": {"actions": ["rec"]}}},
        },
    }

    def rec(i, c, e, a):
        order.append(e.type)

    interp = SyncInterpreter(
        mk(cfg, actions={"rec": rec}), clock=SimulatedClock()
    )
    interp.start()
    interp.send_events(["EXT", "GO"])
    interp.stop()
    return order


# =============================================================================
# C3  AFTER (timer lane) vs EXT backlog -- #48's starvation guarantee
# =============================================================================
@case("C3", "AFTER timer vs a 50-deep external backlog (async)")
async def c3():
    order = []
    cfg = {
        "id": "o",
        "initial": "s",
        "states": {
            "s": {
                "after": {"10": {"target": "done", "actions": ["rec"]}},
                "on": {"E": {"actions": ["rec"]}},
            },
            "done": {"on": {"E": {"actions": ["rec"]}}},
        },
    }

    def rec(i, c, e, a):
        order.append("AFTER" if e.type.startswith("after.") else e.type)

    clock = SimulatedClock()
    interp = Interpreter(mk(cfg, actions={"rec": rec}), clock=clock)
    await interp.start()
    for _ in range(50):
        await interp.send("E")
    await clock.increment(20)  # the timer becomes due with 50 E's queued
    for _ in range(5000):
        await asyncio.sleep(0)
    await interp.stop()
    # report the POSITION of the timer among the 51 processed events
    return {
        "after_index": order.index("AFTER") if "AFTER" in order else None,
        "total": len(order),
    }


@case("C3s", "AFTER timer vs a 50-deep external backlog (sync)")
def c3s():
    order = []
    cfg = {
        "id": "o",
        "initial": "s",
        "states": {
            "s": {
                "after": {"10": {"target": "done", "actions": ["rec"]}},
                "on": {"E": {"actions": ["rec"]}},
            },
            "done": {"on": {"E": {"actions": ["rec"]}}},
        },
    }

    def rec(i, c, e, a):
        order.append("AFTER" if e.type.startswith("after.") else e.type)

    clock = SimulatedClock()
    interp = SyncInterpreter(mk(cfg, actions={"rec": rec}), clock=clock)
    interp.start()
    # the sync engine drains per `send`, so a backlog only exists via
    # `send_events`; queue 50 then advance the clock.
    interp._event_queue.extend(
        [interp._prepare_event("E") for _ in range(50)]
    )
    clock.increment(20)
    interp._process_event_queue()
    interp.stop()
    return {
        "after_index": order.index("AFTER") if "AFTER" in order else None,
        "total": len(order),
    }


# =============================================================================
# C4  DONE (invoke completion) vs EXT backlog
# =============================================================================
@case("C4", "DONE (invoke completion) vs a 20-deep external backlog (async)")
async def c4():
    order = []
    cfg = {
        "id": "o",
        "initial": "w",
        "states": {
            "w": {
                "invoke": {
                    "id": "s",
                    "src": "svc",
                    "onDone": {"target": "d", "actions": ["rec"]},
                },
                "on": {"E": {"actions": ["rec"]}},
            },
            "d": {"on": {"E": {"actions": ["rec"]}}},
        },
    }

    def rec(i, c, e, a):
        order.append("DONE" if e.type.startswith("done.") else e.type)

    async def svc(i, c, e):
        await asyncio.sleep(0)
        return 1

    interp = Interpreter(
        mk(cfg, actions={"rec": rec}, services={"svc": svc}),
        clock=SimulatedClock(),
    )
    await interp.start()
    for _ in range(20):
        await interp.send("E")
    for _ in range(5000):
        await asyncio.sleep(0)
    await interp.stop()
    return {
        "done_index": order.index("DONE") if "DONE" in order else None,
        "total": len(order),
    }


# =============================================================================
# C5  DEFER replay vs EXT -- replayed events go to the HEAD
# =============================================================================
@case("C5", "DEFER replay vs live external traffic (async)")
async def c5():
    order = []
    cfg = {
        "id": "o",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {
            "a": {"on": {"OPEN": {"target": "b"}}},
            "b": {
                "on": {
                    "HELD": {"actions": ["rec"]},
                    "LIVE": {"actions": ["rec"]},
                    "SHUT": {"target": "a"},
                }
            },
        },
    }

    def rec(i, c, e, a):
        order.append(e.type)

    interp = Interpreter(mk(cfg, actions={"rec": rec}), clock=SimulatedClock())
    await interp.start()
    await interp.send("HELD")  # unhandled in `a` -> deferred
    await interp.send("LIVE")  # also unhandled in `a` -> deferred
    await interp.send("OPEN")  # state change -> replay
    for _ in range(3000):
        await asyncio.sleep(0)
    await interp.stop()
    return order


@case("C5s", "DEFER replay vs live external traffic (sync)")
def c5s():
    order = []
    cfg = {
        "id": "o",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {
            "a": {"on": {"OPEN": {"target": "b"}}},
            "b": {
                "on": {
                    "HELD": {"actions": ["rec"]},
                    "LIVE": {"actions": ["rec"]},
                    "SHUT": {"target": "a"},
                }
            },
        },
    }

    def rec(i, c, e, a):
        order.append(e.type)

    interp = SyncInterpreter(
        mk(cfg, actions={"rec": rec}), clock=SimulatedClock()
    )
    interp.start()
    interp.send("HELD")
    interp.send("LIVE")
    interp.send("OPEN")
    interp.stop()
    return order


# =============================================================================
# C6  SELFSEND (#90 reroute) vs an inbox event queued while idle
# =============================================================================
@case("C6", "SELFSEND from an action vs an event queued earlier (async)")
async def c6():
    order = []
    cfg = {
        "id": "o",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "GO": {"actions": ["selfsend"]},
                    "SELF": {"actions": ["rec"]},
                    "EARLY": {"actions": ["rec"]},
                }
            }
        },
    }

    def rec(i, c, e, a):
        order.append(e.type)

    async def selfsend(i, c, e, a):
        await i.send("SELF")

    interp = Interpreter(
        mk(cfg, actions={"rec": rec, "selfsend": selfsend}),
        clock=SimulatedClock(),
    )
    await interp.start()
    await interp.send("EARLY")  # inbox, while idle
    await interp.send("GO")
    for _ in range(3000):
        await asyncio.sleep(0)
    await interp.stop()
    return order


# =============================================================================
# C7  AFTER vs INT(raise) vs PRIO all made ready in the same macrostep
# =============================================================================
@case("C7", "AFTER + PRIO + INT all ready at one decision point (async)")
async def c7():
    order = []
    cfg = {
        "id": "o",
        "initial": "s",
        "states": {
            "s": {
                "after": {"10": {"actions": ["rec"], "target": "s", "reenter": False}},
                "on": {
                    "GO": {
                        "actions": [
                            {"type": "raise", "params": {"event": "R"}},
                            "prio_and_wait",
                        ]
                    },
                    "R": {"actions": ["rec"]},
                    "P": {"actions": ["rec"]},
                },
            }
        },
    }

    def rec(i, c, e, a):
        order.append("AFTER" if e.type.startswith("after.") else e.type)

    async def prio_and_wait(i, c, e, a):
        i.send_priority("P")

    clock = SimulatedClock()
    interp = Interpreter(
        mk(cfg, actions={"rec": rec, "prio_and_wait": prio_and_wait}),
        clock=clock,
    )
    await interp.start()
    await clock.increment(10)  # timer now due & in the lane
    await interp.send("GO")
    for _ in range(3000):
        await asyncio.sleep(0)
    await interp.stop()
    return order


# =============================================================================
# =============================================================================
# C8  PRIO vs INT(raise) -- a priority send made while a raise is pending
# =============================================================================
@case("C8", "PRIO sent during a macrostep vs a pending INT raise (async)")
async def c8():
    order = []
    cfg = {
        "id": "o",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "GO": {
                        "actions": [
                            {"type": "raise", "params": {"event": "R"}},
                            "prio",
                        ]
                    },
                    "R": {"actions": ["rec"]},
                    "P": {"actions": ["rec"]},
                }
            }
        },
    }

    def rec(i, c, e, a):
        order.append(e.type)

    def prio(i, c, e, a):
        i.send_priority("P")

    interp = Interpreter(
        mk(cfg, actions={"rec": rec, "prio": prio}), clock=SimulatedClock()
    )
    await interp.start()
    await interp.send("GO")
    for _ in range(3000):
        await asyncio.sleep(0)
    await interp.stop()
    return order


# =============================================================================
# C9  DEFER replay of MANY held events -- is the replay order FIFO and stable?
# =============================================================================
@case("C9", "DEFER replay order for 25 held events (async)")
async def c9():
    order = []
    held = [f"H{i:02d}" for i in range(25)]
    cfg = {
        "id": "o",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {
            "a": {"on": {"OPEN": {"target": "b"}}},
            "b": {"on": {h: {"actions": ["rec"]} for h in held}},
        },
    }

    def rec(i, c, e, a):
        order.append(e.type)

    interp = Interpreter(mk(cfg, actions={"rec": rec}), clock=SimulatedClock())
    await interp.start()
    for h in held:
        await interp.send(h)
    await interp.send("OPEN")
    for _ in range(5000):
        await asyncio.sleep(0)
    await interp.stop()
    return {"fifo": order == held, "order": order}


@case("C9s", "DEFER replay order for 25 held events (sync)")
def c9s():
    order = []
    held = [f"H{i:02d}" for i in range(25)]
    cfg = {
        "id": "o",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {
            "a": {"on": {"OPEN": {"target": "b"}}},
            "b": {"on": {h: {"actions": ["rec"]} for h in held}},
        },
    }

    def rec(i, c, e, a):
        order.append(e.type)

    interp = SyncInterpreter(
        mk(cfg, actions={"rec": rec}), clock=SimulatedClock()
    )
    interp.start()
    for h in held:
        interp.send(h)
    interp.send("OPEN")
    interp.stop()
    return {"fifo": order == held, "order": order}


# =============================================================================
# C10  AFTER vs DONE -- a timer and an invoke completion due together
# =============================================================================
@case("C10", "AFTER timer vs DONE completion made ready together (async)")
async def c10():
    order = []
    cfg = {
        "id": "o",
        "initial": "w",
        "states": {
            "w": {
                "invoke": {
                    "id": "s",
                    "src": "svc",
                    "onDone": {"actions": ["rec"]},
                },
                "after": {"10": {"actions": ["rec"]}},
                "on": {"X": {"actions": ["rec"]}},
            }
        },
    }

    def rec(i, c, e, a):
        t = e.type
        order.append(
            "AFTER" if t.startswith("after.") else ("DONE" if t.startswith("done.") else t)
        )

    async def svc(i, c, e):
        for _ in range(4):
            await asyncio.sleep(0)
        return 1

    clock = SimulatedClock()
    interp = Interpreter(
        mk(cfg, actions={"rec": rec}, services={"svc": svc}), clock=clock
    )
    await interp.start()
    await clock.increment(10)
    for _ in range(3000):
        await asyncio.sleep(0)
    await interp.stop()
    return order


# =============================================================================
def main():
    results = {}
    for cid, desc, fn in CASES:
        runs = []
        for _ in range(REPEATS):
            # 🧵 async cases get their OWN loop; sync cases must run with NO
            #    loop running, or `SimulatedClock.increment` returns an
            #    awaitable and the sync engine's own idioms break.
            if asyncio.iscoroutinefunction(fn):
                r = asyncio.run(fn())
            else:
                r = fn()
            runs.append(json.dumps(r, default=str))
        distinct = sorted(set(runs))
        results[cid] = {
            "desc": desc,
            "stable": len(distinct) == 1,
            "distinct": len(distinct),
            "observed": [json.loads(d) for d in distinct],
        }
        flag = "STABLE" if len(distinct) == 1 else f"UNSTABLE({len(distinct)})"
        print(f"[{flag:12s}] {cid:5s} {desc}")
        for d in distinct[:3]:
            print(f"                 -> {d}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "d4_ordering.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print("\nwrote out/d4_ordering.json")


if __name__ == "__main__":
    main()
