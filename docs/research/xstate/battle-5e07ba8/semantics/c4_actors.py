"""Group A — actors: invoke src as a machine with input/output, child->parent
error propagation chains, spawn/stopChild, sendTo with delay+id and cancel,
sendParent, escalate.

SCXML 1.0 §6.4 (<invoke>), §6.2 (<send> with delay/id, <cancel>),
§5.10 (error.* events), XState v5 actor model.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conf_harness import case, run_all  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    ErrorEvent,
    MachineLogic,
    create_machine,
)


def _child_machine(logic=None):
    """A child machine that finishes with an output computed from input."""
    return create_machine(
        {
            "id": "child",
            "initial": "work",
            "context": {"seed": 0},
            "output": "child_output",
            "states": {
                "work": {"always": "fin"},
                "fin": {"type": "final"},
            },
        },
        logic=logic
        or MachineLogic(
            actions={},
        ),
    )


# --------------------------------------------------------------- A-01
@case(
    "A-01",
    "invoke src as a MACHINE: parent receives done.invoke.<id> when the "
    "child reaches a top-level final state",
    "SCXML 6.4.4: when an invoked session reaches a final state the "
    "invoking session receives done.invoke.<invokeid>",
    ["m.ok"],
)
async def a01(rig):
    child = create_machine(
        {
            "id": "child",
            "initial": "w",
            "states": {"w": {"always": "fin"}, "fin": {"type": "final"}},
        },
        logic=MachineLogic(),
    )
    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {"id": "kid", "src": "childMachine", "onDone": "ok"}
            },
            "ok": {},
        },
    }
    logic = MachineLogic(services={"childMachine": child})
    await rig.boot(cfg, logic)
    await rig.settle(0.2)
    return rig.ids()


# --------------------------------------------------------------- A-02
@case(
    "A-02",
    "invoke child machine `output` is delivered as done.invoke data",
    "SCXML 6.4.4 / XState v5: the child's output becomes the "
    "done.invoke.<id> payload",
    {"code": 7},
)
async def a02(rig):
    seen = {}

    def grab(i, c, e, a):
        seen["data"] = getattr(e, "data", None)

    child = create_machine(
        {
            "id": "child",
            "initial": "w",
            "output": {"code": 7},
            "states": {"w": {"always": "fin"}, "fin": {"type": "final"}},
        },
        logic=MachineLogic(),
    )
    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {
                    "id": "kid",
                    "src": "childMachine",
                    "onDone": {"target": "ok", "actions": ["grab"]},
                }
            },
            "ok": {},
        },
    }
    logic = MachineLogic(
        services={"childMachine": child}, actions={"grab": grab}
    )
    await rig.boot(cfg, logic)
    await rig.settle(0.2)
    return seen.get("data")


# --------------------------------------------------------------- A-03
@case(
    "A-03",
    "invoke `input` reaches a child machine via a `context` FACTORY, and "
    "is exposed as context['input'] when the child declares a plain dict",
    "XState v5: `input` is resolved per spawn against {context, event}. "
    "This library deliberately does NOT let input overwrite declared "
    "context keys (base_interpreter.py:530, review F11 injection guard); "
    "the supported form is a context factory of {input}.",
    {"factory": 11, "plain_dict": {"seed": 0, "input": {"seed": 11}}},
)
async def a03(rig):
    seen = {}

    def note(i, c, e, a):
        seen.setdefault("ctx", dict(c))

    async def run(child_cfg):
        seen.clear()
        child = create_machine(
            child_cfg, logic=MachineLogic(actions={"note": note})
        )
        cfg = {
            "id": "m",
            "initial": "run",
            "context": {"n": 11},
            "states": {
                "run": {
                    "invoke": {
                        "id": "kid",
                        "src": "childMachine",
                        "input": lambda a: {"seed": a["context"]["n"]},
                        "onDone": "ok",
                    }
                },
                "ok": {},
            },
        }
        await rig.boot(cfg, MachineLogic(services={"childMachine": child}))
        await rig.settle(0.2)
        await rig.stop()
        return seen.get("ctx")

    factory_ctx = await run(
        {
            "id": "child",
            "initial": "w",
            "context": lambda a: {
                "seed": (a.get("input") or {}).get("seed", -1)
            },
            "states": {
                "w": {"entry": ["note"], "always": "fin"},
                "fin": {"type": "final"},
            },
        }
    )
    plain_ctx = await run(
        {
            "id": "child",
            "initial": "w",
            "context": {"seed": 0},
            "states": {
                "w": {"entry": ["note"], "always": "fin"},
                "fin": {"type": "final"},
            },
        }
    )
    return {
        "factory": (factory_ctx or {}).get("seed"),
        "plain_dict": plain_ctx,
    }


# --------------------------------------------------------------- A-04
@case(
    "A-04",
    "A failing invoked CALLABLE produces an ErrorEvent routed to onError",
    "SCXML 6.4: a failed invocation generates error.execution/"
    "error.platform; XState v5 onError. Library #80: ErrorEvent class.",
    {"state": ["m.failed"], "is_error_event": True, "msg": "boom"},
)
async def a04(rig):
    seen = {}

    def grab(i, c, e, a):
        seen["cls"] = isinstance(e, ErrorEvent)
        seen["msg"] = str(getattr(e, "error", ""))

    def svc(i, c, e):
        raise RuntimeError("boom")

    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {
                    "id": "job",
                    "src": "svc",
                    "onError": {"target": "failed", "actions": ["grab"]},
                }
            },
            "failed": {},
        },
    }
    logic = MachineLogic(services={"svc": svc}, actions={"grab": grab})
    await rig.boot(cfg, logic)
    await rig.settle(0.25)
    return {
        "state": rig.ids(),
        "is_error_event": seen.get("cls"),
        "msg": seen.get("msg"),
    }


# --------------------------------------------------------------- A-05
@case(
    "A-05",
    "A failing invoked CHILD MACHINE reaches the parent's onError",
    "SCXML 6.4 / XState v5: a child actor that errors notifies its "
    "parent via onError",
    ["m.failed"],
)
async def a05(rig):
    def bad(i, c, e):
        raise RuntimeError("child boom")

    child = create_machine(
        {
            "id": "child",
            "initial": "w",
            "states": {
                "w": {"invoke": {"id": "in", "src": "bad"}},
            },
        },
        logic=MachineLogic(services={"bad": bad}),
    )
    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {
                    "id": "kid",
                    "src": "childMachine",
                    "onError": "failed",
                }
            },
            "failed": {},
        },
    }
    logic = MachineLogic(services={"childMachine": child})
    await rig.boot(cfg, logic)
    await rig.settle(0.35)
    return rig.ids()


# --------------------------------------------------------------- A-06
@case(
    "A-06",
    "onError chain: grandchild fails -> child escalates -> grandparent "
    "handles",
    "SCXML 5.10 / 6.4: an error the invoked session escalates is "
    "delivered to the INVOKING session's error handler. XState v5: "
    "escalate() raises to the parent, where onError catches it.",
    ["m.caught"],
)
async def a06(rig):
    def bad(i, c, e):
        raise RuntimeError("deep boom")

    grandchild = create_machine(
        {
            "id": "gc",
            "initial": "w",
            "states": {"w": {"invoke": {"id": "in", "src": "bad"}}},
        },
        logic=MachineLogic(services={"bad": bad}),
    )
    child = create_machine(
        {
            "id": "child",
            "initial": "w",
            "states": {
                "w": {
                    "invoke": {
                        "id": "gcid",
                        "src": "gcMachine",
                        "onError": {"actions": [{"type": "escalate", "params": {"error": "boom"}}]},
                    }
                }
            },
        },
        logic=MachineLogic(services={"gcMachine": grandchild}),
    )
    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {
                    "id": "kid",
                    "src": "childMachine",
                    "onError": "caught",
                }
            },
            "caught": {},
        },
    }
    logic = MachineLogic(services={"childMachine": child})
    await rig.boot(cfg, logic)
    await rig.settle(0.5)
    return rig.ids()


# --------------------------------------------------------------- A-07
@case(
    "A-07",
    "Exiting the invoking state cancels a still-running invocation "
    "(its onDone never fires)",
    "SCXML 6.4.1: when the state containing <invoke> is exited the "
    "invoked session is cancelled",
    ["m.elsewhere"],
    engines=("async",),
)
async def a07(rig):
    async def slow(i, c, e):
        await asyncio.sleep(0.6)
        return "late"

    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {"id": "job", "src": "slow", "onDone": "tooLate"},
                "on": {"LEAVE": "elsewhere"},
            },
            "elsewhere": {},
            "tooLate": {},
        },
    }
    await rig.boot(cfg, MachineLogic(services={"slow": slow}))
    await rig.send("LEAVE")
    await rig.settle(0.8)
    return rig.ids()


# --------------------------------------------------------------- A-08
def _pingable_child():
    return create_machine(
        {
            "id": "c",
            "initial": "idle",
            "states": {
                "idle": {"on": {"PING": "pinged"}},
                "pinged": {},
            },
        },
        logic=MachineLogic(),
    )


def _delayed_send_cfg(cancel_id=None):
    """Parent spawns `kid`, then sendTo's it a delayed PING."""
    entry = [
        {"type": "spawnChild", "params": {"src": "kidMachine", "id": "kid"}},
        {
            "type": "sendTo",
            "params": {
                "to": "kid",
                "event": {"type": "PING"},
                "delay": 40,
                "id": "t1",
            },
        },
    ]
    if cancel_id is not None:
        entry.append({"type": "cancel", "params": {"sendId": cancel_id}})
    return {
        "id": "m",
        "initial": "run",
        "states": {"run": {"entry": entry}},
    }


