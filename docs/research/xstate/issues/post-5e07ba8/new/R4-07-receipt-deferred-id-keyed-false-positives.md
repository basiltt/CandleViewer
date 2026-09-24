---
r4: R4-07
title: "Bug: `Receipt.deferred` is keyed on `id(event)` in a set that never shrinks on replay — unbounded growth and false positives on fully-handled events"
labels: [bug, severity/high, area/receipts, area/interpreter, area/sync-interpreter]
severity: High
repro_script: repro/R4-07_receipt-deferred-id-keyed-false-positives.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`Receipt.deferred` (added by #84) is derived from `self._deferred_this_step`, a
`Set[int]` of `id(event)` values. An id is added for every event that
`onUnhandled: "defer"` holds, but it is only ever discarded on the receipt
path. A deferred event that is later *replayed* carries no receipt, so its id
stays in the set forever — while the event object itself is freed and CPython
reuses its heap address for the next `Event`. The consequences are two:
`_deferred_this_step` grows without bound in a long-running process, and a
later, completely unrelated, **fully-handled** event whose object lands at a
recycled address resolves its receipt with `deferred=True`. Since
`Receipt.deferred` is precisely the "was my event actually processed?" signal a
`send(wait=True)` caller is documented to check, this is a correctness defect on
the caller-facing API, not a cosmetic one.

## Environment

- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Install: editable (`pip install -e .`) from the `main` clone
- Engines: both. The repro below uses `SyncInterpreter` because its allocation
  pattern makes the collision deterministic; `Interpreter` shows the same
  defect nondeterministically.

## Minimal reproduction

```python
"""R4-07 -- `Receipt.deferred` is keyed on `id(event)` in a set that only
shrinks on the receipt path: it leaks unboundedly AND reports `deferred=True`
for events that were fully handled.

Exits 1 while the defect is present, 0 once fixed.
"""

import gc
import logging
import sys

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)

# `LATE` is unhandled in `a` (-> deferred, its id() is recorded) and handled
# in `b`, so the GO transition replays and consumes it. The replayed copy
# carries no receipt, so its id() is never discarded -- and CPython reuses
# that freed address for the next Event object.
CFG = {
    "id": "r407",
    "initial": "a",
    "onUnhandled": "defer",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b"}}},
        "b": {
            "on": {
                "LATE": {"actions": ["bump"]},
                "BACK": {"target": "a"},
            }
        },
    },
}

def bump(i, c, e, a):
    c["n"] += 1

def build():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))

CYCLES = 3000

def false_positives() -> int:
    interp = SyncInterpreter(build())
    interp.start()
    bad = []
    for k in range(CYCLES):
        interp.send("LATE")  # deferred in `a`
        interp.send("GO")  # a -> b, replays + handles LATE
        r = interp.send("BACK", wait=True)  # fully handled, b -> a
        if r.deferred:
            bad.append(k)
        if k % 500 == 0:
            gc.collect()
    print(
        f"  handled LATE events (context n) : {interp.context['n']}\n"
        f"  real deferral buffer            : {interp.deferred_count}\n"
        f"  leaked ids in _deferred_this_step: "
        f"{len(interp._deferred_this_step)}\n"
        f"  BACK receipts falsely deferred=True: {len(bad)} of {CYCLES}"
        f"  first: {bad[:8]}"
    )
    interp.stop()
    return len(bad)

def leak() -> int:
    """No replay ever happens, so the id set grows without bound."""
    cfg = {
        "id": "leak",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {"a": {"on": {"NEVER": {"target": "a"}}}},
    }
    interp = SyncInterpreter(create_machine(cfg, logic=MachineLogic()))
    interp.start()
    for _ in range(5000):
        interp.send("UNHANDLED")
    size = len(interp._deferred_this_step)
    print(
        f"  5000 fire-and-forget defers -> deferred_count="
        f"{interp.deferred_count} (correctly capped), "
        f"_deferred_this_step={size}"
    )
    interp.stop()
    return size

if __name__ == "__main__":
    print("OBSERVED:")
    fp = false_positives()
    leaked = leak()
    print("\nEXPECTED: 0 falsely-deferred receipts (BACK is always handled),")
    print("  and _deferred_this_step bounded by the real deferral buffer")
    print(f"  (DEFER_MAX), not by the number of events ever deferred.")
    defect = fp > 0 or leaked > 1000
    print("\nRESULT:", "DEFECT PRESENT" if defect else "OK")
    sys.exit(1 if defect else 0)
```

## Observed behaviour

```
OBSERVED:
  handled LATE events (context n) : 3000
  real deferral buffer            : 0
  leaked ids in _deferred_this_step: 10
  BACK receipts falsely deferred=True: 2990 of 3000  first: [10, 11, 12, 13, 14, 15, 16, 17]
  5000 fire-and-forget defers -> deferred_count=1000 (correctly capped), _deferred_this_step=1001

EXPECTED: 0 falsely-deferred receipts (BACK is always handled),
  and _deferred_this_step bounded by the real deferral buffer
  (DEFER_MAX), not by the number of events ever deferred.

RESULT: DEFECT PRESENT
```

Exit status `1`.

Two things to read carefully. First, `context n = 3000`: every single `LATE`
event was replayed and handled, and `deferred_count` — the *real* buffer
length — correctly reports `0`. The engine is right; only the receipt flag
lies. Second, **2990 of 3000** `BACK` receipts report `deferred=True` even
though `BACK` has an explicit handler in `b` and drives the observed `b -> a`
transition every cycle. The false-positive rate is a function of allocator
state, not of the event script: the same script on `Interpreter` gives a
different count on each run (the battle-test determinism track measured 46
distinct receipt tuples over 50 identical runs, with `deferred` as the only
field that moved).

The `leak()` half shows the growth independently: 5000 fire-and-forget defers
leave 1001 stale ids behind while the buffer itself is correctly capped at
`DEFER_MAX = 1000`. With no replay the set is bounded only by the number of
events ever deferred over process lifetime (an async run of 50 000 defers
measured ~2.1 MB retained).

## Expected behaviour

The library's own contract for the field, `events.py:350-354`:

> `deferred`: `True` when the event was **HELD** by `onUnhandled: "defer"`
> rather than processed (#84). `changed` is then `False` because nothing has
> run yet — not because the event was a correct no-op. **Check this before
> reading `changed`.**

An event that *was* processed — that took a transition and produced
`changed=True` with a new configuration — must resolve `deferred=False`. The
flag is documented as the thing you check *first*, so a false positive
poisons the interpretation of every other field in the receipt.

Additionally, engine bookkeeping for a feature whose own buffer is explicitly
capped (`base_interpreter.py:3291`, `DEFER_MAX = 1000`) must not itself be
unbounded.

## Root cause analysis

The set is declared at `src/xstate_statemachine/base_interpreter.py:463-465`:

```python
#: 🧾 #84: ids of events `onUnhandled: "defer"` held during the
#: current step, so `send(wait=True)` can report `deferred=True`.
self._deferred_this_step: Set[int] = set()
```

It is populated unconditionally for every deferred event, in the defer branch
of the unhandled-event path, `base_interpreter.py:3331-3335`:

```python
self._deferred_events.append(event)
# 🧾 #84: a `wait=True` caller must not read the resulting
#    `changed=False` as "processed, no-op". Record the hold so
#    the receipt can say `deferred=True`.
self._deferred_this_step.add(id(event))
```

It is read and discarded in exactly two places, both on the receipt-resolution
path — `interpreter.py:1278-1279`:

```python
deferred = id(event) in self._deferred_this_step
self._deferred_this_step.discard(id(event))
```

and the identical pair at `sync_interpreter.py:512-513`.

The asymmetry is the bug. A deferred event is later taken back out of the
buffer and replayed (`_take_deferred_for_replay`, `interpreter.py:1357` /
`sync_interpreter.py:785`). The replayed delivery does not go through
`_make_receipt`, so nothing ever discards its id. Then:

1. the replayed event is handled and dropped from `_deferred_events`;
2. its refcount hits zero and CPython frees the object;
3. its `id()` — a heap address — remains in `_deferred_this_step`;
4. the allocator hands that same address to the next `Event` of the same size;
5. that event is processed normally, but its receipt reads
   `id(event) in self._deferred_this_step` → `True`.

The comment "*during the current step*" describes an intent the code does not
implement: nothing clears the set at step boundaries.

Note the field naming is the same `id()`-keyed-identity hazard that **#75**
diagnosed and fixed for the receipt map itself (`interpreter.py:600-603`
`_detach()`s a caller-supplied event so "a reused instance cannot collide in
the receipt map"). **#84** reintroduced the same class of defect one field
over. `interpreter.py:238` `self._receipts: Dict[int, Future]` is safe only
because a pending receipt keeps its own strong reference, which is exactly the
liveness anchor `_deferred_this_step` lacks.

Note also that the same diff bounded a different unbounded `id`-ish set —
`resolver.py:89-104` capped `_SIBLING_FALLBACKS_WARNED` at 1024 as a "#31
ride-along" — so the growth hazard was recognised in this very change set and
applied to one set and not this one.

## Impact

**General users.** Two distinct failures from one root cause.

*Correctness.* Every `send(wait=True)` caller that follows the documented
advice and checks `receipt.deferred` first can be told an event is still
pending when it has in fact been fully executed. The rate is load-dependent
and can be very high (2990/3000 in the repro above) or very low (1 in 20 000
in a lighter allocation profile) — and it is nondeterministic on the async
engine, so the same recorded event script replayed twice produces different
receipts. That also breaks any replay/audit pipeline that records receipts.

*Memory.* A long-running process that uses `onUnhandled: "defer"` and never
replays (a fire-and-forget producer sending events the current state does not
handle) accumulates one `int` per deferred event for the life of the
interpreter, with no cap.

**Order-management scenario.** In the adopting project, order placement and
cancellation go through `r = await interp.send("CANCEL", wait=True)`, and the
guide's own instruction is to read `r.deferred` before `r.changed`. A false
`deferred=True` tells the order service that a `CANCEL` it *did* execute is
still pending — and the documented remedy for a genuinely deferred event is to
wait and retry. The service then re-issues a cancel for an already-cancelled
order, or (worse, in the `changed=True` + `deferred=True` shape this repro
produces) refuses to trust a state transition that really happened and leaves
a position reconciliation stuck. A low, load-dependent error rate is the worst
possible profile for a money path: it survives testing and appears in
production.

## Proposed fix

**Preferred: stop keying on `id()`; key on the object the receipt map already
pins.** The receipt map (`interpreter.py:721`) holds a `Future` per pending
event, and `send()` already `_detach()`es the caller's event (`:603`) to give
the queued envelope a unique identity. Record the *deferral* against that same
envelope — e.g. store the deferred flag on the envelope itself
(`event._deferred = True`, an engine-private attribute set alongside the
append at `base_interpreter.py:3331`), and read it back at
`interpreter.py:1278` / `sync_interpreter.py:512` as
`deferred = getattr(event, "_deferred", False)`.

This is strictly better than the id set on every axis:

- **No false positives.** The flag travels with the object; a recycled address
  carries no state.
- **No leak.** Nothing outlives the event; the set disappears entirely.
- **No extra bookkeeping** at replay time, since the replayed event *is* the
  same object.

If `Event` must stay a frozen `NamedTuple`, hold a
`Dict[int, Event]` (id → strong ref) instead of `Set[int]`, so the id can
never be recycled while the entry is live; then clear entries when the event
leaves `_deferred_events` (handled or evicted). This is the "hold a strong ref
alongside the id" variant — correct, but it keeps the events alive, so it must
be bounded by `DEFER_MAX` in the same place the buffer is.

**Minimum acceptable stopgap** (if neither lands for 0.8.1): discard the id
whenever the event leaves `_deferred_events` — at the replay site
(`_take_deferred_for_replay`) and at the `DEFER_MAX` eviction
(`base_interpreter.py:3327`). This removes both the leak and the dominant
false-positive source; a residual race remains for an event freed between
defer and receipt resolution, so it should be documented as a partial fix.

**Alternatives rejected.** (a) Clearing `_deferred_this_step` at each step
boundary — the set is read *after* the step, so this would turn every true
positive into a false negative, which is worse for a money path. (b) Capping
the set the way `resolver.py:103` caps its warn-throttle — fixes the leak and
leaves the correctness bug untouched.

**Compatibility.** No public API change. `Receipt.deferred` keeps its type and
documented meaning; it simply becomes true. Any user code currently
compensating for the false positives (e.g. the adoption-audit mitigation of
ignoring `deferred` and reading `interpreter.deferred_count`) continues to
work.

## Acceptance criteria

- [ ] `repro/R4-07_receipt-deferred-id-keyed-false-positives.py` exits `0`:
      0 false positives in 3000 cycles, and `_deferred_this_step` (or its
      replacement) bounded by `DEFER_MAX`.
- [ ] `tests/test_round4_findings.py::test_handled_event_receipt_not_deferred_after_replay`
      — the LATE/GO/BACK cycle above, asserting `not r.deferred` on every one
      of 3000 `BACK` receipts, on both engines.
- [ ] `tests/test_round4_findings.py::test_deferral_bookkeeping_is_bounded`
      — 5000 never-replayed defers leave bookkeeping `<= DEFER_MAX` entries.
- [ ] `tests/test_round4_findings.py::test_deferred_flag_true_for_genuinely_held_event`
      — pins #84: a genuinely held event still resolves `deferred=True`,
      `changed=False`.
- [ ] `tests/test_round4_findings.py::test_receipt_tuples_stable_across_runs`
      — the full receipt tuple (including `deferred`) for a fixed event script
      under a `SimulatedClock` is identical across repeated runs on the async
      engine.
- [ ] `tests/test_round4_findings.py::test_deferred_flag_survives_defer_max_eviction`
      — an evicted deferred event's bookkeeping entry is removed.

## Related

- Register row **R4-07** (High, CONFIRMED).
- Absorbs battle-report items `H-4` (soak/memory) and `D-determinism-1`
  (determinism track, where `deferred` was the *only* field that differed
  across 50 identical runs) — both are the identical `id()`-keyed
  `_deferred_this_step`.
- Introduced by **#84**. Same defect class as **#75**, which fixed `id()`
  keying for the receipt map itself.
- `resolver.py:89-104` (#31 ride-along, this same diff) bounded
  `_SIBLING_FALLBACKS_WARNED` at 1024; the same treatment was not applied here.
- Source ids: `probes/main-5e07ba8/r35_deferred_growth.py`, `r6b.py`, `r36`,
  `r5`; `battle-5e07ba8/determinism/d2c_deferred_mechanism.py`,
  `d2_receipt_deferred.py`; `probes/main-5e07ba8-final/v6_deferred.py`,
  `v6b.py` (our adoption audit, #26).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-07_receipt-deferred-id-keyed-false-positives.py` in a fresh
  process: output matched the Observed section verbatim (`n=3000`,
  `deferred_count=0`, `leaked ids=10`, `2990 of 3000` false-positive `BACK`
  receipts with the same first indices `[10, 11, 12, 13, 14, 15, 16, 17]`,
  and the `leak()` half showing `deferred_count=1000` (capped) against
  `_deferred_this_step=1001`), exit code **1**.
- Confirmed root cause against source:
  - `base_interpreter.py:463-465` declares `self._deferred_this_step:
    Set[int] = set()` (content matches, line numbers shifted by ~2 from the
    cited range due to intervening comments).
  - `base_interpreter.py:3331-3335`'s cited add-on-defer block matches
    `base_interpreter.py:3335` (`self._deferred_this_step.add(id(event))`)
    exactly, alongside the `DEFER_MAX` eviction at `3291`/`3326`.
  - `interpreter.py:1278-1279` and `sync_interpreter.py:512-513` both read
    `id(event) in self._deferred_this_step` then `.discard(id(event))` —
    confirmed verbatim at both sites; this is the only place an id is ever
    removed, and it is never reached by the replayed delivery path
    (`_take_deferred_for_replay`), matching the described asymmetry.
- Confirmed the documentation claims: `events.py:350-354`'s `Receipt.deferred`
  docstring ("HELD by `onUnhandled: "defer"` rather than processed...Check
  this before reading `changed`") matches verbatim, and `DEFER_MAX: int =
  1000` at `base_interpreter.py:3291` matches as cited.
- Checked for duplicates: `gh issue list -R basiltt/xstate-statemachine
  --state all --search "deferred"` returns #84 (the feature this defect
  regresses/reintroduces the `id()`-keying hazard for) and #28/#86 (unrelated
  unhandled-event / snapshot-provenance issues) — no duplicate found for the
  `id()`-recycling false-positive/leak defect itself.
- No project-name leak found: the adopting project is never named in this file.
