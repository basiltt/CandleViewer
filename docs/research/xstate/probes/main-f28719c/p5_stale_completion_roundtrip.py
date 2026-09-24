"""P5 (STANDALONE): #195's live-invocation gate is only a provenance test,
so a GENUINE but STALE completion still short-circuits a fresh invocation.

`_completion_is_for_live_invocation` returns `is_system_event(event)` and
nothing else; the docstring argues a stale completion "is impossible
because exiting cancels the work". The snapshot lane breaks that argument:
a `done.invoke.fetch` that was queued but not yet processed persists with
`"engine": true`, restores as engine-minted, and is delivered into a
restored machine whose `fetch` invocation has just been started afresh. The
old result drives `onDone` while the new service is still running.

Exit 1 = stale completion accepted.
"""
import asyncio, json, sys
from xstate_statemachine import (
    create_machine, Interpreter, MachineLogic,
)
from xstate_statemachine.events import engine_done, persist_event

CFG = {
    "id": "m",
    "initial": "loading",
    "context": {"result": None},
    "states": {
        "loading": {
            "invoke": {
                "id": "fetch",
                "src": "fetch",
                "onDone": {"target": "ready", "actions": ["store"]},
            },
        },
        "ready": {},
    },
}

STARTS = {"n": 0}


async def fetch(interp, ctx, ev):
    STARTS["n"] += 1
    await asyncio.sleep(1.0)
    return {"value": "FRESH"}


def store(interp, ctx, ev, adef=None):
    ctx["result"] = ev.data


def build():
    return create_machine(
        json.loads(json.dumps(CFG)),
        logic=MachineLogic(services={"fetch": fetch}, actions={"store": store}),
    )


async def main():
    # 1) Build a snapshot of a running machine in `loading` that carries an
    #    in-flight, genuine engine completion for a PREVIOUS invocation.
    i = await Interpreter(build()).start()
    blob = json.loads(json.dumps(i.get_persisted_snapshot()))
    await i.stop()
    stale = engine_done("done.invoke.fetch", {"value": "STALE"}, "fetch")
    rec = persist_event(stale)
    print("persisted record:", rec)
    blob["pending_events"] = [rec]

    # 2) Restore. The restored machine starts `fetch` afresh (1 s), and the
    #    stale completion is delivered immediately.
    j = Interpreter.from_snapshot(json.dumps(blob), build())
    await j.start()
    await asyncio.sleep(0.2)
    ids = sorted(j.current_state_ids)
    res = dict(j.context).get("result")
    await j.stop()
    return ids, res, STARTS["n"]


ids, res, starts = asyncio.run(asyncio.wait_for(main(), 25.0))
print(f"states={ids} context.result={res} fetch_invocations={starts}")
bad = res == {"value": "STALE"}
print("VERDICT:", "STALE COMPLETION DROVE onDone (bug)" if bad else "ignored (ok)")
sys.exit(1 if bad else 0)
