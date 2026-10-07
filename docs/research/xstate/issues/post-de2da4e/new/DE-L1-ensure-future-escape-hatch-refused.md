---
id: DE-L1
title: "Bug: ReentrantWaitError (#219) refuses the documented `ensure_future` escape hatch, because the guard rides an inheritable ContextVar"
labels: [bug, area/interpreter, events, severity/medium]
severity: Medium
repro_script: repro/DE-L1-ensure-future-escape-hatch-refused.py
commit: de2da4e
verified: true
---

## Summary

This is from our "make it perfect" list after twelve rounds of adoption
review: the library is adopted and running, and these are the few items
left between *adopt with constraints* and *nothing open*.

The #219 changelog states the contract plainly:

> *"The receipt can still be handed out (`asyncio.ensure_future(i.send(..., wait=True))`) and awaited later; only the in-step await is refused."*

The guard's predicate is wider than that contract. `_ACTIVE_ACTION_OWNER`
is a `ContextVar`, and `asyncio.ensure_future` / `create_task` **copy the
current context**, so a task spawned inside an action inherits
`_ACTIVE_ACTION_OWNER = <this interpreter>` and keeps it **for its whole
life** — long after the spawning action returned and the run loop went
idle. The predicate therefore reads *"this task descends from one of my
actions"*, not *"this task is one of my actions"*, and only the second
implies a deadlock.

Two shapes are refused in which no deadlock is possible:

* **Lane A — a background worker born in an action.** An entry action does
  `asyncio.ensure_future(worker(i))`; `worker` sleeps 300 ms — the machine
  is long quiescent — then `await i.send("GO", wait=True)`. Refused.
* **Lane B — the documented idiom itself, whenever the spawning action
  yields.** If the action awaits anything after handing the receipt out,
  the wrapper task is scheduled *while the action is still on the stack*
  and is refused.

**This is not a request to revert #219.** That fix converts a silent
permanent `start()` deadlock into a loud immediate error and is strictly
better than what it replaced. It is a report that the predicate lands on
the exact escape hatch the changelog documents, non-deterministically.

## Environment

* Library: `main` @ `de2da4e` (unreleased 0.8.1; `__version__` still
  reports `0.8.0`, so this keys on the commit).
* CPython 3.13.7, Windows 11, fresh venv, run from a neutral cwd.
* Engine: async (`Interpreter`). The sync engine is **already correct** —
  `sync_interpreter.py:584` gates on the instance flag `self._is_processing`,
  which is exactly the predicate proposed below.

## Minimal reproduction

Standalone: stdlib + `xstate_statemachine` only, every helper inlined, run
from the neutral cwd `<home>`. **Exit 1 = reproduced.**

