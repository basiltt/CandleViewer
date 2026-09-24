---
r5: R5-08
title: "Bug: `send_threadsafe()` bypasses the #105 self-send gate, so an action that hands its own re-trigger to a worker thread is never charged to `maxIterations`"
labels: [bug, severity/high, area/interpreter]
severity: High
repro_script: repro/R5-08_threadsafe-bypasses-self-send-gate.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

#105 made a `send()` issued *from inside one of this interpreter's own
actions* route to the internal queue and count against the machine's
`maxIterations` chain budget, closing the unbounded-self-feed hole. The
classification is implemented as `_ACTIVE_ACTION_OWNER.get() is self` — a
`contextvars.ContextVar` read. A thread started by a user action runs in a
**fresh, empty context**, so `send_threadsafe()` from that thread reads
`None`, is classified as *external* traffic, and skips the budget entirely.
The documented hand-off-to-a-worker pattern is therefore the one route on
which `maxIterations` is unenforceable: on this repro the direct route stops
at 21 executions against a limit of 20, while the `send_threadsafe` route
runs to the probe's own ceiling of 60 with the budget never engaging.

## Environment

- Commit: `3ed3099` (`main`, merge of #139 `fix/0.8.1-round4`; unreleased
  0.8.1 — `__version__` still reports `0.8.0`, so this build is identified
  by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
"""R5-08 repro: `send_threadsafe` bypasses the #105 self-send gate.

`_issued_from_own_action()` reads a `ContextVar`. A thread started by a user
action gets a fresh, empty context, so its `send_threadsafe` is classified as
an EXTERNAL event, skips the internal queue, and is never charged to the
chain budget. `maxIterations` therefore does not bound an action that hands
its own re-trigger to a worker thread.

Control (same machine, same action, direct `await i.send(...)`) IS budgeted.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""

import asyncio
import logging
import sys
import threading

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CEILING = 60  # the action's own stop, so the probe always terminates
LIMIT = 20  # machine maxIterations

CFG = {
    "id": "spin",
    "initial": "a",
    "maxIterations": LIMIT,
    "context": {},
    "states": {"a": {"on": {"T": {"actions": ["resend"]}}}},
}


async def run(mode: str) -> int:
    seen = {"n": 0}

    async def resend(i, c, e, a):
        seen["n"] += 1
        if seen["n"] >= CEILING:
            return
        if mode == "direct":
            await i.send("T")
        else:
            threading.Thread(
                target=lambda: i.send_threadsafe("T"), daemon=True
            ).start()

    interp = await Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"resend": resend}))
    ).start()
    await interp.send("T")
    await asyncio.sleep(1.5)
    await interp.stop()
    return seen["n"]


async def main() -> int:
    direct = await run("direct")
    threadsafe = await run("threadsafe")

    print("OBSERVED:")
    print("  maxIterations                       :", LIMIT)
    print("  direct  `await i.send()` executions  :", direct)
    print("  `send_threadsafe()` executions       :", threadsafe)
    print("  threadsafe budgeted (<= 25)          :", threadsafe <= 25)
    print("EXPECTED:")
    print("  both routes are self-generated work and are charged to the")
    print("  chain budget; both counts <= ~25 (maxIterations + slack)")

    if threadsafe > 25:
        print("RESULT: FAIL - send_threadsafe is not gated by maxIterations")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED:
  maxIterations                       : 20
  direct  `await i.send()` executions  : 21
  `send_threadsafe()` executions       : 60
  threadsafe budgeted (<= 25)          : False
EXPECTED:
  both routes are self-generated work and are charged to the
  chain budget; both counts <= ~25 (maxIterations + slack)
RESULT: FAIL - send_threadsafe is not gated by maxIterations
```

Exit status `1`.

`60` is the *probe's* ceiling, not the library's — the action stops itself at
`CEILING` so the script always terminates. Without that stop the chain is
unbounded. The corroborating probe in our audit
(`probes/main-3ed3099/p2_gate_and_inline.py`, cases J-4/J-4b/J-4c) shows the
same split across all three self-send routes: `create_task(send(...))` → 21
(budgeted), a nested action → 21 (budgeted), `send_threadsafe` from a
thread → 60 with `j4c_threadsafe_budgeted: false`.

## Expected behaviour

The library's own contract, `src/xstate_statemachine/interpreter.py:1622-1625`:

> ``True`` when the current task is inside one of THIS interpreter's user
> actions (#105) -- the only case a `send()` is self-generated.

and at `interpreter.py:741-748`:

> #90: a `send()` issued FROM AN ACTION on this interpreter is
> self-generated work, exactly like `raise`. It used to bypass the chain
> budget entirely … Route it to the internal queue and count it.

`maxIterations` is documented as the ceiling on self-generated work per
macrostep. Whether the action delivers its re-trigger on the loop or via a
worker thread is an implementation detail of the *user's* code; the
causal relationship — this event exists because that action ran — is
identical, so the accounting must be identical. `send_threadsafe` is
documented as "the same guardrail as `send()`"
(`interpreter.py:1035-1039`, for `#78` strict/schema validation), which
sets the expectation that the two entry points agree on classification.

SCXML §3.13 draws the same line by *origin*, not by transport: events the
machine generates during a macrostep are internal and are processed before
the next external event; only genuinely external input restarts the step.

## Root cause analysis

`src/xstate_statemachine/interpreter.py:75-76` declares the owner as a
context variable:

```python
_ACTIVE_ACTION_OWNER: "contextvars.ContextVar[Optional[BaseInterpreter[Any]]]" = (
    contextvars.ContextVar("xsm_active_action_owner", default=None)
)
```

and `interpreter.py:1622-1625` is the whole classifier:

```python
def _issued_from_own_action(self) -> bool:
    return _ACTIVE_ACTION_OWNER.get() is self
```

`send()` consults it on both the BLOCK path (`:722`) and the default path
(`:750`) and, when it returns `True`, appends to `self._internal_queue` and
increments `self._raise_depth` — the budgeted route.

`send_threadsafe()` (`interpreter.py:1002-1045`) never consults it at all.
It validates the event on the calling thread (`_check_strict`, `:1040` — the
#78 guardrail) and then schedules:

```python
async def _deliver() -> None:
    self._enqueue(event_obj)

return asyncio.run_coroutine_threadsafe(_deliver(), self._loop)
```

`_enqueue` is the *external* inbox path. Two things defeat the gate here even
if the call were added:

1. **`contextvars` does not propagate to `threading.Thread`.** Only
   `asyncio.create_task` copies the current context, which is exactly why
   J-4's `create_task(send(...))` case *is* correctly budgeted — the child
   task inherits the owner. A plain thread starts from a fresh context and
   reads the `default=None`.
2. **The coroutine runs on the loop, not in the caller's context.**
   `run_coroutine_threadsafe` executes `_deliver()` in whatever context the
   loop gives it, so moving the check inside `_deliver` would not recover the
   caller's identity either.

The classifier is therefore correct for every *task*-based route and
structurally blind to every *thread*-based one.

## Impact

**General users.** `send_threadsafe` exists precisely for the "hand the slow
work to a worker thread and send the result back" pattern, which the services
and concurrency docs recommend. Any action that spawns a worker which can
re-trigger the same state — a retry loop, a poller, a reconnect backoff —
has no ceiling. The symptom is not an exception but unbounded CPU and an
event loop that never reaches quiescence, with `maxIterations` configured and
apparently in force (the same machine driven the direct way stops correctly,
so a test written against the direct route passes).

**Order-management scenario (our adoption audit, #26).** Our exchange client
is threaded: an action on `submitting` hands the REST call to a worker and the
worker calls `send_threadsafe("ACK")` / `send_threadsafe("REJECT")` when it
returns. A reject that re-enters `submitting` (the standard retry shape) is a
self-feeding chain, and `maxIterations` — the control we rely on to stop a
retry storm from becoming an order storm — does not engage. The machine
re-submits without bound while every configured safety limit reads as set.
This is the reason our constraint CV-C33 now forbids calling
`send_threadsafe` directly and routes it through a gateway that applies the
self-send rule by hand.

## Proposed fix

**Capture the classification on the calling thread, carry it to the loop.**
`send_threadsafe` already does its validation work on the caller's thread for
exactly this reason (#78). Do the same for ownership:

```python
def send_threadsafe(self, event_or_type, **payload):
    ...
    event_obj = self._prepare_event(event_or_type, **payload)
    self._check_strict(event_obj)
    self_issued = self._issued_from_own_action()   # caller's context

    async def _deliver() -> None:
        if self_issued and not self._refuse_if_not_running(event_obj):
            self._raise_depth += 1
            self._internal_queue.append(event_obj)
            return
        self._enqueue(event_obj)

    return asyncio.run_coroutine_threadsafe(_deliver(), self._loop)
```

This alone does not help a *plain* `threading.Thread`, because the context
does not cross the thread boundary. Two complementary options:

- **Preferred — make the owner thread-inheritable at the spawn site the
  library controls.** Where the engine invokes a user action it already sets
  `_ACTIVE_ACTION_OWNER`; additionally record the owner on a
  `threading.local()`-backed registry keyed by the *spawning* thread, and have
  `_issued_from_own_action()` fall back to walking that registry. This is the
  only approach that catches a thread the user starts themselves, which is the
  documented pattern.
- **Simpler, explicit — an opt-in parameter.**
  `send_threadsafe(..., internal=True)` (or `send_threadsafe_internal`) that
  routes to the internal queue and the budget. Cheap, no magic, but it makes
  correct accounting the caller's responsibility and so does not close the
  hole for existing code.

A third, orthogonal defence worth having regardless: make the chain budget
observable when it *would* have tripped. Today the only evidence of the
bypass is that nothing happens.

**Compatibility.** Routing a genuinely self-issued threadsafe send to the
internal queue changes ordering for those events (they are now processed
before pending external traffic, matching `send()`), and can newly trip
`RunawayChainError` on code that previously spun silently. Both are the
intended semantics of #105/#90; call it out in the changelog. Externally
issued `send_threadsafe` calls — the overwhelming majority — are unaffected.

## Acceptance criteria

- [ ] `repro/R5-08_threadsafe-bypasses-self-send-gate.py` exits `0`.
- [ ] `tests/test_round5_findings.py::test_send_threadsafe_from_action_spawned_thread_is_budgeted`
      — an action that starts a `threading.Thread` calling
      `send_threadsafe` on its own interpreter stops at `maxIterations`,
      with the same count (±1) as the direct `await i.send()` route.
- [ ] `tests/test_round5_findings.py::test_send_threadsafe_from_action_trips_runaway_chain_error`
      — the trip is observable: `last_transition_ok` is `False` and
      `last_error` is a `RunawayChainError`.
- [ ] `tests/test_round5_findings.py::test_send_threadsafe_from_foreign_thread_is_still_external`
      — a thread with no action on its stack is NOT charged to the budget
      and keeps external ordering (no regression for the normal use).
- [ ] `tests/test_round5_findings.py::test_self_send_classification_parity`
      — a table over all four routes (`await send`, `create_task(send)`,
      nested action, `send_threadsafe` from a spawned thread) asserting
      identical budget behaviour.
- [ ] Docs: `docs/_guide/interpreters.md` `send_threadsafe` section states
      whether a send from an action-spawned thread is internal or external.

## Related

- **Round-4 issues:** #105 (the self-send gate this bypasses), #90 (routing
  an action's `send()` to the internal queue and counting it), #78 (the
  precedent for doing work on the calling thread inside `send_threadsafe`).
- **R5-09** — the other half of the budget story: the settle budget is reset
  per drain rather than per macrostep. Both are "the ceiling is not applied
  where the contract says it is"; they are independent code paths.
- **R5-16** (Medium) — `send_threadsafe` has no usable backpressure signal on
  the calling thread. Same method, same root shape: work that the caller
  should learn about synchronously is deferred onto the loop.
- **Register source ids:** R5-08 ← `J-4` (`32-r5-diff-review.md`).
- **Evidence:** `probes/main-3ed3099/p2_gate_and_inline.py` (cases J-4,
  J-4b, J-4c, J-4d); `33-r5-findings-register.md` §2/§3 R5-08.

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7
- Commit: `3ed3099`
- Re-ran `repro/R5-08_threadsafe-bypasses-self-send-gate.py` fresh: exit `1`,
  output unchanged (`direct: 21`, `threadsafe: 60`, budgeted: `False`).
- Root-cause citations checked against source: `interpreter.py` declares
  `_ACTIVE_ACTION_OWNER` as a module-level `ContextVar`, `_issued_from_own_action`
  reads it (`return _ACTIVE_ACTION_OWNER.get() is self`), and `send_threadsafe`
  validates via `_check_strict` then schedules `_deliver()` (which calls
  `_enqueue`, the external path) via `run_coroutine_threadsafe` — matches the
  finding's description; line numbers drift by a couple of lines from comment
  reflow but content and control flow are exactly as cited.
- Duplicate check: `gh issue list --search "send_threadsafe"` returns #78
  (strict/`event_schemas` bypass — a different guardrail), #37, #85, #79 — none
  cover the `maxIterations`/self-send-gate bypass via a spawned thread. No
  duplicate found.
- Self-contained, no project-name/label leak: confirmed.
