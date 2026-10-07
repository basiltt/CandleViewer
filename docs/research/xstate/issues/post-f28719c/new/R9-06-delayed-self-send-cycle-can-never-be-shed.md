---
r9: R9-06
severity: Medium
verified: true
build: f28719c
relates_to: [192, 179]
labels: [bug, severity/medium, area/interpreter, events]
repro: new/repro/R9-06_delayed_selfsend_unbounded.py
---

# A delayed self-`send` cycle is charged to no budget and tagged *external* by #192, so it can never be shed — `maxIterations` is inert on that path

**Severity (ours):** Medium
**Build:** `main` @ `f28719c` (merge of PR #202, unreleased 0.8.1; `__version__` still reports `0.8.0` — keyed on the commit)
**Environment:** CPython 3.13.7, Windows 11, fresh venv
**Relates to:** #192 — narrower than claimed: the provenance-based charge/shed split #192 introduces has a third, uncharged case it does not classify.

---

## Summary

#192 correctly distinguishes self-issued priority sends (charge them) from externally-issued ones (shield them). A **delayed** self-`send` falls through that classification: by the time it is delivered, its provenance reads as *external*, so it is shielded from the shed — but it is also never charged to the chain budget in the first place.

The result is a cycle that `maxIterations` cannot bound. The machine spins with `status="running"`, no `RunawayChainError`, and no drop hook.

This is not a regression from #192 — the path was uncharged before — but #192 **cements** it, because the event is now explicitly tagged as the category that must not be shed.

## Root cause

`src/xstate_statemachine/interpreter.py:2144-2158` (`_deliver`): a zero-delay self-`raise` during processing is charged (`self._raise_depth += 1`, line 2154) and queued internally. But a **delayed** self-send (`delay` truthy) instead schedules a timer (`_set_timeout`, line 2177) whose callback, on firing, calls `self._deliver_priority(target_event)` **with the default `engine_completion=False`** (line 2172-2173 in the `_fire()` closure) — there is no call-site override for "this delayed send targets myself and originated from my own action".

`_deliver_priority` (`interpreter.py:2429-2478`) sets `self_generated = engine_completion` (line 2465) and only increments `_raise_depth` when `engine_completion` is `True` (line 2477). Since the delayed self-send's callback passes the default `False`, the item is queued as `(event, self_generated=False)` — never charged.

The shed test in the run loop (`interpreter.py:1676`): `over = self._raise_depth > limit and self_generated` — requires `self_generated` to be `True` to shed at all. A delayed self-send item carries `self_generated=False`, so `over` can never be `True` for it, however high `_raise_depth` climbs from other charged work; and since it was never charged either, `_raise_depth` does not climb from this cycle at all. `maxIterations` cannot bound it by either input to that test.

## Impact

**General:** `maxIterations` is the library's advertised backstop against a runaway chart. Every other route to a runaway now respects it — that is #179/#192/#201, and the plateau lands at exactly `maxIterations + 2` on both lanes for those. A delayed self-send is the one remaining hole, which makes it more surprising than it would have been a release ago, since the advertised invariant now holds everywhere else.

**Order-management:** a state entered via a delayed self-arm (e.g. a poll/retry loop implemented as `entry: raise({delay: N})` back to itself or a sibling) that never terminates burns a core indefinitely and never surfaces as an error a caller's `on_error`/`RunawayChainError` handler would catch — it is invisible to the exact mechanism meant to catch unbounded self-feeding.

## Minimal reproduction

`R9-06_delayed_selfsend_unbounded.py` (attached; stdlib + `xstate_statemachine` only, inlined, run from a neutral cwd). Two-state cycle (`a <-GO-> b`) where each state's `entry` fires a 1 ms delayed self-`raise` of `GO`; `maxIterations: 20`. `async def` service semantics not applicable — this path is action/event-level, not a service invocation, so there is no `def`/`async def` axis to parametrise; `SyncInterpreter` has no delayed-send timer mechanism in the same shape (it processes eventless/`always` chains synchronously and does not schedule `_set_timeout` callbacks against a running loop the same way), so this is `Interpreter`-only by construction of the feature under test.

## Observed (fresh run)

```
laps(exits)=659
after 10s: raise_depth=0 chain_tripped=False states=['m.b'] maxIterations=20
VERDICT: UNBOUNDED (bug)
```
Exit code: 1.

## Expected

Per the library's own contract (docstring at `interpreter.py:2443-2460`, "Chain-budget accounting is decided by PROVENANCE, never by timing (#180)... an engine completion the machine produced... is self-generated work and IS charged"), a self-issued delayed send is self-generated work by the same test the docstring states for zero-delay self-raises and engine completions — it should be charged and, once the chain trips, shed. XState v5's `raise({ delay })` action targets the machine's own event queue and is bounded by the same guard-against-infinite-loop machinery XState applies to any other self-transition storm; there is no comparable "some self-feeding is exempt from the loop guard by construction" carve-out in the reference implementation.

## Suggested direction

Charge a delayed self-`send` at **arming** time (in `_deliver`, where the issuing action's own provenance as a self-raise is already known, at the point the timer is scheduled) rather than at delivery time (in the `_fire()` closure, where by the time the timer fires the call site only has the target event, not who armed it or why). Alternatively, carry the originating provenance through the `_scheduled_sends` registry so `_fire()` can pass `engine_completion=True` when the delay was armed by our own self-raise.

## Proposed fix

In `_deliver` (`interpreter.py:2144-2178`), when `actor is self` and a delay is present, record `engine_completion=True` (or an equivalent "self-armed" flag) alongside the scheduled-send registry entry, and have the `_fire()` closure's call to `_deliver_priority` (currently unconditionally `engine_completion=False` at line 2173) read that flag instead of always defaulting to `False`.

## Acceptance criteria

- `test_delayed_selfsend_is_charged_to_chain_budget` — the attached two-state 1 ms-delay cycle with `maxIterations: N` (small, e.g. 20) trips `RunawayChainError` (or the equivalent chain-tripped/dropped-event observable) within a bounded wall-clock window, on `Interpreter` (this path does not exist on `SyncInterpreter`; note that explicitly in the test skip reason rather than parametrising it away silently).
- `test_delayed_selfsend_charge_matches_immediate_selfraise` — a delayed self-`raise` and a zero-delay self-`raise` of the same event, from the same state shape, trip the chain guard at the same `_raise_depth`/lap count (parity between the two provenance paths that are currently treated inconsistently).
- `test_external_delayed_send_still_unshielded_from_shedding` (regression guard) — a delayed send from *outside* (a caller's own `send(..., delay=...)`-style external timer, not a self-`raise`) is still never charged/shed, preserving #192's actual external-traffic guarantee; the fix must not regress that.

## Our containment

We forbid `priority=True` everywhere and ban delayed self-sends in machine definitions, so this is contained for us. Filed because the `maxIterations` contract is load-bearing for anyone relying on it as a safety bound.

## Verification

- Date: 2026-09-22
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `f28719c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- cwd used: `<home>` (neutral, outside both repos)
- Exit codes: `R9-06_delayed_selfsend_unbounded.py` → **1** (unbounded; `laps(exits)=659` in 10 s, `raise_depth=0`, `chain_tripped=False`, `status=running`)