```python
"""STANDALONE repro — DE-L1: the documented #219 `ensure_future` escape hatch
is refused, because the guard rides an INHERITABLE ContextVar.

Library @ de2da4e (unreleased 0.8.1; __version__ still reports 0.8.0).
stdlib + xstate_statemachine only. Every helper inlined. Run from ANY cwd.

Exit 1 == DEFECT REPRODUCED.
"""

import asyncio
import contextvars
import sys

from xstate_statemachine import create_machine, Interpreter
from xstate_statemachine.machine_logic import MachineLogic

CONFIG = {
    "id": "de",
    "initial": "x",
    "states": {
        "x": {"entry": ["kick"], "on": {"GO": "y"}},
        "y": {},
    },
}

WATCHDOG = 10.0


async def _case(spawn, label):
    """Returns (outcome, final_state)."""
    box = {"outcome": None}

    async def worker(interp):
        # The machine is long idle by now; the run loop is NOT in a step,
        # so no deadlock is possible on this await.
        await asyncio.sleep(0.30)
        try:
            await interp.send("GO", wait=True)
            box["outcome"] = "OK"
        except Exception as exc:  # noqa: BLE001
            box["outcome"] = type(exc).__name__

    holder = {}

    async def kick(interp, ctx, event, action_def):  # entry action
        spawn(holder, worker, interp)

    logic = MachineLogic(actions={"kick": kick})
    machine = create_machine(CONFIG, logic=logic)
    interp = Interpreter(machine)
    await asyncio.wait_for(interp.start(), timeout=WATCHDOG)

    deadline = asyncio.get_running_loop().time() + 5.0
    while box["outcome"] is None and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)  # poll to convergence

    state = sorted(interp.current_state_ids)
    await interp.stop()
    print(f"  {label:<46} -> {box['outcome']!r}, state={state}")
    return box["outcome"], state


def _spawn_inherited(holder, worker, interp):
    """The idiom `interpreters.md` prescribes."""
    holder["t"] = asyncio.ensure_future(worker(interp))


def _spawn_fresh_context(holder, worker, interp):
    """The workaround: a FRESH context, so _ACTIVE_ACTION_OWNER is unset."""
    ctx = contextvars.Context()
    holder["t"] = ctx.run(asyncio.ensure_future, worker(interp))

# --------------------------------------------------------------------------
# LANE B -- the documented idiom itself, when the spawning action yields.
# `interpreters.md` prescribes `asyncio.ensure_future(i.send(..., wait=True))`
# and "await it later". If the action awaits anything at all afterwards, the
# wrapper task runs WHILE the action is still on the stack and is refused.
# --------------------------------------------------------------------------


async def _lane_b(action_yields, label):
    """Returns (outcome, final_state)."""
    box = {}

    async def kick(interp, ctx, event, action_def):  # entry action
        box["h"] = asyncio.ensure_future(interp.send("GO", wait=True))
        if action_yields:
            await asyncio.sleep(0.05)  # ANY further await flips the outcome

    logic = MachineLogic(actions={"kick": kick})
    machine = create_machine(CONFIG, logic=logic)
    interp = Interpreter(machine)
    await asyncio.wait_for(interp.start(), timeout=WATCHDOG)

    try:
        await asyncio.wait_for(box["h"], timeout=5.0)
        outcome = "OK"
    except Exception as exc:  # noqa: BLE001
        outcome = type(exc).__name__

    state = sorted(interp.current_state_ids)
    await interp.stop()
    print(f"  {label:<46} -> {outcome!r}, state={state}")
    return outcome, state


async def main():
    print("DE-L1 — background worker spawned inside an action, sends 300ms AFTER idle")
    print("The machine is quiescent when the send happens; no deadlock is possible.\n")

    inherited, st_inherited = await _case(_spawn_inherited, "ensure_future (documented idiom)")
    fresh, st_fresh = await _case(_spawn_fresh_context, "ensure_future in a FRESH context")

    print()
    print("LANE B -- the documented idiom, await-it-later, action returns vs yields")
    print("Same idiom; the only difference is whether the action awaits afterwards.")
    print()

    no_yield, st_no_yield = await _lane_b(False, "ensure_future, action returns at once")
    yielded, st_yielded = await _lane_b(True, "ensure_future, action then awaits 50ms")

    print()
    lane_a = inherited == "ReentrantWaitError" and fresh == "OK"
    lane_b = no_yield == "OK" and yielded == "ReentrantWaitError"
    print(f"A: documented idiom refused after idle : {inherited == 'ReentrantWaitError'}")
    print(f"A: fresh-context control works         : {fresh == 'OK'}")
    print(f"A: machine advanced (idiom / control)  : {st_inherited == ['de.y']} / {st_fresh == ['de.y']}")
    print(f"B: idiom OK when the action returns    : {no_yield == 'OK'}")
    print(f"B: SAME idiom refused when it yields   : {yielded == 'ReentrantWaitError'}")
    print(f"B: machine advanced (returns / yields) : {st_no_yield == ['de.y']} / {st_yielded == ['de.y']}")

    reproduced = lane_a and lane_b
    print()
    print(f"REPRODUCED (both lanes): {reproduced}")
    return 1 if reproduced else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), timeout=30.0)))
    except asyncio.TimeoutError:
        print("WATCHDOG: hung")
        sys.exit(2)
```

## Observed behaviour

```
DE-L1 — background worker spawned inside an action, sends 300ms AFTER idle
The machine is quiescent when the send happens; no deadlock is possible.

  ensure_future (documented idiom)               -> 'ReentrantWaitError', state=['de.x']
  ensure_future in a FRESH context               -> 'OK', state=['de.y']

LANE B -- the documented idiom, await-it-later, action returns vs yields
Same idiom; the only difference is whether the action awaits afterwards.

  ensure_future, action returns at once          -> 'OK', state=['de.y']
  ensure_future, action then awaits 50ms         -> 'ReentrantWaitError', state=['de.x']

A: documented idiom refused after idle : True
A: fresh-context control works         : True
A: machine advanced (idiom / control)  : False / True
B: idiom OK when the action returns    : True
B: SAME idiom refused when it yields   : True
B: machine advanced (returns / yields) : True / False

REPRODUCED (both lanes): True
```

