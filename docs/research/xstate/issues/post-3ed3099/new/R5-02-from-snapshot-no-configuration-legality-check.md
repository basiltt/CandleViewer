---
r5: R5-02
title: "Bug: `from_snapshot()` performs no configuration-legality check — a truncated `configuration` restores as a `running` machine with zero active leaves and is permanently inert"
labels: [bug, severity/blocker, area/persistence]
severity: Blocker
repro_script: repro/R5-02_restore-accepts-leafless-configuration.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

#102 closed its reproducer on the **write** side; the invariant behind it was
never mirrored on the **read** side, and #110's `check_shape()` tests
*non-emptiness* rather than legality. A snapshot whose `configuration` list
has lost its leaf elements — leaving only ancestors, e.g. `["ord"]` — passes
`check_shape` (`persistence.py:186`), and `from_snapshot()` then *prefers*
`configuration` over the still-correct `state_ids` sitting in the same blob
(`base_interpreter.py:1442`), so the good data is never consulted. The result
is a live interpreter with `status="running"`, `error=None` and an empty
active configuration: it matches no event, ever, on either engine. The engine
already owns the right predicate (`_active_leaf_present()`,
`base_interpreter.py:1112`) and applies it only when writing.

## Environment

- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (`main`, unreleased
  0.8.1; `__version__` still reports `0.8.0`, so this build is identified by
  commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source modified.

## Minimal reproduction

```python
"""R5-02 repro: `from_snapshot()` performs no configuration-legality check.
A snapshot whose `configuration` list has been truncated to the machine root
(ancestors only, no leaf) is accepted, restores with `status="running"` and
zero active leaves, and is permanently inert — while the still-correct
`state_ids` field sitting in the same blob is never consulted.

Stdlib + xstate_statemachine only. Exits 1 while present, 0 once fixed.
"""

import json
import sys

from xstate_statemachine import MachineLogic, SyncInterpreter, create_machine
from xstate_statemachine.exceptions import XStateMachineError

CFG = {
    "id": "ord",
    "initial": "working",
    "context": {"filled": 0},
    "states": {
        "working": {"on": {"FILL": "filled"}},
        "filled": {},
    },
}


def build():
    return create_machine(CFG, logic=MachineLogic())


def main() -> int:
    live = SyncInterpreter(build()).start()
    snap = live.get_persisted_snapshot()
    good_cfg = list(snap["configuration"])
    good_ids = list(snap["state_ids"])

    # Simulate a partial/truncated durable write: list elements lost, JSON
    # still well-formed, `machine_hash` intact, `state_ids` untouched.
    snap["configuration"] = [x for x in good_cfg if x == "ord"]
    blob = json.dumps(snap)

    print("OBSERVED:")
    print("  good configuration        :", good_cfg)
    print("  good state_ids            :", good_ids)
    print("  tampered configuration    :", snap["configuration"])
    print("  intact state_ids in blob  :", snap["state_ids"])

    try:
        restored = SyncInterpreter.from_snapshot(blob, build()).start()
    except XStateMachineError as exc:
        print("  from_snapshot             : refused with", type(exc).__name__)
        print("RESULT: PASS")
        return 0

    ids = sorted(restored.current_state_ids)
    status = restored.status
    receipt = restored.send("FILL")
    ids_after = sorted(restored.current_state_ids)

    print("  from_snapshot             : ACCEPTED")
    print("  restored current_state_ids:", ids)
    print("  restored status           :", status)
    print("  restored error            :", restored.error)
    print("  FILL receipt              :", receipt)
    print("  state ids after FILL      :", ids_after)

    print("EXPECTED:")
    print("  from_snapshot() raises SnapshotCorruptError (an XStateMachineError):")
    print("  a 'running' configuration with zero atomic states is not a legal")
    print("  SCXML configuration; alternatively fall back to the intact")
    print("  state_ids ['ord.working'].")

    if not ids and status == "running":
        print("RESULT: FAIL - restored into a running machine with no active leaf")
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(main())
```

## Observed behaviour

```
OBSERVED:
  good configuration        : ['ord', 'ord.working']
  good state_ids            : ['ord.working']
  tampered configuration    : ['ord']
  intact state_ids in blob  : ['ord.working']
  from_snapshot             : ACCEPTED
  restored current_state_ids: []
  restored status           : running
  restored error            : None
  FILL receipt              : None
  state ids after FILL      : []
EXPECTED:
  from_snapshot() raises SnapshotCorruptError (an XStateMachineError):
  a 'running' configuration with zero atomic states is not a legal
  SCXML configuration; alternatively fall back to the intact
  state_ids ['ord.working'].
RESULT: FAIL - restored into a running machine with no active leaf
```

Exit status `1`.

The same payload on the async `Interpreter` behaves identically (accepted,
ids `[]`, `status="running"`, still `[]` after an event), confirmed in
`triage-r5/t1_snapshot.py::B` and in the independent re-run recorded in
`34-r5-02-refutation.md`:

| probe | result |
|---|---|
| sync, `configuration` truncated to `["ord"]` | accepted; ids `[]`; `status="running"`; `[]` after the event |
| async `Interpreter`, same payload | accepted; ids `[]`; `status="running"`; `[]` after the event |
| **control**: `configuration` key removed entirely | restores correctly via `state_ids` |

The control row is the sharp edge: the blob contains everything needed to
restore correctly, and the one field that *is* consulted is the corrupted one.

## Expected behaviour

W3C SCXML §3.2.1 / §3.13 define a legal configuration as one containing
exactly one active atomic descendant for every active compound state and all
children of every active `<parallel>` state. A `running` machine whose active
configuration contains no atomic state is not a legal configuration at any
point, so it must not be constructible by restore.

XState v5's persistence contract (<https://stately.ai/docs/persistence>) is
that `createActor(logic, { snapshot })` resumes an actor that "continues from
where it left off". An actor that continues from nowhere, reporting
`status: "running"`, violates it. Note that XState persists a *nested* `value`
object, in which a root-only value is not expressible the way a flattened
ancestor list is — so this flat `configuration` representation is
library-specific and parity offers no cover for the behaviour.

The library's own documented contract, quoted from `check_shape()` at
`persistence.py:148-156`:

> Reject a structurally invalid payload with a typed error (#110).
>
> Runs after `check_version` / `check_identity` and before any field is read,
> so a corrupted blob cannot surface as a bare ``KeyError`` **or be restored
> into an impossible state**.

A `running` configuration with no atomic state is precisely an impossible
state. The docstring even names the intended check — *"and a `running`
snapshot that names at least one state"* — which is the weaker property that
was actually implemented.

Expected concretely: `from_snapshot()` raises `SnapshotCorruptError` (an
`XStateMachineError`) for this blob, naming the offending region; or, if a
recovery path is preferred, falls back to `state_ids` when `configuration`
does not yield a legal configuration and then re-checks.

## Root cause analysis

Two lines, both trivially fixable.

**1. `persistence.py:186-189` tests emptiness, not legality:**

```python
if status == "running" and not (
    snapshot.get("configuration") or snapshot["state_ids"]
):
    fail("status is 'running' but the configuration is empty")
```

`["ord"]` is truthy, so the check passes. The test is also purely lexical —
`check_shape` has no access to the `MachineNode`, so it cannot know that
`"ord"` is the root and therefore cannot be a leaf. Any legality check has to
live where the machine is in scope, i.e. in `from_snapshot`.

**2. `base_interpreter.py:1442` prefers the corrupted field:**

```python
interpreter._active_state_nodes.clear()
restore_ids = snapshot.get("configuration") or snapshot["state_ids"]
for state_id in restore_ids:
    node = machine.get_state_by_id(state_id)
    if node:
        interpreter._active_state_nodes.add(node)
        ancestor = node.parent
        while ancestor is not None:
            interpreter._active_state_nodes.add(ancestor)
            ancestor = ancestor.parent
    else:
        raise StateNotFoundError(target=state_id)
```

The loop resolves `"ord"` successfully (it is a real node), adds it, walks its
non-existent ancestors, and finishes. There is **no post-loop assertion** that
the result contains a leaf, that each active compound state has an active
child, or that each region of an active parallel state is populated.
`status` is assigned verbatim at `:1428` (`interpreter.status =
snapshot["status"]`), so the machine reports `running`. `current_state_ids`
filters to `is_atomic or is_final`, so the root contributes nothing and the
property returns `[]`.

The correct predicate, `_active_leaf_present()` (`base_interpreter.py:1112`),
already exists in the same class and is used **only** on the write side
(`get_persisted_snapshot` at `:1156`, `_await_settled_for_snapshot` at
`:1097`). Nothing calls it on restore. That asymmetry is the whole defect.

This is not a regression — the read path has never checked legality. What
changed in round 4 is that #110 introduced `check_shape` and documented it as
preventing restore "into an impossible state", so the gap is now a
contradiction of a shipped, documented contract rather than a silent absence.

## Impact

**General users.** Snapshots live in Redis, on disk, in a queue, or in a
column — media where a truncated or partially-overwritten write is a normal
failure mode, and precisely the threat `check_shape` exists to defend against.
A write that drops list elements while leaving the JSON parseable and
`machine_hash` intact produces a blob that restores silently into a dead
machine. Every public health probe reports healthy: `status == "running"`,
`error is None`, `has_dormant_invocations` / `has_dormant_timers` nothing to
restart, `queue_depth == 0`, `is_running is True`. Events return
`Receipt(changed=False, error=None, deferred=False)` — indistinguishable from
a legitimately unhandled event. The only detection available today is for the
application to assert `current_state_ids` is non-empty after every restore,
which requires knowing about this bug. It is also the durable half of R5-01:
a tear produced by the write-side hole loads clean a second time and the
corruption becomes permanent.

*On severity:* an independent refutation pass
(`34-r5-02-refutation.md`) confirmed every claim and argued for Major on the
grounds that the library cannot itself emit such a payload — `#102` refuses
mid-step, `#112` repairs settle trips in place, `SnapshotDriftError` catches
migrations — so reaching it requires an externally mutated blob. The register
of record keeps it at Blocker because hostile/damaged storage is exactly the
input this code path exists to validate, and because R5-01 supplies an
in-library route to a configuration that is illegal in the same way. Both
readings are recorded here so the maintainers can weigh them.

**Order-management scenario (our adoption audit, #26).** Each order's
lifecycle is an interpreter, checkpointed so an order survives a process
restart. A partial write to the order-state store — a truncated Redis value, a
torn page, a half-flushed append — produces this blob. The order loads on
restart, reports `running`, and is deaf: the exchange `FILL` returns
`changed=False, error=None`; the operator `CANCEL` returns the identical
receipt. A filled order is never recorded as filled and a cancel is never
placed, while every monitoring surface asserts the order is alive and healthy.
Unbounded financial exposure from a non-crashing, non-logging failure, and it
is undetectable without an out-of-band legality check we would have to write
ourselves.

## Proposed fix

**One configuration-legality invariant, enforced on both sides.** This is the
read half of the same change proposed in R5-01; they should land together.

Define the predicate once on `BaseInterpreter`, replacing
`_active_leaf_present()`:

```python
def _configuration_is_legal(self, nodes=None) -> bool:
    """A legal SCXML configuration (§3.2.1/§3.13):
      * at least one active atomic-or-final leaf;
      * every active non-root node has its parent active;
      * every active compound state has EXACTLY ONE active child;
      * every active parallel state has ALL its children active.
    """
```

*Write side* (R5-01): call it at `base_interpreter.py:1156` and `:1097` in
place of `_active_leaf_present()`.

*Read side* (this issue): after the reconstruction loop at
`base_interpreter.py:1442-1459`, and only when `status == "running"`:

```python
if interpreter.status == "running" and not interpreter._configuration_is_legal():
    raise SnapshotCorruptError(
        f"Snapshot is malformed: restored configuration {sorted(...)} is not a "
        f"legal configuration for machine '{machine.id}'."
    )
```

`SnapshotCorruptError` is the right type — it already subclasses
`XStateMachineError`, it is what `check_shape` raises, and `from_snapshot`'s
docstring already advertises it. Raising from `from_snapshot` rather than
`check_shape` is necessary because legality needs the `MachineNode`, which
`check_shape` does not receive.

**Optional recovery instead of refusal.** Since the blob in the repro contains
enough information to restore correctly, a friendlier variant is to try
`configuration` first, and if the result is illegal, retry from
`state_ids` (rebuilding ancestors) before raising. This turns a class of
partial corruptions into clean recoveries and costs nothing when the blob is
intact. If implemented, it must still raise when *both* fields yield an
illegal configuration, and should emit a warning so the corruption is visible
rather than silently papered over.

**Compatibility.** Every blob newly rejected today produces an inert
interpreter, so rejecting it is strictly an improvement — but it is a
behaviour change for anyone whose store already holds such a blob (they move
from a silent failure to a loud one, which is the point). Worth a changelog
entry and, if a gentler migration is wanted, a
`validate_configuration: bool = True` parameter on `from_snapshot` for one
release. `#112`'s `_repair_configuration` should not be reached by this path;
if the maintainers prefer *repair* over *refusal*, it must be applied
explicitly and reported, never silently.

## Acceptance criteria

- [ ] `repro/R5-02_restore-accepts-leafless-configuration.py` exits `0`.
- [ ] `tests/test_persistence.py::test_from_snapshot_rejects_root_only_configuration`
      — the exact repro blob raises `SnapshotCorruptError` on both
      `SyncInterpreter` and `Interpreter`.
- [ ] `tests/test_persistence.py::test_from_snapshot_rejects_parallel_region_without_leaf`
      — the R5-01 tear shape (region node active, no child) is refused on
      restore even if it is somehow produced.
- [ ] `tests/test_persistence.py::test_from_snapshot_rejects_orphan_leaf_without_ancestors`
      — a `configuration` naming a deep leaf whose ancestors were dropped is
      either repaired by the existing ancestor walk or refused, never left
      partial.
- [ ] `tests/test_persistence.py::test_from_snapshot_accepts_legacy_state_ids_only_snapshot`
      — the existing fallback path (no `configuration` key) still restores
      correctly; guards against over-tightening.
- [ ] `tests/test_persistence.py::test_from_snapshot_does_not_reject_stopped_or_done_snapshots`
      — legality is enforced for `running` only.
- [ ] `tests/test_persistence.py::test_configuration_legality_property`
      — **hypothesis** property test over random machines containing at least
      one `parallel` state with 2–4 regions of depth 1–3: drive a random event
      sequence, snapshot **at every quiescent point**, and assert (a) every
      snapshot is legal and round-trips to an identical active configuration,
      and (b) for every non-empty proper subset of the `configuration` list
      that is illegal, `from_snapshot` raises `SnapshotCorruptError` (or
      recovers to the legal configuration if the fallback variant is chosen)
      — never returns an interpreter with `status == "running"` and no active
      leaf. ≥500 examples, 0 failures. This is the same generator R5-01 uses.
- [ ] Changelog entry: `from_snapshot()` now validates configuration legality
      and raises `SnapshotCorruptError`.

## Related

- **#110** (round 4, `SnapshotCorruptError` / `check_shape`) — closed as
  filed; this is the legality check its own docstring promises ("or be
  restored into an impossible state") but does not implement. Filed new rather
  than as a reopen because #110's acceptance criteria as written were met.
- **#102** (round 4, `SnapshotMidStepError`) — the write-side guard, which is
  exactly what makes this blob unreachable from a well-formed payload, and
  exactly what was never mirrored here.
- **R5-01** (Blocker, `_active_leaf_present()` is an any-leaf test) — the
  write side of the same missing invariant, and an in-library route to a
  configuration illegal in the same way. **Fix both with one predicate.**
- **#112** (`_repair_configuration`) — repairs the live settle-trip case and
  is not reached on the restore path; noted so it is not mistaken for
  coverage.
- **R5-03** (High, raw `TypeError`/`AttributeError`/`ValueError` escape
  `from_snapshot`) — the same function, the same "typed errors only" contract,
  a different set of fields.
- **R5-17** (Medium, non-`str` event types accepted via the restore path) —
  another #113-class check enforced on `send()` but not on restore.
- **Register source ids:** R5-02 ← D5-concurrency-1, D5-semantics-3,
  D5-fuzz-3 (restore half). Register of record: `33-r5-findings-register.md`
  §2/§3; adversarial refutation: `34-r5-02-refutation.md`.
- **Evidence:** `triage-r5/t1_snapshot.py::B`,
  `battle-3ed3099/semantics/repro/d5s3_truncated_config_inert.py`.

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (confirmed via
  `git log -1` in the library clone).
- `repro/R5-02_restore-accepts-leafless-configuration.py` written fresh for
  this issue and run capped at 90 s: output matches the Observed section
  verbatim, exit code `1`.
- `triage-r5/t1_snapshot.py` re-run in a fresh process on this commit:
  `B_accepted: true`, `B_ids: []`, `B_status: "running"`,
  `B_ids_after_GO: []`, against `B_good_config: ['fz','fz.b']` /
  `B_good_ids: ['fz.b']`.
- Root cause confirmed against source: `check_shape` non-emptiness test at
  `persistence.py:186-189` with its docstring at `:148-156`;
  `restore_ids = snapshot.get("configuration") or snapshot["state_ids"]` at
  `base_interpreter.py:1442`; `interpreter.status = snapshot["status"]` at
  `:1428`; `_active_leaf_present()` at `:1112` with its only call sites at
  `:1097` and `:1156`.
- No project-name or label leakage in this body or the repro script.
