---
lc: LC-21
title: "Feature: persisted snapshots carry no schema version or machine identity"
labels: [enhancement, severity/high, area/persistence, candleviewer]
severity: High
blocks_adoption: false
repro_script: repro/LC-21_no-snapshot-schema-version.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`get_persisted_snapshot()` emits exactly nine keys — `status`, `context`, `state_ids`, `configuration`, `output`, `error`, `history`, `actors`, `system` — and none of them identifies the snapshot format or the machine that produced it. `from_snapshot()` therefore cannot tell a snapshot written by this version from one written by a future version with a different layout, nor one produced by a *different* machine that happens to share state ids. Every consumer that persists snapshots beyond a single process lifetime must invent its own versioning envelope, and any consumer that does not will one day restore a stale payload into an evolved machine and get silent corruption instead of an error.

## Environment

- Library: xstate-statemachine 0.7.0, commit `42612cf` (local clone, `pip install -e .`)
- Python: 3.13.7
- OS: Windows-11-10.0.26200-SP0

## Current workaround and why it is insufficient

Wrap every snapshot in an application-owned envelope before it reaches storage:

```python
import hashlib, json, time

CV_SCHEMA_VERSION = 3
UPCASTERS = {1: _v1_to_v2, 2: _v2_to_v3}


def machine_hash(machine) -> str:
    """Structural fingerprint - must be recomputed by hand from the machine tree."""
    shape = json.dumps(_walk_states(machine), sort_keys=True)  # our own traversal
    return hashlib.sha256(shape.encode()).hexdigest()[:16]


def save(interp, machine) -> str:
    return json.dumps({
        "cv_schema_version": CV_SCHEMA_VERSION,
        "machine_id": machine.id,
        "machine_hash": machine_hash(machine),
        "taken_at": time.time(),
        "payload": interp.get_persisted_snapshot(),
    })


def load(blob: str, machine):
    env = json.loads(blob)
    v = env["cv_schema_version"]
    while v < CV_SCHEMA_VERSION:
        env["payload"] = UPCASTERS[v](env["payload"]); v += 1
    if env["machine_hash"] != machine_hash(machine):
        raise SemanticDriftError(env["machine_id"])
    return Interpreter.from_snapshot(json.dumps(env["payload"]), machine)
```

Why this is not enough:

1. **It cannot version the payload it wraps.** Our envelope version tracks *our* changes. If a future library release changes the shape of the nine inner keys — adds a required field, changes `history` from `{parent: [ids]}` to something richer — our `cv_schema_version` is unchanged, our upcaster chain is a no-op, and the library happily consumes a payload whose meaning has shifted. Only the library can version its own format.
2. **`machine_hash` requires reimplementing the library's own tree walk** in application code, so the fingerprint drifts out of sync with the structure it is meant to fingerprint every time the model gains a field.
3. **Every user must build this independently**, and get it right the first time — versioning is impossible to retrofit, because the snapshots already in storage have no version field to branch on.
4. **The library's own `_pending_actor_snapshots` re-emission path** (`base_interpreter.py:747`) round-trips child snapshots verbatim across saves. Those preserved blobs can outlive several releases inside a parent's snapshot, entirely outside the reach of an outer envelope.

The reproduction below shows what the unwrapped library does today.

