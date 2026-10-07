# #215's `_descent_done` gate: an entry action that awaits its own receipt hangs `start()` forever, silently

**Severity:** Medium
**Build:** `main` @ `c78ce99` (merge of PR #217, `fix/0.8.1-round10`; unreleased 0.8.1). `__version__` still reports `0.8.0` — **key on the commit.**
**r11:** R11-06 · **verified:** true
**Labels:** `bug`, `severity/medium`, `area/interpreter`, `events`

---

## Summary

#215 added a gate at the top of `Interpreter._run_event_loop`: the loop `await`s `self._descent_done` before consuming anything. `_descent_done` is set only at the **end** of `start()`'s try-body (and in its `finally`).

So an `async def` entry action that awaits a receipt on its own interpreter — `await i.send("GO", wait=True)` — creates an unsatisfiable cycle: the receipt resolves only once the run loop processes `GO`, and the run loop is parked on `_descent_done`, which only the completion of that same entry action can open. **With no timeout in the user's action, `start()` never returns.**

It is completely silent: `last_error is None`, `status` is `running`, and the configuration is legal — indistinguishable from an entry action that is merely slow. #207's `on_invocation_stranded` does not cover it, because no `invoke` is involved.

The shape is **new at this commit**: running the identical chart on a subclass that opens the gate before spawning the loop (pre-#215 behaviour, **library source untouched**) returns from `start()` in 0.00 s with `n=1`.

## Environment

- CPython 3.13.7, Windows 11 Pro 10.0.26200, fresh venv, neutral working directory (`<home>`).
- `xstate-statemachine` `main` @ `c78ce99` (merge of PR #217 from `fix/0.8.1-round10`). `__version__` reports `0.8.0` (unreleased 0.8.1) — key on the commit.
- Async engine only: the gate is `Interpreter`-specific. `SyncInterpreter` has no run-loop task and no `_descent_done`, so there is nothing to park — its entry actions cannot be `async def` and cannot await a receipt. Both action spellings are nonetheless exercised across the two probes (`async def` on the defect, plain `def` on the control) to show the hang is not a service-kind artefact.

## Minimal reproduction

Standalone — stdlib plus `xstate_statemachine` only, all helpers inlined, runs from any working directory. `start()` is bounded at 3 s purely so the probe can report; **in real use there is no bound.** **Exit 1 = defect present** (`start()` hangs while the bounded control returns); **exit 0 = fixed**.

```python
"""R11-06 (STANDALONE): #215's `_descent_done` gate deadlocks `start()` forever,
silently, when an entry action awaits a receipt on its own interpreter.

#215 made `Interpreter._run_event_loop` `await self._descent_done.wait()` before
entering its main loop. `_descent_done` is set only at the END of `start()`'s
try-body. So an `async def` entry action that does
`await i.send("GO", wait=True)` cannot be satisfied: the receipt resolves only
when the run loop processes `GO`, and the run loop is parked on the gate, which
only the completion of that same entry action can open.

With no timeout in the user's action, `start()` NEVER RETURNS. It is silent:
`last_error is None`, status `running`, configuration legal -- indistinguishable
from a slow entry action.

Control A below is the correctly-bounded case: an `always` self-cycle in the
descent returns from `start()` with `RunawayChainError`. The settle budget DOES
cover the descent; only the receipt cycle hangs.

Exit 0 = start() returns within the bound (defect fixed).
Exit 1 = start() times out while the control returns.

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 40 s.
"""
from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import create_machine, Interpreter, MachineLogic

START_BOUND_S = 3.0


def hang_cfg() -> dict:
    return {
        "id": "dead",
        "initial": "x",
        "states": {
            "x": {"entry": ["await_own_receipt"], "on": {"GO": "y"}},
            "y": {},
        },
    }


def control_cfg() -> dict:
    """An `always` self-cycle in the descent -- bounded by the settle budget."""
    return {
        "id": "ctl",
        "initial": "x",
        "maxIterations": 12,
        "states": {
            "x": {"entry": ["bump"], "always": {"target": "x", "reenter": True}},
        },
    }


async def probe_hang() -> dict:
    holder: dict = {}

    async def await_own_receipt(i, c, e, a=None):  # noqa: ANN001  async def
        holder["interp"] = i
        # The receipt can only resolve once the run loop runs -- and the run
        # loop is waiting for THIS action to finish opening `_descent_done`.
        await i.send("GO", wait=True)

    machine = create_machine(
        hang_cfg(),
        logic=MachineLogic(actions={"await_own_receipt": await_own_receipt}),
    )
    interp = Interpreter(machine)

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    timed_out = False
    try:
        await asyncio.wait_for(interp.start(), START_BOUND_S)
    except asyncio.TimeoutError:
        timed_out = True
    elapsed = round(loop.time() - t0, 2)

    out = {
        "start_timed_out": timed_out,
        "start_seconds": elapsed,
        "last_error": type(getattr(interp, "last_error", None)).__name__,
        "status": str(getattr(interp, "status", "?")),
        "states": list(getattr(interp, "current_state_ids", []) or []),
    }
    try:
        await asyncio.wait_for(interp.stop(), 2.0)
    except Exception:
        pass
    return out


async def probe_control() -> dict:
    n = {"i": 0}

    def bump(i, c, e, a=None):  # noqa: ANN001  plain def
        n["i"] += 1

    machine = create_machine(
        control_cfg(), logic=MachineLogic(actions={"bump": bump})
    )
    interp = Interpreter(machine)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    timed_out = False
    try:
        await asyncio.wait_for(interp.start(), START_BOUND_S)
    except asyncio.TimeoutError:
        timed_out = True
    elapsed = round(loop.time() - t0, 2)
    out = {
        "start_timed_out": timed_out,
        "start_seconds": elapsed,
        "entries": n["i"],
        "last_error": type(getattr(interp, "last_error", None)).__name__,
    }
    try:
        await asyncio.wait_for(interp.stop(), 2.0)
    except Exception:
        pass
    return out


async def main() -> int:
    hang = await probe_hang()
    ctl = await probe_control()

    print("A) entry action awaits its own receipt (the defect)")
    for k, v in hang.items():
        print(f"     {k:<18}{v}")
    print()
    print("B) CONTROL: `always` self-cycle in the descent (settle budget)")
    for k, v in ctl.items():
        print(f"     {k:<18}{v}")
    print()

    reproduced = hang["start_timed_out"] and not ctl["start_timed_out"]
    print(f"start() hung           : {hang['start_timed_out']}")
    print(f"control returned bounded: {not ctl['start_timed_out']}")
    print(f"hang is SILENT         : {hang['last_error'] == 'NoneType'}")
    print(f"REPRODUCED: {reproduced}")
    return 1 if reproduced else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), 40)))
    except asyncio.TimeoutError:
        print("WATCHDOG: exceeded 40 s")
        sys.exit(2)
```

## Observed

Verbatim fresh run of the block above, from neutral cwd `<home>` at `c78ce99`:

```
A) entry action awaits its own receipt (the defect)
     start_timed_out   True
     start_seconds     3.0
     last_error        NoneType
     status            running
     states            ['dead.x']

B) CONTROL: `always` self-cycle in the descent (settle budget)
     start_timed_out   False
     start_seconds     0.0
     entries           13
     last_error        RunawayChainError

start() hung           : True
control returned bounded: True
hang is SILENT         : True
REPRODUCED: True
```

Exit code **1**. `start_seconds 3.0` is the probe's own `wait_for` expiring, not a settle.

Two things follow from control B. First, **the settle budget does cover the descent** — an `always` self-cycle inside the initial descent is correctly bounded and `start()` returns with `RunawayChainError` at `maxIterations=12` (12 + 1 seed entry = 13). Only the receipt cycle hangs, so this is not a general "descent is unbounded" complaint. Second, the shape is new at this commit: the identical chart on a subclass that opens the gate before spawning the loop (pre-#215 behaviour, **library source untouched**) returns from `start()` in **0.00 s** with `n=1` — 3.01 s → 0.00 s is the causal delta.

## Expected

`start()` is contracted to return, and the release notes describe the gate as an *ordering* device, not a barrier that can be closed permanently by user code.

`CHANGELOG.md:49-54` (the #215 entry):

> the run loop consumed the initial descent's own `raise` while an `async def` entry action was still yielding — interleaving two macrosteps the sync engine's re-entrancy guard forbids. The reset now keys on external provenance; **the loop waits for the descent to settle**; descent-queued raises get seed standing.

The stated goal is parity with the sync engine's **re-entrancy guard** — a flag, which a re-entrant call falls through — not a rendezvous that a descent action can be made to wait on. `SyncInterpreter` achieves the same ordering with a re-entrancy flag and does not deadlock on the same chart.

Every other start-time liveness hazard in this library has been closed with a bound and a named error rather than left open: `#181` (`await start()` hung unboundedly on a slow invoked child) and `#194` (`start(children_timeout=)` a no-op against a plain-`def` child entry action) both landed on "`start()` must be bounded and must say why"; `#103`, `#144` and `#166` closed non-terminating `start()`/`send(wait=True)` paths as **Blocker**. A silent, unbounded `start()` is precisely the class this series has repeatedly ruled a defect.

`interpreter.py:1723-1726` is also explicit that the wait is a *sequencing* concession (“let `start()` finish the initial descent before taking anything it queued”) — it does not contemplate the descent itself depending on the loop.

## Root cause

The gate and its only opener are on opposite sides of an unbreakable cycle. Open at `c78ce99`:

```python
# src/xstate_statemachine/interpreter.py:1723-1726  (_run_event_loop)
if self._descent_done is not None:
    # 🚦 #215: let `start()` finish the initial descent before
    #    taking anything it queued (see `_descent_done`).
    await self._descent_done.wait()
```

```python
# src/xstate_statemachine/interpreter.py:625  (start)
self._descent_done = asyncio.Event()  # #215: loop waits on this
self._event_loop_task = self._spawn_run_loop()
```

```python
# src/xstate_statemachine/interpreter.py:720  (end of start()'s try-body)
self._descent_done.set()  # #215: the loop may now consume
```

```python
# src/xstate_statemachine/interpreter.py:739-740  (finally)
if self._descent_done is not None:
    self._descent_done.set()  # never leave the loop parked
```

The loop task is spawned at `:625`, **before** the descent runs, and immediately parks at `:1726`. The descent's entry actions run inside the try-body between `:626` and `:720`. An entry action that `await`s `send("GO", wait=True)` cannot complete until the loop consumes `GO`; the loop cannot consume anything until `:720` runs; `:720` cannot run until the entry action completes. The `finally` at `:739-740` is the intended escape hatch — but it is only reached if the try-body *finishes or raises*, which is exactly what the cycle prevents. Nothing in either path is time-bounded, so the deadlock is permanent and raises nothing.

## Impact

**General.** Awaiting one's own receipt *directly* from an entry action is admittedly unusual, and that is why this is filed Medium rather than High. What is *not* unusual is calling a helper that happens to await a receipt — a "publish and confirm" utility, a shared bootstrap routine, a tracing decorator, anything that wraps `send(..., wait=True)`. The caller of that helper has no local signal that it is unsafe in entry position, and the constraint is not documented anywhere: `send(..., wait=True)` is not stated to be non-reentrant from within entry/exit actions on the same interpreter.

The failure mode is what makes it worse than its likelihood suggests: an **unbounded hang inside `start()`** with every observability surface reporting health — `last_error is None`, `status == "running"`, a legal configuration, and `current_state_ids` populated. There is no `on_invocation_stranded` (#207) signal because no `invoke` is involved, nothing in the logs names the cause, and the symptom is identical to a merely slow entry action. A supervisor that retries startup on timeout will retry for ever, each attempt leaking a parked task and an interpreter; one that does not retry simply never comes up.

**Order management.** In our adoption audit (#26) the affected shape is the **session-bootstrap entry action on a long-running OMS process**: a venue-session machine whose initial state's entry action calls the shared "announce and confirm" helper — publish a state-change notification and await its receipt — before the session is declared open. That helper is used in dozens of non-entry positions where it is correct, and it is the same routine the heartbeat group calls. If it is ever reached from entry position, the venue session hangs at open with `status == "running"`: the supervisor's health check passes, the session never trades, and no error is ever surfaced to route orders away from that venue. A silent never-open is strictly worse for an OMS than a loud failed-open, because failover keys on the error.

## Proposed fix

Two options, both cheap, and not mutually exclusive:

1. **Set `_descent_done` before running entry actions and use a re-entrancy flag** to preserve #215's ordering guarantee. This is what #215's own entry describes as the sync engine's approach (`CHANGELOG.md:49-54`, "the sync engine's re-entrancy guard"), and `SyncInterpreter` does not deadlock on this chart. It preserves the lap-parity property #215 exists for while removing the deadlock, because the guard is checked by the *re-entrant* caller rather than waited on by the loop.
2. **Bound the gate** — `await asyncio.wait_for(self._descent_done.wait(), <timeout>)` at `interpreter.py:1726` — and raise a named error on expiry so the cycle is at least loud and diagnosable. Worth doing as a safety net regardless of (1), since it converts any future variant of this cycle from a silent hang into an error.

Separately, document that `send(..., wait=True)` is **not reentrant from within entry/exit actions on the same interpreter** — that constraint is not currently stated anywhere, and it is not obvious from the receipt API.

## Acceptance criteria

- `test_start_returns_when_entry_action_awaits_own_receipt__async_def` — an `async def` entry action doing `await i.send("GO", wait=True)`; `start()` must return (or raise a named, documented error) within a bounded time rather than hanging. Assert `last_error` is either `None` with `start()` returned, or the named error — never "hung and silent".
- `test_start_returns_when_entry_action_awaits_own_receipt__def_helper` — the plain-`def` lane: a `def` entry action that schedules the same receipt-awaiting helper; `start()` must still be bounded, confirming the fix is not keyed to the coroutine spelling.
- `test_sync_engine_entry_reentrant_send_unchanged` — `SyncInterpreter` parity guard: the equivalent chart must keep its current (non-deadlocking) behaviour, so the async fix converges on the sync engine's re-entrancy-guard semantics rather than diverging further.
- `test_start_descent_always_cycle_still_bounded__both_engines` — regression guard for the control: an `always` self-cycle in the descent must still return with `RunawayChainError` at `maxIterations`, i.e. the fix must not remove #215's settle coverage of the descent.
- `test_descent_lap_parity_unchanged` — the three-lane lap-parity property #215 was written for (`always` + zero-delay `raise`, limits 1–25) must still hold after the gate change; re-run the existing #215 sweep unmodified.
- `test_descent_queued_raise_not_consumed_early` — the ordering guarantee itself: a `raise` queued by a descent entry action must still not be consumed by the run loop before the descent settles, proven with an `async def` entry action that yields mid-descent.

## Related

- **#215** — introduced the `_descent_done` gate this hangs on; the residual is one hop out from the fix that shipped.
- **#207** — `on_invocation_stranded`; explicitly does **not** cover this, since no `invoke` is involved, which is why the hang has no observability surface.
- **#209** / **#201** — the lap-parity claims #215's gate exists to make true; the fix must not regress them.
- Prior closures in the same class, all requiring `start()` to be bounded and loud: **#181** (`await start()` hangs on a slow invoked child), **#194** (`start(children_timeout=)` a no-op), **#103** / **#144** / **#166** (non-terminating `start()` / `send(wait=True)`, all Blocker), **#148** (status `running` while a receipt hangs for ever).

## Verification

- Repro executed fresh from neutral cwd `<home>` against `c78ce99` (`git rev-parse HEAD` = `c78ce991e23c9cdaaeec99b29351ceb690044c2c`), venv `_ref/xstate-statemachine/.venv-main`, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. **Exit code 1.** Output in *Observed* is that run, verbatim.
- The fenced block under *Minimal reproduction* is **byte-identical** to `repro/R11-06_descent_gate_start_hang.py` (diff-checked after extraction), imports nothing outside the stdlib and `xstate_statemachine`, and inlines every helper.
- Causality established without touching library source: a subclass opening the gate before spawning the loop returns `start()` in 0.00 s on the identical chart (3.01 s → 0.00 s).
- Control B (`always` self-cycle, plain `def` action) returns bounded with `RunawayChainError` in the same run, so the hang is specific to the receipt cycle and not a general descent-unboundedness claim.
- Source lines quoted in *Root cause* re-read at `c78ce99`: `interpreter.py:625`, `:720`, `:739-740`, `:1723-1726`, `:475`, `:284`.
- Contract quote re-read at `c78ce99`: `CHANGELOG.md:49-54`.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all --limit 300 --search` over `descent`, `start hang`, `deadlock`, `receipt`, `wait=True` — nothing open, and no existing issue covers the `_descent_done` gate (#215 itself is CLOSED and this is its residual, filed new rather than reopened).