Exit code **1**. In both refusals the machine does **not advance** (stays in
`x`) and the receipt is abandoned; the caller gets a hard exception where
it previously got a resolved receipt.

## Expected behaviour

Both lanes resolve their receipts and the machine reaches `y`:

* A helper task that outlives the action which spawned it, sending to a
  quiescent interpreter, is ordinary external traffic and must not be
  refused.
* The documented `ensure_future` idiom behaves identically whether or not
  the spawning action awaits afterwards. Today its safety is **scheduling
  order, not a property of the API** — and the pinned test
  `test_handing_out_the_receipt_and_awaiting_later_is_fine` passes only
  because its action returns immediately, so it cannot catch lane B.

## Root cause analysis

`interpreter.py:1144` — the guard inside the `_Awaitable` returned by the
receipt wrapper:

```python
if _ACTIVE_ACTION_OWNER.get() is self and not receipt.done():
    raise ReentrantWaitError(self.id, event_type)
```

`interpreter.py:76` declares `_ACTIVE_ACTION_OWNER` as a
`contextvars.ContextVar`; `interpreter.py:2256` sets it for the duration of
`_run_user_action`:

```python
token = _ACTIVE_ACTION_OWNER.set(self)
try:
    ...
finally:
    _ACTIVE_ACTION_OWNER.reset(token)
```

The `reset` restores the value **in the action's own context**. A task
created from that context during the window already holds an independent
copy, which the `reset` cannot reach — so the spawned task carries
`_ACTIVE_ACTION_OWNER is self` for its entire life, including long after
the run loop went idle. That is inheritance working as designed; it is just
not the question the guard needs answered.

The `ContextVar` is the right tool for the **provenance** question #105
asks (*"who produced this event?"* — provenance *should* be inherited by
descendants, and `_issued_from_own_action` at `interpreter.py:2326` is a
correct use of it). It is the wrong tool for the **liveness** question #219
asks (*"can this await make progress?"*), which is a property of the run
loop at this instant and is not inherited by anything.

## Impact

* The escape hatch the changelog documents is refused
  **timing-dependently** — an adopter who adds one `await` to an action
  flips a working idiom into a hard exception.
* The standard "an action kicks off a long-lived helper that later asks the
  machine a question" pattern is broken; it worked on `c78ce99` and raises
  on `de2da4e`, so `ReentrantWaitError` is effectively a breaking change
  for that shape.
* The failure surfaces only under timing a unit test tends not to produce,
  which is why the existing pin does not catch it.

Mitigating (and why we rate this **Medium**, not High — recorded so the
severity is arguable rather than asserted):

1. Every refused shape has a deterministic documented alternative.
2. The failure is **loud and immediate**, not silent.
3. It is **strictly safer than the behaviour it replaced** — a permanent
   silent `start()` deadlock with `last_error = None`.

Points 1–3 are properties of the defect. For a project that *does* use the
documented idiom this breaks a pattern the docs actively recommend, and we
would understand it being rated higher upstream than it is on our board.

## Proposed fix

Key the guard on the identity of the **currently-executing action** rather
than on an inherited `ContextVar` — i.e. gate on the interpreter actually
being mid-action, using state that cannot propagate into spawned tasks.

The sync engine already does exactly this (`sync_interpreter.py:584` reads
the instance flag `self._is_processing`), so this also brings the two
engines to one predicate.

```python
# interpreter.py, _run_user_action (~2256)
token = _ACTIVE_ACTION_OWNER.set(self)
self._in_user_action += 1            # plain instance counter, not inherited
try:
    ...
finally:
    self._in_user_action -= 1
    _ACTIVE_ACTION_OWNER.reset(token)

# interpreter.py, the guard (~1144)
if (
    self._in_user_action
    and _ACTIVE_ACTION_OWNER.get() is self
    and not receipt.done()
):
    raise ReentrantWaitError(self.id, event_type)
```

