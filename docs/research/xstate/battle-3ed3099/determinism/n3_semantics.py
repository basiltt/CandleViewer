"""N3 -- 50x byte-identical traces on BOTH engines, including the new inline
sync-service semantics (#116), plus a direct #116/#109/#108/#130 semantics
probe.

The headline determinism claim for a replay pipeline is: one script, 50 runs,
one digest. This runs the full dmachine comparison surface 50x per engine and
then asks the semantics questions the round-4 fixes claim to have settled.

REDUCED: 50 runs x 400-step script per engine (the prior track's 1000-step
x 50 campaign was re-run separately as d1 at 20x1000; this one keeps the
brief's 50x repeat count and shortens the script to fit the time bound).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from dmachine import (  # noqa: E402
    Recorder,
    TracePlugin,
    build,
    canon_snapshot,
    make_script,
)
from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

RUNS = 50
STEPS = 400


async def one_async(script):
    rec = Recorder()
    clock = SimulatedClock()
    i = Interpreter(build(rec), clock=clock)
    await i.start()
    for step in script:
        if step[0] == "tick":
            await clock.increment(step[1])
        else:
            await i.send(step[1], **step[2])
    snap = canon_snapshot(i.get_persisted_snapshot())
    await i.stop()
    return json.dumps(rec.actions), snap


def one_sync(script):
    rec = Recorder()
    clock = SimulatedClock()
    i = SyncInterpreter(build(rec), clock=clock)
    i.start()
    for step in script:
        if step[0] == "tick":
            clock.increment(step[1])
        else:
            i.send(step[1], **step[2])
    snap = canon_snapshot(i.get_persisted_snapshot())
    i.stop()
    return json.dumps(rec.actions), snap


# --- #116 inline sync service: completion ordering, both call shapes -------
S116 = {
    "id": "s116",
    "initial": "idle",
    "context": {"ok": 0, "cancel": 0},
    "states": {
        "idle": {"on": {"GO": "busy"}},
        "busy": {
            "invoke": {
                "id": "svc",
                "src": "work",
                "onDone": {"target": "idle", "actions": ["ok"]},
            },
            "on": {"CANCEL": {"target": "idle", "actions": ["cancel"]}},
        },
    },
}


def s116_logic():
    def ok(i, c, e, a):
        c["ok"] += 1

    def cancel(i, c, e, a):
        c["cancel"] += 1

    return MachineLogic(
        actions={"ok": ok, "cancel": cancel},
        services={"work": lambda i, c, e: {"v": 1}},
    )


async def probe_116():
    """(GO, CANCEL)x10 through four call shapes on both engines."""
    res = {}
    script = []
    for _ in range(10):
        script += ["GO", "CANCEL"]

    # sync, one-at-a-time
    s = SyncInterpreter(create_machine(S116, logic=s116_logic()))
    s.start()
    for e in script:
        s.send(e)
    res["sync_send_each"] = dict(s.context)
    s.stop()

    # sync, send_events batch
    s = SyncInterpreter(create_machine(S116, logic=s116_logic()))
    s.start()
    if hasattr(s, "send_events"):
        s.send_events(script)
        res["sync_send_events"] = dict(s.context)
    s.stop()

    # async, one-at-a-time
    a = Interpreter(create_machine(S116, logic=s116_logic()))
    await a.start()
    for e in script:
        await a.send(e)
    for _ in range(200):
        await asyncio.sleep(0)
    res["async_send_each"] = dict(a.context)
    await a.stop()

    a = Interpreter(create_machine(S116, logic=s116_logic()))
    await a.start()
    if hasattr(a, "send_events"):
        await a.send_events(script)
        for _ in range(200):
            await asyncio.sleep(0)
        res["async_send_events"] = dict(a.context)
    await a.stop()

    vals = {json.dumps(v, sort_keys=True) for v in res.values()}
    res["ALL_AGREE"] = len(vals) == 1
    res["distinct"] = sorted(vals)
    return res


# --- #109 done.invoke carries declared `output`, not private context -------
CHILD109 = {
    "id": "c109",
    "initial": "go",
    "context": {"secret": "DO-NOT-LEAK", "n": 7},
    "output": {"result": "final-answer"},
    "states": {"go": {"type": "final"}},
}
P109 = {
    "id": "p109",
    "initial": "wait",
    "context": {"got": None},
    "states": {
        "wait": {
            "invoke": {
                "id": "kid",
                "src": "kidMachine",
                "onDone": {"target": "done", "actions": ["grab"]},
            }
        },
        "done": {"type": "final"},
    },
}


async def probe_109():
    grabbed = {}

    def grab(i, c, e, a):
        grabbed["data"] = getattr(e, "data", None)
        c["got"] = repr(grabbed["data"])[:200]

    kid = create_machine(CHILD109, logic=MachineLogic())
    p = create_machine(
        P109,
        logic=MachineLogic(actions={"grab": grab}, services={"kidMachine": kid}),
    )
    i = Interpreter(p)
    await i.start()
    for _ in range(300):
        await asyncio.sleep(0)
    await i.stop()
    d = grabbed.get("data")
    txt = repr(d)
    return {
        "done_invoke_data": txt[:300],
        "leaks_private_context": "DO-NOT-LEAK" in txt,
        "carries_declared_output": "final-answer" in txt,
    }


# --- #108 a transition targeting the machine ROOT is rejected at build -----
ROOTT = {
    "id": "rt",
    "initial": "a",
    "states": {"a": {"on": {"GO": {"target": "#rt"}}}, "b": {}},
}


def probe_108():
    try:
        create_machine(ROOTT, logic=MachineLogic())
        return {"result": "NO-RAISE (accepted a root target)"}
    except Exception as e:  # noqa: BLE001
        return {"result": type(e).__name__, "msg": str(e)[:160]}


# --- #130 escalate from an invoked child reaches the parent's onError ------
CHILD130 = {
    "id": "c130",
    "initial": "boom",
    "states": {
        "boom": {
            "entry": [
                {"type": "escalate", "params": {"error": "child-blew-up"}}
            ]
        }
    },
}
P130 = {
    "id": "p130",
    "initial": "wait",
    "context": {"err": None},
    "states": {
        "wait": {
            "invoke": {
                "id": "kid",
                "src": "kidMachine",
                "onError": {"target": "failed", "actions": ["note_err"]},
            }
        },
        "failed": {"type": "final"},
    },
}


async def probe_130():
    seen = {}

    def note_err(i, c, e, a):
        seen["err"] = repr(getattr(e, "data", e))[:200]
        c["err"] = seen["err"]

    kid = create_machine(CHILD130, logic=MachineLogic())
    p = create_machine(
        P130,
        logic=MachineLogic(
            actions={"note_err": note_err}, services={"kidMachine": kid}
        ),
    )
    i = Interpreter(p)
    await i.start()
    for _ in range(300):
        await asyncio.sleep(0)
    state = sorted(s.id for s in i._active_state_nodes if not s.states)
    await i.stop()
    return {
        "parent_state": state,
        "onError_fired": "err" in seen,
        "error_payload": seen.get("err", None),
        "reached_failed": state == ["p130.failed"],
    }


async def main():
    script = make_script(STEPS)
    res = {}

    a = [await one_async(script) for _ in range(RUNS)]
    s = [one_sync(script) for _ in range(RUNS)]
    res["replay"] = {
        "runs": RUNS,
        "steps": STEPS,
        "async_distinct_action_traces": len({x[0] for x in a}),
        "async_distinct_final_snapshots": len({x[1] for x in a}),
        "sync_distinct_action_traces": len({x[0] for x in s}),
        "sync_distinct_final_snapshots": len({x[1] for x in s}),
        "cross_engine_actions_equal": a[0][0] == s[0][0],
        "cross_engine_snapshot_equal": a[0][1] == s[0][1],
    }

    res["116_completion_ordering"] = await probe_116()
    res["109_done_invoke_output"] = await probe_109()
    res["108_root_target"] = probe_108()
    res["130_escalate"] = await probe_130()

    for k, v in res.items():
        print(f"\n== {k} ==")
        for kk, vv in v.items():
            print(f"   {kk:34s}: {vv}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "n3_semantics.json"), "w") as f:
        json.dump(res, f, indent=2, default=str)
    print("\nwrote out/n3_semantics.json")


if __name__ == "__main__":
    asyncio.run(main())
