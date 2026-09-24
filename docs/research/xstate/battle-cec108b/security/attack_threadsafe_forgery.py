"""New attack: send_threadsafe(internal=True) forgery from an EXTERNAL
plain thread. #150 relies on internal=True/None auto-detection to decide
whether a threadsafe send is charged to maxIterations. A hostile/buggy
caller on a plain (non-context-inheriting) thread can pass internal=True
to exempt an unbounded stream of self-sends from the runaway-chain budget
entirely, turning a bounded safety net into an unbounded one -- test
whether the engine catches this or trusts the caller's claim blindly."""
import sys, asyncio, threading, time
sys.path.insert(0, "src")
from xstate_statemachine import create_machine, MachineLogic, Interpreter

count = {"n": 0}


def bump(interp, context, event, action_def):
    count["n"] += 1


cfg = {
    "id": "m",
    "initial": "a",
    "context": {},
    "max_iterations": 50,
    "states": {"a": {"on": {"GO": {"target": "a", "actions": ["bump"]}}}},
}
m = create_machine(cfg, logic=MachineLogic(actions={"bump": bump}))


async def main():
    interp = Interpreter(m)
    await interp.start()

    # Baseline: forge internal=False repeatedly from a plain thread and
    # confirm the budget DOES trip (sanity: budget works when honestly
    # classified as external).
    def honest_external():
        futs = []
        for _ in range(200):
            try:
                futs.append(interp.send_threadsafe("GO", internal=False))
            except Exception:
                break
        for f in futs:
            try:
                f.result(timeout=2)
            except Exception:
                pass

    t1 = threading.Thread(target=honest_external)
    t1.start()
    t1.join(timeout=10)
    await asyncio.sleep(0.3)
    baseline_count = count["n"]
    baseline_status = interp.status
    baseline_error = interp.last_error
    print(
        f"[baseline honest external] bump_count={baseline_count} "
        f"status={baseline_status} last_error={type(baseline_error).__name__ if baseline_error else None}"
    )

    await interp.stop()

    # Attack: forge internal=True from the SAME kind of plain thread.
    count["n"] = 0
    interp2 = Interpreter(m)
    await interp2.start()

    def forged_internal():
        futs = []
        for _ in range(200):
            try:
                futs.append(interp2.send_threadsafe("GO", internal=True))
            except Exception:
                break
        for f in futs:
            try:
                f.result(timeout=2)
            except Exception:
                pass

    t2 = threading.Thread(target=forged_internal)
    t2.start()
    t2.join(timeout=10)
    await asyncio.sleep(0.3)
    forged_count = count["n"]
    forged_status = interp2.status
    forged_error = interp2.last_error
    print(
        f"[forged internal=True]     bump_count={forged_count} "
        f"status={forged_status} last_error={type(forged_error).__name__ if forged_error else None}"
    )

    if forged_count >= 200 and (baseline_count < 200 or baseline_error is not None):
        print(
            "FINDING: internal=True is trusted verbatim from any thread; a "
            "plain external thread claiming internal=True delivers its full "
            "batch uncounted against maxIterations, while the honest "
            "internal=False run is budget-limited/trips. This lets an "
            "external producer bypass the runaway-chain protection entirely "
            "by lying about provenance -- no verification of the claim "
            "against actual call-site context is performed."
        )
    else:
        print("OK: no observable bypass in this run (see counts above).")

    await interp2.stop()


asyncio.run(main())
