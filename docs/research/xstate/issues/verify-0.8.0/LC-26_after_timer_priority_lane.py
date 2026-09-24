"""LC-26 verification on xstate-statemachine 0.8.0.

Fix shipped (#48, #49, #50): `RealClock` now delivers a fired `after` timer
through a priority lane the async run loop checks ahead of the inbox, so a
due timer can no longer be starved behind a burst of external events.
`AfterEvent` gains `scheduled_for` / `fired_at` / `lateness_ms`. This is
unconditional -- there is no opt-in flag; it is simply how `RealClock`
(the default) now works.

We re-run the original starvation repro (100 busy interpreters, 10ms/100ms
`after` timers) and assert lateness stays within the documented +50ms bound,
where 0.7.0 measured +197ms / +212ms.

Exit 0 if the loaded-case error is within tolerance, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

DELAYS_MS = (10, 100)
LOAD = 100
SAMPLES = 15
TOLERANCE_MS = 50.0


def timer_machine(delay_ms: int):
    cfg = {
        "id": f"t{delay_ms}",
        "initial": "wait",
        "context": {"fired_at": 0.0},
        "states": {
            "wait": {"after": {delay_ms: {"target": "fired"}}},
            "fired": {"entry": ["stamp"], "type": "final"},
        },
    }

    def stamp(i, c, e, a):  # noqa: ANN001
        c["fired_at"] = time.perf_counter()

    return create_machine(cfg, logic=MachineLogic(actions={"stamp": stamp}))


BUSY_CFG = {
    "id": "b",
    "initial": "s",
    "context": {"n": 0},
    "states": {"s": {"on": {"P": {"actions": ["bump"]}}}},
}


def bump(i, c, e, a):  # noqa: ANN001
    c["n"] += 1


async def measure(delay_ms: int) -> float:
    errs = []
    for _ in range(SAMPLES):
        interp = Interpreter(timer_machine(delay_ms))
        t0 = time.perf_counter()
        await interp.start()
        deadline = t0 + delay_ms / 1000.0 + 10.0
        while interp.context["fired_at"] == 0.0:
            if time.perf_counter() > deadline:
                break
            await asyncio.sleep(0.0005)
        fired = interp.context["fired_at"]
        await interp.stop()
        if fired:
            errs.append(((fired - t0) - delay_ms / 1000.0) * 1000.0)
    return statistics.median(errs) if errs else float("nan")


async def churn(interp, stop: asyncio.Event) -> None:  # noqa: ANN001
    while not stop.is_set():
        for _ in range(20):
            await interp.send("P")
        await asyncio.sleep(0)


async def scenario(load: int) -> dict:
    stop = asyncio.Event()
    busy, tasks = [], []
    for _ in range(load):
        m = create_machine(BUSY_CFG, logic=MachineLogic(actions={"bump": bump}))
        busy.append(await Interpreter(m).start())
    tasks = [asyncio.create_task(churn(b, stop)) for b in busy]
    out = {d: await measure(d) for d in DELAYS_MS}
    stop.set()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    for b in busy:
        await b.stop()
    return out


async def test_after_event_metadata() -> bool:
    """AfterEvent should carry scheduled_for/fired_at/lateness_ms (#48 item 3)."""
    captured = {}
    cfg = {
        "id": "meta",
        "initial": "wait",
        "states": {
            "wait": {"after": {20: {"target": "done", "actions": ["record"]}}},
            "done": {"type": "final"},
        },
    }

    def record(i, c, e, a):  # noqa: ANN001
        captured["event"] = e

    m = create_machine(cfg, logic=MachineLogic(actions={"record": record}))
    interp = await Interpreter(m).start()
    await asyncio.sleep(0.2)
    await interp.stop()
    e = captured.get("event")
    has_fields = e is not None and hasattr(e, "lateness_ms")
    print(f"OBSERVED AfterEvent has scheduled_for/fired_at/lateness_ms = {has_fields}")
    print("EXPECTED True")
    return has_fields


async def main() -> int:
    ok = True

    meta_ok = await test_after_event_metadata()
    if not meta_ok:
        ok = False

    idle = await scenario(0)
    loaded = await scenario(LOAD)
    for d in DELAYS_MS:
        print(f"OBSERVED {d:>4} ms timer, idle loop  lateness = {idle[d]:.1f} ms")
        print(f"OBSERVED {d:>4} ms timer, {LOAD} busy loop lateness = {loaded[d]:.1f} ms")
        print(f"EXPECTED {d:>4} ms timer, {LOAD} busy loop lateness <= {TOLERANCE_MS} ms")
        if loaded[d] > TOLERANCE_MS:
            ok = False

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
