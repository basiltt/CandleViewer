"""
Verification script for gh#76 / LC N-2 on xstate-statemachine main @ 5327ba6.

Acceptance criteria (from gh#76):
  A. repro/N-02_sync-timer-unreachable-in-loop.py exits 0.
  B. A SyncInterpreter built inside a running loop shows clock.pending == 1
     for an armed `after`, and one tick() past the deadline moves it.
  C. tick() is authoritative: after it returns, no deadline that was due at
     entry remains undelivered, in either context.
  D. The off-loop behaviour is unchanged (no regression against #50 --
     still zero threads per timer).

Exits 0 only if ALL criteria pass.
"""
import asyncio
import subprocess
import sys
import threading
import time

from xstate_statemachine import SyncInterpreter, create_machine

CFG = {
    "id": "sy",
    "initial": "a",
    "states": {"a": {"after": {40: "b"}}, "b": {}},
}

REPRO = (
    r"C:\Users\basil\Desktop\Projects\FullStackProjects\CandleViewer\docs\research"
    r"\xstate\issues\new-0.8.0\repro\N-02_sync-timer-unreachable-in-loop.py"
)


def check(label, cond, observed, expected):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}: OBSERVED={observed!r} EXPECTED={expected!r}")
    return cond


def crit_a():
    proc = subprocess.run([sys.executable, REPRO], capture_output=True, text=True)
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr)
    return check("A: original repro exits 0", proc.returncode == 0, proc.returncode, 0)


async def crit_b_c():
    i = SyncInterpreter(create_machine(CFG))
    i.start()
    pending = i.clock.pending
    time.sleep(0.120)
    i.tick()
    states = sorted(i.current_state_ids)
    ok = pending == 1 and states == ["sy.b"]
    return check(
        "B/C: in-running-loop pending==1 before tick, tick() delivers due deadline",
        ok,
        (pending, states),
        (1, ["sy.b"]),
    )


def crit_d():
    before = threading.active_count()
    interpreters = []
    for _ in range(25):
        i = SyncInterpreter(create_machine(CFG))
        i.start()
        interpreters.append(i)
    after = threading.active_count()
    delta = after - before
    ok = delta == 0
    # also confirm off-loop firing still works (no regression)
    time.sleep(0.120)
    i2 = interpreters[0]
    i2.tick()
    fired = sorted(i2.current_state_ids) == ["sy.b"]
    return check(
        "D: 25 sync machines with armed timers -> +0 threads; off-loop still fires",
        ok and fired,
        (delta, fired),
        (0, True),
    )


async def main():
    results = []
    results.append(crit_a())
    results.append(await crit_b_c())
    results.append(crit_d())
    print()
    print("ALL PASS" if all(results) else "SOME FAILED")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
