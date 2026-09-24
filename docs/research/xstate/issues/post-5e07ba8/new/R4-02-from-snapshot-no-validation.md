---
r4: R4-02
title: "Bug: from_snapshot() performs no validation and leaks untyped exceptions on malformed snapshots"
labels: [bug, severity/medium, area/persistence, area/validation]
severity: Medium
repro_script: repro/R4-02_from_snapshot_no_validation.py
commit: 5e07ba8
python: 3.13.7
verified: true
---
## Summary

`Interpreter.from_snapshot()` / `SyncInterpreter.from_snapshot()` accept a
persisted snapshot with no legality checks on `status`, `context`, or the
rebuilt active-state configuration, and several malformed shapes escape
the library's documented `except XStateMachineError` catch-all as bare
`KeyError` / `AttributeError`. Filed as Blocker in the original register
row; downgraded to Medium in the final verdict pass because the pure
"accepts garbage silently" sub-case (status/context) is a data-integrity
defect rather than an availability one, while the untyped-exception
sub-case is a documented-contract violation. The genuinely Blocker
sub-case — an **empty configuration** restoring as a healthy, permanently
inert interpreter — is filed separately as R4-01 (mid-macrostep torn
snapshot); this issue covers the remaining validation gaps and the
untyped-exception leaks that make every one of them possible.

## Environment

- Commit: `5e07ba8` (xstate_statemachine 0.8.1 unreleased; `__version__` reports 0.8.0)
- Python: 3.13.7, Windows 11
- Editable install of the library under a project-local venv (`.venv-main`)

## Minimal reproduction

```python
# -*- coding: utf-8 -*-
"""R4-02: `from_snapshot()` performs no configuration-legality, status, or
context validation, and leaks raw builtin exceptions (KeyError/TypeError/
AttributeError) for malformed persisted-snapshot shapes instead of the
library's documented `XStateMachineError` catch-all.

Standalone, derived from battle-5e07ba8/fuzz/repros.py::d7 and
battle-5e07ba8/persistence/t3_probes.py::probe_corrupt (P7).

Exits 1 (defect present) if either:
  (a) a snapshot with an EMPTY configuration is accepted and produces a
      "running", healthy-looking interpreter with no active states, or
  (b) any of a set of malformed snapshot fields (status, context type,
      pending_events shape) escapes as a bare builtin exception instead of
      XStateMachineError.
Exits 0 once both are fixed.
"""
from __future__ import annotations

import copy
import json

from xstate_statemachine import SyncInterpreter, XStateMachineError, create_machine

CFG = {
    "id": "m",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}},
}


def main() -> int:
    machine = create_machine(CFG)
    i = SyncInterpreter(machine)
    i.start()
    snap = i.get_persisted_snapshot()

    findings = []

    # --- (a) empty configuration is silently accepted -----------------
    s_empty = copy.deepcopy(snap)
    s_empty.update({"configuration": [], "state_ids": []})
    r = SyncInterpreter.from_snapshot(
        json.dumps(s_empty, default=str), machine, verify_machine_hash=False
    )
    empty_accepted = r.status == "running" and sorted(r.current_state_ids) == []
    print(
        f"OBSERVED (a): empty configuration -> status={r.status!r} "
        f"states={sorted(r.current_state_ids)}"
    )
    print("EXPECTED (a): a typed XStateMachineError (e.g. InvalidConfigError)")
    findings.append(empty_accepted)

    # --- (b) malformed fields leak bare builtin exceptions --------------
    mutations = {
        "status='zzz'": {"status": "zzz"},
        "status=5": {"status": 5},
        "context=42": {"context": 42},
        "pending_events=[{}]": {"pending_events": [{}]},
        "pending_events=[null]": {"pending_events": [None]},
        'state_ids=[["m.a"]]': {"configuration": None, "state_ids": [["m.a"]]},
    }
    untyped = []
    for name, mut in mutations.items():
        s = copy.deepcopy(snap)
        s.update(mut)
        try:
            SyncInterpreter.from_snapshot(
                json.dumps(s, default=str), machine, verify_machine_hash=False
            )
            outcome = "ACCEPTED (no validation)"
        except XStateMachineError as exc:
            outcome = f"typed {type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001
            outcome = f"UNTYPED {type(exc).__name__}: {exc}"
            untyped.append(name)
        print(f"OBSERVED (b) {name}: {outcome}")
    print("EXPECTED (b): every malformed field raises an XStateMachineError subclass")

    defect_present = empty_accepted or len(untyped) > 0
    print(
        f"\nVERDICT: empty_config_accepted={empty_accepted} "
        f"untyped_escapes={untyped}"
    )
    return 1 if defect_present else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Observed behaviour

```
OBSERVED (a): empty configuration -> status='running' states=[]
EXPECTED (a): a typed XStateMachineError (e.g. InvalidConfigError)
OBSERVED (b) status='zzz': ACCEPTED (no validation)
OBSERVED (b) status=5: ACCEPTED (no validation)
OBSERVED (b) context=42: ACCEPTED (no validation)
OBSERVED (b) pending_events=[{}]: UNTYPED KeyError: 'type'
OBSERVED (b) pending_events=[null]: UNTYPED AttributeError: 'NoneType' object has no attribute 'get'
OBSERVED (b) state_ids=[["m.a"]]: UNTYPED AttributeError: 'list' object has no attribute 'split'
EXPECTED (b): every malformed field raises an XStateMachineError subclass