Requiring **both** conditions preserves every refusal #219 intends — the
genuine in-step await is, by construction, still inside `_run_user_action`,
so the counter is non-zero — while releasing both false positives, because
a task that outlives the action sees `_in_user_action == 0`.

A counter rather than a bool because actions can nest (an action that
awaits something which runs another action); a bool would be cleared early
by the inner `finally`.

A strictly tighter variant, if you would rather not add state: compare
`asyncio.current_task()` against the task recorded when the action was
entered. That is the literal "is this the action's own task" test and is
equivalent for every shape we could construct; the counter is simpler and
cheaper on the hot path.

**Even without a code change**, the documentation fix is small and would
help a lot: state that the `ensure_future` escape hatch is only safe if the
spawning action **returns without further awaiting**, and document
`contextvars.Context().run(asyncio.ensure_future, ...)` as the supported
spelling for a helper that must talk back to the machine. We have taken
that second route on our side, but we would still rather see the predicate
narrowed, because the current behaviour is order-dependent.

## Acceptance criteria

* `repro/DE-L1-ensure-future-escape-hatch-refused.py` exits **0** — all
  four rows resolve `OK` and reach `de.y`.
* New test `test_worker_spawned_in_an_action_may_wait_after_idle`: an entry
  action `ensure_future`s a helper that sleeps past quiescence and then
  `await interp.send(..., wait=True)`; the receipt resolves and the machine
  advances.
* The existing pin
  `test_handing_out_the_receipt_and_awaiting_later_is_fine` is
  **parametrised over `action_yields ∈ {False, True}`** and passes on both
  — this is the assertion that closes lane B and that the current pin
  cannot make.
* Regression guard, unchanged: an action that awaits its own receipt
  **in-step** still raises `ReentrantWaitError`, and `start()` still
  returns rather than hanging — on both engines.
* The async and sync engines agree on the predicate (the round-11 `p4`
  seven-cell matrix still passes on both).

## Verification

- Repro run from the neutral cwd `<home>` with the `.venv-main`
  interpreter (`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`), well inside the 90 s
  bound: **exit 1**, no `ImportError`, output exactly as quoted under
  "## Observed behaviour", `REPRODUCED (both lanes): True`.
- The code block under "## Minimal reproduction" is **byte-identical** to
  `repro/DE-L1-ensure-future-escape-hatch-refused.py` (5287 bytes, compared
  programmatically).
- Root-cause lines confirmed open in current source at `de2da4e`:
  - `interpreter.py:1144` — `if _ACTIVE_ACTION_OWNER.get() is self and not
    receipt.done():`, the guard predicate, verbatim as quoted.
  - `interpreter.py:76` — `_ACTIVE_ACTION_OWNER` declared as a `ContextVar`.
  - `interpreter.py:2256` — `token = _ACTIVE_ACTION_OWNER.set(self)`, the
    set/reset around `_run_user_action`.
  - `interpreter.py:2326` — `return _ACTIVE_ACTION_OWNER.get() is self`,
    `_issued_from_own_action`, the correct provenance use of the same var.
  - `sync_interpreter.py:584` — `if wait and self._is_processing:`, the
    instance-flag predicate the proposed fix would bring the async engine
    to. Confirmed the flag is a plain `bool` attribute
    (`sync_interpreter.py:220`), set and cleared around processing
    (`sync_interpreter.py:380/397/401`).
- The documented contract this contradicts is confirmed present verbatim:
  `CHANGELOG.md:28` ("The receipt can still be handed out
  (`asyncio.ensure_future(i.send(..., wait=True))`) and awaited later; only
  the in-step await is refused") and — more directly —
  `docs/_guide/interpreters.md:519`, where the idiom is annotated
  `# fine: awaited elsewhere` with no stated precondition.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 320` searched for `ensure_future`, `ReentrantWaitError`,
  `ContextVar`. The only hit is `#219` itself (CLOSED); nothing open covers
  the guard's width.

## Related

* #219 (the fix this refines), #105 (`_ACTIVE_ACTION_OWNER`'s original
  provenance purpose), PR #223.
* `interpreters.md` — the `asyncio.ensure_future(i.send(..., wait=True))`
  idiom this refuses.
* `tests/test_round11_findings.py::test_handing_out_the_receipt_and_awaiting_later_is_fine`
  — the pin whose green result is scheduling luck.
* Our adoption audit (#26), round 12.
