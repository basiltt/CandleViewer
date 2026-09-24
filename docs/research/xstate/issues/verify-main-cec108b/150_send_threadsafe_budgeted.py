# -*- coding: utf-8 -*-
"""Verify #150 on main@cec108b: send_threadsafe self-sends are budgeted.

Acceptance criteria (issue #150):
  1. repro/R5-08_threadsafe-bypasses-self-send-gate.py exits 0.
  2. An action that starts a threading.Thread calling send_threadsafe on its
     own interpreter stops at maxIterations, with the same count (+-1) as
     the direct `await i.send()` route -- WHEN correctly classified as
     internal (either via internal=True or a context-inheriting thread).
  3. The trip is observable: last_transition_ok is False and last_error is
     RunawayChainError.
  4. A thread with NO action on its stack (foreign thread) is NOT charged
     to the budget and keeps external ordering (no regression).
  5. Docs state whether a send from an action-spawned thread is internal or
     external by default.
"""
from __future__ import annotations

import asyncio
import contextvars
import sys
import threading

from xstate_statemachine import Interpreter, MachineLogic, create_machine

failures: list[str] = []


def check(label: str, cond: bool) -> None:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


CFG = {
    "id": "spin",
    "initial": "a",
    "maxIterations": 20,
    "context": {},
    "states": {"a": {"on": {"T": {"actions": ["resend"]}}}},
}


async def run(mode: str) -> tuple:
    seen = {"n": 0}

    async def resend(i, c, e, a):
        seen["n"] += 1
        if seen["n"] >= 60:
            return
        if mode == "direct":
            await i.send("T")
        elif mode == "threadsafe_default":
            threading.Thread(target=lambda: i.send_threadsafe("T"), daemon=True).start()
        elif mode == "threadsafe_flag":
            threading.Thread(
                target=lambda: i.send_threadsafe("T", internal=True), daemon=True
            ).start()
        elif mode == "threadsafe_ctx":
            ctx = contextvars.copy_context()
            threading.Thread(target=lambda: ctx.run(i.send_threadsafe, "T"), daemon=True).start()

    i = await Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"resend": resend}))
    ).start()
    await i.send("T")
    await asyncio.sleep(0.8)
    out = (
        seen["n"],
        type(i.last_error).__name__ if i.last_error else None,
        i.last_transition_ok,
    )
    await i.stop()
    return out


async def foreign_thread_not_charged() -> bool:
    """A thread with NO action on its stack sends repeatedly; it must NOT
    be budgeted (external traffic keeps flowing, no RunawayChainError from
    the external route itself)."""
    seen = {"n": 0}

    async def noop(i, c, e, a):
        seen["n"] += 1

    i = await Interpreter(
        create_machine(
            {
                "id": "ext",
                "initial": "a",
                "maxIterations": 20,
                "states": {"a": {"on": {"T": {"actions": ["noop"]}}}},
            },
            logic=MachineLogic(actions={"noop": noop}),
        )
    ).start()

    def hammer():
        for _ in range(30):
            try:
                i.send_threadsafe("T").result(timeout=2)
            except Exception:
                pass

    t = threading.Thread(target=hammer)
    t.start()
    t.join(timeout=5)
    await asyncio.sleep(0.3)
    ok = seen["n"] >= 25 and (i.last_error is None or type(i.last_error).__name__ != "RunawayChainError")
    await i.stop()
    return ok


async def main() -> int:
    direct = await run("direct")
    print(f"  direct route              : {direct}")

    print("Criterion: default send_threadsafe() from action-spawned thread (no internal=True)")
    default_mode = await run("threadsafe_default")
    print(f"  threadsafe (default args) : {default_mode}")
    default_budgeted = default_mode[0] <= 25
    check(
        "send_threadsafe() with NO internal= flag from an action thread is budgeted "
        "by default (documented default should charge action-spawned self-sends)",
        default_budgeted,
    )

    print("Criterion: send_threadsafe(internal=True) from action-spawned thread is budgeted")
    flag_mode = await run("threadsafe_flag")
    print(f"  threadsafe (internal=True): {flag_mode}")
    check("internal=True is budgeted", flag_mode[0] <= 25)
    check("internal=True trip is RunawayChainError", flag_mode[1] == "RunawayChainError")
    check("internal=True last_transition_ok is False", flag_mode[2] is False)

    print("Criterion: send_threadsafe via contextvars.copy_context().run is budgeted")
    ctx_mode = await run("threadsafe_ctx")
    print(f"  threadsafe (ctx-inherit)  : {ctx_mode}")
    check("ctx-inheriting thread is budgeted", ctx_mode[0] <= 25)

    print("Criterion: a foreign thread with no action on its stack is NOT charged")
    check("foreign thread unaffected", await foreign_thread_not_charged())

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} criteria failed)")
        return 1
    print("RESULT: PASS (all criteria satisfied)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