```python
"""LC-21 - persisted snapshots carry no schema version or machine identity.

`get_persisted_snapshot()` emits exactly nine keys, none of which identify the
snapshot format or the machine that produced it. A snapshot written by an older
build, or by a *different* machine that happens to share state ids, restores
silently.
"""

from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import Interpreter, create_machine

CFG_V1 = {"id": "o", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
# A *different* machine that happens to reuse the id `o` and the state id `o.a`.
CFG_OTHER = {"id": "o", "initial": "a",
             "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}}}

EXPECTED_META = ("version", "schema_version", "machine_id", "machine_hash", "taken_at")


async def main() -> int:
    interp = await Interpreter(create_machine(CFG_V1)).start()
    snapshot = json.loads(interp.get_snapshot())
    await interp.stop()

    print(f"OBSERVED snapshot keys: {sorted(snapshot)}")
    for key in EXPECTED_META:
        print(f"OBSERVED   {key!r} present: {key in snapshot}")

    raised = None
    try:
        restored = Interpreter.from_snapshot(json.dumps(snapshot), create_machine(CFG_OTHER))
        await restored.start()
        state = sorted(restored.current_state_ids)
        await restored.stop()
    except Exception as exc:  # noqa: BLE001
        raised, state = type(exc).__name__, None
    print(f"OBSERVED restoring the snapshot into a *different* machine raised={raised} state={state}")

    # A hand-forged future-format snapshot is also accepted without complaint.
    forged = dict(snapshot, version=99, unknown_future_field={"x": 1})
    try:
        r2 = Interpreter.from_snapshot(json.dumps(forged), create_machine(CFG_V1))
        await r2.start()
        await r2.stop()
        print("OBSERVED a snapshot claiming version=99 restores without error")
    except Exception as exc:  # noqa: BLE001
        print(f"OBSERVED version=99 snapshot rejected: {type(exc).__name__}")

    print("EXPECTED get_persisted_snapshot() writes a 'version' (and ideally a "
          "machine-structure hash), and from_snapshot() rejects a version or "
          "hash it does not understand")
    return 1 if "version" not in snapshot else 0


sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED snapshot keys: ['actors', 'configuration', 'context', 'error', 'history', 'output', 'state_ids', 'status', 'system']
OBSERVED   'version' present: False
OBSERVED   'schema_version' present: False
OBSERVED   'machine_id' present: False
OBSERVED   'machine_hash' present: False
OBSERVED   'taken_at' present: False
OBSERVED restoring the snapshot into a *different* machine raised=None state=['o.a']
OBSERVED a snapshot claiming version=99 restores without error
EXPECTED get_persisted_snapshot() writes a 'version' (and ideally a machine-structure hash), and from_snapshot() rejects a version or hash it does not understand
(exit code 1)
```

This nine-key inventory was confirmed field by field against `get_persisted_snapshot()`; the repro above prints it directly.

## Expected behaviour

