"""Verify #152 on cec108b: guardErrorPolicy 'raise' cancels only its own
candidate; the unguarded fallback is still taken and last_error/on_guard_error
still observe the failure. Exit 0 only if all criteria pass."""
import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, SyncInterpreter, create_machine


def gboom(c, e):
    raise RuntimeError("guardboom")


CFG = {
    "id": "ld",
    "initial": "verifying",
    "guardErrorPolicy": "raise",
    "states": {
        "verifying": {
            "invoke": {
                "id": "ver",
                "src": "svc",
                "onDone": [
                    {"target": "accepted", "guard": "risk_ok"},
                    {"target": "rejected"},
                ],
            }
        },
        "accepted": {},
        "rejected": {},
    },
}


def mk(logic):
    return create_machine(CFG, logic=logic)


def check(cond, label, results):
    results.append((label, bool(cond)))


def main() -> int:
    results = []

    # 1. sync: fallback reached, last_error set
    s = SyncInterpreter(
        mk(MachineLogic(guards={"risk_ok": gboom}, services={"svc": lambda *a: {"ok": 1}}))
    ).start()
    check(s.value == "rejected", "sync fallback taken", results)
    check(isinstance(s.last_error, RuntimeError), "sync last_error set", results)

    # 2. async: fallback reached
    async def svc(i, c, e):
        return {"ok": True}

    async def run_async():
        i = await Interpreter(
            mk(MachineLogic(guards={"risk_ok": gboom}, services={"svc": svc}))
        ).start()
        await asyncio.sleep(0.1)
        out = (i.value, type(i.last_error).__name__)
        await i.stop()
        return out

    av, aerr = asyncio.run(run_async())
    check(av == "rejected", "async fallback taken", results)
    check(aerr == "RuntimeError", "async last_error set", results)

    # 3. caller-driven send() still raises for sync and delivers error on async receipt
    cfg2 = {
        "id": "g", "initial": "a", "guardErrorPolicy": "raise",
        "states": {"a": {"on": {"GO": [{"target": "b", "guard": "boom"}, {"target": "c"}]}},
                   "b": {}, "c": {}},
    }

    def boom(c, e):
        raise ValueError("x")

    s2 = SyncInterpreter(create_machine(cfg2, logic=MachineLogic(guards={"boom": boom}))).start()
    raised = False
    try:
        s2.send("GO")
    except ValueError:
        raised = True
    check(raised, "sync send() raises to caller", results)
    check(s2.value == "c", "sync send() still reaches fallback", results)

    async def run_async2():
        i = await Interpreter(create_machine(cfg2, logic=MachineLogic(guards={"boom": boom}))).start()
        r = await i.send("GO", wait=True)
        out = (i.value, type(r.error).__name__)
        await i.stop()
        return out

    av2, aerr2 = asyncio.run(run_async2())
    check(av2 == "c", "async receipt fallback taken", results)
    check(aerr2 == "ValueError", "async receipt.error set", results)

    print("RESULTS:")
    ok = True
    for label, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
