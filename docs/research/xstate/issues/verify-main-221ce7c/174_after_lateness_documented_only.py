# -*- coding: utf-8 -*-
"""Verify #174 on main @ 221ce7c: NOT a code fix -- a documentation change.
Confirms (a) the docs now state the plain-service-blocks-timers behaviour,
and (b) the underlying 50ms `after` lateness under load is UNCHANGED /
still missed, i.e. the CHANGELOG "Changed" entry is accurate: it documents
existing behaviour rather than bounding it.

Criteria:
 1. `docs/_guide/production-characteristics.md` contains a statement of
    "a plain-`def` service blocks its own machine's timers for its whole
    duration" referencing #174, with the `after: 100` / 500ms example.
 2. Under a 100-iteration busy loop (the round-6 repro shape), observed
    `after` lateness against a 50ms budget is still >> 0 (budget missed),
    matching the CHANGELOG's explicit statement that "the `maxIterations`
    settle budget bounds microsteps, not wall-clock lateness."
 3. The `after: 100` vs 500ms plain-service class from the CHANGELOG is
    reproduced: the timer fires only once the entering macrostep's
    in-flight plain service completes, i.e. late by ~= the service
    duration, not ~100ms.

Exit 0 if all criteria hold (i.e. #174 is confirmed DOCUMENTED-ONLY, not
fixed) -- 1 if either the docs are missing OR the behaviour has actually
been bounded (which would mean the classification should change).
"""
import asyncio
import sys
import time
from pathlib import Path

from xstate_statemachine import Interpreter, MachineLogic, create_machine

DOCS_PATH = Path(
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine"
    "/docs/_guide/production-characteristics.md"
)

BUDGET_MS = 50
N_ITERS = 100


async def busy_loop_lateness():
    """Round-6 repro shape: a 100-iteration busy loop delays draining a
    due `after` well past its 50ms budget."""
    cfg = {
        "id": "t",
        "initial": "a",
        "states": {
            "a": {"after": {BUDGET_MS: {"target": "fired"}}},
            "fired": {"type": "final"},
        },
    }
    m = create_machine(cfg, logic=MachineLogic())
    i = Interpreter(m)
    t0 = time.monotonic()
    await i.start()
    # Busy loop: hog the loop with sync-ish awaits so the due timer can't
    # be drained promptly.
    for _ in range(N_ITERS):
        await asyncio.sleep(0)
        x = sum(range(2000))
    while "t.fired" not in i.current_state_ids:
        await asyncio.sleep(0.001)
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    await i.stop()
    return elapsed_ms


async def service_blocks_timer():
    """CHANGELOG example: `after: 100` alongside a 500ms plain service
    fires at ~500ms, not ~100ms."""
    def slow_service(i, c, e):
        time.sleep(0.5)
        return None

    cfg = {
        "id": "s",
        "initial": "a",
        "states": {
            "a": {
                "after": {100: {"target": "timeout"}},
                "invoke": {"src": "slow", "onDone": "done"},
            },
            "timeout": {"type": "final"},
            "done": {"type": "final"},
        },
    }
    m = create_machine(cfg, logic=MachineLogic(services={"slow": slow_service}))
    i = Interpreter(m)
    t0 = time.monotonic()
    await i.start()
    while i.status == "running":
        await asyncio.sleep(0.001)
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    return elapsed_ms, list(i.current_state_ids)


def main():
    doc_text = DOCS_PATH.read_text(encoding="utf-8") if DOCS_PATH.exists() else ""
    c1 = (
        "#174" in doc_text
        and "blocks its own machine" in doc_text
        and "500 ms" in doc_text
    )
    print(f"[1] production-characteristics.md documents #174 (blocking timers): {c1}")

    lateness_ms = asyncio.run(busy_loop_lateness()) - BUDGET_MS
    print(f"busy-loop lateness: {lateness_ms:.1f}ms over the {BUDGET_MS}ms budget")
    c2 = lateness_ms > 15  # budget meaningfully missed, not just noise
    print(f"[2] 50ms budget still missed under busy-loop load: {c2}")

    svc_elapsed_ms, final_states = asyncio.run(service_blocks_timer())
    print(f"service-blocks-timer elapsed: {svc_elapsed_ms:.0f}ms final_states={final_states}")
    # Whichever transition "wins" (after vs done.invoke), the machine can't
    # settle before the entering macrostep's in-flight 500ms plain service
    # returns -- so it takes ~500ms, not ~100ms, regardless of final state.
    c3 = svc_elapsed_ms > 300
    print(f"[3] after:100 blocked behind 500ms plain service (documented class): {c3}")

    ok = c1 and c2 and c3
    print("RESULT:", "PASS (confirms DOCUMENTED-ONLY, not fixed)" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