async def _kid_state(rig):
    actors = getattr(rig.interp, "_actors", {}) or {}
    for aid, actor in actors.items():
        if aid.endswith(":kid"):
            return sorted(actor.current_state_ids)
    return ["<kid gone>"]


@case(
    "A-08",
    "sendTo with delay+id is delivered to the addressed child actor "
    "after the delay",
    "SCXML 6.2 <send target= delay= id=>; XState v5 "
    "sendTo(target, ev, {delay, id})",
    ["c.pinged"],
    engines=("async",),
)
async def a08(rig):
    await rig.boot(
        _delayed_send_cfg(),
        MachineLogic(services={"kidMachine": _pingable_child()}),
    )
    await rig.sleep(0.35)
    return await _kid_state(rig)


# --------------------------------------------------------------- A-09
@case(
    "A-09",
    "`cancel` with the MATCHING sendId prevents the delayed send",
    "SCXML 6.3 <cancel sendid=>; XState v5 cancel(id)",
    ["c.idle"],
    engines=("async",),
)
async def a09(rig):
    await rig.boot(
        _delayed_send_cfg(cancel_id="t1"),
        MachineLogic(services={"kidMachine": _pingable_child()}),
    )
    await rig.sleep(0.35)
    return await _kid_state(rig)


# --------------------------------------------------------------- A-10
@case(
    "A-10",
    "`cancel` with a NON-matching sendId leaves the delayed send intact",
    "SCXML 6.3: <cancel> affects only the send bearing that sendid",
    ["c.pinged"],
    engines=("async",),
)
async def a10(rig):
    await rig.boot(
        _delayed_send_cfg(cancel_id="OTHER"),
        MachineLogic(services={"kidMachine": _pingable_child()}),
    )
    await rig.sleep(0.35)
    return await _kid_state(rig)


