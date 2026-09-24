# R5-02 — adversarial refutation: "no read-side legality check on restored configuration"

Library: `_ref/xstate-statemachine` @ 3ed3099 (unreleased 0.8.1).
Repro: `triage-r5/t1_snapshot.py::B`, plus `/tmp/r502*.py` (re-run with the
mandatory policy block, on both engines, and with a non-tampered migration path).

## Verdict

**DOWNGRADE to Major** (from Blocker). The defect reproduces exactly as claimed and
is not documented, not API misuse, and not XState parity — but it is **not reachable
from any output the library itself produces**. It is a corruption-detection gap on
the read side, not a live-engine fault.

## What reproduces (all confirmed)

With the mandatory config block present (`actionErrorPolicy/onUnhandled/
guardErrorPolicy/strictTargets/strict/spawnBlockingTimeout`), on **both** engines:

| probe | result |
|---|---|
| sync, `configuration` truncated to `["fz"]` | accepted; `current_state_ids=[]`; `status="running"`; after `GO` still `[]` |
| async (`Interpreter`) same payload | accepted; ids `[]`; `status="running"`; `[]` after `GO` |
| control: `configuration` key removed entirely | restores correctly to `["fz.b"]` via `state_ids` |

So the claimed mechanism is exact:

- `persistence.py:186` — `if status == "running" and not (snapshot.get("configuration")
  or snapshot["state_ids"])` is a **non-emptiness** test. `["fz"]` (machine root alone)
  satisfies it.
- `base_interpreter.py:1442` — `restore_ids = snapshot.get("configuration") or
  snapshot["state_ids"]` prefers `configuration`, so the still-correct `state_ids`
  (`["fz.b"]`) is never consulted. The root node is skipped by the live-config
  accessor, leaving zero leaves.
- The correct predicate `_active_leaf_present()` (`base_interpreter.py:1112`) exists
  and is applied only on the **write** side (`get_persisted_snapshot`, #102) and in
  `_await_settled_for_snapshot`.

This directly contradicts `check_shape`'s own docstring: *"so a corrupted blob cannot
surface as a bare KeyError **or be restored into an impossible state**"*. A `running`
configuration with no atomic state is precisely an impossible SCXML configuration.

## Refutation attempts — all fail

- **Documented?** No. `from_snapshot` documents `StateNotFoundError`,
  `InvalidConfigError`, `SnapshotVersionError`, `SnapshotDriftError`. #135 documents
  that `status` is not a *liveness* signal after restore — that is about dormant
  invokes/timers, not about a configuration with no leaf at all. The inert machine
  here also reports `has_dormant_*` nothing to restart.
- **API misuse?** No. Mandatory policy block present, both engines, `start()` called,
  default `verify_machine_hash=True` (the truncation preserves `machine_hash`, so the
  drift check does not fire).
- **Superseded by #102?** No — #102 closed the *write* side only, by construction:
  the write-side guard is exactly what makes this unreachable from a well-formed
  payload, and exactly what was never mirrored on read.
- **XState v5 agrees?** Not applicable as a defence: XState persists a nested `value`
  object, where a "root-only" value is not expressible the way a flattened ancestor
  list is. This flat `configuration` list is a library-specific representation, so
  parity gives no cover.
- **Duplicate of a closed issue?** No. #102 (write side), #110 (`SnapshotCorruptError`
  shape checks), #112 (`_repair_configuration` for the live settle-trip) are the
  neighbours; none covers read-side leaf legality.

## Why Major and not Blocker

The library cannot emit such a payload:

- `get_persisted_snapshot()` refuses mid-step (`SnapshotMidStepError`, #102).
- A settle-budget trip repairs in place (`_repair_configuration`, #112) and snapshots
  as `configuration=['tp','tp.x'], state_ids=['tp.x']` — legal.
- A `done` machine snapshots `['fin','fin.z']` — legal.
- A real machine-structure migration is refused earlier by `SnapshotDriftError`.

Reaching the bug requires an **externally mutated snapshot** — a truncated/partial
write to Redis/disk/queue that removes list elements while leaving the JSON and the
`machine_hash` intact. That is a real OMS risk (which is why `check_shape` exists at
all), and the failure mode is the worst kind — silent acceptance, `status="running"`,
permanently inert, no error, no log — but it is a robustness/validation gap on hostile
input, not a defect the engine produces on its own. Blocker is reserved for the latter.

## Fix (one line, already owned by the engine)

In `persistence.check_shape`, replace the non-emptiness test with a leaf test — or,
equivalently, in `from_snapshot` prefer `configuration` only when it yields at least
one atomic node and otherwise fall back to `state_ids`, then assert
`_active_leaf_present()` before returning. The predicate already exists.

## Residual (out of scope for R5-02, observed in the same run)

`t1_snapshot.py::C/D/E` still show **10 untyped** escapes from `from_snapshot`
(`TypeError`/`AttributeError`/`ValueError` from mutated `status`, `history`, `actors`,
`system`, `deferred`, `version`, non-`str` `pending_events[].type`, and
`snapshot_str=None`), i.e. `check_shape`'s "typed error" contract is partial beyond
this finding too. Tracked separately.
