"""Probe suite C: context mutation & snapshot isolation, persisted-snapshot
round-trip (timers / invokes on resume), determinism under identical event
sequences (replay-ability), event payload handling, raise/sendTo/spawn
ordering, strict mode.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import probe, run_all  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    create_machine,
)

SETTLE = 0.1


async def boot(cfg, logic):
    return await Interpreter(create_machine(cfg, logic=logic)).start()


# ---------------------------------------------------------------- C1
@probe(
    "C1",
    "Action mutating context in place: does the mutation leak into an EARLIER snapshot?",
    {"snap_before": {"n": 0}, "snap_after": {"n": 1}, "leaked": False},
)
async def c1():
    def bump(i, c, e, a):  # noqa: ANN001
        c["n"] += 1

    cfg = {
        "id": "m",
        "initial": "s",
        "context": {"n": 0},
        "states": {"s": {"on": {"BUMP": {"actions": ["bump"]}}}},
    }
    i = await boot(cfg, MachineLogic(actions={"bump": bump}))
    snap_before = json.loads(i.get_snapshot())["context"]
    await i.send("BUMP")
    await asyncio.sleep(SETTLE)
    snap_after = json.loads(i.get_snapshot())["context"]
    await i.stop()
    return {
        "snap_before": snap_before,
        "snap_after": snap_after,
        "leaked": snap_before == snap_after,
    }


# ---------------------------------------------------------------- C2
@probe(
    "C2",
    "Nested mutable context: deep mutation must not retro-edit a prior snapshot",
    {"before": {"orders": []}, "after": {"orders": ["o1"]}},
)
async def c2():
    def add(i, c, e, a):  # noqa: ANN001
        c["orders"].append("o1")

    cfg = {
        "id": "m",
        "initial": "s",
        "context": {"orders": []},
        "states": {"s": {"on": {"ADD": {"actions": ["add"]}}}},
    }
    i = await boot(cfg, MachineLogic(actions={"add": add}))
    before = copy.deepcopy(i.get_persisted_snapshot()["context"])
    await i.send("ADD")
    await asyncio.sleep(SETTLE)
    after = i.get_persisted_snapshot()["context"]
    await i.stop()
    return {"before": before, "after": after}


# ---------------------------------------------------------------- C3
@probe(
    "C3",
    "Two interpreters of the SAME machine object do not share context",
    {"a": {"n": 1}, "b": {"n": 0}},
)
async def c3():
    def bump(i, c, e, a):  # noqa: ANN001
        c["n"] += 1

    cfg = {
        "id": "m",
        "initial": "s",
        "context": {"n": 0},
        "states": {"s": {"on": {"BUMP": {"actions": ["bump"]}}}},
    }
    machine = create_machine(cfg, logic=MachineLogic(actions={"bump": bump}))
    ia = await Interpreter(machine).start()
    ib = await Interpreter(machine).start()
    await ia.send("BUMP")
    await asyncio.sleep(SETTLE)
    out = {"a": dict(ia.context), "b": dict(ib.context)}
    await ia.stop()
    await ib.stop()
    return out


# ---------------------------------------------------------------- C4
@probe(
    "C4",
    "Snapshot round-trip restores state ids and context exactly",
    {"ids": ["m.b"], "ctx": {"n": 3}},
)
async def c4():
    def bump(i, c, e, a):  # noqa: ANN001
        c["n"] += 1

    cfg = {
        "id": "m",
        "initial": "a",
        "context": {"n": 0},
        "states": {
            "a": {"on": {"BUMP": {"actions": ["bump"]}, "GO": "b"}},
            "b": {},
        },
    }
    logic = MachineLogic(actions={"bump": bump})
    machine = create_machine(cfg, logic=logic)
    i = await Interpreter(machine).start()
    for _ in range(3):
        await i.send("BUMP")
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    snap = i.get_snapshot()
    await i.stop()

    machine2 = create_machine(cfg, logic=MachineLogic(actions={"bump": bump}))
    r = Interpreter.from_snapshot(snap, machine2)
    out = {"ids": sorted(r.current_state_ids), "ctx": dict(r.context)}
    return out


# ---------------------------------------------------------------- C5
@probe(
    "C5",
    "Restored interpreter can be started and still processes events",
    {"ids": ["m.c"], "running": True},
)
async def c5():
    cfg = {
        "id": "m",
        "initial": "a",
        "context": {},
        "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"GO2": "c"}}, "c": {}},
    }
    machine = create_machine(cfg, logic=MachineLogic())
    i = await Interpreter(machine).start()
    await i.send("GO")
    await asyncio.sleep(SETTLE)
    snap = i.get_snapshot()
    await i.stop()

    machine2 = create_machine(cfg, logic=MachineLogic())
    r = Interpreter.from_snapshot(snap, machine2)
    await r.start()
    await r.send("GO2")
    await asyncio.sleep(SETTLE)
    out = {"ids": sorted(r.current_state_ids), "running": r.is_running}
    await r.stop()
    return out


# ---------------------------------------------------------------- C6
@probe(
    "C6",
    "Restoring a snapshot taken mid-'after' RESUMES the delayed transition",
    {"fired": True},
)
async def c6():
    flags = {"fired": False}

    def mark(i, c, e, a):  # noqa: ANN001
        flags["fired"] = True

    cfg = {
        "id": "m",
        "initial": "wait",
        "context": {},
        "states": {
            "wait": {"after": {150: {"target": "late", "actions": ["mark"]}}},
            "late": {},
        },
    }
    logic = MachineLogic(actions={"mark": mark})
    i = await Interpreter(create_machine(cfg, logic=logic)).start()
    await asyncio.sleep(0.02)
    snap = i.get_snapshot()
    await i.stop()
    flags["fired"] = False

    r = Interpreter.from_snapshot(
        snap, create_machine(cfg, logic=MachineLogic(actions={"mark": mark}))
    )
    await r.start()
    await asyncio.sleep(0.4)
    out = {"fired": flags["fired"]}
    await r.stop()
    return out


# ---------------------------------------------------------------- C7
@probe(
    "C7",
    "Restoring a snapshot taken mid-'invoke' RE-RUNS the invoked service",
    {"calls": 1},
)
async def c7():
    calls = {"n": 0}

    async def svc(interp, ctx, evt):  # noqa: ANN001
        calls["n"] += 1
        await asyncio.sleep(0.3)
        return "ok"

    cfg = {
        "id": "m",
        "initial": "run",
        "context": {},
        "states": {
            "run": {"invoke": {"id": "job", "src": "svc", "onDone": "ok"}},
            "ok": {},
        },
    }
    i = await Interpreter(
        create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
    ).start()
    await asyncio.sleep(0.05)
    snap = i.get_snapshot()
    await i.stop()
    calls["n"] = 0

    r = Interpreter.from_snapshot(
        snap, create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
    )
    await r.start()
    await asyncio.sleep(0.15)
    out = {"calls": calls["n"]}
    await r.stop()
    return out


# ---------------------------------------------------------------- C8
@probe(
    "C8",
    "DETERMINISM: identical event sequence over 5 runs yields identical state+context+action trace",
    {"unique_results": 1},
)
async def c8():
    seq = ["NEW", "ACK", "PARTIAL", "PARTIAL", "FILL"]

    async def run_once() -> str:
        trace: List[str] = []

        def rec(name):
            def f(i, c, e, a):  # noqa: ANN001
                trace.append(f"{name}:{e.type}")

            return f

        def fill(i, c, e, a):  # noqa: ANN001
            c["filled"] += e.payload.get("qty", 0)
            trace.append(f"fill:{c['filled']}")

        cfg = {
            "id": "oms",
            "initial": "new",
            "context": {"filled": 0},
            "states": {
                "new": {"entry": ["e_new"], "on": {"NEW": "pending"}},
                "pending": {
                    "entry": ["e_pending"],
                    "on": {"ACK": "live"},
                },
                "live": {
                    "entry": ["e_live"],
                    "on": {
                        "PARTIAL": {"actions": ["fill"]},
                        "FILL": {"target": "filled", "actions": ["fill"]},
                    },
                },
                "filled": {"entry": ["e_filled"], "type": "final"},
            },
        }
        logic = MachineLogic(
            actions={
                "e_new": rec("e_new"),
                "e_pending": rec("e_pending"),
                "e_live": rec("e_live"),
                "e_filled": rec("e_filled"),
                "fill": fill,
            }
        )
        i = await boot(cfg, logic)
        for ev in seq:
            await i.send(ev, qty=10)
            await asyncio.sleep(0.01)
        await asyncio.sleep(SETTLE)
        result = json.dumps(
            {
                "ids": sorted(i.current_state_ids),
                "ctx": dict(i.context),
                "trace": trace,
            },
            sort_keys=True,
        )
        await i.stop()
        return result

    results = {await run_once() for _ in range(5)}
    return {"unique_results": len(results)}


# ---------------------------------------------------------------- C9
@probe(
    "C9",
    "DETERMINISM with parallel regions: repeated identical runs agree",
    {"unique_results": 1},
)
async def c9():
    async def run_once() -> str:
        trace: List[str] = []

        def rec(name):
            def f(i, c, e, a):  # noqa: ANN001
                trace.append(name)

            return f

        cfg = {
            "id": "m",
            "initial": "P",
            "context": {},
            "states": {
                "P": {
                    "type": "parallel",
                    "states": {
                        "R1": {
                            "initial": "a",
                            "states": {
                                "a": {
                                    "entry": ["r1a"],
                                    "on": {"E": "b"},
                                },
                                "b": {"entry": ["r1b"]},
                            },
                        },
                        "R2": {
                            "initial": "a",
                            "states": {
                                "a": {
                                    "entry": ["r2a"],
                                    "on": {"E": "b"},
                                },
                                "b": {"entry": ["r2b"]},
                            },
                        },
                        "R3": {
                            "initial": "a",
                            "states": {
                                "a": {
                                    "entry": ["r3a"],
                                    "on": {"E": "b"},
                                },
                                "b": {"entry": ["r3b"]},
                            },
                        },
                    },
                }
            },
        }
        names = ["r1a", "r1b", "r2a", "r2b", "r3a", "r3b"]
        logic = MachineLogic(actions={n: rec(n) for n in names})
        i = await boot(cfg, logic)
        await i.send("E")
        await asyncio.sleep(SETTLE)
        result = json.dumps(
            {"ids": sorted(i.current_state_ids), "trace": trace},
            sort_keys=True,
        )
        await i.stop()
        return result

    results = {await run_once() for _ in range(5)}
    return {"unique_results": len(results)}


# ---------------------------------------------------------------- C10
@probe(
    "C10",
    "raise: a raised event is processed before the next external event",
    ["entry", "RAISED", "EXTERNAL"],
)
async def c10():
    trace: List[str] = []

    def mark_entry(i, c, e, a):  # noqa: ANN001
        trace.append("entry")

    def rec(i, c, e, a):  # noqa: ANN001
        trace.append(e.type)

    cfg = {
        "id": "m",
        "initial": "a",
        "context": {},
        "states": {
            "a": {"on": {"GO": "b"}},
            "b": {
                "entry": [
                    "mark_entry",
                    {"type": "raise", "params": {"event": "RAISED"}},
                ],
                "on": {
                    "RAISED": {"actions": ["rec"]},
                    "EXTERNAL": {"actions": ["rec"]},
                },
            },
        },
    }
    logic = MachineLogic(actions={"mark_entry": mark_entry, "rec": rec})
    i = await boot(cfg, logic)
    await i.send("GO")
    await i.send("EXTERNAL")
    await asyncio.sleep(SETTLE)
    await i.stop()
    return trace


# ---------------------------------------------------------------- C11
@probe(
    "C11",
    "Event payload is exposed on event.payload and arbitrary shapes survive",
    {"payload": {"price": 1.5, "tags": ["a"], "nested": {"k": 1}}},
)
async def c11():
    seen: Dict[str, Any] = {}

    def cap(i, c, e, a):  # noqa: ANN001
        seen["payload"] = dict(e.payload)

    cfg = {
        "id": "m",
        "initial": "s",
        "context": {},
        "states": {"s": {"on": {"E": {"actions": ["cap"]}}}},
    }
    i = await boot(cfg, MachineLogic(actions={"cap": cap}))
    await i.send("E", price=1.5, tags=["a"], nested={"k": 1})
    await asyncio.sleep(SETTLE)
    await i.stop()
    return {"payload": seen.get("payload")}


# ---------------------------------------------------------------- C12
@probe(
    "C12",
    "No event payload VALIDATION: a wrong-typed payload is accepted silently",
    {"raised": None, "payload": {"qty": "not-a-number"}},
)
async def c12():
    seen: Dict[str, Any] = {}

    def cap(i, c, e, a):  # noqa: ANN001
        seen["payload"] = dict(e.payload)

    cfg = {
        "id": "m",
        "initial": "s",
        "context": {},
        "states": {"s": {"on": {"E": {"actions": ["cap"]}}}},
    }
    i = await boot(cfg, MachineLogic(actions={"cap": cap}))
    raised = None
    try:
        await i.send("E", qty="not-a-number")
        await asyncio.sleep(SETTLE)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    await i.stop()
    return {"raised": raised, "payload": seen.get("payload")}


# ---------------------------------------------------------------- C13
@probe(
    "C13",
    "An action raising an exception: does it kill the interpreter or get swallowed?",
    {"running": True, "later_event_handled": True},
)
async def c13():
    flags = {"later": False}

    def boom(i, c, e, a):  # noqa: ANN001
        raise ValueError("action blew up")

    def later(i, c, e, a):  # noqa: ANN001
        flags["later"] = True

    cfg = {
        "id": "m",
        "initial": "s",
        "context": {},
        "states": {
            "s": {
                "on": {
                    "BOOM": {"actions": ["boom"]},
                    "LATER": {"actions": ["later"]},
                }
            }
        },
    }
    logic = MachineLogic(actions={"boom": boom, "later": later})
    i = await boot(cfg, logic)
    try:
        await i.send("BOOM")
        await asyncio.sleep(SETTLE)
    except Exception:  # noqa: BLE001
        pass
    running = i.is_running
    try:
        await i.send("LATER")
        await asyncio.sleep(SETTLE)
    except Exception:  # noqa: BLE001
        pass
    out = {"running": running, "later_event_handled": flags["later"]}
    try:
        await i.stop()
    except Exception:  # noqa: BLE001
        pass
    return out


# ---------------------------------------------------------------- C14
@probe(
    "C14",
    "Unknown action name in config raises at create_machine time (fail loud)",
    "ImplementationMissingError",
)
async def c14():
    cfg = {
        "id": "m",
        "initial": "s",
        "context": {},
        "states": {"s": {"entry": ["does_not_exist"]}},
    }
    try:
        machine = create_machine(cfg, logic=MachineLogic())
        i = await Interpreter(machine).start()
        await asyncio.sleep(SETTLE)
        st = sorted(i.current_state_ids)
        await i.stop()
        return f"NO ERROR - started in {st}"
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__


# ---------------------------------------------------------------- C15
@probe(
    "C15",
    "Unknown target state name in config: fails loud at create or at transition?",
    "raised-at-some-point",
)
async def c15():
    cfg = {
        "id": "m",
        "initial": "s",
        "context": {},
        "states": {"s": {"on": {"GO": "nowhere_at_all"}}},
    }
    try:
        machine = create_machine(cfg, logic=MachineLogic())
    except Exception as exc:  # noqa: BLE001
        return f"create_machine:{type(exc).__name__}"
    i = await Interpreter(machine).start()
    try:
        await i.send("GO")
        await asyncio.sleep(SETTLE)
    except Exception as exc:  # noqa: BLE001
        await i.stop()
        return f"send:{type(exc).__name__}"
    st = sorted(i.current_state_ids)
    running = i.is_running
    try:
        await i.stop()
    except Exception:  # noqa: BLE001
        pass
    return f"silent: state={st} running={running}"


# ---------------------------------------------------------------- C16
@probe(
    "C16",
    "sendTo addressing: invoke `id` / `systemId` must be usable as the target name",
    {"by_service_key": "PONG", "by_invoke_id": "PONG", "by_system_id": "PONG"},
)
async def c16():
    child_cfg = {
        "id": "child",
        "initial": "idle",
        "context": {},
        "states": {
            "idle": {
                "on": {
                    "PING": {
                        "actions": [
                            {
                                "type": "send_parent",
                                "params": {"event": "PONG"},
                            }
                        ]
                    }
                }
            }
        },
    }
    child = create_machine(child_cfg, logic=MachineLogic())

    async def attempt(to: str, invoke: Dict[str, Any]):
        seen: Dict[str, Any] = {}

        def cap(i, c, e, a):  # noqa: ANN001
            seen["reply"] = e.type

        parent_cfg = {
            "id": "p",
            "initial": "run",
            "context": {},
            "states": {
                "run": {
                    "invoke": invoke,
                    "on": {
                        "POKE": {
                            "actions": [
                                {
                                    "type": "send_to",
                                    "params": {"to": to, "event": "PING"},
                                }
                            ]
                        },
                        "PONG": {"target": "got", "actions": ["cap"]},
                    },
                },
                "got": {},
            },
        }
        logic = MachineLogic(actions={"cap": cap}, services={"child": child})
        i = await boot(parent_cfg, logic)
        await asyncio.sleep(0.1)
        await i.send("POKE")
        await asyncio.sleep(0.25)
        await i.stop()
        return seen.get("reply")

    return {
        "by_service_key": await attempt(
            "child", {"id": "kid", "src": "child"}
        ),
        "by_invoke_id": await attempt("kid", {"id": "kid", "src": "child"}),
        "by_system_id": await attempt(
            "kid", {"id": "kid", "src": "child", "systemId": "kid"}
        ),
    }


# ---------------------------------------------------------------- C17
@probe(
    "C17",
    "Events arriving while the machine is in a transient/invoking state are "
    "SILENTLY DROPPED (no queue, no deferral, no error)",
    {"unique": 1, "filled": 30, "final": ["oms.filled"]},
)
async def c17():
    async def run_once() -> str:
        trace: List[str] = []

        def rec(n):
            def f(i, c, e, a):  # noqa: ANN001
                trace.append(f"{n}:{e.type}")

            return f

        def fill(i, c, e, a):  # noqa: ANN001
            c["filled"] += e.payload.get("qty", 0)

        async def svc(i, c, e):  # noqa: ANN001
            await asyncio.sleep(0.005)
            return {"ok": True}

        cfg = {
            "id": "oms",
            "initial": "new",
            "context": {"filled": 0},
            "states": {
                "new": {"on": {"NEW": "pending"}},
                "pending": {
                    "invoke": {
                        "id": "ack",
                        "src": "svc",
                        "onDone": "live",
                    }
                },
                "live": {
                    "on": {
                        "PARTIAL": {"actions": ["fill"]},
                        "FILL": {"target": "filled", "actions": ["fill"]},
                    }
                },
                "filled": {"type": "final"},
            },
        }
        logic = MachineLogic(
            actions={"fill": fill, "rec": rec("rec")}, services={"svc": svc}
        )
        i = await boot(cfg, logic)
        # 💥 Burst-send with no awaiting of the intermediate invoke.
        await i.send("NEW")
        for _ in range(2):
            await i.send("PARTIAL", qty=10)
        await i.send("FILL", qty=10)
        await asyncio.sleep(0.3)
        result = json.dumps(
            {"ids": sorted(i.current_state_ids), "ctx": dict(i.context)},
            sort_keys=True,
        )
        await i.stop()
        return result

    results = [await run_once() for _ in range(10)]
    parsed = json.loads(results[0])
    return {
        "unique": len(set(results)),
        "filled": parsed["ctx"]["filled"],
        "final": parsed["ids"],
    }


if __name__ == "__main__":
    run_all("03_context_snapshot_determinism")
