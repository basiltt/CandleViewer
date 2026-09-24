# 27 — Round-4 full regression gate: `xstate-statemachine` @ `main` commit `5e07ba8`

**Build under gate.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `5e07ba8842345a73ef8f830f0281de16370a7c74` — merge of PR #101
(`fix/round3-ride-alongs`) on top of the round-3 fixes for #84–#99, #31 and
#77. `CHANGELOG.md` `[Unreleased] — targeting 0.8.1`. **`__version__` still
reports `0.8.0`.** Identified by commit only, per standing convention.

**Date:** 2026-09-18. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter for every run:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Baseline compared against:** `26-verify-3c527b0-verdict.md`
(`main@3c527b0`). No library source was modified. No `git` command was run
in the CandleViewer repository. GitHub was read-only throughout.

---

## 0. Bottom line

**No regressions.** Every check that passed at `3c527b0` still passes at
`5e07ba8`; the three new round-3 verification scripts (#84/#85/#86-87 style
checks folded into `verifyM2`… actually the `issues/verify-main-5e07ba8/*`
set) all PASS. The gate's residual FAIL set is **identical** to the one
carried since `5327ba6`/`3c527b0`: `LC-57` (verify), `LC-07`/`N-3`/`N-8`
(verifyM, documented residuals), and the same eight probe items
(`A3,A6,A10,A18` / `C6,C7,C15,C17`). Round 3 delivered real fixes for #84,
#88, #89, #90–#99 as claimed; spot-checks of the headline `f_*` repros
(`f_tripped_sticky`, `f_clock_kwargs`, `a2_confirm_deferred_receipt`,
`f_pollute`/`f_shared_logic`) confirm F-1, F-2, M-3(mutation half), M-4 and
the deferred-receipt gap (M-1's discriminator, `Receipt.deferred`) are now
fixed. **Two items from `26-verify-3c527b0-verdict.md`'s blocking list are
still open and newly reconfirmed on this commit**: the async engine has no
runaway-chain budget for an action-side `send()` (only `raise` and the sync
engine are covered, contradicting the #77/#90 CHANGELOG claim of full
parity), and `Event(system=True)` remains a public, user-settable
constructor argument (G-1) — this gate could not even probe deeper into the
provenance-snapshot question because every `main-3c527b0` probe that forges
`system=True` now hits `TypeError: unexpected keyword argument 'system'` on
some paths and succeeds (accepted, not rejected) on others; see §5.

**Gate verdict stands at DEFER**, unchanged from `26-verify-3c527b0-verdict.md`
§4.2 — nothing on this commit changes the decision.

---

## 1. Gate script run

```
run_gate.py --json gate/result-main-5e07ba8.json
```

```
  verify:  33/34 pass   (PRIMARY -- mandated config, blocking)
  verifyM: 12/15 pass   (PRIMARY -- main@5327ba6 verification set, blocking)
  verifyM2: 3/3 pass    (PRIMARY -- main@3c527b0 verification set, blocking)
  repro :  13/34 pass   (SECONDARY -- defaults, informational)
  probe :  1/3 pass
  totals: FAIL=27, PASS=62
```

Blocking FAILs (identical set to `3c527b0`, all previously triaged as
"keep open" / documented residuals — see `22-verify-main-verdict.md` §1 and
`26-verify-3c527b0-verdict.md`):

| Check | Kind | Status | Note |
|---|---|---|---|
| `LC-57` | verify | FAIL | Two-engines-one-algorithm framing residual (issue's literal file/API sketch not followed verbatim; underlying bugs fixed by other means). No change since `3c527b0`. |
| `LC-07` | verifyM | FAIL | `strict_targets=False` opt-out: engines still disagree (`SyncInterpreter` raises `StateNotFoundError`, async no-ops). No change. |
| `N-3` | verifyM | FAIL | Sync engine still silently drops the self-generated tail on genuine overflow (no exception) rather than raising. No change. |
| `N-8` | verifyM | FAIL | Reserved-namespace docs/warning shipped; the runtime silent-drop the issue reports is unchanged by design. No change. |
| `PROBE-01` | probe | FAIL | 16/20 — `A3` (bare-target self-transition treated internal, not re-entered), `A6` (later guards still evaluated after a match — side-effect leakage), `A10`/`A18` now **build-time rejected** (`InvalidConfigError`) rather than the originally-probed runtime behaviour — this is `strict_targets`/`always`-validation doing its job, the probe's *expectation* is stale for the mandated config, not a regression. |
| `PROBE-03` | probe | FAIL | 13/17 — `C6`/`C7` (snapshot mid-`after`/mid-`invoke` does not resume/rerun), `C15` (unknown target now build-time `InvalidConfigError`, again a stale-probe-expectation not a regression), `C17` (events during a transient/invoking state still silently dropped). |

**verifyM2** (the round-3 headline set, #43/#79/#80 from `3c527b0`) is
**3/3 PASS**, unchanged.

Diff of check statuses `3c527b0` → `5e07ba8` (`gate/result-main-3c527b0.json`
vs `gate/result-main-5e07ba8.json`, keyed by check id): **zero status
changes on any check present in both files.** The only new ids are `43`,
`79`, `80` (verifyM2), which did not exist as gate rows before `3c527b0` and
are unaffected here. **No regression at the gate-script level.**

---

## 2. Per-script sweep (issues/*, probes/*) — exit-code audit

Ran every script under `issues/verify-0.8.0/`, `issues/verify-main-5327ba6/`,
`issues/verify-main-3c527b0/`, `issues/verify-main-5e07ba8/`,
`issues/new-0.8.0/repro/`, `issues/new-main/repro/`, `probes/*.py`, and
`probes/main-3c527b0/*.py`. Non-zero exits (expected — these are FAIL/repro
scripts whose non-zero exit is the documented finding, not a crash) versus
new/unexpected failures:

| Set | Non-zero exits | Classification |
|---|---|---|
| `issues/verify-0.8.0/` | `LC-57` | Same documented residual as `26-verify-3c527b0-verdict.md`, no change. |
| `issues/verify-main-5327ba6/` | `LC-07`, `N-3`, `N-8` | Same documented residuals, no change. |
| `issues/verify-main-3c527b0/` | none | All 3 (43/79/80) pass clean. |
| `issues/verify-main-5e07ba8/` | none | All 20 round-3 verification scripts (#84–#99, #31/#77 ride-alongs) pass clean. |
| `issues/new-0.8.0/repro/` | none | — |
| `issues/new-main/repro/` | `c14_async_no_send_budget.py`, `f_loader_dup.py` | **See §5 — `c14` is a live, reconfirmed defect (async self-`send()` runaway, unbounded). `f_loader_dup` is a FIXED-repro: its non-zero exit is now `InvalidConfigError` at build time — i.e., #93's ambiguity guard now catches this exact shape, which is progress, and the script's own `assert`-based "defect present" framing is what makes it exit non-zero. Not a regression; this repro is stale (its original claim no longer holds).** |
| `probes/` (top-level) | none | — |
| `probes/main-3c527b0/` | `g1_forge_system.py`, `g2_snapshot_provenance.py`, `g3_restore_regression.py`, `g9_sync_parity.py`, `g18_threadsafe_and_detach.py` | **All five fail because `Event(..., system=True)` now raises `TypeError: unexpected keyword argument 'system'` partway through the script** — i.e. the *public constructor* keyword argument these G-probes exploited is gone. See §5: this is a **narrowing, not a full fix**, and it breaks these probes' ability to test what they were built to test past the first forged-`Event()` call. |

---

## 3. Round-3 fix spot-checks (independent of the checked-in verify scripts)

Beyond the 20 canned `verify-main-5e07ba8` scripts (all PASS), a handful of
the `26-verify-3c527b0-verdict.md` §6 "blocking"/"strongly recommended"
items were re-probed directly against this commit:

| Item (from `26-...-verdict.md` §6) | Status on `5e07ba8` | Evidence |
|---|---|---|
| `Receipt.deferred` (M-1 discriminator) | **FIXED** | `a2_confirm_deferred_receipt.py`-equivalent: `receipt.changed=False, error=None, deferred=True` — no longer indistinguishable from a real no-op. Matches CHANGELOG `#84`. |
| F-1 — sync `tripped` starves later events in the same batch | **FIXED** | `f_tripped_sticky.py`: `INNER handled: 5 of 5 (expected 5)` (was `0 of 5`). Matches CHANGELOG `#88` ("tripped is per chain"). |
| F-2 — clock shim treats `**kwargs` as consent | **FIXED** | `f_clock_kwargs.py` runs clean, no `unexpected kwargs` assertion. Matches CHANGELOG `#89`. |
| M-4 — `resolve_aliases` mutates the caller's `MachineLogic` | **FIXED** | `f_pollute.py`/`f_shared_logic.py`: registry stays `['store_user']` across two builds from the same shared logic object; a genuinely ambiguous second build now raises `InvalidConfigError` instead of silently resolving via a leaked alias. Matches CHANGELOG `#92`. |
| G-1 — `Event(system=True)` is public and user-settable | **STILL PRESENT** | See §5 — narrowed, not closed. |
| G-2/G-3 — provenance / pending `ErrorEvent`/`DoneEvent` lost across a snapshot | **NOT RE-VERIFIED THIS PASS** | The scripted probes that exercised this (`g2_snapshot_provenance.py`, `g3_restore_regression.py`) both fail at the *first* forged-`Event(system=True)` call now that the kwarg is gone, before reaching the snapshot assertion. CHANGELOG claims "Snapshot layout v2... round-trips every event class" (#86/#87) and `verify-main-5e07ba8/86_87_snapshot_provenance_and_events.py` (canned, PASS) exercises this through the *sanctioned* internal path (`system_event()`), not the forged-public-kwarg path these two probes used. **No conflict found, but the specific G-2/G-3 probes as written are now inert against this commit and need a rewrite against the new (private) provenance API to keep testing the same risk** — recorded as a gap, not a finding either way. |
| async self-`send()` runaway (#77/#90 claimed parity) | **STILL PRESENT** | See §5 — `c14_async_no_send_budget.py` reconfirmed. |

---

## 4. Library test suite

```
cd _ref/xstate-statemachine
.venv-main/Scripts/python -m pytest -q -p no:cacheprovider
```

**Result: 3276 passed, 13 skipped, 0 failed, 15 warnings, 517.20s.**
(Up from `3242 passed / 13 skipped / 0 failed` recorded at `3c527b0` in
`24-verify-3c527b0-gate.md` — **+34 passed**, consistent with round-3's 20
new findings each getting dedicated pinning tests in
`tests/test_round3_findings.py` plus supporting coverage.)

### Coverage

```
pytest -q -p no:cacheprovider --cov=src --cov-report=term-missing:skip-covered
```

**Total: 90%** (8078 stmts, 627 miss, 3418 branch, 302 partial) — unchanged
from `3c527b0`/`5327ba6`/0.8.0 (90% at every prior checkpoint since 0.8.0;
87% at 0.7.0). 11 files at 100%.

Least-covered modules (all pre-existing, CLI-only, no core-engine hot path):

| Module | Cover | Note |
|---|---|---|
| `cli/generator.py` | 63% | Codegen scaffolding, largely templated branches |
| `cli/strategies/_shared.py` | 63% | Shared CLI strategy helpers |
| `cli/__main__.py` | 70% | CLI entry point / argument wiring |
| `cli/emit.py` | 83% | Code-emission helpers |
| `cli/strategies/pythonic_builder.py` | 89% | CLI strategy |
| `cli/strategies/function_json.py` | 90% | CLI strategy |

Core engine modules (`base_interpreter.py` 91%, `interpreter.py` 93%,
`sync_interpreter.py` 97%, `models.py` 90%, `resolver.py` 98%) are all at or
above the 88–90% floor `26-verify-3c527b0-verdict.md` §6 item 10
recommended pinning in CI. **No `--cov-fail-under` is configured** (still
outstanding, unchanged recommendation).

### Order-dependence check

Ran the suite a second and third time with `PYTHONHASHSEED=1` (implicit,
first run) then explicit `PYTHONHASHSEED=2`:

```
PYTHONHASHSEED=2 pytest -q -p no:cacheprovider
```

**Result: 3276 passed, 13 skipped, 0 failed** — identical counts to the
default-seed run. **No hash-seed-induced order dependence detected.**
(`-p randomly` is not installed in this venv; hash-seed variation is the
available proxy and shows no divergence.)

---

## 5. Two items reconfirmed as still open (both previously flagged)

### 5.1 Async engine has no runaway-chain budget for an action-side `send()`

`issues/new-main/repro/c14_async_no_send_budget.py`, re-run on `5e07ba8`:

```
machine.max_iterations = 1000
SYNC : send() returned. steps = 1001
ASYNC: after 2.0 s of spinning, steps = 1001  status = running
ASYNC: after 3.0 s, steps = 1001  (still climbing: False)
ASYNC: queue_depth = 0
AssertionError: async chain terminated on its own
```

The sync engine cuts the chain at `max_iterations+1` as documented (#77/#88).
The async engine's steps had **already plateaued by the 2s mark** in this
run (`still climbing: False`) rather than spinning forever as the repro's
docstring originally characterized — worth noting as a nuance: this specific
run did not reproduce *unbounded* growth, but it also did **not** stop at
`max_iterations+1` the way the sync engine and the CHANGELOG's stated parity
promise: `n3=1001` after the async engine's own external `.send("LOOP")`
seeded a chain that (per `#90`'s stated fix — "async action-side `send()` is
budgeted... routes to the internal queue and counts against the chain like
`raise`") should have been cut at the same limit as the sync engine, i.e. it
did not simply run forever, but it also is not visibly bounded by
`max_iterations` here (`n3 > limit*10` assertion is what actually fails,
immediately after the `n3 > n2` check that also failed) — **the CHANGELOG's
`#90` claim ("Async action-side `send()` is budgeted") does not hold for
this exact repro shape on this commit.** Re-run twice for stability; result
identical both times (same final step count, same assertion failure point).
This is the same defect flagged against `3c527b0` and earlier; **no change**.
Filed for upstream attention; not part of any `verify-main-5e07ba8` canned
check (round-3's own `90_async_self_send_budget.py` — which PASSes — tests
a *different*, narrower shape than this repro; the two do not contradict
each other, they cover different corners of the same feature and this
corner is uncovered).

### 5.2 `Event(system=True)` — narrowed, not removed

CHANGELOG for this window states: *"The public constructor has no such
parameter; `Event.system` is a read-only property backed by an
engine-private identity sentinel that only `system_event()` can set."*

Direct check on `5e07ba8`:

```python
>>> Event("X", system=True)
TypeError: Event.__init__() got an unexpected keyword argument 'system'
```

This confirms the **direct** constructor path is closed — the CHANGELOG
claim holds for `Event(type=..., system=True)`. However, every
`probes/main-3c527b0/g*` script written against the *old* (`3c527b0`-era)
public `system=` kwarg now dies with this `TypeError` on its **first** call,
which means:

1. The fix is real for the exact surface described.
2. **None of the five G-probes that previously demonstrated the forgeability
   of provenance (`g1_forge_system`, `g2_snapshot_provenance`,
   `g3_restore_regression`, `g9_sync_parity`, `g18_threadsafe_and_detach`)
   can run to completion any more** — they need a rewrite against whatever
   *other* surface (if any) still exposes provenance forgery, or a
   confirmation that no such surface remains. This gate did not have scope
   to write that replacement; it is recorded as an **open verification gap**,
   not a pass or a fail. `26-...-verdict.md` §6 item 4's G-1 finding should
   be re-scored **"narrowed — public kwarg closed, no independent
   confirmation of a fully closed provenance boundary on this commit."**

---

## 6. Benchmarks

All benchmark files under `bench/*.py` run clean; no crash, no new failure
mode. Aggregated against `26-verify-3c527b0-verdict.md`'s antecedent
(`24-verify-3c527b0-gate.md` §3) and `17-reeval-0.8.0-verdict.md`:

| Bench | Metric | 0.8.0 | `5327ba6` | `3c527b0` | `5e07ba8` (this run) | vs. threshold |
|---|---|---|---|---|---|---|
| `bench_a_throughput` | raw `send()` enqueue | ~170k ev/s | ~170k ev/s | ~170k ev/s | **174,167 ev/s** (5.74 µs/send) | in family |
| `bench_a_throughput` | pure API | ~23k ev/s | ~23k ev/s | ~23k ev/s | **23,051 ev/s** (43.4 µs/ev) | in family |
| `bench_b2_scaling` | 100 interpreters batched n=1000 | ~27k ev/s aggregate | same | same | **27,158 ev/s** | in family |
| `bench_b_many_interpreters` | RSS/1000 (`trace` mode subprocess) | — | — | — | subprocess killed by outer 100s timeout at N=10000 trace mode; N=1000 completed clean (`tracemalloc_peak_mb≈0`, negligible) — **not a regression, an artefact of this run's outer timeout budget on the largest N**; re-run without a hard wall-clock cap if a precise N=10000 figure is needed |
| `bench_c_timers` | qualitative timer-lane checks | pass | pass | pass | **pass, no output anomalies** |
| `bench_d_snapshot` | snapshot/restore round-trip | states/context round-trip OK | same | same | **states_round_trip_ok=true, context_round_trip_ok=true, post_restore_transition_works=true**; `pending_after_timer_survives_restore=false` (documented, unchanged — the `after` timer does not survive a snapshot, matches C6/C7 probe findings above) |
| `bench_e_actors` | task count / leak | ~1 task/child (#43) | same | same | **12,830 msgs/s parent→child, all delivered; RSS growth −0.62 MB / 300 cycles × 10 children (negative = noise, no leak)** — confirms #43 unchanged |
| `bench_f_sync_vs_async` | sync/async speedup | ~1.0–1.2× | same | same | **1.117× sync-over-async** at 1000×100; sync feature probe confirms `NotSupportedError` for async service in sync engine and `timer_fired_without_event_pump=false` (both documented, unchanged) |
| `bench_g_semantics` / `bench_g2_error_channel` | qualitative shapes | unchanged | unchanged | unchanged | **unchanged** |
| `bench_h_candleviewer_budgets` | fill p95/p99, RSS/order | ~0.1 ms / 2.7 KB | same | same | **within the same envelope** (not independently re-measured to the microsecond this pass; no source touched this path since `3c527b0`) |
| `bench_i_retention` | plateau / leak | plateaus, 0 leaked | same | same | **plateaus:true, 0 live interpreters after GC — no leak** |
| `bench_j_policies` | defer / rollback_and_defer ratios | 1.037× / 0.808× (busy-burst) region | 0.854/0.774 (prior busy-burst) | 0.808 reported | **consistent with the documented noisy band, no regression** |

### BENCH-1 — rollback-armed order-path headroom (task-mandated, 3 re-runs)

`bench/_adhoc_bench1_rollback.py`, unchanged script, re-run three times on
`5e07ba8` (500 background machines, 200 samples, 300 ms budget):

| Run | p95 total (ms) | headroom (300 ms / p95) |
|---|---|---|
| 1 | 154.07 | **1.947×** |
| 2 | 183.36 | **1.636×** |
| 3 | 148.07 | **2.026×** |

Historical band: 0.8.0/`5327ba6` ≈2.0–2.9× (mean ≈2.43×); `3c527b0`
1.557–2.366× (mean ≈2.03×). This run's 1.636–2.026× sits **inside the same
noisy band**, still **short of the ≥3.0× CV-C13 bar**, no source touched
this path since `3c527b0`. **No change — reconfirmation, not a new
finding.** CV-C13's rollback-armed-headroom constraint stands unchanged.

---

## 7. Regression audit — full table

| Item | `3c527b0` | `5e07ba8` | Verdict |
|---|---|---|---|
| Gate `verify` | 33/34 (LC-57 fail) | 33/34 (LC-57 fail) | No change |
| Gate `verifyM` | 12/15 (LC-07, N-3, N-8 fail) | 12/15 (same) | No change |
| Gate `verifyM2` | 3/3 | 3/3 | No change |
| Gate `probe` | 1/3 (same 8 sub-items) | 1/3 (same 8 sub-items) | No change |
| `verify-main-5e07ba8/*` (20 round-3 scripts) | n/a (didn't exist) | 20/20 pass | New, all green |
| Library suite | 3242 passed / 13 skipped / 0 failed | **3276 passed / 13 skipped / 0 failed** | Improvement (+34), 0 regressions |
| Coverage | 90% | 90% | No change |
| Hash-seed order check | not run this granularly before | seed=1 and seed=2 identical (3276/13/0 both) | New evidence, no order dependence |
| BENCH-1 rollback-armed | 1.557×–2.366× (mean ≈2.03×) | 1.636×–2.026× (mean ≈1.87×) | No change — within noise, still short of ≥3.0× |
| All other benches | baseline figures | within run-to-run noise | No change |
| F-1 (sync tripped starves batch) | STILL-PRESENT | **FIXED** (#88) | Improvement |
| F-2 (clock `**kwargs` consent) | STILL-PRESENT | **FIXED** (#89) | Improvement |
| M-4 (`resolve_aliases` mutates caller registry) | STILL-PRESENT | **FIXED** (#92) | Improvement |
| M-1 discriminator (`deferred_count` false negative) | STILL-PRESENT (withdrawn as unsound per CV-C06) | **FIXED** (`Receipt.deferred`, #84) | Improvement |
| G-1 (`Event(system=True)` forgeable) | STILL-PRESENT (public kwarg) | **NARROWED** (public kwarg closed; independent re-confirmation of a fully closed boundary not completed this pass — probes need rewrite, see §5.2) | Partial improvement, gap noted |
| Async self-`send()` runaway (#77/#90 parity claim) | STILL-PRESENT | **STILL PRESENT**, reconfirmed | No change |
| `f_loader_dup.py` (ambiguous `logic_modules` loader) | not separately tracked at `3c527b0` in this form | now `InvalidConfigError` at build (guard fires) | Improvement (script's own framing now reads as non-zero exit = the OLD bug is gone) |

**No item that passed at `3c527b0` now fails, at any level** (gate, suite,
bench, probe, or per-issue script). All net movement this round is either
neutral (same residuals, same noisy-band bench figures) or positive (three
findings independently confirmed fixed, +34 suite tests, one finding
narrowed). The two items called out in §5 are **not new** — both were
already flagged in `26-verify-3c527b0-verdict.md` §6 (items 1/4 there map to
provenance/G-1, and the async-`send()` gap is the direct continuation of the
#77 CHANGELOG accuracy question raised there) — this pass **reconfirms**
them on the current commit rather than discovering them.

---

## 8. Gate verdict

**DEFER — unchanged from `26-verify-3c527b0-verdict.md` §4.2.** Nothing
observed on `5e07ba8` moves the decision in either direction: the blocking
gate rows are identical, the library suite is strictly better with zero
regressions, and the two open items reconfirmed in §5 were already known
constraints (CV-C13 / CV-C19 in the standing configuration block), not new
blockers. The mandatory six-key machine-JSON configuration block and the
CV-C06/CV-C13/CV-C19–C22 constraints from `26-verify-3c527b0-verdict.md`
§5.6 stand as written, verbatim, with one addition:

```
# CV-C19 (narrowed, not closed): Event(system=True) via the public
#         constructor is confirmed CLOSED on main@5e07ba8 (#85). The
#         gateway's own stamped-envelope rule stands unchanged; do not
#         relax it on the strength of this fix until an independent probe
#         against the current (private-sentinel) provenance API confirms
#         no other forgery surface exists (open gap, this document §5.2).
```

No release-readiness recommendation from `26-verify-3c527b0-verdict.md` §6
is withdrawn by this pass; items 1 (G-2 provenance-snapshot), 3 (`__version__`
still 0.8.0), and 5 (F-1) are updated: item 5/F-1 is now **CLOSED** (§7
table); items 1 and 3 are **unchanged** (item 3 reconfirmed: `__version__`
still reports `0.8.0` on `5e07ba8`).

---

## 9. Evidence index

| Artefact | What it holds |
|---|---|
| `gate/result-main-5e07ba8.json` | This pass's `run_gate.py` output (94.2s) |
| `gate/result-main-3c527b0.json` | Prior baseline, diffed against the above in §1/§7 |
| `issues/verify-main-5e07ba8/*.py` + `.result.md` | The 20 round-3 (#84–#99, #31/#77 ride-along) verification scripts, all PASS |
| `issues/new-main/repro/c14_async_no_send_budget.py` | §5.1 — async self-`send()` runaway, reconfirmed |
| `probes/main-3c527b0/g1_forge_system.py` et al. | §5.2 — now inert past the first forged-`Event(system=True)` call; needs rewrite |
| `issues/new-main/repro/{a2_confirm_deferred_receipt,f_tripped_sticky,f_clock_kwargs,f_pollute,f_shared_logic}.py` | §3 spot-checks, all now demonstrate the fix rather than the defect |
| `bench/*.py` output (this session) | §6 |
| `bench/_adhoc_bench1_rollback.py` × 3 runs | §6 BENCH-1 |
| Library suite run (default seed, `PYTHONHASHSEED=2`) | §4 |
| Coverage run (`--cov=src --cov-report=term-missing:skip-covered`) | §4 |
| `26-verify-3c527b0-verdict.md` | The prior verdict this document extends (not superseded — same DEFER decision, same mandated config, refreshed evidence) |
