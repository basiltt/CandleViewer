"""m11 — D6-fuzz: #116 engine parity for plain-`def` services is broken by
the #149 `service_executor` change.

#116's contract: "a plain-sync `invoke` completes at the same point on both
engines". #149 moved plain-`def` services off the loop onto a
`ThreadPoolExecutor` and claims "the entering *macrostep* awaits the result,
so #116's ordering holds".

It does not. On the async engine `start()` RETURNS with the machine still in
the invoking state; the completion lands some time later. The sync engine
completes the service inside `start()`. An event sent immediately after
`start()` therefore sees a different configuration on each engine.

This reruns the exact prior-round oracle: `(GO, CANCEL) x 10`.
"""
from __future__ import annotations
import asyncio, copy, logging, sys, time
logging.disable(logging.CRITICAL)
from xstate_statemachine import (
    create_machine, MachineLogic, Interpreter, SyncInterpreter,
)

CFG = {
    "id": "m", "initial": "idle", "context": {"ok": 0, "cancel": 0},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {
            "invoke": {"id": "i", "src": "plain",
                       "onDone": {"target": "idle", "actions": ["ok"]}},
            "on": {"CANCEL": {"target": "idle", "actions": ["cancel"]}},
        },
    },
}


def logic():
    return MachineLogic(
        actions={"ok": lambda i, c, e, a: c.__setitem__("ok", c["ok"] + 1),
                 "cancel": lambda i, c, e, a: c.__setitem__(
                     "cancel", c["cancel"] + 1)},
        guards={},
        services={"plain": lambda i, c, e: {"v": 1}},   # plain def
    )


def run_sync():
    it = SyncInterpreter(create_machine(copy.deepcopy(CFG), logic=logic()))
    it.start()
    for _ in range(10):
        it.send("GO")
        it.send("CANCEL")
    return dict(it.context)


async def run_async():
    it = Interpreter(create_machine(copy.deepcopy(CFG), logic=logic()))
    await asyncio.wait_for(it.start(), timeout=10)
    for _ in range(10):
        await asyncio.wait_for(it.send("GO", wait=True), timeout=10)
        await asyncio.wait_for(it.send("CANCEL", wait=True), timeout=10)
    out = dict(it.context)
    try:
        await asyncio.wait_for(it.stop(), timeout=5)
    except Exception:
        pass
    return out


# --- second probe: does start() settle a plain-def invoke? ---------------
START_CFG = {
    "id": "m", "initial": "a",
    "states": {
        "a": {"invoke": {"id": "i", "src": "plain", "onDone": "b"}},
        "b": {"on": {"GO": "c"}},
        "c": {},
    },
}


def start_sync():
    it = SyncInterpreter(create_machine(copy.deepcopy(START_CFG),
                                        logic=logic()))
    it.start()
    after_start = sorted(it.current_state_ids)
    it.send("GO")
    return after_start, sorted(it.current_state_ids)


async def start_async():
    it = Interpreter(create_machine(copy.deepcopy(START_CFG), logic=logic()))
    await asyncio.wait_for(it.start(), timeout=10)
    after_start = sorted(it.current_state_ids)
    await asyncio.wait_for(it.send("GO", wait=True), timeout=10)
    out = (after_start, sorted(it.current_state_ids))
    try:
        await asyncio.wait_for(it.stop(), timeout=5)
    except Exception:
        pass
    return out


def main(trials=10):
    s = run_sync()
    a = asyncio.run(run_async())
    print(f"#116 (GO,CANCEL)x10  sync={s}  async={a}  "
          f"{'PARITY' if s == a else 'DIVERGENT'}", flush=True)

    ss = start_sync()
    diverge = 0
    sample = None
    for _ in range(trials):
        aa = asyncio.run(start_async())
        if aa != ss:
            diverge += 1
            sample = sample or aa
    print(f"start()-settles-invoke  sync=(after_start={ss[0]}, after_GO={ss[1]})"
          f"  async divergent {diverge}/{trials} sample={sample}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
