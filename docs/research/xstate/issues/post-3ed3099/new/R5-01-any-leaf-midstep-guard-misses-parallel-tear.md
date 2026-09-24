---
r5: R5-01
title: "Bug: `SnapshotMidStepError` is gated on an any-leaf test, so a parallel machine mid-transition in one region snapshots with that whole region missing and restores half-dead"
labels: [bug, severity/blocker, area/persistence]
severity: Blocker
repro_script: repro/R5-01_parallel-tear-passes-midstep-guard.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

#102 closed its reproducer; the invariant behind it is still unenforced.
`get_persisted_snapshot()` refuses a mid-macrostep snapshot only when
`_step_in_flight() and not _active_leaf_present()`, and
`_active_leaf_present()` (`base_interpreter.py:1112`) is
`any(atomic node is active)`. "At least one atomic state anywhere" is not
SCXML configuration legality — legality is *exactly one active leaf per
region*. In a `parallel` machine, a macrostep open in one region leaves the
other region's leaf active, so the guard passes and the snapshot records a
configuration with an entire region absent. That blob restores without any
error into a `running` machine that silently ignores every event belonging
to the missing region, forever. The same conjunct leaves a second hole: the
macrostep is still in flight *after* the entry set is applied while entry
actions run, so a leaf is present there too and a snapshot taken from an
entry action serialises the new state id with the pre-action context.

## Environment

- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (`main`, unreleased
  0.8.1; `__version__` still reports `0.8.0`, so this build is identified by
  commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source modified.

## Minimal reproduction

```python
"""R5-01 repro: `SnapshotMidStepError` (#102) uses an *any-leaf* test, so a
parallel machine whose one region is mid-transition still snapshots — with the
whole region missing — and restores as a half-dead machine reporting healthy.

Stdlib + xstate_statemachine only. Exits 1 while present, 0 once fixed.
"""

import asyncio
import json
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError

CFG = {
    "id": "ord",
    "type": "parallel",
    "context": {},
    "states": {
        "exchange": {
            "initial": "working",
            "states": {
                "working": {"on": {"FILL": {"target": "filled", "actions": ["slow"]}}},
                "filled": {},
            },
        },
        "risk": {"initial": "checking", "states": {"checking": {}}},
    },
}


async def slow(interpreter, ctx, event, action_def):
    # A realistic awaiting transition action (DB write / exchange call).
    await asyncio.sleep(0.4)


def logic():
    return MachineLogic(actions={"slow": slow})


async def main() -> int:
    live = await Interpreter(create_machine(CFG, logic=logic())).start()
    task = live.send("FILL")
    await asyncio.sleep(0.15)  # inside the exchange region's macrostep

    refused = None
    snap = None
    try:
        snap = live.get_persisted_snapshot()
    except SnapshotMidStepError as exc:
        refused = type(exc).__name__

    await task
    await asyncio.sleep(0.05)
    await live.stop()

    print("OBSERVED:")
    print("  snapshot refused          :", refused)
    if snap is not None:
        blob = json.dumps(snap)
        doc = json.loads(blob)
        print("  snapshot state_ids        :", doc.get("state_ids"))
        print("  snapshot configuration    :", doc.get("configuration"))
        restored = await Interpreter.from_snapshot(
            blob, create_machine(CFG, logic=logic())
        ).start()
        r_fill = await restored.send("FILL", wait=True)
        print("  restored current_state_ids:", sorted(restored.current_state_ids))
        print("  restored status           :", restored.status)
        print("  restored FILL receipt     :", r_fill)
        await restored.stop()

    print("EXPECTED:")
    print("  SnapshotMidStepError, or a configuration with exactly one active")
    print("  leaf per parallel region (both 'ord.exchange.*' and 'ord.risk.*')")

    if refused is None:
        cfg = set(json.loads(json.dumps(snap)).get("configuration") or [])
        torn = not any(c.startswith("ord.exchange.") for c in cfg)
        if torn:
            print("RESULT: FAIL - region 'ord.exchange' absent from an accepted snapshot")
            return 1
    print("RESULT: PASS")
    return 0


sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED:
  snapshot refused          : None
  snapshot state_ids        : ['ord.risk.checking']
  snapshot configuration    : ['ord', 'ord.exchange', 'ord.risk', 'ord.risk.checking']
  restored current_state_ids: ['ord.risk.checking']
  restored status           : running
  restored FILL receipt     : Receipt(state_ids=frozenset({'ord.risk.checking'}), changed=False, error=None, deferred=False)
EXPECTED:
  SnapshotMidStepError, or a configuration with exactly one active
  leaf per parallel region (both 'ord.exchange.*' and 'ord.risk.*')
RESULT: FAIL - region 'ord.exchange' absent from an accepted snapshot
```

Exit status `1`.

Note that `ord.exchange` *is* present in `configuration` — the region node
itself never left — but it has no child, so the region is dead on restore.
`state_ids` shows only the other region's leaf. The `FILL` receipt on the
restored machine is
`Receipt(..., changed=False, error=None, deferred=False)` — byte-identical
to the receipt a legitimately-unhandled event produces.

Two corroborating scripts re-run verbatim on the same commit:

- `battle-3ed3099/persistence/d3b_partial_parallel.py` — snapshot during the
  `exchange` region's `onDone`:
  `state_ids = ['order.submitted.risk.checking']`,
  `configuration = ['order', 'order.submitted', 'order.submitted.exchange', 'order.submitted.risk', 'order.submitted.risk.checking']`;
  restored gives `status=running`, `error=None`, `dormant=False` and
  `filled = 0` against `3` for the uninterrupted run — *"the order can never
  fill or complete."*
- `battle-3ed3099/semantics/repro/d5s1_entry_action_torn_snapshot.py` — the
  entry-action half, on **both** engines:
  `snapshot mid-entry: ACCEPTED state_ids=['oms.filled'] ctx={'filled_qty': 0}`
  while the live machine settles to `filled_qty=100`;
  `last_transition_ok=True`, `last_error=None`. The restored machine claims
  the order is filled with zero filled quantity.

## Expected behaviour

W3C SCXML §3.13 (*Selecting and Executing Transitions*) defines the
configuration as well-defined only at a macrostep boundary, and SCXML's
configuration legality (§3.2.1, §3.13) requires that when a `<parallel>`
state is active, **every one of its children is active**, and every active
compound state has exactly one active child. A configuration in which
`ord.exchange` is active with no active child is not a legal configuration at
any observable point, so it must never be serialised.

XState v5 makes the same guarantee at the API level:
`actor.getPersistedSnapshot()` returns the actor's *settled* state, and the
persistence guide (<https://stately.ai/docs/persistence>) describes the
persisted snapshot as something you restore an actor from so that it
"continues from where it left off". A restored parallel actor that continues
in only one of its regions violates that contract.

The library's own contract, quoted from `get_persisted_snapshot()`'s
docstring at `base_interpreter.py:1121-1127`:

> Raises:
>     SnapshotMidStepError: if a macrostep is in flight (#102). Between a
>     transition's exit set and entry set the configuration has no leaf;
>     persisting that would restore as a permanently inert machine
>     reporting `running`.

and `_active_leaf_present()`'s own docstring at `:1111`:

> ``True`` when the configuration contains at least one atomic state --
> i.e. it is a legal SCXML configuration (#102/#108).

The "i.e." is the defect: *at least one atomic state* is not the definition
of a legal SCXML configuration. The docstring's stated intent — never persist
something that restores into a machine that cannot act — is exactly what is
violated here; the failure is simply partial (one region) rather than total.

Concretely expected:

1. `get_persisted_snapshot()` raises `SnapshotMidStepError` for any
   configuration that is not leaf-legal per region, not merely for the
   globally leafless one.
2. A snapshot taken from an entry action either raises, or reflects a fully
   committed state/context pair — never a post-transition state id with
   pre-action context.

## Root cause analysis

`base_interpreter.py:1111-1118`:

```python
def _active_leaf_present(self) -> bool:
    """``True`` when the configuration contains at least one atomic
    state -- i.e. it is a legal SCXML configuration (#102/#108)."""
    return any(
        not node.states or node.is_final
        for node in self._active_state_nodes
        if node is not self.machine
    )
```

consumed at `base_interpreter.py:1156`:

```python
if self._step_in_flight() and not self._active_leaf_present():
    if _seen is None:
        raise SnapshotMidStepError(self.id)
    self._await_settled_for_snapshot()
```

and again in `_await_settled_for_snapshot()` at `:1097-1103`, which spins on
the same conjunct.

Two independent holes follow from the single `any(...)`:

1. **Parallel tear.** `_exit_states` drains only the leaves of the region
   being transitioned; the sibling region's leaf stays in
   `_active_state_nodes`. `any(...)` therefore returns `True` throughout the
   window, the guard is never reached, and the snapshot at `:1168+` reads
   `_active_state_nodes` directly (`"configuration": sorted(node.id for node
   in self._active_state_nodes)`), emitting the region node without a child.
   `current_state_ids` filters to `is_atomic or is_final`, which is why
   `state_ids` silently omits the region entirely rather than signalling.

2. **Entry-action window.** `_enter_states` adds the target leaf to
   `_active_state_nodes` *before* running the entry actions, and
   `_step_in_flight()` stays `True` for the remainder of the macrostep. A leaf
   is present, so the guard passes, and any snapshot taken from an entry
   action pairs the committed target state id with a context that the entry
   actions have not yet mutated (`d5s1`: `oms.filled` + `filled_qty: 0`).

The write-side predicate is the only place legality is tested anywhere in the
library; see R5-02 for the read side, which never tests it at all.

Introduced by the #102 fix itself — this is not a regression of behaviour but
a regression of *intent*: the predicate was written to satisfy the single flat
machine in its reproducer. `tests/test_wave2_review_findings` is the test that
would have caught it had its configuration been parallel rather than flat.

## Impact

**General users.** Any application that snapshots a `parallel` machine from a
timer, a signal handler, a sidecar checkpoint task, or from an entry/exit
action (the hook the library itself exposes for it) can persist a blob with a
whole region missing. It restores clean — `status="running"`, `error=None`,
`has_dormant_invocations=False` — and is then permanently deaf to every event
handled by the lost region while remaining fully responsive to the others. No
error, no log line, no public predicate distinguishes it from a healthy
machine. Because `#102` shipped and is documented as closing this class, users
are now *more* likely to trust a snapshot than before. Detection today
requires the application to independently reconstruct SCXML legality over the
restored configuration.

**Order-management scenario (our adoption audit, #26).** Order lifecycles are
modelled as `parallel` machines: an `exchange` region (`working → filled`)
running concurrently with a `risk` region (`checking → passed/blocked`).
Transition actions on the exchange region `await` — they write to the DB and
call the exchange client — and that await *is* the window. A checkpoint tick
or a crash during `working → filled` persists an order whose `exchange` region
is gone. On restart the order loads, reports `running`, and the risk region
keeps working normally, so every health probe and every risk assertion passes
— while the exchange `FILL` and the operator `CANCEL` both return
`Receipt(changed=False, error=None, deferred=False)`. The order is filled at
the venue and never recorded as filled, and the cancel is never placed, with
the system asserting the whole time that the order is healthy and
risk-checked. The entry-action half is worse in kind: the order persists as
`filled` with `filled_qty = 0`, so reconciliation sees a completed order with
no quantity. This finding alone holds our order path at DEFER.

## Proposed fix

**The single configuration-legality invariant.** Define it once and enforce it
on both sides (R5-02 is the read side of the same invariant; fixing them
together is one change, not two patches):

```python
def _configuration_is_legal(nodes) -> bool:
    # every active parallel state has ALL its children active
    # every active compound state has EXACTLY ONE child active
    # every active non-root node has its parent active
    # at least one active atomic/final leaf exists
```

*Write side* — replace `_active_leaf_present()` at `base_interpreter.py:1112`
with this predicate and keep the existing call site at `:1156` unchanged
(`if self._step_in_flight() and not self._configuration_is_legal(...)`). The
spin in `_await_settled_for_snapshot()` at `:1097` should use the same
predicate, so a child actor is waited on until it is *legal*, not until it has
some leaf.

*Entry-action window* — the leaf-per-region predicate does not by itself close
the second hole, because during entry the configuration is legal and only the
context is stale. Two options, in preference order:

1. **Commit the macrostep atomically for observers**: stage the configuration
   *and* the context in `_execute_transition` and publish both with one
   assignment when entry actions complete. Observers then only ever see a
   committed (state, context) pair, and this also closes the crash route.
2. **Treat `_step_in_flight()` as sufficient for the root call**: refuse any
   root snapshot while a macrostep is open, regardless of leaf presence.
   Smaller, but it is a behaviour change for callers who snapshot from an
   action today (they must switch to the quiescent boundary) and it does not
   help the crash route.

Option 1 is preferable and matches the `⚛️ ATOMICITY: exit → actions → enter
is ONE transaction` comment the engine already carries.

*Compatibility.* The predicate only ever refuses blobs that are currently
accepted and that are, by construction, unrestorable — strictly an
improvement. It should be a changelog entry; the recursive child path must
keep its `_await_settled_for_snapshot()` behaviour rather than raising, so a
parent's snapshot is not failed by a child's race. A `SnapshotMidStepError`
message naming the offending region would make the refusal actionable.

## Acceptance criteria

- [ ] `repro/R5-01_parallel-tear-passes-midstep-guard.py` exits `0`.
- [ ] `tests/test_persistence.py::test_snapshot_during_parallel_region_transition_is_refused`
      — a snapshot taken while one region of a `parallel` machine is
      mid-transition raises `SnapshotMidStepError`, on both engines.
- [ ] `tests/test_persistence.py::test_snapshot_from_entry_action_never_pairs_new_state_with_old_context`
      — covers the `d5s1` half; no `state_ids=['oms.filled']` with
      `filled_qty=0`.
- [ ] `tests/test_persistence.py::test_configuration_legality_predicate`
      — unit test of the new predicate: parallel-with-missing-region,
      compound-with-two-children, orphan-leaf-without-parent, and legal
      configurations, each classified correctly.
- [ ] `tests/test_persistence.py::test_snapshot_legality_property`
      — **hypothesis** property test: generate random machines containing at
      least one `parallel` state with 2–4 regions of depth 1–3, drive a random
      event sequence, and snapshot **at every quiescent point**; assert every
      accepted snapshot satisfies the legality predicate and round-trips to an
      identical configuration, and that every refusal is a
      `SnapshotMidStepError`. Currently fails; must reach 0 failures over
      ≥500 examples. (The same generator serves R5-02's read-side property.)
- [ ] `tests/test_wave2_review_findings.py` — the existing #102 test extended
      to a parallel configuration, so the original reproducer's shape is no
      longer the only one covered.
- [ ] Changelog entry: `SnapshotMidStepError` now enforces per-region
      configuration legality, not just leaf presence.

## Related

- **#102** (round 4, `SnapshotMidStepError`) — closed as filed; its
  reproducer passes. This is the invariant behind it, filed new rather than as
  a reopen because #102's acceptance criteria as written were met.
- **R5-02** (Blocker, no read-side legality check on `from_snapshot()`) — the
  other half of the same missing invariant; the two should be fixed by one
  predicate. R5-02 is what turns this transient tear into a durable one.
- **#110** (`SnapshotCorruptError` shape checks) and **#112**
  (`_repair_configuration`) — the neighbouring restore-side work; neither
  covers per-region leaf legality.
- **R5-12** (Blocker, `actionErrorPolicy:"fail"` reverts to the source state
  and the result is snapshottable) — a *legal-but-wrong-leaf* window that this
  predicate does **not** close; listed so the fix is not assumed to cover it.
- **Register source ids:** R5-01 ← D5-persistence-1, D5-semantics-1, J-1,
  J-1b, J-10 (exit-window half). Register of record:
  `33-r5-findings-register.md` §2/§3.
- **Evidence:** `triage-r5/t1_snapshot.py::A`,
  `battle-3ed3099/persistence/d3b_partial_parallel.py`,
  `battle-3ed3099/persistence/n3_parallel_tear.py`,
  `battle-3ed3099/semantics/repro/d5s1_entry_action_torn_snapshot.py`.

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (confirmed via
  `git log -1` in the library clone).
- `repro/R5-01_parallel-tear-passes-midstep-guard.py` written fresh for this
  issue and run capped at 90 s: output matches the Observed section verbatim,
  exit code `1`.
- `d3b_partial_parallel.py` and `d5s1_entry_action_torn_snapshot.py` re-run
  verbatim on this commit in fresh processes; both still reproduce as quoted.
- Root cause confirmed against source: `_active_leaf_present()` at
  `base_interpreter.py:1111-1118`, consumed at `:1156` and `:1097`;
  `get_persisted_snapshot()` docstring contract at `:1121-1127`.
- No project-name or label leakage in this body or the repro script.