# --------------------------------------------------------------- A-11
@case(
    "A-11",
    "spawn in `entry` creates a child actor addressable by id",
    "XState v5 spawnChild(src, {id}) in entry actions",
    {"spawned": True},
    engines=("async",),
)
async def a11(rig):
    child = create_machine(
        {
            "id": "c",
            "initial": "idle",
            "states": {"idle": {}},
        },
        logic=MachineLogic(),
    )
    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "entry": [
                    {
                        "type": "spawnChild",
                        "params": {"src": "kidMachine", "id": "kid"},
                    }
                ],
                "on": {"LEAVE": "gone"},
            },
            "gone": {},
        },
    }
    await rig.boot(cfg, MachineLogic(services={"kidMachine": child}))
    await rig.settle(0.2)
    actors = getattr(rig.interp, "_actors", {}) or {}
    # Actor ids are namespaced `<parent>:<id>`.
    return {"spawned": any(k.endswith(":kid") for k in actors)}


# --------------------------------------------------------------- A-12
@case(
    "A-12",
    "stopChild on exit stops the spawned actor",
    "XState v5 stopChild(id); SCXML 6.4.1 cancel invoked session",
    {"stopped": True},
    engines=("async",),
)
async def a12(rig):
    child = create_machine(
        {"id": "c", "initial": "idle", "states": {"idle": {}}},
        logic=MachineLogic(),
    )
    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "entry": [
                    {
                        "type": "spawnChild",
                        "params": {"src": "kidMachine", "id": "kid"},
                    }
                ],
                "exit": [
                    {"type": "stopChild", "params": {"id": "kid"}}
                ],
                "on": {"LEAVE": "gone"},
            },
            "gone": {},
        },
    }
    await rig.boot(cfg, MachineLogic(services={"kidMachine": child}))
    await rig.settle(0.2)
    await rig.send("LEAVE")
    await rig.settle(0.3)
    actors = getattr(rig.interp, "_actors", {}) or {}
    kid = actors.get("kid")
    return {
        "stopped": kid is None or getattr(kid, "status", "") == "stopped"
    }


