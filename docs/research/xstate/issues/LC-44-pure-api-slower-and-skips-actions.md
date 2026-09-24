---
lc: LC-44
title: "Perf: the pure API (`transition`/`get_next_snapshot`) is 3–4× slower per event than a real `SyncInterpreter`"
labels: [performance, severity/medium, area/interpreter]
severity: Medium
blocks_adoption: false
repro_script: repro/LC-44_pure-api-slower-and-skips-actions.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`helpers.transition()` / `get_next_snapshot()` — the "pure" reducer advertised for unit testing and "preview the next step" UI — is measurably **slower per event than driving a real `SyncInterpreter`**: 75.8 µs/event vs 19.5 µs/event on the same machine and events (3.9×). Each call constructs a fresh `_Probe` *subclass* (the class statement is inside `_build_probe`, so a new type object is created per call), constructs a full `SyncInterpreter` from it, deep-copies the context in and out, and re-derives the configuration node-by-node via `get_state_by_id`. A reducer that builds an entire interpreter per call is not a reducer.

**Scope note (revised after verification).** An earlier draft of this report also claimed that the pure API "silently" skips user-supplied action callables and that this was a bug. That framing was wrong on both counts and has been withdrawn:

- **It matches XState.** XState v5 documents actions as "fire-and-forget effects", with `assign` explicitly called out as the special action that changes context. `transition(machine, state, event)` returns `[nextSnapshot, actions]` precisely so the *caller* executes the effects. Applying `assign` and returning everything else is the correct parity contract, not a defect.
- **It is documented.** `docs/_guide/testing-and-pure-api.md:69-70` states: "the pure API resolves guards and computes actions, but never **executes** them. Actions are returned for inspection." So it is not silent either.

The repro script still prints the context divergence, because it is genuinely surprising to a first-time reader and worth knowing about, but it is reported as **context** rather than as a failure, and it no longer affects the exit code. The only defect asserted here is the performance one.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (64-bit, CPython)
- OS: Windows 11 (x64)

## Minimal reproduction

```python
"""LC-44 repro: the "pure" API (`transition` / `get_next_snapshot`) is slower
per event than a real interpreter.

THE DEFECT ASSERTED (exit code depends only on this):

  Every call to `transition()` constructs a brand-new `_Probe` *subclass* (the
  `class` statement lives inside `helpers._build_probe`, so a fresh type object
  is created per call, defeating CPython's type/method caches), builds a full
  `SyncInterpreter` from it, deep-copies the context in (`helpers.py:275`) and
  out (`helpers.py:296`), and re-derives the configuration by `get_state_by_id`
  per node (`helpers.py:346-350`). The result is that the API positioned as the
  cheap, no-overhead path is ~4x MORE expensive per event than just driving a
  `SyncInterpreter`.

CONTEXT, NOT A DEFECT (printed for the reader; does NOT affect exit code):

  The pure API applies the builtin `assign` but does not call user-supplied
  action callables, so `PureSnapshot.context` diverges from the interpreter's.
  This is CORRECT and matches XState v5, where actions are "fire-and-forget
  effects" returned to the caller to execute and `assign` is the special
  context-changing action. It is also documented: see
  `docs/_guide/testing-and-pure-api.md` -- "the pure API resolves guards and
  computes actions, but never **executes** them." An earlier draft of this
  repro treated it as a bug; that claim has been withdrawn.

Exit code 1 if the pure API is slower per event than `SyncInterpreter.send`.
"""

from __future__ import annotations

import logging
import sys
import time

from xstate_statemachine import (
    MachineLogic,
    SyncInterpreter,
    create_machine,
    get_initial_snapshot,
    get_next_snapshot,
)

logging.disable(logging.CRITICAL)

CONFIG = {
    "id": "order",
    "initial": "idle",
    "context": {"qty": 0.0, "fills": 0},
    "states": {
        "idle": {"on": {"SUBMIT": {"target": "open", "actions": ["book"]}}},
        "open": {"on": {"FILL": {"target": "open", "actions": ["book"]}}},
    },
}


def book(interpreter, context, event, action_def) -> None:
    """A perfectly ordinary imperative action: records a fill."""
    context["qty"] += float(event.payload.get("qty", 0.0))
    context["fills"] += 1


def machine():
    return create_machine(CONFIG, logic=MachineLogic(actions={"book": book}))


EVENTS = [{"type": "SUBMIT", "qty": 1.0}] + [
    {"type": "FILL", "qty": 1.0} for _ in range(999)
]

# 1️⃣ Context: pure API vs the real engine, same machine, same events.
#    This divergence is EXPECTED and matches XState -- printed for the reader,
#    not asserted.
m_pure = machine()
snap = get_initial_snapshot(m_pure)
for e in EVENTS:
    snap = get_next_snapshot(m_pure, snap, e)

interp = SyncInterpreter(machine()).start()
for e in EVENTS:
    interp.send(e)

print(f"CONTEXT  pure    state={sorted(snap.state_ids)} context={snap.context}")
print(
    f"CONTEXT  sync    state={interp.current_state_ids} "
    f"context={interp.context}"
)
print(
    "CONTEXT  the context difference above is CORRECT XState-parity "
    "behaviour (actions are effects returned to the caller); not asserted"
)

# 2️⃣ Performance: per-event cost of each path (warm).
def time_pure(n: int) -> float:
    m = machine()
    s = get_initial_snapshot(m)
    evs = EVENTS[:n]
    t0 = time.perf_counter()
    for e in evs:
        s = get_next_snapshot(m, s, e)
    return (time.perf_counter() - t0) / n * 1e6


def time_sync(n: int) -> float:
    it = SyncInterpreter(machine()).start()
    evs = EVENTS[:n]
    t0 = time.perf_counter()
    for e in evs:
        it.send(e)
    return (time.perf_counter() - t0) / n * 1e6


time_pure(200), time_sync(200)  # warm-up
us_pure, us_sync = time_pure(1000), time_sync(1000)
print(f"OBSERVED pure    {us_pure:.1f} us/event")
print(f"OBSERVED sync    {us_sync:.1f} us/event")
print(f"OBSERVED ratio   pure is {us_pure / us_sync:.2f}x the interpreter")
print("EXPECTED the pure reducer to be no slower than the interpreter")

ok_perf = us_pure <= us_sync
sys.exit(0 if ok_perf else 1)
```

