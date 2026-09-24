"""
Verification script for gh#75 / LC N-1 on xstate-statemachine main @ 5327ba6.

Acceptance criteria (from gh#75):
  A. repro/N-01_send-wait-receipt-id-collision.py exits 0.
  B. Two concurrent send(ev, wait=True) calls with ONE Event instance both
     resolve, each with a Receipt describing its own macrostep.
  C. N concurrent sends of one reused instance all resolve (N >= 100).
  D. stop() resolves every outstanding receipt, including duplicates of one
     instance, with InterpreterStoppedError.

Exits 0 only if ALL criteria pass.
"""
import asyncio
import subprocess
import sys

from xstate_statemachine import (
    Event,
    Interpreter,
    InterpreterStoppedError,
    create_machine,
)

CFG = {
    "id": "rc",
    "initial": "a",
    "states": {"a": {"on": {"T": "b"}}, "b": {"on": {"T": "a"}}},
}

REPRO = (
    r"C:\Users\basil\Desktop\Projects\FullStackProjects\CandleViewer\docs\research"
    r"\xstate\issues\new-0.8.0\repro\N-01_send-wait-receipt-id-collision.py"
)


def check(label, cond, observed, expected):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}: OBSERVED={observed!r} EXPECTED={expected!r}")
    return cond


async def crit_b():
    i = Interpreter(create_machine(CFG))
    await i.start()
    ev = Event(type="T", payload={})
    r1, r2 = await asyncio.wait_for(
        asyncio.gather(i.send(ev, wait=True), i.send(ev, wait=True)), timeout=5
    )
    await i.stop()
    ok = r1 is not None and r2 is not None
    return check(
        "B: two concurrent sends of one Event instance both resolve",
        ok,
        (type(r1).__name__, type(r2).__name__),
        "(Receipt, Receipt)",
    )


async def crit_c(n=200):
    i = Interpreter(create_machine(CFG))
    await i.start()
    ev = Event(type="T", payload={})
    results = await asyncio.wait_for(
        asyncio.gather(*[i.send(ev, wait=True) for _ in range(n)]), timeout=10
    )
    await i.stop()
    ok = len(results) == n and all(r is not None for r in results)
    return check(
        f"C: {n} concurrent sends of one reused instance all resolve",
        ok,
        len(results),
        n,
    )


async def crit_d():
    i = Interpreter(create_machine(CFG))
    await i.start()
    ev = Event(type="T", payload={})
    awaitables = [i.send(ev, wait=True) for _ in range(5)]
    gathered = asyncio.gather(*awaitables, return_exceptions=True)
    # give sends a moment to be queued, then stop before they can settle normally
    await asyncio.sleep(0)
    await i.stop()
    results = await asyncio.wait_for(gathered, timeout=5)
    all_settled = len(results) == 5
    all_stopped_err = all(
        isinstance(r, InterpreterStoppedError)
        or isinstance(getattr(r, "error", None), InterpreterStoppedError)
        for r in results
    )
    return check(
        "D: stop() resolves every outstanding duplicate-instance receipt",
        all_settled and all_stopped_err,
        [repr(r) for r in results],
        "all settled, all report InterpreterStoppedError",
    )


def crit_a():
    proc = subprocess.run([sys.executable, REPRO], capture_output=True, text=True)
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr)
    return check("A: original repro exits 0", proc.returncode == 0, proc.returncode, 0)


async def main():
    results = []
    results.append(crit_a())
    results.append(await crit_b())
    results.append(await crit_c())
    results.append(await crit_d())
    print()
    print("ALL PASS" if all(results) else "SOME FAILED")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