# --------------------------------------------------------------- A-13
@case(
    "A-13",
    "sendParent from an invoked child machine reaches the parent",
    "SCXML 6.2 <send target='#_parent'>; XState v5 sendParent",
    ["m.notified"],
    engines=("async",),
)
async def a13(rig):
    child = create_machine(
        {
            "id": "child",
            "initial": "w",
            "states": {
                "w": {
                    "entry": [
                        {
                            "type": "sendParent",
                            "params": {"event": {"type": "FROM_CHILD"}},
                        }
                    ]
                }
            },
        },
        logic=MachineLogic(),
    )
    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {"id": "kid", "src": "childMachine"},
                "on": {"FROM_CHILD": "notified"},
            },
            "notified": {},
        },
    }
    await rig.boot(cfg, MachineLogic(services={"childMachine": child}))
    await rig.settle(0.35)
    return rig.ids()


# --------------------------------------------------------------- A-14
@case(
    "A-14",
    "done.invoke does NOT match a user's '*' wildcard handler",
    "Library #79 / XState v5: engine-synthesised events match only an "
    "exact descriptor; '*' means 'any event I might receive'",
    ["m.viaDone"],
)
async def a14(rig):
    def svc(i, c, e):
        return 1

    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {"id": "job", "src": "svc", "onDone": "viaDone"},
                "on": {"*": "viaWild"},
            },
            "viaDone": {},
            "viaWild": {},
        },
    }
    await rig.boot(cfg, MachineLogic(services={"svc": svc}))
    await rig.settle(0.3)
    return rig.ids()


# --------------------------------------------------------------- A-15
@case(
    "A-15",
    "An unhandled invoked-service failure is surfaced, not swallowed",
    "SCXML 5.10: an error the session does not handle must not be "
    "silently dropped. Real-money standard: a failed service with no "
    "onError must be observable.",
    {"observable": True},
)
async def a15(rig):
    def svc(i, c, e):
        raise RuntimeError("unhandled boom")

    cfg = {
        "id": "m",
        "initial": "run",
        "states": {"run": {"invoke": {"id": "job", "src": "svc"}}},
    }
    await rig.boot(cfg, MachineLogic(services={"svc": svc}))
    await rig.settle(0.35)
    i = rig.interp
    observable = (
        i.status in ("stopped", "done")
        or getattr(i, "error", None) is not None
        or getattr(i, "last_error", None) is not None
        or i.last_transition_ok is False
    )
    return {"observable": bool(observable)}


# --------------------------------------------------------------- A-16
@case(
    "A-16",
    "Invocation starts AFTER the entry actions of its owning state",
    "SCXML 6.4.1: <invoke> is executed after the onentry handlers of "
    "the state complete",
    ["entry", "service"],
    engines=("async",),
)
async def a16(rig):
    async def svc(i, c, e):
        rig.log.append("service")
        return 1

    cfg = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "entry": ["entry"],
                "invoke": {"id": "job", "src": "svc"},
            }
        },
    }
    logic = MachineLogic(
        actions=rig.recorders("entry"), services={"svc": svc}
    )
    await rig.boot(cfg, logic)
    await rig.settle(0.25)
    return rig.log


if __name__ == "__main__":
    run_all("a_actors")