## Observed behaviour

```
CONTEXT  pure    state=['order.open'] context={'qty': 0.0, 'fills': 0}
CONTEXT  sync    state={'order.open'} context={'qty': 1000.0, 'fills': 1000}
CONTEXT  the context difference above is CORRECT XState-parity behaviour (actions are effects returned to the caller); not asserted
OBSERVED pure    75.8 us/event
OBSERVED sync    19.5 us/event
OBSERVED ratio   pure is 3.90x the interpreter
EXPECTED the pure reducer to be no slower than the interpreter
EXIT=1
```

The ratio is machine- and load-dependent — runs during verification produced 3.90× and 5.02× on the same hardware — but the sign is stable across every run: the pure path is several times more expensive per event. This is consistent with the independent `bench_a_throughput.py` measurement (pure API 77.2 µs vs interpreter 33 µs, 2.4×).

The context lines are printed for orientation only. They show the documented XState-parity contract working as intended and do not contribute to the exit code.

## Expected behaviour

The pure reducer should not be several times *more* expensive per event than the effectful interpreter it is a cheaper alternative to.

The docs position it exactly that way — `docs/_guide/testing-and-pure-api.md`: "Sometimes you want to compute the next state *without running anything* — no timers start, no services fire, nothing mutates. That is what the pure API is for: unit tests, planning, and **'preview the next step' UI**." A "preview the next step" UI path and a per-test path both imply cheapness; a user has no reason to suspect that calling `get_next_snapshot()` costs 4× a real `send()`.

XState's equivalent is a genuine pure function over the machine definition: `transition(machine, state, event)` computes the next snapshot and returns the actions, with no actor instantiated (https://stately.ai/docs/transitions, "Transitioning state", since v5.19.0). The structural expectation is the same here — the pure path should reuse a cached probe rather than constructing an interpreter per call.

