# -*- coding: utf-8 -*-
"""Verify #174 on main @ 6db65d8: DOCUMENTED-ONLY (not a code fix) --
`production-characteristics.md` documents that a plain-`def` service
blocks its own machine's `after` timers for its whole duration; the
underlying busy-loop `after` lateness is unchanged. Also confirms the
docs' own claim that `async def` is now timer-safe (post round-7 #179
charging) as a NEW documented remedy, and reproduces it directly.

Criteria:
 1. Docs state the plain-def-blocks-timers behaviour with the #174
    reference and the 500ms example.
 2. Busy-loop lateness against a 50ms `after` budget is still >> 0 with NO
    invoked services involved (pure event-loop contention case) -- #174's
    busy-loop finding is about event-loop contention, independent of
    service kind, so no def/async-def matrix applies here.
 3. `after: 100` beside a 500ms PLAIN-def service fires late (~500ms) --
    unchanged, matches CHANGELOG.
 4. `after: 100` beside a 500ms ASYNC-def service fires ON TIME (~100ms)
    -- the CHANGELOG's claimed remedy, verified directly, since #179
    changed completion charging (adjacent change on this tree).
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import asyncio
import sys
import time
from pathlib import Path

from xstate_statemachine import Interpreter, MachineLogic, create_machine

DOCS_PATH = Path(
    str(_XS / 'docs/_guide/production-characteristics.md')
)

BUDGET_MS = 50
N_ITERS = 100


async def busy_loop_lateness():
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
    for _ in range(N_ITERS):
        await asyncio.sleep(0)
        sum(range(2000))
    while "t.fired" not in i.current_state_ids:
        await asyncio.sleep(0.001)
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    await i.stop()
    return elapsed_ms


async def service_blocks_timer(is_async_service: bool):
    if is_async_service:
        async def slow_service(i, c, e):
            await asyncio.sleep(0.5)
            return None
    else:
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
    print(f"[1] production-characteristics.md documents #174: {c1}")

    lateness_ms = asyncio.run(busy_loop_lateness()) - BUDGET_MS
    print(f"busy-loop lateness: {lateness_ms:.1f}ms over {BUDGET_MS}ms budget")
    c2 = lateness_ms > 15
    print(f"[2] 50ms budget still missed under busy-loop load (no services): {c2}")

    svc_elapsed_def, states_def = asyncio.run(service_blocks_timer(False))
    print(f"[def service] elapsed={svc_elapsed_def:.0f}ms final_states={states_def}")
    c3 = svc_elapsed_def > 300
    print(f"[3] after:100 blocked behind 500ms PLAIN-def service (unchanged): {c3}")

    svc_elapsed_async, states_async = asyncio.run(service_blocks_timer(True))
    print(f"[async def service] elapsed={svc_elapsed_async:.0f}ms final_states={states_async}")
    c4 = svc_elapsed_async < 300 and states_async == ["s.timeout"]
    print(f"[4] after:100 fires on time beside 500ms ASYNC-def service (documented remedy): {c4}")

    ok = c1 and c2 and c3 and c4
    print(
        "\nRESULT:",
        "PASS (confirms DOCUMENTED-ONLY -- no code fix for the underlying "
        "timer-blocking mechanics; async def remedy verified directly)"
        if ok else "FAIL",
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
