---
r4: R4-06
title: "Bug: external `send()` issued while a macrostep is in flight is charged to the self-raised chain budget and silently dropped"
labels: [bug, severity/high, area/interpreter, area/events]
severity: High
repro_script: repro/R4-06_external-events-charged-to-chain-budget.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

On `Interpreter` (the recommended engine), an external `await interp.send(...)`
issued from *outside* the machine while a macrostep is still in flight is
routed onto the internal ("self-raised") queue and counted against
`maxIterations`. Once the count passes the default budget of 1000, an accepted
external event is discarded at the head of the run loop with
`on_event_dropped(reason="chain_budget")`. The gate that decides "this is my
own action re-entering" is the interpreter-wide `self._processing` flag, which
only means "the run loop is busy" — it cannot distinguish a self-send from a
concurrent external producer. For a long-running stateful service with any
awaiting action (a DB write, an HTTP call) and a bursty external feed, this is
silent loss of an event the caller was told had been accepted.

## Environment

- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Install: editable (`pip install -e .`) from the `main` clone
- Engine: `Interpreter` (asyncio), default `maxIterations` (1000)

## Minimal reproduction

```python
"""R4-06 -- external `send()` made during a macrostep is charged to the
self-raised chain budget and silently dropped.

Exits 1 while the defect is present, 0 once fixed.
"""

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)

CFG = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "on": {
                "T": {"actions": ["inc"]},
                "SLOW": {"actions": ["slow"]},
            }
        }
    },
}

def inc(i, c, e, a):
    c["n"] += 1

async def slow(i, c, e, a):
    # A realistic awaiting action: a DB write, an HTTP call to a broker.
    await asyncio.sleep(0.5)

class DropSpy(PluginBase):
    def __init__(self):
        self.drops = []

    def on_event_dropped(self, interp, event, reason):
        self.drops.append((getattr(event, "type", event), reason))

async def run(burst: int):
    spy = DropSpy()
    machine = create_machine(
        CFG, logic=MachineLogic(actions={"inc": inc, "slow": slow})
    )
    interp = Interpreter(machine)
    interp.use(spy)
    await interp.start()

    # Kick off the long-running action, then push external traffic at the
    # interpreter from OUTSIDE while that macrostep is still in flight.
    interp.send("SLOW")
    await asyncio.sleep(0.05)
    for _ in range(burst):
        await interp.send("T")
    await asyncio.sleep(1.2)

    applied = interp.context["n"]
    lost = burst - applied
    print(
        f"  burst={burst:<5} accepted={burst:<5} applied={applied:<5} "
        f"LOST={lost}  drops={len(spy.drops)} "
        f"reasons={sorted({r for _, r in spy.drops})} "
        f"last_transition_ok={interp.last_transition_ok}"
    )
    await interp.stop()
    return lost

async def main() -> int:
    print("OBSERVED:")
    control = await run(999)  # below the default maxIterations=1000
    lost_1500 = await run(1500)
    lost_3000 = await run(3000)

    print("\nEXPECTED: LOST=0 for every burst. External events accepted by")
    print("  `await send()` are never self-raised work and must not be")
    print("  charged to the chained-`raise` budget (maxIterations=1000).")

    bad = control != 0 or lost_1500 != 0 or lost_3000 != 0
    print("\nRESULT:", "DEFECT PRESENT" if bad else "OK")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED:
  burst=999   accepted=999   applied=999   LOST=0  drops=0 reasons=[] last_transition_ok=True
  burst=1500  accepted=1500  applied=1499  LOST=1  drops=1 reasons=['chain_budget'] last_transition_ok=True
  burst=3000  accepted=3000  applied=2999  LOST=1  drops=1 reasons=['chain_budget'] last_transition_ok=True

EXPECTED: LOST=0 for every burst. External events accepted by
  `await send()` are never self-raised work and must not be
  charged to the chained-`raise` budget (maxIterations=1000).

RESULT: DEFECT PRESENT
```

Exit status `1`. The control burst of 999 — one below the budget — is delivered
in full, which pins the cause on the budget rather than on queue capacity or
timing. Note also that `last_transition_ok` reads `True` after the drop,
because subsequent events in the burst succeed and reset it; a caller polling
that flag never sees the failure.

## Expected behaviour

`maxIterations` is the library's runaway-`raise` guard, and the library's own
documentation scopes it explicitly to *self-generated* work. `docs/_guide/json-config.md:110`:

> `maxIterations` … Default `1000`. Runaway guard for work the machine
> generates *for itself* … Counted per **chain** — it resets whenever a step
> generates nothing — so **a batch of any size of independent user events is
> always processed in full on both engines**; only a genuinely self-feeding
> loop trips it, and only the generated tail is dropped.