**On the action contract (explicitly *not* a defect).** Verification confirmed the library matches XState here. XState v5 defines actions as "fire-and-forget effects" and marks `assign` as the special action that changes context (https://stately.ai/docs/actions); `transition()` returns `[snapshot, actions]` so the caller runs the effects. Applying `assign` and returning the rest is the correct parity behaviour, and the library documents it at `docs/_guide/testing-and-pure-api.md:69-70`. No change is requested on this axis, and the related LC-54 documentation request is withdrawn.

## Root cause analysis

`helpers.py:226-276` (`_build_probe`) plus `helpers.py:343-356` (`transition`), per call:

- `_Probe` is defined **inside** `_build_probe` (the `class _Probe(SyncInterpreter)` statement is at `:249`), so a new class object is created on every single call. Verified directly: two consecutive `_build_probe()` calls return probes whose `type()` objects are not identical. This defeats CPython's type and method caches.
- `_Probe(machine, input=input)` (`:273`) constructs a full `SyncInterpreter`: plugin list, event queue, task manager, and a fresh initial-configuration derivation.
- `probe.context = copy.deepcopy(snapshot.context)` (`:275`) on the way in and `context=copy.deepcopy(probe.context)` in `_capture` (`:296`) on the way out — two deep copies of the whole context per event.
- `transition()` clears `probe._active_state_nodes` and re-resolves every id with `machine.get_state_by_id(state_id)` (`:346-350`), an id-map lookup per active node per event.

The interpreter path does none of this per event; it keeps one live configuration set and mutates context in place.

## Impact

**General users.** The pure API is documented for unit tests, planning and "preview the next step" UI — all uses where per-call cost is felt. A large test suite pays ~4× the necessary time, and anyone who reaches for the pure path as a fast way to evaluate many hypothetical events (plan search, what-if previews over a list of candidate events) gets a 3–5× pessimisation relative to the obvious alternative of just driving an interpreter. The cost is invisible without profiling, because the API's shape and documentation both suggest it is the cheap path.

**CandleViewer (trading OMS).** CandleViewer is the downstream application this research was conducted for; it runs a family of order-lifecycle state machines (submit → open → partially-filled → closed) under this library. Our test strategy unit-tests those machine families against the pure API, since it needs no event loop — on the order of a few thousand `get_next_snapshot()` calls across the suite, where the 4× shows up directly as suite wall-clock. Separately, we had scoped the pure API for a pre-trade "what would this order do" preview evaluated per UI interaction; at 76–145 µs/event with an interpreter costing 20–29 µs, that plan is inverted, and we would be better served constructing a throwaway `SyncInterpreter` — which is a strange conclusion to be forced into by a reducer API.

## Proposed fix

Make the pure path actually cheap. None of these change public API or observable semantics:

- **Hoist the `_Probe` class to module scope.** Pass the `recorded` list via an instance attribute (`self._recorded`) rather than closing over it, so the class object is created once at import instead of per call.
- **Cache one probe interpreter per `MachineNode`** — a `WeakKeyDictionary[MachineNode, _Probe]` — and reset it per call (clear the queue, reset `status`, reassign context) instead of constructing a new `SyncInterpreter`.
- **Drop one of the two deep copies.** The inbound copy at `:275` is redundant when the caller passes a `PureSnapshot` the library itself produced, since `_capture` already deep-copied on the way out and snapshots are documented as immutable. Keep the outbound copy, which is what actually guarantees the immutability the guide promises.
- **Cache the configuration resolution.** Store the resolved `Set[StateNode]` alongside the id set on `PureSnapshot` so the `get_state_by_id` loop at `:346-350` disappears for the common chained-call pattern (`snap = get_next_snapshot(m, snap, e)` in a loop).

## Acceptance criteria

- [ ] `tests/test_helpers_pure.py::test_pure_probe_class_is_module_level` — `type(probe)` is the same object across two `_build_probe()` calls (guards the hoist).
- [ ] `tests/test_helpers_pure.py::test_pure_api_semantics_unchanged` — existing pure-API behaviour is preserved by the optimisation: `assign` still applies, user action callables still do not run, and the returned action list is unchanged.
- [ ] `tests/test_helpers_pure.py::test_pure_transition_never_schedules_timers_or_invokes` — an `after` and an `invoke` in the target state start nothing (guards the probe-reuse change, which must not resurrect `_schedule_state_tasks`).
- [ ] `tests/test_helpers_pure.py::test_snapshots_remain_independent` — branching twice from one snapshot leaves the original untouched (guards dropping the inbound deep copy).
- [ ] `tests/test_perf_pure_api.py::test_pure_api_not_slower_than_sync_interpreter` — per-event cost of `get_next_snapshot` is ≤ that of `SyncInterpreter.send` on the same machine (generous margin, marked `slow`).
- [ ] `repro/LC-44_pure-api-slower-and-skips-actions.py` exits 0.

## Related

- **LC-45** — hot-path cost in the shared engine; the pure API inherits all of it per event *plus* its own per-call interpreter construction. Fixing LC-45 lowers both bars but does not close the ratio.
- **LC-23** — original bench observation.
- ~~**LC-54**~~ — withdrawn: the limitation it asked to document is already documented at `docs/_guide/testing-and-pure-api.md:69-70`.

## Verification

- Date: 2026-09-15
- Python: 3.13.7 (CPython, 64-bit, Windows 11 x64)
- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, editable install
- Repro exit code: **1** (fails today), reproduced in a fresh process
- Corrections applied during verification:
  - **Withdrew the "silently skips imperative actions" bug claim.** Checked against https://stately.ai/docs/actions and https://stately.ai/docs/transitions: XState v5 defines actions as "fire-and-forget effects" with `assign` as the special context-changing action, and `transition()` returns actions for the caller to execute. The library's behaviour is correct parity, not a defect.
  - **Withdrew "silently".** The behaviour is documented at `docs/_guide/testing-and-pure-api.md:69-70`. The issue title, labels (`bug` → `performance`), summary, expected-behaviour section, impact and acceptance criteria were all rewritten accordingly, and the repro no longer asserts on context.
  - Root-cause line citations re-checked against the source and corrected: `_build_probe` spans `:226-276` (not `:226-277`), the skipped-action loop is at `:261-267`, the inbound deep copy is at `:275`, and the outbound deep copy is at `:296` (the draft said `:307`).
  - Per-call class creation verified directly rather than asserted from a static read.
  - Observed block refreshed with the measured run and a note that the ratio varies (3.90×–5.02× across runs) while the sign does not.
  - Removed the `candleviewer` label and expanded the CandleViewer impact paragraph to be self-explanatory to a maintainer with no access to our docs; dropped the internal-only "C5.1" and "B1–B20" references.
  - Duplicate check: `gh issue list --repo basiltt/xstate-statemachine --state all` returns exactly one issue (#17, camelCase/snake_case logic auto-discovery, closed). Not a duplicate.