XState v5 names this exact hazard as the first of its persistence caveats (https://stately.ai/docs/persistence#caveats):

> Incompatible state: if the machine or actor logic changes, the restored state may be incompatible with the new logic.

XState leaves resolving that incompatibility to the application — but it is only *possible* to resolve when the payload carries an identity to check against. Note that XState's snapshots are structurally self-describing in a way this library's are not: a persisted XState snapshot nests each child under `children` with its own `src` string, so a mismatched payload tends to fail loudly on restore. Here the nine flat keys carry no `src`, no machine id and no format marker, so there is nothing to branch on.

To be precise about what is and is not being claimed: XState does **not** ship a `version` integer in its snapshots either, so this is a request for the library to go one step beyond XState rather than to match it. The justification is that a serialisation format which omits its own version number is the one design choice that cannot be corrected later, because the fix has no field to branch on — and this library's flat nine-key layout has less inherent self-description to fall back on than XState's.

Concretely, expected: `get_persisted_snapshot()` includes a `version` integer; `from_snapshot()` raises a typed error on a version it does not understand rather than best-effort parsing an unknown layout.

## Root cause analysis

- `src/xstate_statemachine/base_interpreter.py:690-745` — `get_persisted_snapshot()` returns a dict literal of exactly the nine observed keys, ending at `:745`. There is no format-version constant anywhere in the module.
- `src/xstate_statemachine/base_interpreter.py:669-688` — `get_snapshot()` wraps that dict with `json.dumps(..., indent=2, default=str)` (`:683`) and adds nothing.
- `src/xstate_statemachine/base_interpreter.py:815-958` — `from_snapshot()` `json.loads`es the string (wrapping `JSONDecodeError` in `InvalidConfigError`, `:858-862`, and rejecting non-objects at `:864-868`) and then reads keys positionally and defensively. An unknown-layout payload is not distinguishable from a valid one: missing keys fall back to defaults, extra keys are ignored. The only structural validation is that state ids resolve, which raises `StateNotFoundError` — and that fires only for *renamed* states, never for a state id whose meaning changed.
- `src/xstate_statemachine/base_interpreter.py:747` — `_persist_actors` re-emits parked child snapshots verbatim (its own docstring: actors in `_pending_actor_snapshots` "are re-emitted verbatim"), so unversioned payloads propagate across saves and can outlive several releases nested inside a parent.

## Impact

**General users:** the library's persistence story is complete except for the one field that makes it survivable across deployments. A team ships v1, persists thousands of snapshots, changes a machine in v2, and gets silent misbehaviour rather than a load-time error. Debugging that means diffing raw JSON against git history. Worse, the fix cannot be applied retroactively to snapshots already in storage.

**CandleViewer (trading OMS):** we persist every order, leg, reconciliation and TWAP machine (roughly twenty machine definitions) to survive process restarts, so *every* persisted machine is exposed. Two concrete failures:
- **Format drift:** a library upgrade changes the snapshot layout; on restart an order machine's `history` or `actors` is silently reinterpreted and a partially-filled parent order restores with its leg actors dropped — the OMS believes it has no working legs while the exchange is still filling them.
- **Semantic drift at a stable id (LC-23):** we verified that adding a guard to `FILL` while keeping the state id `submitted` restores silently — the order enters `submitted`, `FILL` is now guarded false, and **the order is stuck forever** while fills arrive from the exchange. OMS evolution is far more often "add a guard" than "rename a state", so the common case of drift is exactly the case the library cannot detect. A machine-structure hash in the snapshot turns that into a loud load-time failure.

We carry our own `cv_schema_version` + `machine_hash` envelope and an upcaster registry because of this — cost we would rather not own, and which still cannot cover the inner payload.

## Proposed API

Add a version field, and an optional structural fingerprint:

```python
SNAPSHOT_VERSION = 1  # new module: xstate_statemachine/persistence.py


def get_persisted_snapshot(self, _seen=None) -> Dict[str, Any]:
    return {
        "version": SNAPSHOT_VERSION,
        "machine_id": self.machine.id,
        "machine_hash": self.machine.structure_hash,  # cached property
        "taken_at": time.time(),                      # LC-50
        "status": self.status,
        ...  # the existing nine keys, unchanged
    }
```

Restore-side validation:

```python
Interpreter.from_snapshot(blob, machine)
# -> SnapshotVersionError("snapshot version 2 is newer than supported version 1")

Interpreter.from_snapshot(blob, machine)
# -> SnapshotDriftError("machine 'order' structure changed since this snapshot
#                        was taken (a1b2c3d4 != e5f6a7b8)")

# Opt out when the drift is known-safe and the application has migrated:
Interpreter.from_snapshot(blob, machine, verify_machine_hash=False)
```

Usage example — the CandleViewer boot path, with the envelope deleted:

```python
from xstate_statemachine import Interpreter, SnapshotDriftError, SnapshotVersionError

def restore_order(blob: str, machine) -> Interpreter | None:
    try:
        return Interpreter.from_snapshot(blob, machine)
    except SnapshotVersionError as exc:
        log.error("order snapshot from a newer build; refusing to guess", exc_info=exc)
        raise                      # fail the boot loudly - do not half-restore an order
    except SnapshotDriftError as exc:
        log.warning("machine evolved since snapshot; running migration", exc_info=exc)
        return Interpreter.from_snapshot(migrate(blob), machine, verify_machine_hash=False)
```

Design notes:

- **`version` is an integer**, bumped only when the payload layout changes — not tied to the package version, so patch releases do not invalidate stored snapshots.
- **`from_snapshot` accepts any `version <= SNAPSHOT_VERSION`** and rejects newer ones; older versions are migrated internally by a small upcaster chain in a new `persistence.py` module so users never write one for library-side changes.
- **`machine_hash`** is a stable hash over the machine's structural shape: state ids, types, transition event names, target ids, guard *names*, action *names*, invoke srcs, and `after` delays — deliberately including guard names so the LC-23 "added a guard" case changes the hash, and deliberately excluding docstrings/`meta`/ordering-insensitive detail so cosmetic edits do not. Implement as a cached property on `MachineNode` (`models.py:1090`) so the traversal lives next to the tree it walks.
- **Backwards compatibility:** a snapshot with no `version` key is treated as version 0 (the current format) and restored exactly as today, so snapshots already in storage keep loading. `machine_hash` verification is skipped when the snapshot carries no hash — old payloads cannot be drift-checked, which is precisely the point about retrofitting.
- **Missing-hash strictness** should be a documented default (`verify_machine_hash=True`, no-op on version-0 payloads) rather than a silent skip on version-1 payloads.
- New exceptions subclass the existing `XStateMachineError` so the documented catch-all keeps working.

This pairs naturally with LC-50 (`taken_at`, optional bounded `recent_transitions` ring) and LC-25 (`get_snapshot()` hardcodes `indent=2` — 1.77x size inflation); if the payload is being changed, changing it once is cheaper.

## Acceptance criteria

- [ ] `repro/LC-21_no-snapshot-schema-version.py` exits 0.
- [ ] `tests/test_persistence.py::test_persisted_snapshot_includes_version_and_machine_identity`.
- [ ] `tests/test_persistence.py::test_from_snapshot_rejects_future_version` — asserts `SnapshotVersionError`.
- [ ] `tests/test_persistence.py::test_from_snapshot_accepts_legacy_unversioned_snapshot` — a hand-written nine-key payload still restores.
- [ ] `tests/test_persistence.py::test_machine_hash_changes_when_a_guard_is_added` — the LC-23 drift case; asserts `SnapshotDriftError`.
- [ ] `tests/test_persistence.py::test_machine_hash_is_stable_across_cosmetic_edits` — `meta`/description changes do not invalidate stored snapshots.
- [ ] `tests/test_persistence.py::test_verify_machine_hash_false_allows_drifted_restore`.
- [ ] `tests/test_persistence.py::test_nested_actor_snapshots_carry_their_own_version` — covers the `_persist_actors` re-emission path.
- [ ] `docs/_guide/snapshots.md` documents the version field, the bump policy, `machine_hash`, and a migration example.

## Related

- LC-23 (grouped): semantic drift at a stable state id restores silently — the concrete failure a `machine_hash` prevents.
- LC-50 (grouped): the snapshot cannot answer "how did this order get here?" — `taken_at` and `recent_transitions` belong in the same payload change.
- LC-25 (grouped): `get_snapshot()` hardcodes `indent=2`.
- LC-19 / LC-20: the other two halves of the restore story (dormant invokes, dropped timers).

## Verification

Independently verified on 2026-09-15.

- **Repro run:** `repro/LC-21_no-snapshot-schema-version.py` executed in a fresh process against a clean `pip install -e .` checkout; exit code **1** (fails against the library today). The "Observed behaviour" block above matches the real output of that run.
- **Library:** xstate-statemachine 0.7.0, commit `42612cf`; Python 3.13.7; Windows-11-10.0.26200-SP0.
- **Root cause:** every cited `file:line` was opened and confirmed to contain the quoted code.
- **XState claims:** checked against the live stately.ai pages cited in the Expected section.
- **Duplicates:** `gh issue list --state all` shows one unrelated issue (#17, camelCase action auto-discovery); this is not a duplicate.
