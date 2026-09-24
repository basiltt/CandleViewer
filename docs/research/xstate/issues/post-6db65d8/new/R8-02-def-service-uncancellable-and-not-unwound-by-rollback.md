---
r8: R8-02
title: "Bug: a plain `def` service is uncancellable and is not unwound by `rollback` or by an `always` — the `async def` spelling of the same service is correct on both"
labels: [bug, severity/high, area/interpreter]
severity: High
engines: async `Interpreter`
service_kinds: plain `def` only (the `async def` control is correct)
repro_script: repro/R8-02_def_service_uncancellable_and_not_rolled_back.py
commit: 6db65d8
python: 3.13.7
verified: true
---

## Summary

**Scope first, because we refuted our own initial claim.** A plain `def` service does
**NOT** run inline on the event loop and does **not** block the process: #149 moved it to
`loop.run_in_executor` (`interpreter.py:2811-2836`), and the residual per-machine stall is
correctly documented — *"A plain-`def` service blocks its own machine's timers for its
whole duration (#174) … Other machines on the loop are unaffected"*
(`docs/_guide/production-characteristics.md:93`). That half of our draft is **withdrawn**.

This issue is scoped to the behaviour that survived refutation: a plain `def` service on
the async engine is **uncancellable** and is **not unwound** by `actionErrorPolicy:
"rollback"` or by an `always` roll-forward, while the `async def` spelling of the same
service is correct on both counts. The service *definition kind* — a detail with no
semantics in the statechart — decides whether a cancel lands and whether a rollback undoes
an invoke.

## Environment

* Commit `6db65d8` (unreleased 0.8.1; `__version__` reports `0.8.0`)
* Python 3.13.7, Windows 11
* Async `Interpreter`; plain `def` services (the `async def` control is correct)

## Reproduction (`6db65d8`, both spellings side by side)

`repro/R8-02_def_service_uncancellable_and_not_rolled_back.py` → **exit 1**, verbatim:

```
PASS  {'style': 'async', 'mid_service': ['m.busy'], 'after_cancel': ['m.cancelled'],
       'final': ['m.cancelled'], 'cursor': 0}
FAIL  {'style': 'def',   'mid_service': ['m.busy'], 'after_cancel': ['m.done'],
       'final': ['m.done'],      'cursor': 4242}

BUG: the `def` service was not cancelled; its onDone landed cursor=4242 in a
state that had already been exited.
```

* **Case A — cancellation.** A `CANCEL` sent mid-service loses to `done.invoke` on the
  priority lane: the machine lands `cursor=4242` and `m.done` instead of `m.cancelled`.
  The `async def` spelling cancels correctly (`cursor=0`, `m.cancelled`).
* **Case B — rollback / `always`.** With `actionErrorPolicy: "rollback"` and with an
  `always` guard that leaves the invoking state, the service is invoked anyway:
  `service_calls=["submit_child"]` in **both** cases. The `async def` task's arming *is*
  unwound in both.

## Expected

SCXML §3.9 / §6.4.2 is unambiguous, and the library's `def`/`async def` split has no
licence to diverge from it:

> To exit a state, the SCXML Processor **MUST** execute the executable content in the
> state's `<onexit>` handler. Then it **MUST cancel any ongoing invocations that were
> triggered by that state.**

> If the invoking session takes a transition out of the state containing the `<invoke>`
> before it receives the `done.invoke.id` event, the SCXML Processor **MUST** automatically
> cancel the invoked component and stop its processing. … Once it cancels the invoked
> session, the Processor **MUST** ignore any events it receives from that session. In
> particular it **MUST NOT** insert them into the external event queue of the invoking
> session.

`cursor=4242` is exactly the forbidden case: an event from a cancelled invocation applied
after its state was exited. XState v5 likewise stops an actor when its invoking state is
exited, and has no `def`/`async` distinction to condition that on.

In our own contract suite this is the only failure on the plain lane: B6–B10 run 52/52 on
`async def` and 49/52 on `def`, with all three failures collapsing to this one cause.

### Minimal reproduction — complete, standalone

Byte-identical to `repro/R8-02_def_service_uncancellable_and_not_rolled_back.py`.
Exits **1** while the defect is present, **0** once fixed.

```python
# -*- coding: utf-8 -*-
"""CV-6DB-01 -- a plain `def` service's result lands after the invoking state
was exited: it is never cancelled, and its onDone writes context in a state
that no longer invokes it. The identical machine with an `async def` service
is correct. Exits 1 on the bug.

Run: python cv_6db_01_def_invoke_not_cancelled.py
"""
import asyncio, sys, threading, time
from xstate_statemachine import Interpreter, MachineLogic, create_machine

CFG = {
    "id": "m", "initial": "idle", "context": {"cursor": 0},
    "states": {
        "idle": {"on": {"GO": "busy"}},
        "busy": {
            "invoke": {"id": "w", "src": "work",
                       "onDone": {"target": "done", "actions": ["land"]}},
            "on": {"CANCEL": "cancelled"},
        },
        "done": {}, "cancelled": {},
    },
}

def build(style):
    started = threading.Event()
    if style == "def":
        def work(i, c, e):
            started.set(); time.sleep(0.6); return {"cursor": 4242}
    else:
        async def work(i, c, e):
            started.set(); await asyncio.sleep(0.6); return {"cursor": 4242}
    def land(i, c, e, a): c["cursor"] = e.data["cursor"]
    m = create_machine(CFG, logic=MachineLogic(actions={"land": land},
                                               services={"work": work}))
    return m, started

async def case(style):
    m, started = build(style)
    it = Interpreter(m)
    await it.start()
    go = asyncio.ensure_future(it.send("GO", wait=True))
    for _ in range(200):
        if started.is_set(): break
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.05)
    mid = sorted(it.current_state_ids)
    await asyncio.wait_for(it.send("CANCEL", wait=True), 5)
    after = sorted(it.current_state_ids)
    try: await asyncio.wait_for(go, 5)
    except Exception: pass
    await asyncio.sleep(1.0)              # abandoned service finishes here
    r = {"style": style, "mid_service": mid, "after_cancel": after,
         "final": sorted(it.current_state_ids), "cursor": it.context["cursor"]}
    await asyncio.wait_for(it.stop(), 5)
    return r

async def main():
    bad = 0
    for style in ("async", "def"):
        r = await case(style)
        ok = r["cursor"] == 0 and r["final"] == ["m.cancelled"]
        print(("PASS " if ok else "FAIL "), r)
        bad += not ok
    if bad:
        print("\nBUG: the `def` service was not cancelled; its onDone landed "
              "cursor=4242 in a state that had already been exited.")
    return 1 if bad else 0

sys.exit(asyncio.run(main()))
```

## Root cause (source read at `6db65d8`)

The executor handoff happens **at entry** (`interpreter.py:2811-2836`,
`loop.run_in_executor` per #149) — before the `always` chain runs and before the rollback
epilogue. Once the callable is in the pool there is no handle the engine unwinds, and the
completion it eventually publishes wins the priority lane against a later `CANCEL`. The
coroutine path creates a task the engine *does* hold and *does* cancel.

## What this issue is NOT claiming

We want to be explicit, because our first draft of this finding was wrong and we refuted it
ourselves. A plain `def` service does **not** run inline on the loop thread and does **not**
block the process: #149 moved it to `run_in_executor`; the stall some users see is
`interpreter.py:1571-1577` awaiting `_await_inline_services()` before `_next_event()`, which
starves only that machine's inbox — other interpreters on the same loop keep running. That
behaviour is correctly and helpfully documented at
`docs/_guide/production-characteristics.md:93` (#174), including the remedy. The
documentation is what downgraded this from Blocker to High on our side.

## Why it is still a defect

Plain callables are a first-class `MachineLogic` spelling, accepted silently under
`strict=True`, and nothing warns that they change cancellation and rollback semantics. It
is not a duplicate of #116/#149/#173/#174, which cover ordering, loop blocking and pool
size only. XState v5 has no `def`/`async` distinction and no rollback policy, so it does not
sanction the divergence either way.

## Proposed fix

Either (a) make the executor handoff unwindable — register the future with the step so
`rollback` and an `always` roll-forward can drop it, and let a state exit cancel it — or
(b) reject non-coroutine services under `strict=True` with a clear error, and say plainly
in the docs that `def` services are fire-and-forget with respect to cancellation and
rollback. (b) is a smaller change and arguably the more honest one.

## Impact

**General.** Cancellation is the primary way a statechart bounds unbounded work, and
`rollback` is the library's only atomicity primitive. Both are silently inert for one of
two first-class service spellings, with no warning at `create_machine()` and none under
`strict=True`. Worse than "does not cancel": the abandoned service's `onDone` still
**writes context in a state that has already been exited** (`cursor=4242` above), so the
configuration and the context disagree about what happened.

**Order management.** A `CANCEL` that loses to the very `done.invoke` it was sent to
pre-empt means a cancel-order request races the fill it was trying to prevent — and the
fill wins, landing its payload into a state the machine has already left. An
`actionErrorPolicy: "rollback"` that does not unwind the invoke means a failed action
leaves a real, uncancellable submission in flight while the machine's own state says it
was rolled back.

## Acceptance criteria

Named tests, each parametrised over `("def", "async def")` **and** over both engines
(`Interpreter`, `SyncInterpreter`) where the construct exists:

1. `test_invoke_is_cancelled_on_state_exit[def|async def]` — a `CANCEL` delivered while
   the service runs leaves the machine in `m.cancelled` with `context["cursor"] == 0` on
   **both** spellings; the abandoned service's result is never applied after its state is
   exited (SCXML §6.4.2).
2. `test_rollback_unwinds_invoke_arming[def|async def]` — with
   `actionErrorPolicy: "rollback"`, `service_calls == []` on both spellings.
3. `test_always_rollforward_unwinds_invoke_arming[def|async def]` — an `always` that
   leaves the invoking state before it stabilises never starts the service, on both
   spellings (SCXML §6.1: `<invoke>` runs only after eventless transitions are checked).
4. `test_def_service_rejected_under_strict` — **if** fix option (b) is taken, a
   non-coroutine service under `strict=True` raises with a message naming the
   cancellation/rollback limitation.

Assert the **same** final state and the **same** `service_calls` trace across the
parametrisation — a passing `async def` arm beside a failing `def` arm is the exact shape
that let this through.

## Related

* **#149** — moved plain `def` services to `run_in_executor`. This issue is **narrower
  than our first draft claimed**: #149 is in force and the inline-blocking half is
  withdrawn. What #149 did not do is give the engine a handle it can unwind.
* **#174** — documents the surviving per-machine timer stall
  (`docs/_guide/production-characteristics.md:93`); it is the reason this is High and not
  Blocker.
* **#116** — completion-timing divergence between the engines; ordering only.
* **#173** — `service_pool_size`; pool sizing only.

None of the four covers cancellation or rollback unwinding, which is what this issue is.

## Verification

* Date: 2026-09-21 · Python 3.13.7 · commit `6db65d8`
* `repro/R8-02_def_service_uncancellable_and_not_rolled_back.py` → **exit 1**;
  `async` arm PASS, `def` arm FAIL with `cursor=4242` / `final=['m.done']`.
* Both service spellings run in the same process, back to back, in one script.
* Duplicate check: `gh issue list --state all --limit 240 --search "cancel def service"` —
  #116, #149, #171, #173, #174 all CLOSED and all scoped to ordering / loop blocking /
  pool size; no open duplicate covering cancellation or rollback unwinding.