`CHANGELOG.md` restates the guarantee for the sync engine fix (#77):

> … while a self-feeding loop is still broken and only the generated tail is
> discarded — **never events the caller was told were accepted**.

And the run loop's own log message asserts it (`interpreter.py:1176-1178`):
"Breaking the chain; **externally queued events are unaffected**."

This also matches SCXML, where the external queue and the internal queue are
distinct structures with distinct semantics: `<raise>` targets the internal
queue, while events arriving from external sources are placed on the external
queue (W3C SCXML 1.0, §3.13 "Event Processing" and §4.8 `<raise>`). A guard on
internal-event chaining must not consume external-queue events.

Expected: `LOST=0` for every burst; if the chain budget is genuinely exceeded,
only events that the engine itself generated are dropped.

## Root cause analysis

`src/xstate_statemachine/interpreter.py:633-637` (introduced by **#90**,
"Async action-side `send()` is budgeted"):

```python
# 🏛️ #90: a `send()` issued FROM AN ACTION on this interpreter is
#    self-generated work, exactly like `raise`. ...
if self._processing and not self._refuse_if_not_running(event_obj):
    self._raise_depth += 1
    self._internal_queue.append(event_obj)
    return receipt if receipt is not None else _completed()
self._enqueue(event_obj)
```

The same shape appears at `interpreter.py:620-623` for the `BLOCK` overflow
policy (#38).

The intent — "the caller is one of my own actions" — is correct. The *test* is
not. `self._processing` is set for the whole of
`_process_event_and_transient_transitions` (`interpreter.py:1240`, cleared in
the `finally` at `:1270`). It is an interpreter-wide instance flag meaning "the
run loop is currently busy", with no notion of *who is calling*. Any external
coroutine that calls `await interp.send(...)` while a macrostep is in flight —
which, for any action that `await`s, is most of the wall-clock time — takes the
same branch: its event is appended to `_internal_queue` and `_raise_depth` is
incremented.

The drop then happens at `interpreter.py:1173-1198`: once
`self._raise_depth > limit`, the event **at the head** is discarded, the
plugin hook fires with `reason="chain_budget"`, and `_raise_depth` is reset to
`0`. The reset is why exactly *one* event is lost per trip rather than the
whole tail — a profile that is harder to notice, not less serious.

The sync engine does not have this bug: `sync_interpreter.py:619` computes an
`external_budget = len(self._event_queue)` so that events already accepted are
exempt by construction. The async engine has no equivalent.

A/B against the pre-#90 commit `3c527b0` confirms the regression: 50/50
external events delivered there, 49/50 here.

## Impact

**General users.** Any application whose actions `await` anything (a database
write, an HTTP call, `asyncio.sleep`) and that receives external events from a
concurrent producer will silently lose events under load, on the recommended
engine, at the default configuration. The loss is invisible to a
fire-and-forget caller. A `wait=True` caller does get a failure, but it is an
`InterpreterStoppedError("dropped: '<T>' exceeded the 1000-event self-raised
chain budget on '<id>'")` — which names neither the real cause nor
`RunawayChainError`, and is misleading, since the caller raised nothing.
`last_transition_ok` is typically `True` again by the time anyone reads it.

**Order-management scenario.** In the adopting project's order path, a `FILL`
handler awaits a persistence write while the market feed pushes `TICK` and
`FILL` events from a separate task. Crossing 1000 in-flight-window sends — a
few seconds of a busy session — drops one of them. A lost `FILL` means the
position book and the broker disagree with no error anywhere; a lost `CANCEL`
means an order stays live that the operator believes is cancelled. This is
silent, load-dependent divergence in the money path.

## Proposed fix

**Preferred: make "am I inside my own action?" a task-local fact.** Replace the
`self._processing` instance flag in the two send gates with a
`contextvars.ContextVar[bool]` (e.g. `_IN_ACTION`) set to `True` around
`_run_user_action` (and around guard/service invocation, wherever the engine
calls user code) and reset via the token on exit. `ContextVar` values propagate
into the coroutine's own awaits but *not* into a separate task, so:

- an action's own `await interp.send(...)` reads `True` → routed internally and
  budgeted, preserving #90;
- an external producer task reads `False` → `self._enqueue(event_obj)`, never
  budgeted.

This is the only formulation that is correct under `await` and across
concurrent tasks; an instance flag cannot express it. Note actions spawned into
their *own* tasks by the engine would need the token copied explicitly, or the
flag set at task creation.

**Weaker but still correct fallback.** Port the sync engine's approach: give
the async run loop an `external_budget` equal to the number of events that were
already in `_event_queue` when the drain opened (`sync_interpreter.py:619`), so
only genuinely internal events are eligible for the `chain_budget` drop at
`interpreter.py:1173`.

**Alternatives considered and rejected.** (a) Raising the default
`maxIterations` — only moves the threshold. (b) Dropping the *tail* rather
than the head — makes the loss more visible but does not stop it. (c) Only
budgeting sends whose calling task `is` the run-loop task — works for
`_run_user_action` executed inline, but breaks for any action the engine runs
in a child task; the `ContextVar` covers both.

**Compatibility.** No public API change. Behaviour change is strictly in the
direction of delivering events that are currently dropped. The #90 guarantee
(an action's self-`send()` loop is bounded) is preserved by construction.

## Acceptance criteria

- [ ] `repro/R4-06_external-events-charged-to-chain-budget.py` exits `0`:
      `LOST=0` at bursts of 999, 1500 and 3000.
- [ ] `tests/test_round4_findings.py::test_external_send_during_macrostep_is_not_budgeted`
      — an awaiting action holds a macrostep open while 3000 external
      `await send("T")` calls land; all 3000 are applied and
      `on_event_dropped` never fires.
- [ ] `tests/test_round4_findings.py::test_action_self_send_loop_still_budgeted`
      — pins #90: an action that `await interp.send()`s its own trigger still
      trips at `maxIterations` with `reason="chain_budget"`.
- [ ] `tests/test_round4_findings.py::test_external_send_not_budgeted_under_block_policy`
      — same for the `OverflowPolicy.BLOCK` gate at `interpreter.py:620`.
- [ ] Engine-parity test: async and sync engines both deliver a 3000-event
      external batch in full while an action is running.
- [ ] `docs/_guide/json-config.md` `maxIterations` row and the
      `interpreter.py:1176` log message remain true as written.

## Related

- Register row **R4-06** (High, CONFIRMED; regression introduced in this diff).
- Absorbs battle-report item `H-1` (concurrency track) and the adoption-audit
  gate item `27-r4-gate.md` §5.1 — the finding that the #90 claim
  "async action-side `send()` is budgeted" does not hold for its own repro
  shape. Both are faces of the same over-broad `_processing` gate.
- Introduced by **#90**; interacts with **#38** (the `BLOCK` gate at
  `interpreter.py:620` has the identical flaw) and **#77** (whose
  "never events the caller was told were accepted" guarantee this violates on
  the async engine).
- Related register row **R4-25**: the async trip handler drops whatever is at
  its head with no `is_system_event` check, so the same code path can discard a
  `done.invoke`. R4-06 is the proof that this path does fire in practice.
- Source ids: `probes/main-5e07ba8/r27_default_limit_loss.py`,
  `r25_ab_external_loss.py` (A/B vs `3c527b0`), `r12`–`r14`;
  `probes/main-5e07ba8-final/v5_ext_budget.py` (our adoption audit, #26).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-06_external-events-charged-to-chain-budget.py` in a fresh
  process: output matched the Observed section verbatim (burst=999 LOST=0;
  burst=1500 LOST=1, `reasons=['chain_budget']`; burst=3000 LOST=1,
  `reasons=['chain_budget']`), exit code **1**.
- Confirmed root cause against source: the `self._processing` gate at
  `interpreter.py:619-623` (BLOCK policy) and `:630-634` (default/other
  policies) routes any `send()` observed while a macrostep is in flight onto
  `_internal_queue` with `_raise_depth += 1`, regardless of caller identity.
  The drop at `interpreter.py:1173-1194` fires once `_raise_depth > limit`,
  discards the event at the queue head, and resets `_raise_depth = 0` —
  matching the narrative exactly (line numbers shifted by a few lines from
  the cited `633-637`/`1176-1178` due to intervening comments, but the code
  shape is identical).
- Confirmed the documentation claims: `docs/_guide/json-config.md:110`
  states the per-chain reset guarantee ("a batch of any size of independent
  user events is always processed in full on both engines") and the
  `interpreter.py:1176` log message ("externally queued events are
  unaffected") verbatim as quoted.
- Confirmed the SCXML claim (W3C SCXML 1.0 §3.13 "Event I/O Processors" /
  external event queue and §4.8 `<raise>` targeting the internal queue):
  the spec's internal/external queue split is standard SCXML architecture,
  consistent with the issue's characterization; no changes needed to that
  citation.
- Checked for duplicates: `gh issue list -R basiltt/xstate-statemachine
  --state all --search "chain budget"` returns #90 (async `send()` not
  budgeted — the regression's origin), #77/#88/#94 (sync-engine budget
  scoping) — all related but none is this defect (async engine charging
  *external* sends to the budget); no duplicate found.
- No project-name leak found: the adopting project is never named in this file.