VERDICT: empty_config_accepted=True untyped_escapes=['pending_events=[{}]', 'pending_events=[null]', 'state_ids=[["m.a"]]']
```
(exit code 1 — defect present)

## Expected behaviour

The library documents `XStateMachineError` as the catch-all for engine
errors (used throughout its own public API and error hierarchy in
`exceptions.py`). Restoring a snapshot is a first-class, documented
persistence API (`docs` on `from_snapshot`), so a malformed/corrupted
persisted blob should surface as a typed, catchable member of that
hierarchy — e.g. `SnapshotDriftError` or `InvalidConfigError` — never a
bare `KeyError`/`AttributeError`/`TypeError` from internal field access.
Per the library's own restore-time hash/version checks
(`persistence.check_version`, `persistence.check_identity`), the intent is
clearly to validate a restored snapshot defensively; the validation simply
stops short of `status`, `context` shape, and event-record shape.

## Root cause analysis

- `base_interpreter.py:1216` — `interpreter.status = snapshot["status"]` is
  assigned verbatim with no membership check against the valid status
  enum.
- `base_interpreter.py` restore path builds `_active_state_nodes` from
  `configuration`/`state_ids` with no non-empty / one-leaf-per-region
  check (the empty-configuration sub-case, shared root cause with R4-01).
- `events.py:305` `restore_event()` does `etype = record["type"]` with no
  shape guard before it — a `pending_events` record that is `{}` or
  `None` throws a bare `KeyError`/`AttributeError` instead of being
  wrapped.
- `context` is merged with `isinstance(interpreter.context, dict) and
  isinstance(restored, dict)` (`base_interpreter.py` ~1195) — when
  `restored` (from the snapshot) is not a dict, the `else` branch assigns
  it verbatim (`interpreter.context = restored`), so `context=42` is
  silently accepted as the live context.
- `json.JSONDecodeError` is wrapped at the initial decode step
  (`persistence.py`), but no subsequent field read from the decoded dict
  is guarded, so the type of exception a corrupt blob raises depends
  entirely on which field happens to be touched first.

## Impact

For general users, any process that persists snapshots to an external
store (a queue, DB row, cache) and later fails to fully validate/guard
that store is exposed to un-typed, unexpected exception types at
`from_snapshot()` call sites that only catch `XStateMachineError` — this
breaks the library's own documented exception-handling contract. In the
adopting project's concrete order-management scenario, a snapshot store
with any external write path (a bad migration, a stale schema version, a
manual DB edit) can produce a restored order interpreter with a bogus
`status` or a non-dict `context`, and that interpreter will happily keep
running and matching events with garbage state instead of failing loudly
at restore time.

## Proposed fix

Add a validation pass at the top of `from_snapshot()`, after `upcast()`
and before any field is applied to the new interpreter instance:
- `status` must be one of the documented status values; otherwise raise
  `SnapshotDriftError` (or a new `InvalidSnapshotError`).
- `context` must be a mapping (or `None`); otherwise raise.
- The rebuilt active-state configuration must be non-empty, with exactly
  one leaf per parallel region (shared fix with R4-01).
- Every `pending_events` / `deferred` record must be a mapping containing
  a `type`; add an `else: raise` to `restore_event()`'s `kind` dispatch so
  no branch can silently fall through to a raw field access.

This is backward compatible: well-formed snapshots (the only kind the
library itself ever produces) are unaffected; only malformed/corrupted
blobs newly raise a typed error instead of either succeeding silently or
raising an untyped one.

## Acceptance criteria

- [ ] `from_snapshot()` raises `XStateMachineError` (or a named subclass)
      for: empty configuration, non-enum `status`, non-mapping `context`,
      and any malformed `pending_events`/`deferred` record shape.
- [ ] `tests/test_persistence_validation.py::test_from_snapshot_rejects_malformed_status`
- [ ] `tests/test_persistence_validation.py::test_from_snapshot_rejects_non_mapping_context`
- [ ] `tests/test_persistence_validation.py::test_from_snapshot_rejects_malformed_pending_events`
- [ ] `tests/test_persistence_validation.py::test_from_snapshot_rejects_empty_configuration`
- [ ] `repro/R4-02_from_snapshot_no_validation.py` exits 0

## Related

- Register source ids: `D-persistence-4`, `D-fuzz-6`, `D-fuzz-7`
- Shares root cause / fix surface with R4-01 (empty-configuration
  sub-case is R4-01's Blocker scenario) and R4-13 (settling-budget orphan
  configuration also round-trips inconsistently through this same restore
  path)

## Verification

- Date: 2026-09-19; Python 3.13.7; commit `5e07ba8`.
- Re-ran `repro/R4-02_from_snapshot_no_validation.py` in a fresh process
  (60s cap): output matched the Observed block verbatim; exit code `1`.
- Confirmed root cause at `src/xstate_statemachine/base_interpreter.py:1202`
  (`interpreter.status = snapshot["status"]`, no membership check),
  `:1195-1201` (context merge falls through to verbatim assignment for a
  non-dict `restored`), and `:1208-1220` (configuration rebuild from
  `configuration`/`state_ids` with no non-empty check) — line numbers as
  cited (draft's `~1216`/`~1195` land inside the same statements). Also
  confirmed `events.py` `restore_event()`'s field access has no shape guard
  before the malformed-record cases raise bare `KeyError`/`AttributeError`.
- No external XState/SCXML claim to check here (this issue is about the
  library's own documented `XStateMachineError` contract, not spec
  conformance).
- Searched `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 120 --search "snapshot"`: closest matches are #45 (missing
  version/identity check, already fixed), #46 (context merge aliasing,
  already fixed), #87/#86 (dropped events/provenance) — none cover
  status/context-type/pending-events validation or the untyped-exception
  leak; no duplicate found.
- No project name/label leakage found in the file.
