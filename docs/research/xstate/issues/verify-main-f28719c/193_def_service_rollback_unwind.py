# -*- coding: utf-8 -*-
"""Verify #193 on f28719c: def-service executor handoff moved into the
engine-held task, so rollback/roll-forward cancels before submission.
Matrix: {def, async def} x {cancel-on-exit, rollback, always-rollforward}.
Async Interpreter only (construct is async-engine-specific per #193 scope
-- SyncInterpreter has no executor handoff / no invoke concurrency).
Standalone. Watchdog-protected.
"""
import asyncio
import sys
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

WATCHDOG_S = 30.0


def make_work(kind: str, delay: float, calls: list):
    if kind == "async def":
        async def work(i, c, e):
            calls.append("start")
            await asyncio.sleep(delay)
            return {"cursor": 4242}
    else:
        def work(i, c, e):
            calls.append("start")
            time.sleep(delay)
            return {"cursor": 4242}
    return work


async def cell_cancel_on_exit(kind: str) -> dict:
    cfg = {
        "id": "m",
        "initial": "idle",
        "context": {"cursor": 0},
        "states": {
            "idle": {"on": {"GO": "busy"}},
            "busy": {
                "invoke": {"id": "w", "src": "work", "onDone": {"target": "done", "actions": ["land"]}},
                "on": {"CANCEL": "cancelled"},
            },
            "done": {"on": {"CANCEL": {}}},
            "cancelled": {},
        },
    }

    def land(i, c, e, a):
        c["cursor"] = e.data["cursor"]

    calls: list = []
    work = make_work(kind, 0.15, calls)
    m = create_machine(cfg, logic=MachineLogic(services={"work": work}, actions={"land": land}))
    it = await Interpreter(m).start()
    go = asyncio.ensure_future(it.send("GO", wait=True))
    await asyncio.sleep(0.02)
    await asyncio.wait_for(it.send("CANCEL", wait=True), 5)
    try:
        await asyncio.wait_for(go, 5)
    except Exception:
        pass
    await asyncio.sleep(0.4)
    final = sorted(it.current_state_ids)
    cursor = it.context["cursor"]
    await it.stop()
    if kind == "async def":
        ok = final == ["m.cancelled"] and cursor == 0
    else:
        # documented plain-def contract: the entering step awaits the
        # service before CANCEL is even processed (#116/#149) -- onDone
        # lands in `busy`, then CANCEL is a declared no-op in `done`.
        ok = final == ["m.done"] and cursor == 4242
    return {"kind": kind, "final": final, "cursor": cursor, "ok": ok}


async def cell_rollback(kind: str) -> dict:
    cfg = {
        "id": "m",
        "initial": "idle",
        "actionErrorPolicy": "rollback",
        "states": {
            "idle": {"on": {"GO": "busy"}},
            "busy": {"entry": ["boom"], "invoke": {"id": "w", "src": "svc", "onDone": "done"}},
            "done": {},
        },
    }

    def boom(*a):
        raise RuntimeError("boom")

    calls: list = []
    svc = make_work(kind, 0.05, calls)
    m = create_machine(cfg, logic=MachineLogic(services={"svc": svc}, actions={"boom": boom}))
    it = await Interpreter(m).start()
    await it.send("GO", wait=True)
    await asyncio.sleep(0.3)
    value = it.value
    await it.stop()
    ok = value == "idle" and calls == []
    return {"kind": kind, "value": value, "service_calls": calls, "ok": ok}


async def cell_always_rollforward(kind: str) -> dict:
    # SCXML: <invoke> runs as part of entering the state; `always` is
    # evaluated AFTER entry actions/invoke arm, so the service DOES start
    # even though `always` immediately leaves the state (matches
    # SyncInterpreter parity, per the library's own
    # test_always_rollforward_matches_sync). The contract here is PARITY
    # between engines/spellings, not "never starts".
    cfg = {
        "id": "m",
        "initial": "idle",
        "states": {
            "idle": {"on": {"GO": "busy"}},
            "busy": {"always": "out", "invoke": {"id": "w", "src": "svc", "onDone": "done"}},
            "out": {},
            "done": {},
        },
    }
    calls: list = []
    svc = make_work(kind, 0.05, calls)
    m = create_machine(cfg, logic=MachineLogic(services={"svc": svc}))
    it = await Interpreter(m).start()
    await it.send("GO", wait=True)
    await asyncio.sleep(0.3)
    value = it.value
    await it.stop()
    # Regression guard vs SyncInterpreter behaviour for the same shape.
    from xstate_statemachine import SyncInterpreter

    sync_calls: list = []

    def sync_svc(i, c, e):
        sync_calls.append("start")
        return 1

    sm = create_machine(cfg, logic=MachineLogic(services={"svc": sync_svc}))
    s = SyncInterpreter(sm).start()
    s.send("GO")
    # `def` parity with SyncInterpreter is the library's own stated
    # contract (test_always_rollforward_matches_sync uses a `def`/sync
    # lambda on both sides). `async def` is the interruptible spelling:
    # the roll-forward `always` fires in the same step before the
    # coroutine task gets a turn, so it is cancelled before it ever runs
    # -- consistent with #193's "async def remains the interruptible
    # kind" and with cancel-on-exit above.
    if kind == "async def":
        ok = value == "out" and calls == []
    else:
        ok = value == "out" == s.value and calls == sync_calls
    return {"kind": kind, "value": value, "service_calls": calls, "sync_value": s.value, "sync_calls": sync_calls, "ok": ok}


async def main() -> int:
    results = []
    for kind in ("def", "async def"):
        results.append(("cancel-on-exit", await asyncio.wait_for(cell_cancel_on_exit(kind), WATCHDOG_S)))
        results.append(("rollback", await asyncio.wait_for(cell_rollback(kind), WATCHDOG_S)))
        results.append(("always-rollforward", await asyncio.wait_for(cell_always_rollforward(kind), WATCHDOG_S)))
    ok = True
    for label, r in results:
        print(label, r)
        if not r["ok"]:
            ok = False
    print("VERDICT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
