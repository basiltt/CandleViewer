# `#206`'s chain charge is time-blind, so a `raise(delay=)` self-paced heartbeat dies at `maxIterations` beats

**Severity:** Medium (doc/scope defect on a non-idiomatic spelling; behaviour break not named in the changelog)
**Build:** `main` @ `19cb1f1` (PR #211, commit `4dbf86e`; unreleased 0.8.1). `__version__` still reports `0.8.0` — **key on the commit, not the version string.**
**Environment:** CPython 3.13.7, Windows 11, fresh venv, run from a neutral working directory.
**Both service/action spellings (`def` and `async def`) exercised.** Polled to convergence, not sampled.
**r10:** R10-03 · **Labels:** bug, severity/medium, area/interpreter, timers, docs

---

## Summary

`Interpreter._schedule_send` (`interpreter.py:2206-2247`) now treats a delayed send to self issued from an action as a debt of the arming step (`_chain_owed_sends`, `_armed_this_step += 1`) and charges its firing as engine work (`_deliver_priority(..., engine_completion=self_armed)`), incrementing `_raise_depth`.

**Nothing in that path is time-aware.** The chain is cleared only by the run loop's "raised nothing, armed nothing, owes nothing" test — and a self-paced periodic process re-arms in its own entry action, so that test is false on every lap no matter how much wall-clock time elapsed between beats.

The consequence is wider than the 1 ms ping-pong the changelog describes. A `raise(delay=)` self-paced heartbeat or poller now **stops after `maxIterations` beats** on the async engine and parks with `RunawayChainError`.

## Observed (this repro, `maxIterations = 8`, 3 s window)

| spelling | kind | period | beats | `last_error` |
|---|---|---|---|---|
| `raise(delay=)` | `def` | 30 ms | **9** | `RunawayChainError` |
| `after` | `def` | 30 ms | 93 | — |
| `raise(delay=)` | `def` | 100 ms | **9** | `RunawayChainError` |
| `after` | `def` | 100 ms | 27 | — |
| `raise(delay=)` | `def` | 250 ms | **9** | `RunawayChainError` |
| `after` | `def` | 250 ms | 12 | — |
| `raise(delay=)` | `async def` | 30/100/250 ms | **9 / 9 / 9** | `RunawayChainError` |
| `after` | `async def` | 30/100/250 ms | 92 / 27 / 12 | — |

**The `raise(delay=)` lap count is identical at every period** — confirming the charge is purely per-lap and wholly independent of elapsed time. Against `f28719c` the same chart gave 114 / 34 / 15 beats at those periods with no cut.

## Why this is Medium and not High — stated plainly

We considered filing this higher and talked ourselves down, for three reasons worth recording so the triage is auditable:

1. **It is implied, if not named.** The `#206` changelog entry says a delayed self-raise trips at the same lap as a zero-delay raise cycle, and `json-config.md:110` already scopes `maxIterations` to unbroken self-raise/self-send chains.
2. **The documented idiom is unaffected.** `after` — the spelling `delayed-transitions.md` actually presents for periodic work — measures **93 and 92 beats in 3 s with zero drops** at the same 30 ms and the same `maxIterations: 8`. No document anywhere presents self-`raise(delay=)` as a heartbeat.
3. **The failure is loud**, not silent: `RunawayChainError` on `last_error`, `on_event_dropped(..., "chain_budget")`, a WARNING, and the machine stays `running`. Any external traffic clears the chain (we measured 45/47 beats surviving with external traffic every 4th sample).

## What we would ask for

1. **Name it in the changelog as a behaviour break** for `raise(delay=)` periodic work, with `after` as the stated migration. Anyone who wrote a self-paced poller against 0.8.0 will find it stops at lap N.
2. **`production-characteristics.md:95` ("a budget is not a deadline") now misleads** for this spelling and should be amended.
3. Consider whether the chain-clear test should acquire *any* time awareness. A chain whose only outstanding work is a timer armed 250 ms into the future is not the runaway the budget exists to catch — and the current rule cannot tell the two apart.

## Environment

CPython 3.13.7, Windows 11, `xstate-statemachine` fresh venv, `main` @ `19cb1f1` (commit `19cb1f19fc75575abd85cfa9da738c458f20d015`, PR #211 merge commit `4dbf86e`). `__version__` reports `0.8.0` (unreleased 0.8.1) — key on the commit.

## Root cause

`src/xstate_statemachine/interpreter.py:2206-2247` (`Interpreter._schedule_send`): a delayed send whose actor is `self` and issued while `self._processing` is true (`self_armed = actor is self and self._processing`, line ~2214) is registered in `_chain_owed_sends` and increments `_armed_this_step` (lines 2245-2247) — a debt of the *arming* macrostep. When the timer fires, `_fire()` (lines 2220-2237) delivers it via `_deliver_priority(target_event, engine_completion=self_armed)`, charging the firing as engine-generated work rather than a fresh user-originated cycle.

The chain-clear test at `interpreter.py:1826-1834` only resets `_raise_depth`/`_chain_tripped` when, at the end of a macrostep, `_armed_this_step` is falsy, `_internal_queue` is empty, `_priority_queue` is empty, and `_threadsafe_self_sends_in_flight` is empty. A self-paced heartbeat re-arms its own next beat in its *entry* action every lap, so `_armed_this_step` is truthy on every single macrostep — the clear condition is never satisfied regardless of how much wall-clock time separates beats, because none of the four terms in that test carries any notion of elapsed time.

## Impact

**General:** any `raise(delay=)` self-re-arming heartbeat/poller pattern (as opposed to the documented `after` idiom) is unbounded-lifetime-incompatible under a finite `maxIterations`: it trips `RunawayChainError` at lap `maxIterations + 1` regardless of the delay length — a 30 ms period and a 250 ms period both die at lap 9 with `maxIterations=8`.

**Order-management relevance:** a self-paced polling actor (e.g., an order-status poll-until-filled loop implemented as `raise(delay=)` rather than `after`) that runs longer than `maxIterations` iterations parks itself with `RunawayChainError` and stops polling silently from the caller's perspective unless `last_error`/`on_event_dropped` is actively monitored — a live order could stop being tracked while `status` still reports `running`.

## Proposed fix

Give the chain-clear test (or the arming path) time-awareness so a self-armed *delayed* send is distinguished from a same-tick `raise`: e.g., track the delay's deadline and treat a chain whose only outstanding debt is a still-pending timer more than some epsilon in the future as not "raised this step" for budget purposes, or reset `_settle_iterations`/`_raise_depth` on any macrostep gap exceeding a configurable threshold. At minimum, name the behavior explicitly in the changelog and `production-characteristics.md` so it is not read as covered by "a budget is not a deadline" (`production-characteristics.md:95`), which is written about `after`/service duration, not about a self-re-arming `raise(delay=)` chain.

## Acceptance criteria

- `test_raise_delay_heartbeat_survives_maxIterations__def` — a `raise(delay=)` self-re-arming heartbeat with `maxIterations: 8` and beat periods of 30/100/250 ms, `def` actions, on the async engine, sends ≥ 50 beats in a 3 s window with `last_error is None`.
- `test_raise_delay_heartbeat_survives_maxIterations__async_def` — same, `async def` actions.
- `test_raise_delay_heartbeat_survives_maxIterations__sync_engine_def` and `..._async_def` — same shape on `SyncInterpreter` driven by an external `tick()` loop over the same wall-clock window (per the pin in the `#206` changelog entry, "a timer-paced self-send is driven by the caller's `tick()` and has user standing by construction" — confirm this still holds and is unaffected by any fix).
- `test_after_heartbeat_unaffected__def` / `..._async_def` — regression guard that the documented `after` idiom's beat count is not reduced by any change made here.

## Related

- `#206` (changelog, CHANGELOG.md:29-38) — introduces the self-armed delayed-send charge this issue is about.
- `production-characteristics.md:95` — "a budget is not a deadline"; this issue asks that it be amended to name the `raise(delay=)` exception.
- `json-config.md:110` — scopes `maxIterations` to unbroken self-raise/self-send chains (cited as partial coverage in "Why this is Medium").
- R10-04 (this batch) — a related-but-distinct defect on the same `#206` delayed self-send debt, in the snapshot/restore path rather than the live chain-budget path.

## Standalone repro

Stdlib + `xstate_statemachine` only. Runs from any working directory. Exit 1 = defect present.

```python
"""R10-03 (STANDALONE): #206's chain charge for a self re-armed delayed send is
time-blind, so a `raise(delay=)` self-paced heartbeat dies at `maxIterations`
beats regardless of the beat period.

`Interpreter._schedule_send` (interpreter.py:2206-2247) treats a delayed send to
self issued from an action as a debt of the arming step (`_chain_owed_sends`,
`_armed_this_step += 1`) and charges its firing as engine work
(`_deliver_priority(..., engine_completion=self_armed)`), incrementing
`_raise_depth`. Nothing in that path is time-aware: the chain clears only on
"raised nothing, armed nothing, owes nothing", and a heartbeat re-arms in its
own entry action, so that test is false on every lap. Wall-clock time between
beats never ends the chain.

Control: the DOCUMENTED heartbeat idiom (`after`) is unaffected.

Exit 0 = both spellings survive the window (defect fixed).
Exit 1 = `raise(delay=)` is cut while `after` is not (defect present).

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 40 s.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import create_machine, Interpreter, MachineLogic

MAXIT = 8
PERIODS_MS = (30, 100, 250)
WINDOW_S = 3.0


def _raise_cfg(period_ms: int) -> dict:
    arm = {"type": "raise", "params": {"event": "BEAT", "delay": period_ms}}
    return {
        "id": "hb",
        "initial": "up",
        "maxIterations": MAXIT,
        "states": {
            "up": {"entry": [arm, "beat"], "on": {"BEAT": "down"}},
            "down": {"entry": [arm, "beat"], "on": {"BEAT": "up"}},
        },
    }


def _after_cfg(period_ms: int) -> dict:
    return {
        "id": "hb",
        "initial": "up",
        "maxIterations": MAXIT,
        "states": {
            "up": {"entry": ["beat"], "after": {period_ms: "down"}},
            "down": {"entry": ["beat"], "after": {period_ms: "up"}},
        },
    }


async def run(cfg: dict, kind: str) -> dict:
    beats = {"n": 0}
    drops: list = []

    def _beat(i, c, e, a=None):  # plain def
        beats["n"] += 1

    async def _beat_async(i, c, e, a=None):  # async def
        beats["n"] += 1

    fn = _beat if kind == "def" else _beat_async
    machine = create_machine(
        json.loads(json.dumps(cfg)), logic=MachineLogic(actions={"beat": fn})
    )
    interp = Interpreter(machine)
    try:
        interp.on_event_dropped = lambda *a, **k: drops.append(a)  # best effort
    except Exception:
        pass
    await interp.start()
    await asyncio.sleep(WINDOW_S)
    err = type(getattr(interp, "last_error", None)).__name__
    await interp.stop()
    return {"beats": beats["n"], "last_error": err}


async def main() -> int:
    bad = 0
    print(f"maxIterations={MAXIT}  window={WINDOW_S}s")
    print(f"{'spelling':<14}{'kind':<10}{'period':<9}{'beats':<8}last_error")
    for kind in ("def", "async def"):
        for p in PERIODS_MS:
            r = await run(_raise_cfg(p), kind)
            a = await run(_after_cfg(p), kind)
            print(f"{'raise(delay=)':<14}{kind:<10}{str(p)+'ms':<9}"
                  f"{r['beats']:<8}{r['last_error']}")
            print(f"{'after':<14}{kind:<10}{str(p)+'ms':<9}"
                  f"{a['beats']:<8}{a['last_error']}")
            # The defect: raise(delay=) is cut at ~maxIterations beats while the
            # documented `after` idiom keeps beating for the whole window.
            if r["beats"] <= MAXIT + 4 and a["beats"] > MAXIT + 4:
                bad += 1
    print()
    print("VERDICT:", "DEFECT PRESENT" if bad else "ok (bounded alike)",
          f"({bad}/{len(PERIODS_MS) * 2} cells cut)")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 40.0))
    except asyncio.TimeoutError:
        print("WATCHDOG TIMEOUT")
        rc = 1
    sys.exit(rc)
```

### Actual output at `19cb1f1`

```
maxIterations=8  window=3.0s
spelling      kind      period   beats   last_error
raise(delay=) def       30ms     9       RunawayChainError
after         def       30ms     92      NoneType
raise(delay=) def       100ms    9       RunawayChainError
after         def       100ms    27      NoneType
raise(delay=) def       250ms    9       RunawayChainError
after         def       250ms    12      NoneType
raise(delay=) async def 30ms     9       RunawayChainError
after         async def 30ms     92      NoneType
raise(delay=) async def 100ms    9       RunawayChainError
after         async def 100ms    27      NoneType
raise(delay=) async def 250ms    9       RunawayChainError
after         async def 250ms    12      NoneType

VERDICT: DEFECT PRESENT (4/6 cells cut)
```

(The 4/6 rather than 6/6 is the oracle being conservative at the longest periods, where `after`'s own beat count approaches the threshold within a 3 s window — the `raise(delay=)` cut is present in all 6. `after`'s own count is a live scheduling race so it fluctuates run to run (92 or 93 here) — irrelevant to the defect, which is the `raise(delay=)` column pinned at 9 regardless of period.)

## Verification

- Date: 2026-09-22
- Python: CPython 3.13.7 (`.venv-main`), `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`
- Commit: `main` @ `19cb1f1` (verified via `git rev-parse HEAD` = `19cb1f19fc75575abd85cfa9da738c458f20d015`)
- Command: `python new/repro/R10-03_delayed_selfsend_heartbeat_dies.py`
- cwd: `C:/Users/basil` (neutral)
- Exit code: `1` (defect present, matches "Exit 1 = defect present")
- `verified: true`
