# Independent recheck — #142–#146 (main @ cec108b)

All five re-verified against a fresh checkout; each claim in
CHANGELOG.md `[Unreleased]` was read, the corresponding code paths were
inspected, the existing pins in `tests/test_round5_findings.py` were
re-run in isolation, and independent probes were written to hunt for
false positives (test claims something the code doesn't actually
guarantee) and false negatives (a stale/weak probe that would pass on
a still-broken build).

## Method
- `pytest tests/test_round5_findings.py -k "ConfigurationLegality or InvokeCycleTerminates or FailPolicyStops or HostileSnapshotFieldsAreTyped"` → 12/12 pass.
- Read `_configuration_is_legal` (base_interpreter.py:1222), its two call
  sites (write-side `get_persisted_snapshot`, read-side `from_snapshot`
  restore path at ~1632), `persistence.check_version`/`check_shape`
  (typed #146 guards), the sync-engine chain-budget code
  (`sync_interpreter.py:~840-895`) and its async mirror
  (`interpreter.py:~1500-1515`), and `TestFailPolicyStops` /
  `actionErrorPolicy: "fail"` handling.
- Wrote `probe_144_async.py` / `probe_144_async_count.py` to check
  whether the async engine independently bounds the same nested-invoke
  conservative cycle that #144 fixes on the sync engine.

## #142 — parallel torn-region snapshot (any-leaf → exactly-one-leaf-per-region)
`_configuration_is_legal` is genuinely recursive (parallel: every
non-history region active+legal; compound: exactly one active+legal
child; atomic/final: legal). `TestConfigurationLegality.test_predicate_cases`
exercises all four branches (legal parallel, region-with-no-leaf,
compound-with-two-children, orphan-leaf, empty) directly against the
predicate, and `test_parallel_region_mid_step_snapshot_is_refused` drives
a real async mid-step race and confirms `SnapshotMidStepError` fires
mid-step and a plain snapshot succeeds once settled. No false positive:
the predicate is called with real `StateNode`/`_active_state_nodes`
objects, not mocks, and the illegal cases actually flip the boolean.
**CONFIRMED.**

## #143 — leafless-region restore
`test_restore_refuses_root_only_and_leafless_region` strips a real
persisted-snapshot's `configuration` (root-only, and a parallel region
missing its leaf) and asserts `SnapshotCorruptError` from both engines'
`from_snapshot`. Traced the call site (`base_interpreter.py:~1632`) —
it runs `_configuration_is_legal()` against the *restored* config before
accepting it, same predicate as #142's write-side check, so read/write
legality is provably the same rule, not a parallel reimplementation that
could drift. **CONFIRMED.**

## #144 — nested-invoke conservative cycle vs. `maxIterations`
Changelog text scopes this explicitly to **the sync engine**
("Two livelocks / budget faults on the sync engine ... hung `start()`
... #144"). `TestInvokeCycleTerminates.test_start_returns_for_every_budget`
only drives `SyncInterpreter` — correctly matching the documented scope.
Independent probe: the identical nested-invoke config run on the async
`Interpreter` engine does **not** trip `RunawayChainError` — `svc` was
invoked 34,256 times in 2s with `maxIterations=10` and `status` stayed
`"running"` with `last_error=None` (see `probe_144_async_count.py`).
Root cause: a service's `done.invoke` on the async engine is delivered
via `_deliver_priority`/`self.send()` from a *separate asyncio task*, not
from inside a user action on the interpreter's own task, so
`_issued_from_own_action()` is `False` and the event never increments
`_raise_depth` — the async budget instrumentation simply doesn't see this
shape of cycle. This does **not** contradict the changelog claim (which
never claims async coverage), and it doesn't reproduce the sync bug's
symptom (a hung, non-returning `start()` blocking the whole process) —
the async loop keeps yielding and `start()` returns. It is a real gap
worth a follow-up issue but is out of scope for grading #144 as written.
**CONFIRMED** (as scoped to the sync engine; async-engine gap flagged
separately, not a false-positive in the existing pin).

## #145 — `actionErrorPolicy: "fail"` stops the machine
`TestFailPolicyStops` checks both engines end with `status="stopped"`,
empty `current_state_ids`, a `TransitionFailedError` with the original
`RuntimeError` as `__cause__`, and a `get_persisted_snapshot()` that
round-trips to `("stopped", [])`; a control test confirms
`actionErrorPolicy: "rollback"` is unaffected; and
`test_check_shape_rejects_error_without_message` confirms the read-side
#145 check (`status=="error"` requires a non-empty `error`). Traced
`check_shape` (persistence.py:208-212) — the rule is symmetric with the
`"fail"`→`"stopped"` write-side behaviour and doesn't accidentally reject
legitimate `"error"` snapshots that do carry a message (exercised by
`test_error_snapshot_from_failed_service_still_round_trips`, a
service-failure path unrelated to `actionErrorPolicy`). **CONFIRMED.**

## #146 — hostile snapshot fields are typed
`check_version`/`check_shape` were read line-by-line: `version` rejects
non-int-coercible/bool values before the `int()` cast can raise bare
`TypeError`/`ValueError`; `status` is checked `isinstance(str)` *before*
the `in _VALID_STATUSES` membership test, closing the unhashable-status
`TypeError` (list/dict) that a naive `set` check would raise; `context`,
`state_ids`, `configuration`, `pending_events`/`deferred` (with per-record
`type` re-validated, folding in #158), `history`, `actors`, `system` are
all shape-checked before any reader does `.items()`/indexing on them.
`TestHostileSnapshotFieldsAreTyped.test_every_field_times_every_scalar`
is a full cross-product (12 fields × 7 hostile scalars = 84 cases) that
only requires *some* `XStateMachineError` subtype, not silence — ran it
standalone and it passes with no bare `TypeError`/`AttributeError`
escaping. **CONFIRMED.**

## Summary
| # | Final class | One-line |
|---|---|---|
| 142 | CONFIRMED | Legality is genuinely recursive (parallel/compound/atomic), pin exercises all branches directly against real state nodes. |
| 143 | CONFIRMED | Read-side restore reuses the exact same `_configuration_is_legal` predicate as the write side — no drift possible. |
| 144 | CONFIRMED (sync-scoped) | Fix and changelog correctly scope to the sync engine; async engine has an independent, undocumented gap (doesn't hang, but never trips the budget) — flagged, not a false positive. |
| 145 | CONFIRMED | `"fail"` → stopped/cleared/typed-error is symmetric on both engines and round-trips through the persisted snapshot; `"rollback"` unaffected. |
| 146 | CONFIRMED | Every hostile top-level field (7 scalar shapes × 12 keys) is caught by a typed `SnapshotCorruptError` before any reader can raise a bare Python exception. |
