# -*- coding: utf-8 -*-
# =============================================================================
# RETIRED 2026-09-22 (round 11, main @ c78ce99) -- SUPERSEDED-BY-#212.
#
# This script asserts the #206 rule: that a re-armed delayed self-send is
# charged to the chain budget per lap, so a `raise(delay=)` self ping-pong
# trips RunawayChainError at ~maxIterations.
#
# **#212 DELIBERATELY REVERSES THAT RULE.** A `raise(delay=)` self-send is now
# a TIMER: arming ends the step's chain, firing is a clock event, and a self
# ping-pong of any period is a legal periodic process, NOT a runaway.
#
# It therefore FAILS at c78ce99 (x5/5, stable) and that failure is CORRECT.
# It was the SINGLE stable PASS->FAIL delta across the whole round -- the
# 163-check gate and the 527-script sweep -- and it is category
# SUPERSEDED-BY-#212, not a regression.
#
# Retired by the leading-underscore filename, which `_run_lc_dir` skips, rather
# than deleted: the assertion is the historical record of what the engine used
# to promise, and a future rule change should be diffed against it.
#
# The #212 rule is now pinned POSITIVELY by
# `issues/verify-main-c78ce99/212_selfsend_timer.py` (gate kind `verifyM8`).
#
# See: 60-r11-regression.md s.2, 64-r11-final-readiness-verdict.md s.2(b),
#      20-adoption-gate.md gate-run log for c78ce99.
# =============================================================================
"""Verify #206 on main @ 19cb1f1: delayed self-send is charged to budget.

Interpreter-only by construction (SyncInterpreter has no delayed-send timer
mechanism in this shape). Checks:
  1. The two-state 1ms-delay self-raise cycle trips RunawayChainError /
     on_event_dropped(chain_budget) and stays bounded (does not spin
     forever).
  2. Delayed self-raise trips at (approximately) the same lap count as an
     otherwise-identical zero-delay self-raise (parity between the two
     provenance paths).
  3. An EXTERNAL delayed send (caller's own send(..., delay=...), not a
     self-raise) is still never charged/shed -- #192's guarantee preserved.

Exit 0 only if every criterion is met.
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import create_machine, Interpreter, MachineLogic
from xstate_statemachine.exceptions import RunawayChainError

FAILS: list = []


def fail(label, detail):
    FAILS.append((label, detail))
    print("FAIL:", label, "--", detail)


DELAYED_CFG = {
    "id": "m", "initial": "a", "maxIterations": 20,
    "context": {"n": 0},
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "GO", "delay": 1}}],
              "on": {"GO": "b"}, "exit": ["tick"]},
        "b": {"entry": [{"type": "raise", "params": {"event": "GO", "delay": 1}}],
              "on": {"GO": "a"}, "exit": ["tick"]},
    },
}

IMMEDIATE_CFG = {
    "id": "m", "initial": "a", "maxIterations": 20,
    "context": {"n": 0},
    "states": {
        "a": {"entry": [{"type": "raise", "params": {"event": "GO"}}],
              "on": {"GO": "b"}, "exit": ["tick"]},
        "b": {"entry": [{"type": "raise", "params": {"event": "GO"}}],
              "on": {"GO": "a"}, "exit": ["tick"]},
    },
}


def tick_logic():
    return MachineLogic(actions={"tick": lambda i, c, e, a=None: c.__setitem__("n", c.get("n", 0) + 1)})


DROPPED: list = []


class _DropCollector:
    def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
        DROPPED.append((event, reason))

    def __getattr__(self, name):
        return lambda *a, **k: None


async def run_delayed_cycle(watchdog=8.0):
    DROPPED.clear()
    m = create_machine(json.loads(json.dumps(DELAYED_CFG)), logic=tick_logic())
    i = Interpreter(m)
    i.use(_DropCollector())
    await i.start()
    await asyncio.sleep(watchdog)
    n = i.context["n"]
    err = i.last_error
    await i.stop()
    return n, err, list(DROPPED)


async def run_immediate_cycle_lap_count():
    """Zero-delay self-raise: how many ticks before it trips."""
    DROPPED.clear()
    m = create_machine(json.loads(json.dumps(IMMEDIATE_CFG)), logic=tick_logic())
    i = Interpreter(m)
    i.use(_DropCollector())
    await i.start()
    for _ in range(50):
        await asyncio.sleep(0.05)
        if DROPPED:
            break
    n = i.context["n"]
    await i.stop()
    return n, list(DROPPED)


async def run_external_delayed_send_unshielded():
    """An external caller-issued delayed send (not a self-raise) must
    still never be charged/shed -- i.e. it fires on schedule even after
    many external sends, and does not itself trip the chain guard."""
    CFG = {
        "id": "m", "initial": "a", "maxIterations": 20,
        "states": {"a": {"on": {"PING": "a"}}},
    }
    m = create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())
    i = Interpreter(m)
    DROPPED.clear()
    i.use(_DropCollector())
    await i.start()
    # Fire 30 external delayed sends (more than maxIterations) -- these are
    # NOT self-raises (issued from outside processing), so must not trip.
    for _ in range(30):
        await i.send("PING", delay=1)
    await asyncio.sleep(0.5)
    tripped = bool(DROPPED)
    await i.stop()
    return tripped


async def main() -> int:
    print("== Criterion 1: delayed self-send cycle is bounded (trips RunawayChainError) ==")
    n, err, dropped = await run_delayed_cycle()
    reasons = [r for _, r in dropped]
    print(f"  ticks={n} last_error={type(err).__name__} dropped_reasons={reasons}")
    if not isinstance(err, RunawayChainError):
        fail("206-c1-runaway-error", f"last_error is {type(err).__name__}, expected RunawayChainError")
    if "chain_budget" not in reasons:
        fail("206-c1-dropped-reason", f"no 'chain_budget' drop observed: {reasons}")
    if n >= 3 * 20:
        fail("206-c1-unbounded", f"ticks={n} suggests unbounded spin (>= 3x maxIterations)")
    if not FAILS:
        print("  ok: bounded and RunawayChainError observed")

    print("== Criterion 2: delayed vs zero-delay self-raise trip within close lap counts ==")
    n_imm, dropped_imm = await run_immediate_cycle_lap_count()
    print(f"  immediate cycle ticks-at-trip={n_imm}, delayed cycle ticks-at-trip={n}")
    if abs(n_imm - n) > 3:
        fail("206-c2-parity", f"lap counts diverge: immediate={n_imm} delayed={n}")
    else:
        print("  ok: lap counts within tolerance")

    print("== Criterion 3: external delayed sends are NOT charged/shed (still unshielded) ==")
    tripped = await run_external_delayed_send_unshielded()
    print(f"  30 external delayed sends -> chain tripped: {tripped}")
    if tripped:
        fail("206-c3-external-regression", "external delayed sends were incorrectly charged/shed")
    else:
        print("  ok: external delayed sends remain unshielded from the chain guard (#192 preserved)")

    print()
    if FAILS:
        print(f"VERDICT: FAIL ({len(FAILS)} criterion/a)")
        for label, detail in FAILS:
            print("  -", label, ":", detail)
        return 1
    print("VERDICT: ALL CRITERIA MET")
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 60.0))
    except asyncio.TimeoutError:
        print("watchdog fired")
        rc = 1
    raise SystemExit(rc)
