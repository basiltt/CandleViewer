# Verify summary — main@5e07ba8

Re-verification pass over all 19 `*.result.md` files. For each PARTIAL/NOT-FIXED
finding, the corresponding repro script was independently re-run in a fresh
process this pass (commands and exit codes below) to confirm the result.

## #31 — relative dot-target: engine parity for unresolvable targets
**Classification:** FIXED. All 5 criteria pass, including the previously
reopened criterion 4 (both engines now produce the identical `StateNotFoundError`
surface under `strict_targets=False`).
**Disposition:** confirm-closed.

## #77 — sync macrostep budget: overflow observability, per-chain scope, completions
**Classification:** FIXED. Previously-reopened criterion 6 ("overflow raises
rather than silently discarding") now met — `RunawayChainError` on receipt,
`on_event_dropped(reason="chain_budget")` fires, machine stays `running`.
**Disposition:** confirm-closed.

## #79 — system-event exemption by provenance, not name-prefix
**Classification:** FIXED. Previously-reopened criterion 8 (provenance not
forgeable, survives snapshot) now met via identity-sentinel check + v2 snapshot
layout round-trip.
**Disposition:** confirm-closed.

## #84 — `Receipt.deferred`: distinguishing a deferred event from a genuine no-op
**Classification:** FIXED. All criteria pass; pinning tests present.
**Disposition:** confirm-closed.

## #85 — provenance not forgeable, `Event.system` read-only
**Classification:** FIXED. All 5 acceptance criteria pass (no public `system=`
constructor kwarg, sentinel not reachable via copy/deepcopy/pickle/`replace`).
**Disposition:** confirm-closed.

## #86 — snapshot schema / provenance survives restore
**Classification:** FIXED, with one documented out-of-scope residual (a v2
snapshot loaded by pre-fix 0.8.0 code silently drops `data`/`error` payload
rather than raising — a downgrade-compatibility gap not covered by #86's
acceptance criteria).
**Disposition:** confirm-closed.

## #87 — pending `ErrorEvent`/`DoneEvent` preserved through snapshot round-trip
**Classification:** FIXED (evidence folded into #86.result.md). All 4 criteria
pass.
**Disposition:** confirm-closed.

## #88 — runaway-chain guard scoped per-chain
**Classification:** FIXED.
**Disposition:** confirm-closed.

## #89 — `sync=` compat shim: `**kwargs` clock not treated as consent
**Classification:** FIXED. All 5 criteria pass; `_accepts_kwarg` now excludes
`VAR_KEYWORD` from counting as explicit `sync` support.
**Disposition:** confirm-closed.

## #90 — `max_iterations` budget extended to action-side `send()` on async engine
**Classification:** FIXED. All 4 criteria pass; async self-`send()` now routes
through `_internal_queue`/`_raise_depth` and trips the same per-chain budget.
**Disposition:** confirm-closed.

## #91 — alias-ambiguity guard doesn't fire for its own documented example
**Classification:** PARTIAL. Core contract (criteria 1, 2, 4) is fixed: design
(a) chosen — exact-match precedence retained, plus a new `UserWarning` when a
*different* callable is also registered under a normalizing-equal spelling.
Unmet criterion 3, quoted from the issue's Expected section: *"Independently,
the config side should be checked: two required names that normalise equal and
resolve to one callable should **at least warn**."* `resolve_aliases` only
inspects the registry (`by_key`), never the set of required names requested by
the config, so this config-side duplicate-name check was never implemented.
Re-ran `91_alias_shadow_warning.py` fresh: exit 0, output confirms
`produced UserWarning(s): []` for the two-config-names-one-callable case,
i.e. the gap is real and reproduced.
**Disposition:** REOPEN (scoped narrowly to the unmet config-side check; the
core alias-ambiguity fix itself is confirmed correct and should not be
re-litigated).

## #92 — `create_machine` registry mutation / retroactive rebinding
**Classification:** FIXED. All 5 criteria pass (machine-owned `copy.copy()`
of `MachineLogic`, no cross-machine alias-key leakage, ambiguity guard still
trips for a second machine from the same shared logic, no retroactive
rebinding).
**Disposition:** confirm-closed.

## #93 — `logic_modules`/`logic_providers` ambiguity rule
**Classification:** FIXED (per file's own statement that residual notes found
are not reopening #93's acceptance criteria).
**Disposition:** confirm-closed.

## #94 — completions never discarded by the runaway-chain guard
**Classification:** FIXED. Reaches `m.done`, matching prior verdict.
**Disposition:** confirm-closed.

## #95 — library no longer reads deprecated `ErrorEvent.data`
**Classification:** FIXED for the issue's own claim; PARTIAL only against the
broader (non-#95) task framing of "`-W error::DeprecationWarning` passes across
the whole public surface" — a framing goal, not one of #95's own acceptance
criteria. Unmet (broader-framing) item, quoted: *"library no longer reads
`ErrorEvent.data`, so `-W error::DeprecationWarning` CI passes"* is true only
for the `ErrorEvent.data` deprecation specifically — 8 pre-existing,
unrelated test failures remain when running the whole suite under that flag,
caused by tests that exercise the (separate, pre-existing, slated-for-1.0-removal)
relative-dot-target sibling-fallback `DeprecationWarning` without suppressing it.
Re-ran `95_no_self_deprecation.py` under `-W error::DeprecationWarning` fresh:
exit 0, `ALL CRITERIA PASS`, zero `DeprecationWarning`s raised for the
`ErrorEvent.data` path specifically — confirms #95's own 3 criteria are all
met.
**Disposition:** confirm-closed for #95 itself (no unmet criterion of #95's
own remains). The whole-suite `-W error` gap is a separate, low-severity,
pre-existing issue outside #95's scope — not a reopen of #95, but worth its
own ticket if desired (not filed here as it's out of scope for this batch).

## #96 — `_resolve_event_spec` always yields a dict payload for `ErrorEvent`
**Classification:** FIXED. All criteria pass.
**Disposition:** confirm-closed.

## #97 — `escalate` mints an `ErrorEvent`
**Classification:** FIXED. All 3 criteria pass.
**Disposition:** confirm-closed.

## #98 — strict mode rejects forged engine-shaped names
**Classification:** FIXED. All 4 criteria pass, including all 11 previously
forgeable names now raising `UnknownEventError`, real engine events still
exempt, static `on`-key validation unaffected.
**Disposition:** confirm-closed.

## #99 — `SyncInterpreter` onError for a failed invoked child machine
**Classification:** PARTIAL/NOT-FIXED for criterion 4. Sync-side fix (criteria
1-3) is correct and complete. Unmet criterion, quoted: *"The unhandled case is
decided and documented: EITHER both engines escalate, OR both park — not one of
each"* — sync now fails the parent (`status: error`) on an unhandled invoked
child-machine failure, but the async engine's `_deliver_invoked_completion`
(`interpreter.py:2039-2073`) still has no `_has_error_handler`/`_fail()` call in
its `status == "error"` branch, unlike the callable-service path
(`_invoke_service_task`, ~line 1858) in the same file. Re-ran
`99_sync_child_onerror.py` fresh: exit 0 but `ALL PASS: False`; verbatim
confirms sync unhandled case now correctly shows `status: error error:
ValueError('child boom')` while async unhandled case still shows
`status: running error: None` — the parent parks forever. This is the same
asymmetry #99 was filed to close, now reproduced on the opposite engine.
**Disposition:** REOPEN (or file a scoped follow-up against
`Interpreter._deliver_invoked_completion` specifically — the fix is
mechanical: mirror `_invoke_service_task`'s `_has_error_handler`/`_fail`
pairing).

## Items requiring REOPEN
- **#91** — config-side duplicate-name warning (criterion 3) not implemented.
- **#99** — async invoked-child-machine failure path (`_deliver_invoked_completion`)
  still parks silently on unhandled error; only the sync side was fixed.

## Items confirm-closed
#31, #77, #79, #84, #85, #86, #87, #88, #89, #90, #92, #93, #94, #95 (own
criteria), #96, #97, #98.
