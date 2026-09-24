# -*- coding: utf-8 -*-
"""Verify #175 (Case D) on main @ 6db65d8: does stop() resolve EVERY
outstanding receipt for a REUSED `Event` instance racing it with
InterpreterStoppedError -- no ordinary success receipt leaks past stop()?

Matrix: {def, async def} action bodies (this bug is about receipt
bookkeeping, not services, but action-hook parity matters per round-7
scope, so both action kinds are exercised) x concurrent racers.

Criteria (from issue #175 "Ask"):
 1. Every outstanding duplicate-Event-instance receipt racing stop() is
    resolved with InterpreterStoppedError OR ordinary success IF (and
    only if) it was genuinely applied before stop.
 2. No crashed/unexpected receipt outcomes.
 3. The regression: across many trials, zero receipts land as ordinary
    success for events that were still queued (unapplied) at stop() --
    i.e. `applied == 0` implies all receipts are InterpreterStoppedError
    (mirrors tests/test_round7_findings.py::TestStopResolvesQueuedDuplicateInstanceReceipts).
"""
import asyncio
import sys

from xstate_statemachine import Event, Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import InterpreterStoppedError

CFG = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"EV": {"actions": ["slow"]}}}},
}


async def one_trial(is_async_action: bool, n_racers: int):
    if is_async_action:
        async def slow(i, c, e, a=None):
            c["n"] += 1
    else:
        def slow(i, c, e, a=None):
            c["n"] += 1

    m = create_machine(CFG, logic=MachineLogic(actions={"slow": slow}))
    i = Interpreter(m)
    await i.start()

    ev = Event(type="EV", payload={})

    async def racer():
        try:
            return await i.send(ev, wait=True)
        except Exception as exc:  # pragma: no cover - defensive
            return exc

    tasks = [asyncio.create_task(racer()) for _ in range(n_racers)]
    await asyncio.sleep(0)
    stop_task = asyncio.create_task(i.stop())
    results = await asyncio.gather(*tasks, stop_task, return_exceptions=True)
    receipts = results[:-1]
    applied = i.context["n"]

    ok_success = []
    ok_stopped = []
    other = []
    for r in receipts:
        if isinstance(r, Exception):
            other.append(r)
            continue
        if r.error is not None and isinstance(r.error, InterpreterStoppedError):
            ok_stopped.append(r)
        elif r.error is None:
            ok_success.append(r)
        else:
            other.append(r)

    return len(ok_success), len(ok_stopped), len(other), applied


def run_matrix(is_async_action: bool, n_trials: int = 20, n_racers: int = 20):
    total_success = 0
    total_other = 0
    total_bad_success = 0  # success receipts when applied==0 (the exact regression)
    for _ in range(n_trials):
        s, st, o, applied = asyncio.run(one_trial(is_async_action, n_racers))
        total_success += s
        total_other += o
        if applied == 0:
            total_bad_success += s
    return total_success, total_other, total_bad_success


if __name__ == "__main__":
    results = {}
    for kind, is_async in (("def", False), ("async def", True)):
        s, o, bad = run_matrix(is_async)
        # criterion 2: no crashed outcomes
        c2 = o == 0
        # criterion 3: no receipt lands as ordinary success while nothing
        # was actually applied (i.e. the Case D regression: queued-at-stop
        # receipts must be InterpreterStoppedError, never plain success)
        c3 = bad == 0
        ok = c2 and c3
        results[kind] = (ok, s, o, bad)

    print("=== CELL TABLE #175 (Case D) ===")
    print(f"{'action-kind':<12}{'result':<8}success_total  other_total  bad_success(applied=0)")
    all_ok = True
    for kind, (ok, s, o, bad) in results.items():
        res = "PASS" if ok else "FAIL"
        all_ok = all_ok and ok
        print(f"{kind:<12}{res:<8}{s:<15}{o:<13}{bad}")

    print("\nRESULT:", "PASS (Case D fixed: stop() resolves every queued "
          "duplicate-instance receipt correctly)" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 1)
