# 26 — Verdict: `xstate-statemachine` @ `main` commit `3c527b0` (unreleased 0.8.1)

**Build under verdict.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `3c527b0d04c0d2d0ebb565af7e9e905f7178f620` — the merge of PR #83
(`fix/0.8.1-remaining-issues`, functional commit `2459c82`) on top of `5327ba6`.
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`. **`__version__` still reports
`0.8.0`.** This build is identified **by commit, never by version string**, here
and in every downstream reference (`run_gate.py` baseline, ADR-0016 pin, E50
chores, the CI assertion).

**Date:** 2026-09-18. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro 10.0.26200.
**Interpreter for every run:** `_ref/xstate-statemachine/.venv-main/Scripts/python`
with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Baseline replaced:** `22-verify-main-verdict.md` (`main@5327ba6`).
**Inputs:** `23-verify-3c527b0-findings.md` (re-test of the 13 `5327ba6`
findings), `24-verify-3c527b0-gate.md` (gate + suite + benchmarks),
`25-verify-3c527b0-diff-review.md` (`5327ba6..3c527b0` source diff, G-1…G-12),
`issues/verify-main-3c527b0/{43,79,80}.result.md` (the three per-issue
verifications for this commit).

No library source was modified. No `git` command was run in the CandleViewer
repository. GitHub was read-only throughout this phase.

---

## 0. Bottom line

**PR #83 did three good things and introduced three High defects on the
persistence path. The gate decision moves for the first time since 0.7.0.**

- **The three headline fixes are real.** #43 (one asyncio task per invoked
  child), #79 (provenance-based system events) and #80 (a dedicated
  `ErrorEvent`) all verify against their own acceptance criteria — 7/7, 10/10
  and 8/8 respectively. #43 in particular is excellent engineering: the
  `children + 1` budget is independently reproduced at n=1/10/50, 1 000
  spawn/complete cycles leak nothing, and the exit-vs-completion race is
  handled correctly under a ±2 ms scan. The gate's LC-28 check flips **FAIL →
  PASS**. The library's own suite grows to **3 242 passed / 13 skipped / 0
  failed** at **90%** coverage.
- **No regressions in the classical sense.** Nothing that passed at `5327ba6`
  fails at `3c527b0` at the gate, suite, bench, probe or per-issue-script
  level. Twelve of the thirteen `5327ba6` findings are unchanged; the
  thirteenth (M-5) had its premise removed by #79 exactly as the CHANGELOG
  predicted.
- **But two features that shipped in the same release met each other on the
  snapshot boundary and neither was taught about the other.** **G-2**:
  provenance is not persisted, so a restored `escalate` event comes back as
  user traffic and fails a machine with `onUnhandled: "error"` — a behavioural
  regression *created by this commit*, in the sense that the `5327ba6`
  name-based rule gave the same answer before and after a restore and the
  `3c527b0` provenance rule does not. **G-3**: a pending `ErrorEvent` is
  silently dropped by `get_persisted_snapshot()` because the inbox filter is
  `isinstance(e, Event)` and `ErrorEvent` is a `NamedTuple` — #80 routed
  *every* service and child failure through a class that falls through #47's
  mailbox-persistence guarantee. **G-1**: `Event.system` is a public,
  user-settable dataclass field; `send(Event("X", system=True))` bypasses
  `strict`, `onUnhandled` and `"*"` on both engines and through
  `send_threadsafe`.
- **M-1 is STILL-PRESENT and its proposed mitigation is now known to be
  unsound.** The receipt of an event parked by `onUnhandled: "defer"` still
  resolves `changed=False, error=None`, and `Receipt` is still
  `('state_ids', 'changed', 'error')`. Worse than at `5327ba6`: the
  `deferred_count` discriminator the `22-` verdict proposed as our CV-C06
  mitigation **reads `0` at the caller's `await` point for both the deferred
  and the genuinely-null case** (`probes/main-3c527b0/p3_m1_deep.py` V3). The
  mitigation must be re-derived before CV-C06 can rely on it.
- **Gate: 7 High open → decision-table row 5 → DEFER for the library-adoption
  half.** This is the first time the table has moved off "ADOPT with
  constraints" since the 0.8.0 run, and it is not a judgement call: rows are
  applied in order and row 5 (`> 5 High open`) now matches on the merits. The
  correct response is **not** to re-weight the findings; it is to get G-2 and
  G-3 fixed before 0.8.1 tags, at which point the count returns to 4 and row 6
  applies again. **Our in-house shim (Part 2 of ADR-0016) is unaffected and
  remains the execution path.**

---

## 1. Per-issue disposition — the 16 issues open before PR #82/#83

Every issue in the register that was open before the #82/#83 wave, re-verified
on `3c527b0`. Evidence column cites `issues/verify-main-3c527b0/<GH#>.result.md`
where a fresh script exists for this commit, otherwise the `5327ba6`
verification carried forward under `23-verify-3c527b0-findings.md`'s
no-regression finding.

**Action vocabulary.** *confirm closed* = every acceptance criterion is met by
code on this commit; if the maintainer closed it on the #82/#83 merge, that
closure is correct and our comment confirms it. *REOPEN* = at least one
acceptance criterion is **genuinely unmet by code**, not by wording, naming or
test-file paths.

