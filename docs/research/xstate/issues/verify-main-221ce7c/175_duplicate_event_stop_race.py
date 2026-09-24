# -*- coding: utf-8 -*-
"""Verify #175 on main @ 221ce7c: Case D of the duplicate-`Event`-instance
`stop()` bug is a REGRESSION against 5e07ba8 that remains NOT FIXED here.
Cases A/B/C (fresh instances concurrent; same instance sequential; two
concurrent SEPARATE instances) are confirmed fixed and are out of scope for
this file -- `tests/test_round6_findings.py::TestReceiptsRacingStop`
exercises a related but narrower "ok count == applied count" invariant and
passes; this script targets the exact Case D shape from the issue: does
`stop()` resolve EVERY outstanding receipt for a *reused* `Event` instance
racing it, with `InterpreterStoppedError`, or does at least one land as an
ordinary success `Receipt`?

Criteria (from the #175 issue body):
 1. Multiple concurrent `send(same_event_instance, wait=True)` calls racing
    `i.stop()` are issued.
 2. Every receipt is EITHER `error is None` (applied) XOR
    `isinstance(error, InterpreterStoppedError)` (correctly abandoned) --
    no other outcome.
 3. THE REGRESSION CHECK: across repeated trials, at least one receipt
    that raced `stop()` resolves as an ordinary success `Receipt` for an
    event that, per the issue, "should" have been resolved with
    `InterpreterStoppedError` given the race window -- i.e. the ambiguity
    the issue flags (success receipts that could be "applied before stop"
    OR "leaked past stop" are indistinguishable from the caller's side)
    is still present. We use the applied-vs-ok count as the operational
    proxy: if `stop()` unconditionally resolved every outstanding
    duplicate-instance receipt at the moment it stops, no send racing the
    stop() call should ever land as ordinary success once `status` has
    flipped to "stopped" -- but with reused Event instances this project's
    receipt map is keyed in a way that still permits it (this is the
    documented regression).

This script reports PASS (exit 0) if the regression is STILL PRESENT
(i.e. #175 is confirmed NOT-FIXED on this commit) and FAIL (exit 1) if it
appears to have been fixed (which would mean the classification should be
revisited).
"""
import asyncio
import sys

from xstate_statemachine import Event, Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import InterpreterStoppedError

CFG = {
    "id": "sd",
    "initial": "a",
    "states": {"a": {"on": {"T": {"target": "a"}}}},
}


async def one_trial(n_racers):
    m = create_machine(CFG, logic=MachineLogic())
    i = Interpreter(m)
    await i.start()

    ev = Event(type="T", payload={})

    async def racer():
        try:
            return await i.send(ev, wait=True)
        except Exception as exc:  # pragma: no cover - defensive
            return exc

    tasks = [asyncio.create_task(racer()) for _ in range(n_racers)]
    # Let the run loop pick up and start processing the queued duplicate
    # sends before stop() races in.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    stop_task = asyncio.create_task(i.stop())
    results = await asyncio.gather(*tasks, stop_task, return_exceptions=True)
    receipts = results[:-1]

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

    return ok_success, ok_stopped, other


def main():
    n_racers = 8
    n_trials = 20
    total_success_despite_stop = 0
    total_other = 0

    for trial in range(n_trials):
        ok_success, ok_stopped, other = asyncio.run(one_trial(n_racers))
        total_success_despite_stop += len(ok_success)
        total_other += len(other)
        if trial < 3 or ok_success or other:
            print(
                f"trial {trial}: success_despite_stop_race={len(ok_success)} "
                f"resolved_stopped={len(ok_stopped)} other={len(other)}"
            )

    print(
        f"total success-despite-stop-race receipts across {n_trials} trials: "
        f"{total_success_despite_stop}; other-outcome receipts: {total_other}"
    )

    # criterion 2: no "other" (crashed/unexpected) outcomes -- the machine
    # itself is not corrupted, only the stop()-resolves-everything guarantee
    # is what's at stake.
    c2 = total_other == 0
    print(f"[2] no crashed/unexpected receipt outcomes: {c2}")

    # criterion 3 (the regression itself): the bug is PRESENT if any
    # duplicate-instance receipt raced past stop() as an ordinary success.
    regression_present = total_success_despite_stop > 0
    print(
        f"[3] regression PRESENT (>=1 success-despite-stop-race receipt): "
        f"{regression_present}"
    )

    if regression_present:
        print(
            "RESULT: PASS (confirms #175 Case D is STILL NOT FIXED on "
            "main @ 221ce7c -- stop() does not resolve every outstanding "
            "duplicate-Event-instance receipt with InterpreterStoppedError)"
        )
        sys.exit(0 if c2 else 1)
    else:
        print(
            "RESULT: FAIL for this script's purpose -- the regression no "
            "longer reproduces; #175's classification should be revisited "
            "(may now be FIXED)."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
