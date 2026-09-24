# 22 — Verdict: `xstate-statemachine` @ `main` commit `5327ba6` (pre-0.8.1)

**Build under verdict.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `5327ba69fb735cfe24c7b3772050dac0a71a7b3d`. `CHANGELOG.md`
`[Unreleased] — targeting 0.8.1`. **`__version__` still reports `0.8.0`.**
This build is identified **by commit, never by version string**, here and in
every downstream reference (`run_gate.py` baseline, ADR-0016 pin, E50 chores).

**Date:** 2026-09-18. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro 10.0.26200.
**Interpreter used for every run:** `_ref/xstate-statemachine/.venv-main/Scripts/python`
with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Baseline replaced:** `17-reeval-0.8.0-verdict.md` (0.8.0 @ `9bf6065`).
**Inputs:** `18-verify-main-gate.md` (gate + suite + bench),
`19-verify-main-diff-review.md` (`v0.8.0..HEAD` source diff, F-1…F-11),
`21-verify-main-adversarial.md` (57 purpose-built hostile probes, M-1…M-6),
`issues/verify-main-5327ba6/*.result.md` (13 per-issue re-verifications).

---

## 0. Bottom line

**No regressions.** Every status delta against the 0.8.0 register moved in the
fixing direction. Six of the seven CHANGELOG `[Unreleased]` "Fixed" bullets
verify as claimed; the seventh (#77, sync macrostep budget) fixes the defect it
names and introduces three new ones in the same code path.

**Upstream no longer blocks us.** All four originally-filed Blockers remain
closed, and the two 0.8.0-era High defects that had no mitigation other than
"don't do that" — `send(wait=True)` hanging on a reused `Event` (#75/#39) and
`SyncInterpreter` timers unreachable inside a loop (#76/#50) — are genuinely
fixed under adversarial probing. **Two CandleViewer constraints retire
outright** (CV-C06's fresh-`Event` clause, CV-C14's gateway-validation clause):
the library now does that work itself.

**One new finding governs the order path.** **M-1**: the two library features
CandleViewer's order path is *mandated* to use together — `onUnhandled: "defer"`
(CV-C01) and `send(wait=True)` receipts (CV-C06) — compose into a confident
false negative. A deferred event's receipt resolves immediately with
`changed=False, error=None`: indistinguishable from "the machine looked at your
event and correctly did nothing", for an event that is parked and about to drive
its transition. This is not a hang and not data loss; it is a gate that says
*no* about an event that is about to say *yes*, at the exact moment the two
mandated settings are supposed to produce a right answer.

**Gate decision (§3): ADOPT WITH CONSTRAINTS — unchanged in form, materially
improved in substance.** The operative condition from the 0.8.0 run was, and
remains, **ours, not upstream's**: the `E29-T10` linter (CV-LINT-XS1…XS12) and
`tests/xstate_contract/` must be green before the first live-path statechart.
Non-order paths are unblocked by anything upstream; the order path additionally
waits on M-1 (upstream fix, or the CV-C06 `deferred_count` clause implemented in
`cv.statechart`).

---

## 1. Per-open-issue disposition

Every open upstream issue in the register, re-verified on this commit. Evidence
column cites `issues/verify-main-5327ba6/<id>.result.md` unless noted.
Draft comments: `issues/comments-main-5327ba6/<GH#>.md`.

| GH# | LC / N | Classification on `5327ba6` | Residual | Disposition |
|---|---|---|---|---|
| **#27** | LC-01 (action-raise commits transition) | **FIXED-OPT-IN** | `InvalidConfigError` not `ValueError` (cosmetic); `failed_actions` surfaced via `on_transition_failed` + `last_transition_ok`, not on `on_transition` itself; `SyncInterpreter` parity asserted by the library's own test, not independently re-driven here. Raise-withdrawal and the once-per-*process* warning latch both confirmed; the idle checkpoint-skip reproduces at 0.9978×–1.056× of baseline (CHANGELOG claims ≈0.98×, was 0.776×). | **close** |
| **#31** | LC-07 (relative dot-target silent no-op) | **PARTIAL** | Child-first `.child` resolution, the deprecation-warned sibling fallback, once-per-`(source,target)` warning throttling, multi-segment `.child.grandchild`, and build-time rejection of unresolvable static targets all confirmed. **Acceptance criterion #4 (engine parity) still fails under the documented `strict_targets=False` opt-out**: `SyncInterpreter` raises `StateNotFoundError` at `send()` time, async `Interpreter` silently no-ops. Also: the repo's own repro needs a signature update for the unrelated 4-arg action-callable change. | **keep open**, re-scoped to "runtime engine parity under `strict_targets=False`" |
| **#37** | LC-43 (`WrongThreadError` message) | **FIXED** | Stale repro script only (`LC-43_cross-thread-send-silently-lost.py` measures delivery counts from a worker that now correctly crashes); not a library gap. | **close** |
| **#39** | LC-42 (`send` fire-and-forget, no answer) | **FIXED** | Reserved-payload-key `DeprecationWarning` and the "Getting an answer from a machine" docs page not independently re-checked; FIFO-among-priority not isolated from aggregate latency. | **close** |
| **#43** | LC-28 (idle actor costs 2 tasks) | **NOT-FIXED** (task-count criterion) | Unchanged from 0.8.0: `2.0` tasks per child at n=2/10/50. The poll→`wait_done()` half shipped in 0.8.0 and holds (`onDone` latency 0.58 ms, zero idle wakeups); the "collapse the second task" half never landed. | **keep open**, recommend re-scoping the acceptance criteria to the task-collapse item only |
| **#44** | LC-19 (restore does not restart invokes) | **FIXED** | `status` still reports `"running"` for a parked restored machine — by design; `has_dormant_invocations` / `pending_invocations()` are the liveness signal, now confirmed identical on **both** engines. Three of the issue's named tests not independently re-driven. | **close** |
| **#50** | LC-38 (sync interpreter timer threads) | **FIXED** | 1000-timer stress and the `SyncInterpreter` docstring wording not re-driven this pass (green at 0.8.0, untouched by the diff). See **F-2** below — the legacy-clock compatibility shim has a hole for `**kwargs` clocks. | **close** (F-2 rides along as a new issue, not a reopen) |
| **#51** | LC-34 (no strict mode) | **FIXED** for the `send_threadsafe` guardrail + static-`raise` build-time validation; `strict` itself remains **FIXED-OPT-IN** (`strict=False` default, per the issue's own compatibility plan) | Static `raise` of a typo'd *reserved-namespace* event is still not caught at build time (**F-8**, rides along on #79). `send_threadsafe()` error precedence before `start()` (**M-6**). | **close** |
| **#52** | LC-37 (arity misclassification) | **FIXED** | `MachineLogic(strict=True)` refuses undecorated public methods with a message naming the offender; decorated methods bind by decorator not arity; `_private` helpers exempt; default `False` is byte-compatible; un-classifiable arity now `UserWarning`s rather than silently dropping. 10/10 assertions pass. | **close** |
| **#60** | LC-57 (two engines duplicate core algorithm) | **PARTIAL** | The "one shared algorithm" half genuinely landed. The gate's FAIL on this row is scoped to its LC-52 sub-claim (`ErrorEvent`), which did not ship — tracked separately as #80. | **keep open**, or close and let #80 carry the remainder |
| **#75** | N-1 (`wait=True` receipt `id()` collision) | **FIXED** | None. Held at 200 concurrent duplicates, and at 500-way concurrency under three policies simultaneously in the adversarial pass. Root cause fixed structurally (`Interpreter._detach()` at the send boundary), not patched. | **close** |
| **#76** | N-2 (sync `after` unreachable in a loop) | **FIXED** | `inspect.signature`-once claim not probed at byte level; functional behaviour correct in both contexts, no thread-count regression. | **close** |
| **#77** | N-3 (sync macrostep budget clears queue) | **PARTIAL** | The data-loss defect is fixed (1501- and 5000-event batches fully processed, `queue_depth == 0`, 3000 independent one-deep raises all delivered, byte-identical sync/async traces, named parity tests present). **Not fixed:** overflow is still silent — `send()` returns normally, `status` stays `"running"`, only a log line. The criteria asked for *raise*. **Three new defects in the same fix:** F-1 (sticky trip starves later unrelated events), F-6 (`done.invoke` classed self-generated, machine parks), M-2 (async engine's budget does not bound an action-side `send()`, so the parity claim is inaccurate). | **keep open**, re-scoped to raise-on-overflow; F-1/F-6/M-2 filed separately |
| **#78** | N-4 (`send_threadsafe` bypasses strict) | **FIXED** | None. Guardrail runs on the calling thread before anything is queued, under loop saturation and 10-thread contention. Cosmetic: the issue names `tests/test_strict_mode.py`, the file is `tests/test_strict.py`. | **close** |
| **#79** | N-8 (`error.*`/`done.*` names invisible) | **PARTIAL** | Documentation + a build-time `UserWarning` for reserved `on` keys shipped; **the runtime defect is unchanged and explicitly deferred to 0.9** ("provenance-tagged system events"). The warning does not cover `send()` and misses case variants (`DONE.review` — **M-5**). New: a CI that turns warnings into errors will now break machines that previously worked. | **keep open**, retag for 0.9 |
| **#80** | LC-52 (`error.platform.*` delivered as `DoneEvent`) | **NOT-FIXED** | Everything the issue asked for is open: no `ErrorEvent` type, `DoneEvent` still doubles as success and failure, consumers still string-match `event.type.startswith("error.")`. Correctly and visibly deferred (not silently dropped — every other issue in this window is itemised in the CHANGELOG and this one is not). | **keep open**, acceptance criteria apply verbatim |
| **#26** | Meta — adoption readiness | — | — | **update** (`issues/comments-main-5327ba6/meta-26.md`) |

**Counts.** 9 close · 6 keep open · 1 meta update.
Of the 34 originally-filed issues the register now stands at
**25 FIXED-DEFAULT · 5 FIXED-OPT-IN · 3 PARTIAL · 1 NOT-FIXED**.

---

## 2. Regressions and new defects

### 2.1 Regressions: **none**

Explicit audit of every status delta (`18-verify-main-gate.md` §3):

| Item | 0.8.0 | `5327ba6` | Classification |
|---|---|---|---|
| Gate primary (`verify`) set | 32/34, FAILs = LC-28, LC-57 | 32/34, **same two** | no change |
| Gate secondary (`repro`, defaults) | 22 FAIL, all triaged | **same 22** | no change |
| Probes | 43/51, baseline A3 A6 A10 A18 / C6 C7 C15 C17 | **identical set** | no change |
| Library suite | 3170 P / 13 S / 0 F | **3234 P / 13 S / 0 F** | improvement |
| Coverage | 87% (last measured at 0.7.0) | **90%** | improvement |
| N-1 / N-2 / N-3 / N-4 | open | **fixed** | improvement (4 CHANGELOG bullets) |
| N-8 | open | open + build-time warning | observability improvement, defect unchanged |
| LC-07 crit. 4 | known residual | identical | no change |
| Public API | — | additive only: `SYSTEM_EVENT_PREFIXES`, `has_dormant_invocations`, `MachineLogic(strict=)`, `Clock.set_timeout(sync=)` | no removals, **no snapshot-format change** |

No test function was deleted and no skip/xfail was added across the whole diff
(`git diff v0.8.0..HEAD -- tests/ | grep -E "^-\s*(async )?def test"` → empty).

### 2.2 New defects — consolidated and de-duplicated

The diff review (F-1…F-11) and the adversarial pass (M-1…M-6) overlap. Merged:
**F-3 ≡ M-4** (registry mutation), **F-4 ≡ M-3** (config-side ambiguity),
**F-8 ⊂ M-5** (reserved-namespace gaps in the build-time guard). Canonical set,
**13 findings: 3 High, 6 Medium, 3 Low, 1 Info; 0 Blocker.**

| ID | Severity | Area | Defect | Repro | Upstream action |
|---|---|---|---|---|---|
| **M-1** | **High** | `defer` × `wait=True` | A deferred event's receipt resolves `changed=False, error=None` — indistinguishable from "processed, no effect". The receipt is computed by comparing configuration+context at end-of-macrostep, with no knowledge of the `defer` disposition recorded microseconds earlier. | `probes/main-5327ba6/a2_confirm_deferred_receipt.py` | **new issue** |
| **F-1** | **High** | sync `maxIterations` (#77) | The overflow `tripped` flag is deliberately never cleared for the rest of the drain and is scoped to the *drain*, not the offending chain. One self-feeding `SPIN` starves the one-deep `raise` of five subsequent, unrelated `WORK` events in the same `send_events()` batch. Async engine does not behave this way. | `issues/verify-main/repro/f_tripped_sticky.py` | **new issue** |
| **F-2** | **High** | `sync=` clock kwarg (#76) | The compatibility shim inspects `set_timeout`'s signature and treats a `**kwargs` catch-all as *consent* to receive `sync=`. A 0.8.0-protocol clock declaring `**kwargs` for its own reasons is fed an argument it has never heard of. | `issues/verify-main/repro/f_clock_kwargs.py` | **new issue** |
| **M-2** | Medium | async runaway budget | `max_iterations` bounds the `raise` built-in but not an action calling `send()` on its own interpreter — so the #77 CHANGELOG's engine-parity claim is inaccurate, and the async engine (the only one CV-C03 permits) has the unbounded shape. | `probes/main-5327ba6/c14_async_no_send_budget.py` | **new issue** |
| **M-3** (=F-4) | Medium | alias resolution | The ambiguity guard misses its own documented example: two *different config names* that normalise equal both silently bind to one callable. The check guards the registry side only. | `probes/main-5327ba6/g1b_alias_ambiguity_and_leak.py`, `repro/f_loader_twoname.py` | **new issue** |
| **M-4** (=F-3) | Medium | alias resolution | `create_machine()` / `resolve_aliases` **mutates the caller's `MachineLogic` registry in place.** Aliases accumulate across machines, suppressing the ambiguity guard for later machines, retroactively rebinding earlier ones, and turning an unrelated later `create_machine()` into a hard `InvalidConfigError`. | `repro/f_pollute.py`, `repro/f_shared_logic.py` | **new issue** |
| **F-5** | Medium | `logic_modules` loader | The normalised index uses `setdefault`, so duplicate snake/camel implementations in one module are resolved by **iteration order** with no error — the documented ambiguity rejection never reaches this path. | `repro/f_loader_dup.py` | **new issue** |
| **F-6** | Medium | sync `maxIterations` (#77) | A `done.invoke` from a sync service is classed as "self-generated". After a trip, a legitimate invoke completion is dropped and the machine parks in the invoking state. | `repro/f_sticky_invoke.py` | **new issue** |
| **F-7** | Medium | rollback checkpoint skip (#27) | Behaviour change shipped without a risk note: the skip predicate does not model `always`/`on` action lists on the *target*. Verified safe in the case tested; the predicate is narrower than the invariant it must uphold. | `repro/f_rollback_gap.py` | ride-along on **#27** |
| **M-5** (⊃F-8) | Low | `SYSTEM_EVENT_PREFIXES` | Importable but not extensible; the build-time warning is narrower than the runtime rule — misses case variants (`DONE.review`), does not cover `send()`, and `strict` still exempts reserved prefixes so a typo'd static `raise` into one is not caught at build time. | `def_threads_dormant_namespaces.py` (F-suite), `repro/f_strict_raise.py` | ride-along on **#79** |
| **M-6** | Low | `send_threadsafe()` | Error precedence across lifecycle phases: before `start()`, the strict/schema error and the not-started error race for which surfaces. | `def_threads_dormant_namespaces.py` (D-suite) | ride-along on **#78** |
| **F-9** | Low | per-chain budget | A legitimate 1001-deep chain **is** cut, and sync/async disagree by one (`s1000` vs `s1001`) despite the parity claim. The cut is silent: `status` stays `"running"`, `last_transition_ok` stays `True`, no hook fires. | `repro/f_chain.py`, `repro/f_parity.py` | ride-along on **#77** |
| **F-10** | Low | `resolver.py` | `_SIBLING_FALLBACKS_WARNED` is an unbounded module-global set keyed `(source.id, target)`; a process creating many machines leaks entries. | `probes/main-5327ba6/g1b_alias_ambiguity_and_leak.py` | ride-along on **#31** |
| **F-11** | Info | public API | Additive only; no removals; no snapshot-format change. | — | — |

**New issue drafts** (8) in `issues/new-main/`: M-1, F-1, F-2, M-2, M-3, M-4,
F-5, F-6. Same front-matter format as `issues/new-0.8.0/`, each with its repro
copied into `issues/new-main/repro/`. **Nothing filed.**

### 2.3 Why M-1 is the one that matters

M-1 is narrower than anything in the 0.7.0 register and more dangerous in shape
than most of the 0.8.0 set, for one reason: **its trigger is our mandated
configuration, not a misuse of it.** CV-C01 mandates `defer` on the order path;
CV-C06 mandates `wait=True` for every gated decision. A FILL that arrives one
microstep early — the precise scenario `defer` was adopted to fix (probe B5 of
the 0.8.0 corpus) — returns a receipt saying the fill did not land. A caller
that retries, or reports "not filled" and unwinds, does so against a machine
that is about to fill. Carefulness is not a control that detects this, because
the wrong answer is a *confident* one.

---

## 3. Gate decision

### 3.1 Decision-table walk (`20-adoption-gate.md` §7)

| Row | Condition | Trips? |
|---|---|---|
| 1 | Any `ERROR` row in the gate output | **No.** `FAIL=25, PASS=46`, zero `ERROR`. Evidence is valid. |
| 2 | Suite fails, or coverage < 86% | **No.** 3234 passed / 13 skipped / 0 failed; coverage **90%** (up from 87%). |
| 3 | Snapshot format changed while LC-21 open | **No.** LC-21 closed at 0.8.0; the format is unchanged on this commit (diff review F-11). |
| 4 | Any filed **Blocker** repro still exits 1 | **No — with the same asterisk as 0.8.0.** All four Blockers closed; LC-01 and LC-03 remain **FIXED-OPT-IN**, and per §9.2 amendment 3 a FIXED-OPT-IN Blocker counts closed *only while its option is lint-enforced*. `E29-T10` has not shipped, so on a literal reading row 4 still applies **to the order path**. |
| 5 | > 5 High open | **No.** High open: LC-07 (#31, narrowed), M-1, F-1, F-2 = **4**. |
| 6 | 1–5 High open, each with a mechanically enforced mitigation + passing test in `tests/xstate_contract/`; all Medium triaged | **Matches — precondition still unmet.** Each open High has a *specified* enforcing mechanism (LC-07→CV-LINT-XS8 bans `strict_targets=False`; M-1→CV-C06 `deferred_count` clause; F-1/F-2→CV-C03 bans `SyncInterpreter` and CV-C10 mandates the library's own `SimulatedClock`), but `tests/xstate_contract/` and the linter do not exist. |
| 7 | 1–5 High open **without** enforced mitigations | **This is the honest row today**, exactly as at 0.8.0. |
| 8, 9 | — | Not reached (High still open; BENCH-1/2/6 also unmet). |

**Result: ADOPT WITH CONSTRAINTS, CONDITIONAL — row 6 claimed on the strength
of row 7's honest reading, unchanged in form from 0.8.0.**

### 3.2 The operative condition, stated plainly

The condition that governed the 0.8.0 decision was **our linter and contract
suite, not an upstream defect**. That is still true, and it is now *more*
true:

> **Nothing upstream blocks adoption on a non-order path.** Every Blocker is
> closed; every 0.8.0-era High that lacked a mitigation now has one or is fixed;
> the two constraints that existed only because the library would not do the
> work (fresh-`Event` discipline, gateway-side event validation) have retired
> into the library. The remaining upstream items — #31, #43, #77, #79, #80 —
> are all either behind an opt-out CandleViewer never takes
> (`strict_targets=False`), a capacity-planning line item (2 tasks/actor), an
> ergonomics gap (silent overflow), or a namespace we already ban by CV-C15.

**Can ADOPT be unconditional for non-order paths?** **No — but the remaining
condition is entirely ours.** MUST-09 requires `E29-T10` + `tests/xstate_contract/`
to ship **before the first statechart**, on any path: LC-01 and LC-03 are
Blockers closed by an *opt-in policy*, and an unenforced policy is not a
mitigation for a silent failure. Once those two artefacts are green, non-order
adoption is unconditional — no upstream dependency remains for replay/backtest
or the rule-runtime lifecycle layer.

**What remains for the order path**, beyond the linter:

1. **M-1 resolved** — either fixed upstream (the receipt learns the `defer`
   disposition), or covered by the CV-C06 clause: *a `wait=True` receipt with
   `changed=False, error=None` is **inconclusive** unless `deferred_count` is
   `0` at the same instant*, implemented in `cv.statechart` and locked by
   `test_receipt_is_inconclusive_when_deferred`.
2. **CV-C13's accepted cost re-affirmed** — BENCH-1 with `rollback` armed
   measured **2.02×–2.87× (mean ≈2.43×)** across four runs on this box against
   a ≥3.0× bar, matching 0.8.0's documented ~2.46× within run-to-run variance.
   The dedicated event loop/process is what buys it back. The CHANGELOG's
   "≈0.98× of the default" for the new checkpoint-skip is **accurate only for a
   machine whose transitions declare no actions at all** (measured 0.949× with
   no actions, **0.878× with actions**; `bench_j_policies.py` busy-burst:
   0.854×). No CandleViewer machine qualifies for the skip. Report BENCH-1 both
   ways, per §9.2 amendment 4.
3. **CV-C16/C17/C18 shipped as lint rules** (CV-LINT-XS11/XS12 + the
   design-review checklist item).

### 3.3 Recorded decision

```
Gate run 2026-09-18 - xstate-statemachine main @ 5327ba6 (unreleased, pre-0.8.1)
DECISION: ADOPT WITH CONSTRAINTS, CONDITIONAL (unchanged in form from 0.8.0)
  verify   : 32/34 primary pass (PRIMARY, mandated config, blocking)
             FAILs: LC-28 (#43), LC-57 (#60/LC-52) - both unchanged partials
  repro    : 13/34 pass at defaults (SECONDARY, informational)
  probes   : 43/51-equivalent (identical baseline: A3 A6 A10 A18, C6 C7 C15 C17)
  adversarial: 57 purpose-built probes, 8 suites; 5 of 8 claim clusters solid
  suite    : 3234 passed, 13 skipped, 0 failed (was 3170)
  coverage : 90% (was 87% at 0.7.0)
  benches  : BENCH-1 armed 2.43x mean (bar >=3.0x) - unchanged shortfall
             BENCH-2, BENCH-6 still missed; all others PASS - same as 0.8.0
  blockers open: none (LC-01, LC-03 FIXED-OPT-IN - closed only while lint-enforced)
  high open    : LC-07/#31 (narrowed), M-1, F-1, F-2
  new defects  : 13 (3 High, 6 Medium, 3 Low, 1 Info, 0 Blocker)
  regressions  : NONE
  constraints  : CV-C01..CV-C18 (CV-C06 reuse clause and CV-C14 validation
                 clause RETIRED; CV-C16, CV-C17, CV-C18 NEW)
  condition    : E29-T10 linter + tests/xstate_contract/ green before the first
                 live-path statechart. Nothing upstream blocks non-order paths.
                 Order path additionally DEFERRED until M-1 is fixed upstream or
                 covered by the CV-C06 deferred_count clause.
  decided by   : Architect
```

---

## 4. Constraints

### 4.1 Retired by this commit

| Constraint | Basis |
|---|---|
| **CV-C06, fresh-`Event` clause only** — *"Never reuse an `Event` instance across concurrent `wait=True` sends"* | **RETIRED.** #75 fixes this by construction (`Interpreter._detach()` at the send boundary); verified at 500-way concurrency under three policies simultaneously, and at 200-way with `stop()` racing. Delete `test_send_receipt_fresh_event_only` and the **CV-LINT-XS9** clause that enforced it. The rest of CV-C06 stands and is strengthened — §4.2. |
| **CV-C14, gateway-validation clause only** — *"wrapped by `cv.statechart.gateway`, which performs the `strict`/`event_schemas` check itself"* | **RETIRED.** #78 does this in the library, on the calling thread, before queuing, under loop saturation and 10-thread contention. Delete the gateway's duplicate validation. **The `run_coroutine_threadsafe` ban stands** — CV-C14 becomes a ban-only rule. |

### 4.2 Standing

| ID | Status on `5327ba6` |
|---|---|
| **CV-C01** (mandatory policy block; factory-only construction) | **STANDS.** Basis unchanged; and M-1 makes the block's own composition load-bearing — see CV-C06. |
| **CV-C02** (outward effects only from committed-state `entry`, or last in the list) | **STANDS.** #27's raise-withdrawal narrows it for `raise` (withdrawn on rollback, confirmed in 8 hostile shapes including parallel regions and child actors) but **not** for `sendTo` — the CHANGELOG says so explicitly. The rule is unchanged. |
| **CV-C03** (async `Interpreter` only) | **STANDS — rationale shifts.** N-2 and N-3, the sync-engine defects that motivated it, are fixed. It now stands on F-1/F-6 (new sync-only defects in the #77 fix) and the remaining sync surface. **Note: CV-C03 does not protect us from M-2**, which is an *async* hole — hence CV-C16. |
| **CV-C04** (`strict` + non-default `actionErrorPolicy` together) | **STANDS, strengthened.** #51 adds build-time validation of *static* `raise` targets with a `difflib` suggestion, which closes most of the typo class earlier. It does **not** cover dynamic (callable) raises, nor reserved-namespace targets (M-5/F-8). Both halves still required. |
| **CV-C05** (bounded inboxes; `RAISE` on order/exec, `DROP_NEWEST` on market data) | **STANDS, unchanged.** |
| **CV-C06** (`wait=True` for gated decisions) | **STANDS, STRENGTHENED, reuse clause retired.** New mandatory clause: *a `wait=True` receipt with `changed=False, error=None` must be treated as **inconclusive** unless `interpreter.deferred_count` is `0` at the same instant* (M-1). Enforced by `cv.statechart`'s send wrapper + `test_receipt_is_inconclusive_when_deferred`. Also unchanged: never poll `current_state_ids`; `send_priority()` for kill/risk. |
| **CV-C07** (restore reconciles `pending_invocations()`; never blanket `restart_services=True`) | **STANDS, improved.** `has_dormant_invocations` now exists on **both** engines with confirmed parity — a single boot-time health check can be written once. `status` still must not be trusted for liveness. |
| **CV-C08** (snapshots as the JSON string, via `cv.statechart.persistence`) | **STANDS.** No snapshot-format change on this commit. |
| **CV-C09** (plugins filter the init event; dedupe `on_transition_failed`) | **STANDS.** |
| **CV-C10** (`SimulatedClock` everywhere time-dependent) | **STANDS, reinforced.** F-2 shows the legacy-clock shim mis-detects a `**kwargs` clock — one more reason to use the library's own clock rather than a hand-rolled one. |
| **CV-C11** (`last_transition_ok` read immediately, or preferably not at all) | **STANDS, reinforced.** F-9: a silently cut chain leaves `last_transition_ok = True`. |
| **CV-C12** (`after` banned in catalogue machines) | **STANDS.** BENCH-6 unchanged at 174.4 ms against ≤100 ms. |
| **CV-C13** (order path on a dedicated event loop / process) | **STANDS.** Re-measured on this commit: armed `rollback` = **0.778×** (34 278 → 26 657 ev/s, −22.2%), statistically unchanged from 0.8.0's −22.4%. BENCH-1 armed ≈ **2.43×**, below the 3.0× bar. The new no-action checkpoint skip does not apply to any CandleViewer machine. |
| **CV-C14** (`send_threadsafe()` only; `run_coroutine_threadsafe(send(...))` banned) | **STANDS as a ban-only rule** — validation clause retired (§4.1). The ban is reinforced: #37's corrected message confirms the idiom raises `WrongThreadError` eagerly. |
| **CV-C15** (no CandleViewer event named `error.*` / `done.*`) | **STANDS.** N-8's runtime behaviour is unchanged and explicitly deferred to 0.9. The new build-time `UserWarning` covers reserved **`on` keys** only — not `send()`, and it misses case variants (M-5). **`E50-T05`'s event-name gate must therefore still run, and must be case-insensitive, which the library's check is not.** |
| **MUST-05, MUST-08, MUST-12** | **STAND, unchanged.** |
| **MUST-07** (version pin) | **AMENDED** — see §4.4. |
| **MUST-09** (linter + contract suite ship before the first statechart) | **STANDS. This is the single gating condition** (§3.2). |

### 4.3 New

| ID | Constraint | Enforcement |
|---|---|---|
| **CV-C16** | **No action may call `send()` on its own interpreter.** Self-directed events use the `raise` built-in — the only shape the runaway budget actually bounds on the async engine (M-2). | **CV-LINT-XS11** (AST: `<interp>.send(` inside a registered action); `test_no_self_send_in_actions` |
| **CV-C17** | **No catalogue machine may rely on a `raise` chain deeper than 1 000.** Any machine whose design permits a longer chain sets `maxIterations` explicitly and asserts the depth in a test — the cut is silent (`status` stays `"running"`, `last_transition_ok` stays `True`, no hook fires; F-9). | Design-review checklist; `test_chain_depth_under_budget` per family |
| **CV-C18** | **`MachineLogic` instances are never shared across `create_machine()` calls**; each machine gets its own registry, and **one spelling per implementation** is registered. `create_machine()` mutates the registry in place (M-4) and the ambiguity guard misses the common config-side case (M-3) and the `logic_modules` duplicate case (F-5). | Factory assertion on logic-object identity; **CV-LINT-XS12** (no two registry keys with equal `normalize_logic_name`); `MachineLogic(strict=True)` mandated in the factory (#52) |

### 4.4 Version pin

**MUST-07 amended.** The pin becomes:

```
xstate-statemachine == 0.8.1        # once tagged
# until tagged: git commit 5327ba69fb735cfe24c7b3772050dac0a71a7b3d, with sha256
```

**`__version__` on this commit still reports `0.8.0`.** Any pin, gate baseline,
vendored-copy contract test or CI assertion that keys on the version string will
silently accept 0.8.0 for 0.8.1 and vice versa. **Key on the commit** until the
tag lands and the string is corrected — `run_gate.py` is updated accordingly
(§6).

### 4.5 Mandatory configuration block — recomputed

**No library default changed on this commit.** The machine-JSON block in
`17-reeval-0.8.0-verdict.md` §4.1 and `28-statechart-catalogue.md` §"the six
keys" is **unchanged and remains normative verbatim**:

```jsonc
"actionErrorPolicy": "rollback",   // "fail" on the invariant machines (B8/B17/B18/B20)
"onUnhandled":       "defer",      // "error" on the control machines (B13/B14/B18)
"guardErrorPolicy":  "raise",
"strictTargets":     true,
"strict":            true,
"spawnBlockingTimeout": 5000
```

Two **additive** changes to the *factory* block (`§4.2` of the 0.8.0 verdict),
both consequences of new APIs on this commit, neither altering a default:

```python
# cv/statechart/factory.py — ADDITIVE on main @ 5327ba6
logic = MachineLogic(..., strict=True)     # NEW (#52) — CV-C18: refuse undecorated
                                           # public methods instead of guessing by arity.
                                           # One MachineLogic per create_machine() call.
...
# CV-C06 (M-1): wrap every wait=True send so a changed=False/error=None receipt
# is reported INCONCLUSIVE while interp.deferred_count > 0.
```

and one **deletion** from the gateway (CV-C14 retirement): the duplicate
`strict`/`event_schemas` check is now the library's job.

`28-statechart-catalogue.md`'s per-machine config block therefore needs **no
edit**; only its prose note gains the CV-C16/C17/C18 cross-reference.

---

## 5. Release-readiness note for the library team

Recommended checks before tagging **0.8.1**. Ordered by cost of getting it
wrong.

1. **`__version__` still reports `0.8.0`.** The `[Unreleased]` section targets
   0.8.1 and `src/xstate_statemachine/__init__.py` has not been bumped. Anyone
   pinning by version string cannot distinguish this build from the release it
   supersedes. **Bump before tagging**, and consider a test asserting
   `__version__ == <CHANGELOG's newest released heading>`.
2. **#77's fix introduces three defects in its own code path.** F-1 (High — the
   `tripped` flag is scoped to the drain, not the chain, so one runaway starves
   every later unrelated event's self-generated work in the same batch), F-6
   (Medium — `done.invoke` from a sync service is counted as self-generated, so
   a legitimate invoke completion is dropped after a trip and the machine parks),
   and M-2 (Medium — the async engine's budget does not bound an action-side
   `send()`, so the CHANGELOG's *"they do now [agree], and an engine-parity test
   pins it"* is not accurate for that shape). Recommend fixing at least F-1
   before tagging: it is a data-starvation bug reachable from a single
   `send_events()` call, on the engine the fix was written for.
3. **#76's legacy-clock shim treats `**kwargs` as consent** (F-2). A third-party
   clock written against the 0.8.0 `Clock` protocol that declares `**kwargs` for
   its own reasons will be handed an unexpected `sync=`. Signature inspection
   should require the parameter by name, not accept a catch-all.
4. **`resolve_aliases` mutates the caller's `MachineLogic`** (M-4). This is the
   one item in the alias feature with cross-machine blast radius: aliases
   accumulate on a shared registry, suppressing the ambiguity guard for later
   machines and retroactively rebinding earlier ones. Resolve into a
   per-machine copy.
5. **The alias-ambiguity guard misses its own documented example** (M-3) and
   does not reach the `logic_modules` path at all (F-5, `setdefault` → iteration
   order decides). Worth aligning before the feature ships in a release, since
   fixing it later is a behaviour break.
6. **Coverage floor.** Coverage measured **90%** on this commit (up from 87% at
   0.7.0). Recommend pinning a `--cov-fail-under` floor at 88–90 in CI now,
   while the number is at its high-water mark. Suite: 3234 passed, 13 skipped,
   0 failed, 10 warnings, 458 s.
7. **Document the rollback cost honestly.** The new checkpoint-skip's
   "≈ 0.98× of the default" is measured on transitions declaring **no actions**.
   With actions it is 0.878×, and on a busy 50 000-event burst
   (`bench_j_policies.py`) armed rollback is **0.854×** and
   `rollback_and_defer` **0.774×**. Both numbers are defensible; only one is in
   the CHANGELOG. Suggest adding "on transitions that run no actions" to the
   claim.
8. **Rollback checkpoint-skip predicate** (F-7). The skip does not model
   `always`/`on` action lists on the transition's *target*. Verified safe in the
   case tested, but the predicate is narrower than the invariant it upholds —
   worth a targeted test before this is load-bearing.
9. **`_SIBLING_FALLBACKS_WARNED` is an unbounded module-global** (F-10) keyed on
   `(source.id, target)`. A long-lived process building many machines leaks
   entries. An `lru_cache`-bounded set or a per-machine set fixes it.
10. **Deferred-by-design items to state in the release notes**, so they are not
    read as omissions: #80 (`ErrorEvent`) and #79's runtime half (provenance-
    tagged system events, already noted as 0.9), and #43's task-collapse half.

Nothing in this list is a Blocker for tagging 0.8.1 **except** item 1, which is
mechanical. Items 2–4 are the ones we would want fixed before we pin.

---

## 6. Drafted GitHub actions — **not filed**

All text is drafted as files. **Nothing was posted, created, edited or
commented.** No `git` command was run in the CandleViewer repository.

| Path | Contents |
|---|---|
| `issues/comments-main-5327ba6/27.md` … `80.md` | One verification comment per open issue (16 files), each stating the classification on `5327ba6`, the criteria that pass, the residual gap, and an explicit **Disposition: close / keep open**. |
| `issues/comments-main-5327ba6/meta-26.md` | Replacement status block for meta issue #26: the new counts, the gate line, the per-issue table, and the deferred-by-design list. |
| `issues/new-main/M-1-…` … `F-6-…` (8 drafts) | New-issue drafts in the `issues/new-0.8.0/` front-matter format (`lc`, `title`, `labels`, `severity`, `blocks_adoption`, `verified`, `repro_script`, `library_version`, `python`, `found_by`, `related_issue`), each with Summary / Environment / Minimal reproduction / Observed / Expected / Proposed fix / Acceptance criteria. |
| `issues/new-main/repro/*.py` | The runnable repro for each draft, copied from `issues/verify-main/repro/` and `probes/main-5327ba6/`. |

---

## 7. Evidence index

| Artefact | What it holds |
|---|---|
| `18-verify-main-gate.md` | Gate run (`gate/result-main-5327ba6.json`), library suite, coverage, seven benchmarks, the BENCH-1-with-rollback recomputation |
| `19-verify-main-diff-review.md` | `v0.8.0..5327ba6` source diff, F-1…F-11 |
| `21-verify-main-adversarial.md` | 57 hostile probes in 8 suites (`probes/main-5327ba6/`), M-1…M-6 |
| `issues/verify-main-5327ba6/*.result.md` | 13 per-issue re-verifications with criteria tables |
| `issues/verify-main-5327ba6/*.py` | The 13 verification scripts — now a gate check set (§`run_gate.py`) |
| `issues/verify-main/repro/f_*.py` | 22 diff-review repro scripts |
| `gate/result-main-5327ba6.json` | Machine-readable gate result, keyed on commit |