| GH# | LC / N | Classification on `3c527b0` | Residual | Action |
|---|---|---|---|---|
| **#27** | LC-01 (action `raise` commits transition) | **FIXED-OPT-IN** (unchanged) | Cosmetic only: `InvalidConfigError` not `ValueError`; `failed_actions` surfaced via `on_transition_failed` + `last_transition_ok` rather than on `on_transition`. **F-7** rides along: the checkpoint-skip predicate does not model `always`/`on` action lists on the *target* — verified safe in the case tested, narrower than the invariant it upholds. | **confirm closed** (+ F-7 ride-along comment) |
| **#31** | LC-07 (relative dot-target silent no-op) | **PARTIAL** (unchanged) | Acceptance criterion #4 (**engine parity**) is still unmet by code under the documented `strict_targets=False` opt-out: `SyncInterpreter` raises `StateNotFoundError` at `send()` time, async `Interpreter` silently no-ops. Everything else in the issue — child-first `.child` resolution, deprecation-warned sibling fallback, once-per-`(source,target)` throttling, multi-segment targets, build-time rejection of unresolvable static targets — is confirmed working. **F-10** rides along (`_SIBLING_FALLBACKS_WARNED` unbounded module-global). | **REOPEN** (fix still required: runtime engine parity under `strict_targets=False`; suggest re-scoping the issue to that one criterion) |
| **#37** | LC-43 (`WrongThreadError` message) | **FIXED** | None. The stale repro script is ours, not a library gap. | **confirm closed** |
| **#39** | LC-42 (`send` fire-and-forget, no answer) | **FIXED** | Reserved-payload-key `DeprecationWarning` and the docs page not independently re-checked; FIFO-among-priority not isolated from aggregate latency. Neither is an unmet criterion. | **confirm closed** |
| **#43** | LC-28 (idle actor costs two tasks) | **FIXED** on this commit | None. All 7 criteria PASS (`43.result.md`): `_ACTOR_POLL_INTERVAL` gone, 50 idle children add exactly 50 tasks over baseline (budget 51), zero stray `loop.call_later` in a 200 ms idle window with 20 children, `onDone` median 0.96 ms, cancellation-on-exit clean. Independently reproduced by the gate's own unchanged LC-28 script (`[1.0, 1.0, 1.0]`, was `[2.0, 2.0, 2.0]`) and by `probes/main-3c527b0/g20_task_budget.py`. **G-9** rides along (the completion-delivery task is created via `_loop_create_task` and registered with neither the `TaskManager` nor a strong reference — latent, 0/300 lost under a GC-hostile probe). | **confirm closed** (+ G-9 ride-along comment) |
| **#44** | LC-19 (restore does not restart invokes) | **FIXED** | `status` still reports `"running"` for a parked restored machine — by design; `has_dormant_invocations` / `pending_invocations()` are the liveness signal, confirmed identical on both engines. | **confirm closed** |
| **#50** | LC-38 (sync interpreter timer threads) | **FIXED** | **F-2** rides along as a separate new issue, not a reopen: the legacy-clock compatibility shim treats a `**kwargs` catch-all as consent to receive `sync=`. That is a defect in the *shim added by #76*, not an unmet criterion of #50. | **confirm closed** |
| **#51** | LC-34 (no strict mode) | **FIXED** for the `send_threadsafe` guardrail + static-`raise` build-time validation; `strict` itself remains **FIXED-OPT-IN** per the issue's own compatibility plan | The reserved-namespace half of the old F-8 residual is **improved** by #79 (`done.review`, `DONE.review`, `error.validation` now all raise `UnknownEventError` on a `strict` machine) but **not closed** — `is_known_event` still exempts by name via `ENGINE_EVENT_SHAPES`, so `done.invoke.NEVER_INVOKED`, `after.party`, `xstate.whatever` and `___xstate_forged` still pass undeclared (**G-7**). **M-6** rides along on #78, not here. | **confirm closed** (G-7 filed as a new issue against #79's mechanism) |
| **#52** | LC-37 (arity misclassification) | **FIXED** | None. 10/10 assertions pass. | **confirm closed** |
| **#60** | LC-57 (two engines duplicate the core algorithm) | **FIXED for every criterion that describes behaviour** | The shared-algorithm half landed at `5327ba6`; the `ErrorEvent` sub-claim (LC-52) **landed in this commit** and is verified 8/8 (`80.result.md`). The gate's LC-57 script still reads FAIL, but its residual is the *architectural framing* of the original issue — a distinct `core/algorithm.py` plus an `ExecutionStrategy` protocol — which was never the implementation path taken and is not a behavioural criterion. Per the reopen rule (code, not cosmetics) that is not grounds to reopen. **G-8** rides along as a new issue: the sync engine still never converts an invoked **child-machine** failure to `onError` (pre-existing, but in scope for the parity claim). | **confirm closed** (let #80's closure carry the `ErrorEvent` half; G-8 filed separately) |
| **#75** | N-1 (`wait=True` receipt `id()` collision) | **FIXED** | None. Re-confirmed on this commit at 500-way concurrency under `rollback` + `defer` + a bounded `RAISE` inbox (`a_receipts.py` A1, still passing, **unaffected by #43's one-task redesign**). | **confirm closed** |
| **#76** | N-2 (sync `after` unreachable in a loop) | **FIXED** | **F-2** (the `**kwargs` shim hole) is a new defect inside this fix, filed separately — the criteria of #76 itself are met. | **confirm closed** (+ F-2 filed as a new issue) |
| **#77** | N-3 (sync macrostep budget clears the queue) | **PARTIAL** (unchanged) | The data-loss defect is genuinely fixed. **Not fixed and genuinely unmet:** the acceptance criteria asked for overflow to **raise**; it is still silent — `send()` returns normally, `status` stays `"running"`, `last_transition_ok` stays `True`, only a log line is emitted. Three defects live in the same code path: **F-1** (High — the `tripped` flag is scoped to the drain, not the chain; one self-feeding `SPIN` starves five later unrelated `WORK` events in the same `send_events()` batch, `INNER handled: 0 of 5`), **F-6** (a sync `done.invoke` is classed self-generated and dropped after a trip; the machine parks), **M-2** (the async engine's `max_iterations` does not bound an action-side `send()`, so the engine-parity claim is inaccurate). **F-9** rides along (a legitimate 1 001-deep chain is cut, and sync/async disagree by one: `s1000` vs `s1001`). | **REOPEN** (fix still required: raise on overflow instead of dropping silently; F-1/F-6/M-2 filed separately) |
| **#78** | N-4 (`send_threadsafe` bypasses strict) | **FIXED** | **M-6** rides along: error precedence across lifecycle phases — before `start()` the strict/schema error and the not-started error race for which surfaces. Cosmetic: the issue names `tests/test_strict_mode.py`, the file is `tests/test_strict.py`. | **confirm closed** (+ M-6 ride-along comment) |
| **#79** | N-8 (`error.*`/`done.*` names invisible) | **FIXED for the reported defect; the replacement mechanism has a hole in the same acceptance criterion** | The reported defect is closed and closed well — a user-sent `done.review` is now matched by `"*"` and `"done.*"`, trips `onUnhandled: "error"`, and is rejected by `strict`; case variants behave identically; engine-minted `done.invoke.*` / `after.*` stay exempt; `escalate` is unaffected. **But acceptance criterion 8 — "`Event.system` is not spoofable" — is met only against the `send(type, payload)` signature, not against the object.** `Event.system` is an ordinary public dataclass field (`events.py:117`), so `send(Event("X", system=True))` is valid, type-checked user code that bypasses `strict`, `onUnhandled` **and** `"*"` on both engines and via `send_threadsafe` (**G-1**). Two further gaps in the same mechanism: provenance is **not persisted**, so restored engine events become user traffic (**G-2**, a behavioural regression against `5327ba6`); and `strict` still exempts by **name** via `ENGINE_EVENT_SHAPES` (**G-7**). Ride-alongs: **G-10** (dead `_SYSTEM_EVENT_PREFIXES` constant whose comment describes the deleted architecture), **G-11** (three tests deleted for the withdrawn build-time warning with no replacement coverage of the new attack surface), **G-12** (`is_system_event` / `system_event` / `Event.system` are undocumented and unexported while `ENGINE_EVENT_SHAPES` is announced in the CHANGELOG but not re-exported). | **REOPEN** (fix still required: criterion 8 — provenance must not be settable from user-constructed `Event`s, and must survive a snapshot; G-1/G-2/G-7 filed separately with repros, G-10/G-11/G-12 as ride-alongs) |
| **#80** | LC-52 (`error.platform.*` delivered as `DoneEvent`) | **FIXED** | All 8 criteria PASS (`80.result.md`), sync/async parity included. Four defects sit around the new type rather than in its criteria, all filed separately: **G-3** (High — a pending `ErrorEvent` is silently dropped by the snapshot), **G-4** (the library trips its own `ErrorEvent.data` `DeprecationWarning` from `plugins.py:435` and `base_interpreter.py:1781`, unfixable by the user, breaking `-W error::DeprecationWarning` CI), **G-5** (`_resolve_event_spec` builds an `Event` whose `payload` is the exception, not a dict), **G-6** (`escalate` is the one failure path not converted). | **confirm closed** (G-3…G-6 filed separately) |
| **#26** | Meta — adoption readiness | — | — | **update** (`issues/post-3c527b0/meta-26.md`, full replacement body) |

**Counts. 13 confirm closed · 3 REOPEN (#31, #77, #79) · 1 meta update.**

Register position after this pass, across the 34 originally-filed issues:
**28 FIXED-DEFAULT · 5 FIXED-OPT-IN · 1 PARTIAL · 0 NOT-FIXED**
(#43 and #60/LC-52 move to FIXED; #31 remains PARTIAL; #77's partial is
re-expressed as the raise-on-overflow criterion; #79 is FIXED-for-the-reported-
defect with a new hole in its own mechanism, tracked as new issues rather than
as a register regression).

---

## 2. Consolidated new findings still present on `3c527b0`

Two independent sources contribute: the 13 findings carried from `5327ba6`
(`23-verify-3c527b0-findings.md`) and the 12 findings from the PR #83 diff
review (`25-verify-3c527b0-diff-review.md`, G-1…G-12).

### 2.1 Deduplication

| Merge | Basis |
|---|---|
| **M-5 residual ≡ G-7** | M-5's build-time-warning limb is obsolete (the warning was withdrawn) and its `strict`-exempts-reserved-prefixes limb is fixed for `done.`/`error.` — what survives is exactly G-7's `ENGINE_EVENT_SHAPES` prefix hole. Filed once, as G-7. |
| **F-8 ⊂ G-7** | Same residual, same repro family. |
| **F-3 ≡ M-4**, **F-4 ≡ M-3** | Carried forward unchanged from the `5327ba6` merge. |
| **M-5's `SYSTEM_EVENT_PREFIXES`-not-extensible limb ≡ G-10** | Vestigial constant; now a dead-code/doc item, not a behaviour item. |

**Canonical set on `3c527b0`: 24 findings — 6 High, 11 Medium, 7 Low.**

### 2.2 The set

| ID | Sev | Area | Defect (one line) | Repro | Disposition |
|---|---|---|---|---|---|
| **M-1** | **High** | `defer` × `wait=True` | A deferred event's receipt resolves `changed=False, error=None`, byte-identical to a true negative; `Receipt` gained no field; `deferred_count` reads `0` at the caller's `await` point in **both** cases. | `new-main/repro/a2_confirm_deferred_receipt.py`, `probes/main-3c527b0/p3_m1_deep.py` | **new issue** |
| **G-1** | **High** | #79 | `Event.system` is a public, user-settable dataclass field; `send(Event("X", system=True))` bypasses `strict`, `onUnhandled` and `"*"` on both engines and via `send_threadsafe`. | `probes/main-3c527b0/g1_forge_system.py`, `g9_sync_parity.py`, `g18_threadsafe_and_detach.py` | **new issue** |
| **G-2** | **High** | #79 × #47 | Provenance is not persisted. A restored `escalate` event comes back as user traffic: `onUnhandled: "error"` fails the machine, `"*"` swallows it. **Behavioural regression against `5327ba6`**, where the name rule gave the same answer either side of a restore. | `probes/main-3c527b0/g3_restore_regression.py`, `g2_snapshot_provenance.py` | **new issue** |
| **G-3** | **High** | #80 × #47 | `get_persisted_snapshot()` filters the inbox with `isinstance(e, Event)`; `ErrorEvent`/`DoneEvent` are `NamedTuple`s and are dropped with no warning and no record. #47's mailbox guarantee now has a hole precisely at failures. | `probes/main-3c527b0/g17_snapshot_drops_errorevent.py` | **new issue** |
| **F-1** | **High** | #77 | The sync overflow `tripped` flag is scoped to the drain, not the offending chain: one self-feeding `SPIN` starves five later unrelated `WORK` events in the same `send_events()` batch (`INNER handled: 0 of 5`). Async does not behave this way. | `new-main/repro/f_tripped_sticky.py` | **new issue** |
| **F-2** | **High** | #76/#50 | The legacy-clock shim treats a `**kwargs` catch-all as consent and hands a 0.8.0-protocol clock an unexpected `sync=`. | `new-main/repro/f_clock_kwargs.py` | **new issue** |
| **M-2** | Medium | #77 | `max_iterations` bounds the `raise` built-in but not an action calling `send()` on its own interpreter; the async engine — the only one CV-C03 permits — has the unbounded shape (112 486 steps in 3 s and still climbing). | `new-main/repro/c14_async_no_send_budget.py` | **new issue** |
| **M-3** (=F-4) | Medium | alias resolution | The ambiguity guard misses its own documented example: two different *config* names that normalise equal bind to different callables and the config still builds. | `new-main/repro/g1b_alias_ambiguity_and_leak.py`, `f_loader_twoname.py` | **new issue** |
| **M-4** (=F-3) | Medium | alias resolution | `create_machine()` / `resolve_aliases` mutates the caller's `MachineLogic` registry in place; aliases accumulate across machines, suppressing the guard and turning a later unrelated build into `InvalidConfigError`. | `new-main/repro/f_pollute.py`, `f_shared_logic.py` | **new issue** |
| **F-5** | Medium | `logic_modules` | The normalised index uses `setdefault`, so duplicate snake/camel implementations in one module resolve by iteration order with no error. | `new-main/repro/f_loader_dup.py` | **new issue** |
| **F-6** | Medium | #77 | A `done.invoke` from a sync service is classed self-generated; after a trip the completion is dropped and the machine parks in the invoking state. | `new-main/repro/f_sticky_invoke.py` | **new issue** |
| **G-4** | Medium | #80 | `ErrorEvent.data`'s `DeprecationWarning` fires from the library's **own** code (`plugins.py:435`, `base_interpreter.py:1781`), unfixable by the user; `-W error::DeprecationWarning` CI now fails on library code. New on this commit (`5327ba6`: `DEPRECATIONS: []`). | `probes/main-3c527b0/g4_plugin_deprecation.py` | **new issue** |
| **G-5** | Medium | #80 | `_resolve_event_spec` normalises an `ErrorEvent` via `.data`, producing `Event(payload=<exception>)`; `Event.payload` is typed `Dict[str, Any]` and `event.payload.get(...)` now raises `AttributeError`. Reachable end-to-end via `sendParent` supervision. | `probes/main-3c527b0/g13_resolve_event_spec_errorevent.py`, `g13b_reachable.py` | **new issue** |
| **G-6** | Medium | #80 | `escalate` is the one failure path not converted to `ErrorEvent` — still a plain `Event` with the error under `payload["error"]`. | `probes/main-3c527b0/g15_escalate_shape.py` | **new issue** |
| **G-7** (⊇M-5, F-8) | Medium | #79/#51 | `strict` still exempts by **name** via `ENGINE_EVENT_SHAPES`: `done.invoke.NEVER_INVOKED`, `done.state.NO_SUCH_STATE`, `error.platform.NOT_A_SERVICE`, `after.party`, `after.9999999`, `xstate.whatever`, `___xstate_forged` all pass undeclared. `send()` already holds the event object at `_check_strict`, so the provenance flag is available there. | `probes/main-3c527b0/g14_strict_shape_residual.py`, `p1_strict_user_system.py` | **new issue** |
| **G-8** | Medium | parity (pre-existing) | `SyncInterpreter` never converts an invoked **child-machine** failure to `onError`; the parent parks in the invoking state, `status='running'`, `error=None`. Async is correct. Pre-existing, but in scope for #80's parity claim and untested on sync. | `probes/main-3c527b0/g16_sync_child_failure.py`, `g8_unhandled_child_failure.py` | **new issue** |
| **F-7** | Medium | #27 | The rollback checkpoint-skip predicate does not model `always`/`on` action lists on the transition's *target*. Verified safe in the case tested; narrower than the invariant it upholds. | `new-main/repro/f_rollback_gap.py` | **ride-along on #27** |
| **M-6** | Low | #78 | `send_threadsafe()` error precedence before `start()`: the strict/schema error and the not-started error race. | `def_threads_dormant_namespaces.py` (D-suite) | **ride-along on #78** |
| **F-9** | Low | #77 | A legitimate 1 001-deep chain is cut, sync/async disagree by one (`s1000` vs `s1001`), and the cut is silent — `status` `"running"`, `last_transition_ok` `True`, no hook. | `new-main/repro/f_chain.py`, `f_parity.py` | **ride-along on #77** |
| **F-10** | Low | `resolver.py` | `_SIBLING_FALLBACKS_WARNED` is an unbounded module-global set keyed `(source.id, target)`. | `new-main/repro/g1b_alias_ambiguity_and_leak.py` | **ride-along on #31** |
| **G-9** | Low | #43 | The completion-delivery task is created via `_loop_create_task` and registered with neither the `TaskManager` nor a strong reference; CPython holds only a weak reference to a running task. Latent — 0/300 lost under a GC-hostile probe. | `probes/main-3c527b0/g11_delivery_task_untracked.py`, `g12_delivery_task_gc.py` | **ride-along on #43** |
| **G-10** | Low | #79 | Dead constant `_SYSTEM_EVENT_PREFIXES` (`base_interpreter.py:275`) with a comment describing the architecture this commit deleted. Zero remaining readers. | grep | **ride-along on #79** |
| **G-11** | Low | tests | Three tests were deleted for the withdrawn build-time warning with no replacement coverage of the new attack surface: neither the forged-`system` bypass (G-1) nor the restore-provenance gap (G-2) has a test. | — | **ride-along on #79** |
| **G-12** | Low | docs | `is_system_event` / `system_event` / `Event.system` are undocumented and unexported; `ENGINE_EVENT_SHAPES` is announced in the CHANGELOG but not re-exported from the package root. A plugin author has no supported way to ask "did the engine mint this?". | — | **ride-along on #79** |

### 2.3 What becomes a new issue

**16 new issues** — every High and Medium with a runnable repro:

| Sev | Count | IDs |
|---|---|---|
| High | 6 | M-1, G-1, G-2, G-3, F-1, F-2 |
| Medium | 10 | M-2, M-3, M-4, F-5, F-6, G-4, G-5, G-6, G-7, G-8 |

**8 ride-along comments** — the Lows and the one Medium (F-7) whose home issue
is being confirmed closed: F-7 → #27 · M-6 → #78 · F-9 → #77 · F-10 → #31 ·
G-9 → #43 · G-10, G-11, G-12 → #79.

Bodies for all sixteen are in `issues/post-3c527b0/<N>.md`; the eight
`5327ba6`-era drafts are carried over from `issues/new-main/` with front-matter
refreshed to this commit and the `candleviewer` label removed.

### 2.4 The two that matter most to us

**G-2 and G-3 are the findings with our name on them.** The order path is
snapshot/restore-based by CV-C08 and reconciles invokes on restore by CV-C07.
G-2 means a machine restored with an `escalate` event in its inbox goes to
`status="error"` where it previously did not; G-3 means a machine can restore
believing an invoke never failed, sit in the invoking state, and never fire
`onError`. Both are *silent* — G-3's filter does not even log. They are the
same failure mode the whole 0.7.0 register was about, reintroduced at a new
boundary by two features that shipped together.

**M-1 remains the order path's gating defect**, and §2.3 item 4 of
`23-verify-3c527b0-findings.md` removed our proposed mitigation. See §4.

---

## 3. Regressions

**One behavioural regression: G-2. Nothing else.**

This is a deliberate narrowing of the `24-verify-3c527b0-gate.md` §4 statement
("no item that passed at `5327ba6` now fails, at any level"), which remains
true as written — G-2 is not caught by any gate, suite, bench or probe row,
because no check existed for "does the exemption rule give the same answer
either side of a snapshot". It was found by reading the diff.

| Level | Delta vs `5327ba6` | Classification |
|---|---|---|
| Gate `verify` (mandated config) | 32/34 → **33/34**; LC-28 FAIL → PASS; LC-57 unchanged FAIL | **Improvement** |
| Gate `verifyM` | 12/15; FAILs LC-07, N-3, N-8 — all pre-triaged residuals | No change |
| Gate `repro` (defaults, informational) | 13/34, same set | No change |
| Probes | PROBE-01 16/20 (A3 A6 A10 A18), PROBE-03 13/17 (C6 C7 C15 C17) | No change, identical set |
| Library suite | 3 234 → **3 242** passed, 13 skipped, **0 failed** | **Improvement** (+9 `test_actor_perf.py`, −1 net elsewhere) |
| Coverage | 90% → **90%** | No change |
| Benchmarks | all nine clean; BENCH-1 rollback-armed 1.56×–2.37× (mean ≈2.03×) vs `5327ba6`'s 2.02×–2.87× (mean ≈2.43×) — noisy, same shortfall, **no source touched on this path** | No change |
| Actor task budget | 2.0 → **1.0** tasks/child at n=2/10/50 | **Improvement** |
| 13 `5327ba6` findings | 12 STILL-PRESENT, 1 (M-5) OBSOLETE-by-design | No change |
| `"*"` matcher vs `error.*`/`done.*` user events | invisible → **visible** (`matched_by_star: ['ordinary', 'error.validation', 'done.review']`) | **Improvement** — retires the substantive half of CV-C15 |
| Deprecation warnings from library code | `[]` → `['base_interpreter.py:1781', 'plugins.py:435']` | **New defect** (G-4), not a test regression |
| **Exemption rule across a snapshot boundary** | same answer either side → **different answer** | **REGRESSION (G-2)** |

No test function was deleted without replacement of the behaviour it covered,
**except** the three tests for the withdrawn build-time reserved-namespace
warning — correct to delete, but the new attack surface they should have been
replaced by is untested (G-11).

---

## 4. Gate decision — `20-adoption-gate.md` §7

### 4.1 The table, walked in order

| Row | Condition | Trips? |
|---|---|---|
| 1 | Any `ERROR` row in the gate output | **No.** `FAIL=27, PASS=59`, zero `ERROR`. Evidence is valid. |
| 2 | Suite fails, or coverage < 86% | **No.** 3 242 passed / 13 skipped / 0 failed; coverage **90%**. |
| 3 | Snapshot format changed while LC-21 open | **No.** LC-21 closed at 0.8.0. The serialised *format* is unchanged — G-2 and G-3 are gaps in **what is put into** it, not in its shape, so this row does not trip on a literal reading. **Flagged:** if G-2/G-3 are fixed by adding a provenance field or an event-class discriminator to the persisted shape, that *will* be a format change and this row will apply at the next gate. |
| 4 | Any filed **Blocker** repro still exits 1 | **No — with the standing asterisk.** All four Blockers closed; LC-01 and LC-03 remain **FIXED-OPT-IN**, and per §9.2 amendment 3 a FIXED-OPT-IN Blocker counts closed only while its option is lint-enforced. `E29-T10` has not shipped, so on a literal reading row 4 still applies **to the order path**. |
| 5 | All Blockers closed; **> 5 High** open | **YES — THIS ROW MATCHES.** High open on `3c527b0`: **LC-07/#31, M-1, F-1, F-2, G-1, G-2, G-3 = 7**. Was 4 at `5327ba6`. |
| 6–9 | — | **Not reached.** |

### 4.2 Decision

```
Gate re-run 2026-09-18 - xstate-statemachine main @ 3c527b0 (unreleased 0.8.1)
DECISION: DEFER (library-adoption half of ADR-0016 Part 3)
          -- CHANGED from ADOPT WITH CONSTRAINTS, CONDITIONAL at 5327ba6
          -- decision-table row 5: 7 High open (bar: <=5)
  verify   : 33/34 primary pass (PRIMARY, mandated config, blocking)
             LC-28 FAIL -> PASS (#43 landed); LC-57 unchanged framing residual
  verifyM  : 12/15 pass (LC-07, N-3, N-8 -- pre-triaged residuals)
  repro    : 13/34 pass at defaults (SECONDARY, informational)
  probes   : identical baseline (A3 A6 A10 A18, C6 C7 C15 C17)
  suite    : 3242 passed, 13 skipped, 0 failed (was 3234/13/0)
  coverage : 90% (unchanged)
  benches  : #43 actor-task budget children+1 CONFIRMED (1.0 tasks/child, was 2.0)
             BENCH-1 rollback-armed 1.56x-2.37x (mean ~2.03x) vs bar >=3.0x
             -- unchanged shortfall, no source touched on this path
             BENCH-2, BENCH-6 still missed
  regressions  : ONE -- G-2 (provenance does not survive a snapshot; the
                 exemption rule now gives different answers either side of a
                 restore, where at 5327ba6 it gave the same answer)
  blockers open: none (LC-01, LC-03 FIXED-OPT-IN -- closed only while
                 CV-LINT-XS1/XS2 enforce the mandated config)
  high open    : LC-07/#31, M-1, F-1, F-2, G-1, G-2, G-3   (7 -- over the bar)
  new findings : 24 canonical (6 High, 11 Medium, 7 Low, 0 Blocker)
                 -> 16 new issues, 8 ride-along comments
  constraints  : CV-C01..CV-C21  (CV-C15 NARROWED; CV-C19, CV-C20, CV-C21 NEW)
  M-1 status   : STILL-PRESENT. Receipt shape unchanged
                 ('state_ids','changed','error'). The CV-C06 deferred_count
                 mitigation proposed at 5327ba6 is NOT SOUND AS SPECIFIED --
                 deferred_count reads 0 at the caller's await point for the
                 deferred case AND the true-negative case.
  path forward : this is a PRE-RELEASE build. Fixing G-2 and G-3 before 0.8.1
                 tags returns the count to 5 High and row 6 applies again.
                 Our in-house shim (ADR-0016 Part 2) is unaffected and remains
                 the execution path; nothing in this verdict changes it.
  decided by   : Architect
```

### 4.3 M-1, stated explicitly

**M-1 is STILL-PRESENT on `3c527b0`, and it got worse for us, not better.**

PR #83 rewrote `_handle_unhandled_event` — the exact function containing the
`defer` branch — for #79, and reworked `interpreter.py` substantially for #43.
The receipt gap survived both untouched. `Receipt` is still
`('state_ids', 'changed', 'error')`; no field carries the defer disposition;
the receipt object is not updated on replay (`p3_m1_deep.py` V4: still
`changed=False` after the event has driven its transition).

The material change is **negative**: the mitigation `22-verify-main-verdict.md`
§3 and §4.2 specified for CV-C06 — *treat `changed=False, error=None` as
inconclusive unless `interpreter.deferred_count` is `0` at the same instant* —
**does not work**. At the caller's `await` point both the deferred case and the
true-negative case read `deferred_count == 0` (`p3_m1_deep.py` V3). The
observation point at which `a2_confirm_deferred_receipt.py` reads
`deferred_count = 1` is inside the macrostep, not at the call site.

**Consequence.** `test_receipt_is_inconclusive_when_deferred` cannot be written
as specified. Either the receipt learns the disposition upstream (the correct
fix, requested in the new issue), or `cv.statechart` must derive an
out-of-band discriminator — e.g. a plugin `on_event_deferred` hook correlated
by event identity, which the library does not currently expose. **Until one of
those exists, the order path has no admissible gate on a `wait=True` receipt,
and no order-path statechart may ship.** This is unchanged in effect from
`5327ba6` and stronger in evidence.

### 4.4 Escape hatch

`20-adoption-gate.md` §8 (partial adoption) is **not** reached — it presupposes
an ADOPT-family decision. The operative position is:

- **ADR-0016 Part 1 (statechart JSON is the contract) and Part 2 (the in-house
  shim executes it)** are binding now and are untouched by this verdict.
- **ADR-0016 Part 3 (the library replaces the shim)** is **DEFERRED**, for the
  first time on a merits row rather than on our own unshipped linter.
- Non-order-path prototyping against the library in a sandbox with no real
  credentials remains permitted (row 4's standing carve-out).

---

## 5. Constraints

### 5.1 Retired by this commit

| Constraint | Basis |
|---|---|
| **CV-C15, case-insensitivity clause only** | **RETIRED.** #79 makes a user event named `error.*`/`done.*` visible to `"*"` and to `"done.*"`, trippable by `onUnhandled`, and rejected by `strict` — **including case variants** (`DONE.review` behaves identically). `E50-T05`'s event-name gate no longer needs to be case-insensitive for those two namespaces. The rest of CV-C15 is **re-scoped, not retired** — see §5.3. |
| **CV-C06, `deferred_count` clause** | **WITHDRAWN AS UNSOUND, not satisfied.** This is not a retirement in the good sense: the clause specified in `22-verify-main-verdict.md` §4.2 cannot be implemented as written (§4.3 above). It is removed from the constraint set and replaced by a hard prohibition until a working discriminator exists. |

### 5.2 Standing (deltas only; anything not listed stands unchanged from `22-verify-main-verdict.md` §4.2)

| ID | Status on `3c527b0` |
|---|---|
| **CV-C01** (mandatory policy block; factory-only construction) | **STANDS.** No library default changed on this commit. |
| **CV-C03** (async `Interpreter` only) | **STANDS, reinforced.** G-8 adds a fourth sync-only gap (a failed invoked child machine never reaches `onError`). Still does not protect us from M-2 or from G-1/G-2/G-3, all of which are async-side. |
| **CV-C06** (`wait=True` for gated decisions) | **STANDS, with its mitigation clause withdrawn.** New wording: *a `wait=True` receipt with `changed=False, error=None` is **inadmissible** as a gate on any machine configured `onUnhandled: "defer"`, and no order-path statechart may ship until M-1 is fixed upstream or `cv.statechart` obtains an out-of-band defer discriminator.* Enforced by **CV-LINT-XS9** (re-purposed from the retired fresh-`Event` rule) and by the absence of an order-path machine in the registry. |
| **CV-C07** (restore reconciles `pending_invocations()`) | **STANDS, strengthened by G-3.** The reconciliation is now load-bearing for correctness, not just for liveness: a snapshot taken while an `ErrorEvent` is in the inbox loses the failure entirely, so the restore-side invoke reconciliation is the **only** thing that can notice. |
| **CV-C08** (snapshots as the JSON string, via `cv.statechart.persistence`) | **STANDS, strengthened by G-2/G-3** — see CV-C20. |
| **CV-C11** (`last_transition_ok` read immediately, or not at all) | **STANDS, reinforced.** F-9 and #77's silent overflow both leave it `True`. |
| **CV-C13** (order path on a dedicated event loop / process) | **STANDS.** BENCH-1 rollback-armed re-measured 1.56×–2.37× (mean ≈2.03×) against the ≥3.0× bar; noisy, unchanged, no source touched on this path. |
| **CV-C15** (no CandleViewer event named `error.*` / `done.*`) | **NARROWED — see §5.3.** |
| **MUST-07** (version pin) | **AMENDED** — §5.4. |
| **MUST-09** (linter + contract suite before the first statechart) | **STANDS.** No longer the *only* gating condition: row 5 now trips on upstream merits. |

### 5.3 CV-C15, re-scoped

**Old rule:** no CandleViewer event may be named `error.*` or `done.*`; the
`E50-T05` gate must be case-insensitive.

**New rule (normative):** no CandleViewer event may be named with any prefix in
`ENGINE_EVENT_SHAPES`:

```python
ENGINE_EVENT_SHAPES = (
    "done.invoke.", "done.state.", "error.platform.",
    "after.", "xstate.", "___xstate",
)
```

**Rationale.** `models.is_known_event` still returns `True` for anything
matching these by prefix (G-7), so a typo'd event in those namespaces is
accepted silently by `strict`. Conversely, plain `done.*` and `error.*` outside
those exact shapes are now fully visible to `"*"`, `onUnhandled` and `strict`
(verified for `done.review`, `DONE.review`, `error.validation`), so the old
blanket ban on `done.`/`error.` is over-broad and its case-insensitivity
requirement is obsolete.

**`E50-T05` must therefore be re-specified**: ban the six `ENGINE_EVENT_SHAPES`
prefixes, case-sensitively (the library matches case-sensitively and so does
the hole), and drop the blanket `done.`/`error.` ban.

### 5.4 New

| ID | Constraint | Enforcement |
|---|---|---|
| **CV-C19** | **No CandleViewer code may construct an `Event` with `system=True`, and no code may trust `is_system_event()` / `Event.system` as a security or routing boundary.** The flag is a public, user-settable dataclass field (G-1) — it is provenance-shaped but not provenance-guaranteed. Any routing decision that must distinguish engine traffic from user traffic does so on our own gateway-stamped envelope, never on the library flag. | **CV-LINT-XS13** (AST: `Event(` with a `system=` keyword); `test_no_forged_system_events` |
| **CV-C20** | **`cv.statechart.persistence` owns the mailbox across a snapshot boundary.** Before `get_persisted_snapshot()` the interpreter must be quiesced (inbox drained, no in-flight `invoke` completion), and on restore every `pending_invocations()` entry is reconciled against the order/exec store before the machine is resumed. The library's snapshot **silently drops** `ErrorEvent`/`DoneEvent` (G-3) and **silently loses** provenance (G-2); neither is detectable after the fact. | `cv.statechart.persistence.snapshot()` asserts `queue_depth == 0 and deferred_count == 0`; `test_snapshot_refuses_non_quiesced_interpreter`; `test_restore_reconciles_every_pending_invocation` |
| **CV-C21** | **Every `onError` action branches on `isinstance(event, ErrorEvent)` and reads `event.error`.** Never `event.data` (deprecated, removed in 0.9), never `event.type.startswith("error.")`, and never `event.payload.get(...)` on an error-shaped event — `_resolve_event_spec` can hand you an `Event` whose `payload` is the exception object itself (G-5). `escalate` is the exception and must be handled by name: it is still a plain `Event` with the error under `payload["error"]` (G-6). | **CV-LINT-XS14** (AST: `.data` on an `onError` handler parameter); `test_onerror_reads_error_not_data`; `test_escalate_payload_shape` |
| **CV-C22** | **CI does not run `-W error::DeprecationWarning` against library code until G-4 is fixed.** The library trips its own `ErrorEvent.data` deprecation from `plugins.py:435` and `base_interpreter.py:1781`; the recommended way to be 0.9-ready currently fails on code we cannot change. Filter by module, not globally. | `pyproject.toml` `filterwarnings` entry with an explicit `# G-4, remove when fixed upstream` comment |

**Constraint set in force: CV-C01…CV-C22**, with CV-C15 narrowed, CV-C06's
mitigation clause withdrawn as unsound, and CV-C19…CV-C22 new.

### 5.5 Version pin

**MUST-07 amended:**

```
xstate-statemachine == 0.8.1        # once tagged
# until then: git commit 3c527b0d04c0d2d0ebb565af7e9e905f7178f620, with sha256
```

Superseding the `5327ba6` pin. Two standing caveats:

1. **`__version__` still reports `0.8.0`** on this commit while the CHANGELOG
   targets 0.8.1. Key every pin, gate baseline, vendored-copy contract test and
   CI assertion on the **commit**. `run_gate.py`'s `BASELINE_COMMIT` is updated
   accordingly (§7).
2. **This pin records what we tested, not what we endorse.** The gate decision
   on this commit is DEFER (§4.2). Do not take the pin as authorisation to add
   the dependency; ADR-0016 Part 3 has not taken effect.

### 5.6 Mandatory configuration block — recomputed

**No library default changed on this commit.** The six-key machine-JSON block
from `17-reeval-0.8.0-verdict.md` §4.1 and `28-statechart-catalogue.md` is
**unchanged and remains normative verbatim**:

```jsonc
"actionErrorPolicy": "rollback",   // "fail" on the invariant machines (B8/B17/B18/B20)
"onUnhandled":       "defer",      // "error" on the control machines (B13/B14/B18)
"guardErrorPolicy":  "raise",
"strictTargets":     true,
"strict":            true,
"spawnBlockingTimeout": 5000
```

The changes are all **outside the machine JSON**, in the factory, the gateway
and the persistence layer:

```python
# cv/statechart/factory.py — state on main @ 3c527b0
logic = MachineLogic(..., strict=True)     # #52 / CV-C18 — one per create_machine()

# cv/statechart/gateway.py
# CV-C19: Event(system=True) is banned. The gateway stamps its own envelope;
#         library provenance is never a routing or trust boundary (G-1).
# CV-C15 (narrowed): reject any event name with a prefix in
#         ENGINE_EVENT_SHAPES = ("done.invoke.", "done.state.",
#         "error.platform.", "after.", "xstate.", "___xstate")
#         -- these are the only names `strict` still exempts BY NAME (G-7).
#         The old blanket done.*/error.* ban and its case-insensitivity
#         requirement are RETIRED: #79 makes those visible to "*", to
#         onUnhandled and to strict, case variants included.

# cv/statechart/persistence.py
# CV-C20: assert queue_depth == 0 and deferred_count == 0 before snapshotting.
#         The library drops pending ErrorEvent/DoneEvent (G-3) and loses
#         Event.system (G-2) across a round-trip, silently, with no log line.
#         Reconcile every pending_invocations() entry on restore (CV-C07).

# cv/statechart/actions.py
# CV-C21: onError handlers branch on isinstance(event, ErrorEvent) and read
#         event.error. Never .data (deprecated, gone in 0.9), never
#         event.type.startswith("error."), never event.payload.get(...)
#         on an error-shaped event (G-5). `escalate` is the exception: still
#         a plain Event with the error under payload["error"] (G-6).

# CV-C06 (M-1): the deferred_count clause is WITHDRAWN AS UNSOUND. A
#         wait=True receipt reading changed=False/error=None is INADMISSIBLE
#         as a gate on any machine configured onUnhandled: "defer".
```

`28-statechart-catalogue.md`'s per-machine config block needs **no edit**; its
prose note gains the CV-C19…CV-C22 cross-reference and the narrowed CV-C15
event-name rule.

---

## 6. Release-readiness note for the upstream team — refreshed

Written for whoever tags 0.8.1. Ordered by what we would want fixed first.
Everything below is reproduced by a checked-in script; nothing is a hunch.

**Blocking, in our reading, for a *good* 0.8.1:**

1. **G-2 — provenance does not survive a snapshot.** `base_interpreter.py:999`
   persists only `type` and `payload`; `:1229`/`:1235` rebuild every deferred
   and pending event as `Event(type=..., payload=...)`, i.e. `system=False`
   unconditionally. A machine restored with an `escalate` event in its inbox
   and `onUnhandled: "error"` now goes to `status="error"` where it previously
   did not. This is a behavioural regression created by #79 meeting #47, and
   the CHANGELOG does not mention it. If 0.8.1 ships as-is it becomes
   documented 0.8.1 behaviour rather than a `main`-only finding.
   Repro: `g3_restore_regression.py`.
2. **G-3 — a pending `ErrorEvent` is silently dropped by the snapshot.** The
   inbox filter at `base_interpreter.py:1007` is `isinstance(e, Event)`;
   `ErrorEvent`/`DoneEvent` are `NamedTuple`s. #47's stated purpose is that a
   crash between accept and process cannot lose an event; #80 routed *every*
   service and child failure through a class that falls through that filter.
   A machine restores believing the invoke never failed, sits in the invoking
   state, and no `onError` ever fires. At minimum, `logger.warning` on a
   dropped non-`Event` would have surfaced this.
   Repro: `g17_snapshot_drops_errorevent.py`.
3. **`__version__` still reports `0.8.0`** on a tree whose CHANGELOG describes
   0.8.1 — unchanged from the `5327ba6` review, now two reviews old. Bump it;
   consider a test tying it to the newest released CHANGELOG heading.

**Strongly recommended before tagging:**

4. **G-1 — `Event.system` is a public, user-settable field.** The name-based
   rule #79 removed was at least hard to hit by accident; a documented-by-
   dataclass opt-out that any caller can set is a wider hole through a
   different door. Make it private, or key on identity the engine controls.
   Repro: `g1_forge_system.py`, `g9_sync_parity.py`, `g18_threadsafe_and_detach.py`.
5. **F-1 (High, `5327ba6`-era, still present) — the sync `maxIterations`
   `tripped` flag is scoped to the drain, not the chain.** One self-feeding
   `SPIN` starves five subsequent, unrelated `WORK` events in the same
   `send_events()` batch (`INNER handled: 0 of 5`). The async engine does not
   behave this way, so the #77 CHANGELOG's engine-parity claim is not accurate
   for this shape. This is a data-starvation bug reachable from a single
   `send_events()` call, on the engine the fix was written for.
   Repro: `f_tripped_sticky.py`.
6. **F-2 (High, still present) — the legacy-clock shim treats `**kwargs` as
   consent.** A third-party clock written against the 0.8.0 `Clock` protocol
   that declares `**kwargs` for its own reasons is handed an unexpected
   `sync=`. Signature inspection should require the parameter **by name**.
   Repro: `f_clock_kwargs.py`.
7. **M-4 (Medium, still present) — `resolve_aliases` mutates the caller's
   `MachineLogic`.** The one alias-feature item with cross-machine blast
   radius: the registry grows `['store_user'] → ['storeUser','store_user'] →
   ['STOREUSER','storeUser','store_user']` across builds and the second build
   raises `InvalidConfigError`. Resolve into a per-machine copy.
   Repro: `f_pollute.py`, `f_shared_logic.py`.
8. **M-3 (Medium, still present) — the alias-ambiguity guard misses its own
   documented example**, and **F-5** — it does not reach the `logic_modules`
   path at all (`setdefault`, so iteration order decides). Worth aligning
   before the feature ships in a release; fixing it after is a behaviour break.
   Repro: `g1b_alias_ambiguity_and_leak.py`, `f_loader_dup.py`.
9. **G-4 — the library trips its own deprecation warning.** `plugins.py:435`
   and `base_interpreter.py:1781` read `ErrorEvent.data`. A user running
   `-W error::DeprecationWarning` in CI — the recommended way to be 0.9-ready —
   now fails on library code they cannot change. Both sites should branch on
   `isinstance(event, ErrorEvent)`. New on this commit (`5327ba6`:
   `DEPRECATIONS: []`).
10. **M-3/M-1 aside — the coverage floor.** Coverage measured **90%** on this
    commit, unchanged from `5327ba6` and up from 87% at 0.7.0. Pin a
    `--cov-fail-under` floor at 88–90 in CI now, while the number is at its
    high-water mark. Suite: 3 242 passed, 13 skipped, 0 failed, 11 warnings.

**Worth a line in the release notes rather than a fix:**

11. **M-3 aside — document the rollback cost honestly.** "≈0.98× of the
    default" for the checkpoint skip is measured on transitions declaring **no
    actions**. With actions it is 0.878×; on a busy 50 000-event burst
    (`bench_j_policies.py`) armed rollback is 0.854× and `rollback_and_defer`
    0.774×. Suggest "on transitions that run no actions".
12. **F-7 — the checkpoint-skip predicate** does not model `always`/`on` action
    lists on the transition's *target*. Verified safe in the case tested;
    narrower than the invariant it upholds. A targeted test before this becomes
    load-bearing.
13. **G-5/G-6 — `ErrorEvent` edges.** `_resolve_event_spec` builds an `Event`
    whose `payload` is the exception (`Event.payload` is typed
    `Dict[str, Any]`, and this is reachable end-to-end via `sendParent`
    supervision); `escalate` is the one failure path not converted.
14. **G-7 — `strict` still exempts by name.** `after.party` is the nicest
    case: not even a well-formed `after.` shape, and strict waves it through.
    `send()` already holds the event object at `_check_strict`, so the
    provenance flag is available there.
15. **G-8 — sync/async parity gap on invoked child-machine failure.**
    Pre-existing, but #80's scope is "service and child-actor failures" and the
    new test covers only async.
16. **G-9 — the completion-delivery task is untracked.** Created via
    `_loop_create_task`, registered with neither the `TaskManager` nor a strong
    reference. Latent (0/300 lost under a GC-hostile probe); a one-line fix.
17. **G-10/G-11/G-12 — housekeeping around #79.** Dead
    `_SYSTEM_EVENT_PREFIXES` whose comment describes the deleted architecture;
    three tests deleted with no replacement coverage of the new attack surface;
    `is_system_event`/`system_event`/`Event.system` undocumented and
    unexported while `ENGINE_EVENT_SHAPES` is announced in the CHANGELOG but
    not re-exported.
18. **F-9/F-10, M-2, M-6, F-6** — carried forward unchanged from the
    `5327ba6` release-readiness note; see `22-verify-main-verdict.md` §5.
19. **The good news, stated for the record.** #43 is the best piece of work in
    this window: `children + 1` confirmed at n=1/10/50, 1 000 spawn/complete
    cycles leaking nothing, teardown correct on parent `stop()` **and** on
    rollback of the entering transition, and the exit-vs-completion race
    handled under a ±2 ms scan with a passing control. The
    `production-characteristics.md` rewrite is accurate. Our capacity planning
    is revised from `2 × children` to `children + 1`.

**Net.** The diff is positive and #43 is excellent. Items 1 and 2 are the ones
that turn a good release into one the adopting project has to work around,
and both were created by two features in this same release meeting each other
on a boundary neither was taught about.

---

## 7. Drafted GitHub actions — **not filed**

All text is drafted as files under
`docs/research/xstate/issues/post-3c527b0/`. **Nothing was posted, created,
edited or commented during this phase.** No `git` command was run in the
CandleViewer repository. The Post-phase agent is the only one authorised to
write to GitHub.

| Path | Contents |
|---|---|
| `post-3c527b0/<GH#>.md` × 16 | One verification comment per pre-#82/#83 issue (#27 #31 #37 #39 #43 #44 #50 #51 #52 #60 #75 #76 #77 #78 #79 #80), each opening "Verified on main @ 3c527b0 (pre-0.8.1)…", with a criteria ✓/✗ table and an explicit **Disposition**. |
| `post-3c527b0/<N>.md` × 16 | New-issue bodies in the established front-matter format, labels drawn only from `bug`, `enhancement`, `documentation`, `performance`, `severity/*`, `area/*`. |
| `post-3c527b0/meta-26.md` | Full replacement body for meta issue #26. |
| `post-3c527b0/manifest.json` | Machine-readable posting plan: `comments` (issue, file, `comment` \| `comment+reopen`), `new_issues` (file, title, labels), `meta`. |

---

## 8. Evidence index

| Artefact | What it holds |
|---|---|
| `23-verify-3c527b0-findings.md` | Re-test of the 13 `5327ba6` findings; M-1 deep dive; #43 teardown/ordering analysis |
| `24-verify-3c527b0-gate.md` | Gate run (`gate/result-main-3c527b0.json`), library suite, coverage, all nine benchmarks, BENCH-1 rollback-armed re-runs, regression audit |
| `25-verify-3c527b0-diff-review.md` | `5327ba6..3c527b0` source diff (18 files, +1023/−357), G-1…G-12, and the negatives checked clean |
| `issues/verify-main-3c527b0/{43,79,80}.result.md` + `.py` | The three per-issue verifications for this commit; now a gate check set (§`run_gate.py`) |
| `probes/main-3c527b0/g1…g20, p1…p3` | 23 probes: the G-findings, the strict/provenance matrix, actor lifecycle, the M-1 four-variant deep re-test |
| `probes/main-5327ba6/*.py` | The `5327ba6` corpus, re-run unmodified on this commit |
| `issues/new-main/*.md` + `repro/*.py` | The 8 carried-forward drafts with refreshed front-matter and Observed output |
| `issues/post-3c527b0/` | The finalised postable artefacts and `manifest.json` |
| `22-verify-main-verdict.md` | The `5327ba6` verdict this document supersedes |
