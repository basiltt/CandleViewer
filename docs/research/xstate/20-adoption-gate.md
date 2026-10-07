# 20 — Adoption Gate: the re-analysis procedure for each new release

**Scope.** This is the exact, repeatable procedure to run against every new
release of `xstate-statemachine` to decide whether CandleViewer may build on it.
It is written to be executed by someone who was not part of the original study.

**Baseline under evaluation (current):** `main` @ commit **`de2da4e`** (unreleased
0.8.1, merge of PR #223, `fix/0.8.1-round11`; `__version__` still reports `0.8.0` —
**key the baseline on the commit, never on the version string**, twelfth consecutive
round), Python 3.13.7, Windows 11.
**Baseline result (round 12, 2026-09-23):** 5 issues verified — **all five FIXED
(#218–#222)**, 0 partial, 0 not-fixed, 0 regressed-on-one-axis, and **3 of the 5
carry no scope residual at all** (a first). **Zero true regressions** across 168
gate checks and a 573-script sweep — the sixth consecutive round. Post-refutation
the **library** board is **0 Blocker · 0 High · 3 Medium · 6 Low** → **ADOPT WITH
CONSTRAINTS, decision-table ROW 8**, **up two rows** from round 11's row 6 and level
with round 10, on **all four lifecycle families including the order path**.
**The High row is empty for the first time since round 10:** round-11's single open
High (R11-04, the unbounded `_timer_handles` leak) is closed **at the mechanism** by
#218 — 93,168 beats at `handles_max_per_machine = 1` with **RSS Δ 0.00 MB**, against
**+753 MB** on the identical script last round. **Coverage was measured at the commit
under test for the first time in four rounds:** the full suite completed —
**3545 passed, 13 skipped, 0 failed, 92.87 %** — so row 2 no longer rests on a stale
carry-over. **Row 9 is refused on the record: BENCH-6 is unmeasured for a fifth
consecutive round** (and BENCH-1/BENCH-2 joined it), and *unmeasured* is not *met*.
**Two constraints RETIRE (CV-C47, CV-C61)** — the first retirement in this study
driven by a defect being **fixed at the mechanism** rather than superseded — and
**two are new (CV-C63, CV-C64)**. **Would we pin a tag cut here? Yes, with nothing
required to land first — recommendation: cut and tag 0.8.1 at `de2da4e`, bumping
`__version__` in the same commit.** See the round-12 entry in §9's run log and
`69-r12-final-readiness-verdict.md`.

**Previous baseline:** `main` @ commit **`c78ce99`** (unreleased 0.8.1, merge of
PR #217). **Baseline result (round 11, 2026-09-22):** 5 issues verified — all five
FIXED (#212–#216); post-refutation **0 Blocker · 1 High · 4 Medium · 5 Low** →
**ADOPT WITH CONSTRAINTS, decision-table row 6** (down one row from round 10).
The single open High, **R11-04**, was contained by **CV-C47** — which is the whole
difference between row 6 and row 7 — and is **closed by #218 at `de2da4e`**. The
full suite did not complete for the third consecutive round, so row 2 rested on a
one-commit-stale 92.78 %. See `64-r11-final-readiness-verdict.md`.

**Previous baseline:** `main` @ commit **`f28719c`** (unreleased
0.8.1, merge of PR #202; `__version__` still reports `0.8.0` — **key the baseline
on the commit, never on the version string**), Python 3.13.7, Windows 11.
**Baseline result (round 9, 2026-09-22):** 12 issues verified — 11 fixed in code
(9 clean, 2 narrower than claimed), 1 partial, 0 not-fixed; **zero true PASS→FAIL
regressions** (the single gate flip, `LC-42`, is a flaky sub-millisecond latency
threshold, 4/5 PASS); post-refutation **0 Blocker · 2 High · 5 Medium · 8 Low**
→ **ADOPT WITH CONSTRAINTS**, decision-table **row 6**, on **all four lifecycle
families including the order path**. **The Blocker row is empty for the first
time**: round-8's R8-01 is closed by #192, and R9-01 was refuted Blocker→Low.
Both open Highs (**R9-02**, **R9-04**) carry mechanically enforced mitigations
(CV-C45 widened, CV-C32 + new CV-C46) and named contract tests. **Coverage was
not measured this round** — the `--cov` run did not finish inside the wall-clock
bound (~51 % of tests observed green; 92.70 % at `6db65d8`). Row 2 keys on
coverage, so this is recorded as an **open measurement, not a pass**, and is the
first item of the round-10 recipe. See the round-9 entry in §9's run log and
`54-r9-final-readiness-verdict.md`.

**Previous baseline:** `main` @ commit **`6db65d8`** (unreleased
0.8.1, merge of PR #191; `__version__` still reports `0.8.0`).
**Baseline result (round 8, 2026-09-21):** 16 issues verified — 15 fixed in code,
1 documentation-only, 0 not-fixed; suite 3 457 passed at **92.70 %** coverage;
**zero true PASS→FAIL regressions**; post-refutation **1 Blocker · 3 High ·
7 Medium · 4 Low** → **DEFER (order path) / GO (non-order paths under
constraints)**, decision-table row 4. **Row 6 (ADOPT WITH CONSTRAINTS) is
otherwise satisfied** — open-High is 3 against a bar of 5 — so closing the single
Blocker **R8-01** flips the verdict. See the round-8 entry in §9's run log and
`49-r8-final-readiness-verdict.md`.

**Previous baseline:** `main` @ commit **`5327ba6`** (unreleased, pre-0.8.1).
32/34 primary `verify` checks pass (13/34 secondary `repro` at defaults), probes
43/51-equivalent, 5 of 7 benchmark thresholds met, **no regressions** →
**ADOPT WITH CONSTRAINTS, CONDITIONAL** (see §9.3 and `22-verify-main-verdict.md`).

**Previous baseline:** `0.8.0` (commit `9bf6065`) — 12/34 repros pass
unconditionally (+9 verified fixed-but-opt-in), probes 43/51, 5 of 7 thresholds
met → **ADOPT WITH CONSTRAINTS, CONDITIONAL** (§9.1).

**Original baseline:** `0.7.0` (commit `42612cf`) — 34/34 repros reproduce,
probes 41/51, 2 of 7 thresholds met → **DEFER**. Retained in §9 as the
comparison row and in `run_gate.py` as `PROBE_BASELINE_FAILURES_0_7_0`.

> **Classification rule, added for the 0.8.0 run and binding from here on.**
> From 0.8.0 the library fixes defects as **per-machine policies whose default
> preserves the previous semantics**. A repro that still exits 1 must therefore be
> triaged into *unfixed*, *fixed-but-opt-in*, or *stale repro* — never assumed
> unfixed from the exit code alone. A **FIXED-OPT-IN** row counts as closed
> **only** while the option it needs is mandated in the machine-config block and
> that mandate is enforced by the linter. See §9 and
> `17-reeval-0.8.0-verdict.md` §4.

**Governing rule** (from `issues/00-META-candleviewer-adoption-readiness.md` §3):

> All Blocker and High items closed; all Medium items triaged.
> A defect is closed when its repro script exits 0 — never by a changelog entry.

---

## 0. Time budget

| Step | Cost |
|---|---|
| 1. Install & pin | 5 min |
| 2. Repros + probes (`run_gate.py`) | ~3 min |
| 3. Benchmarks (`--with-bench`) | 25–40 min |
| 4. Library's own suite | ~10 min |
| 5. Docs diff | 15 min |
| 6. Decision & write-up | 30 min |
| **Total** | **~1.5 h** |

Steps 1–4 are mechanical. Do not skip step 5: a fix can land without a repro
noticing, and a *behaviour change* can land that no repro covers.

---

## 1. Install the pinned version

Use a dedicated venv, never the ambient interpreter. Record everything.

```bash
# Windows / Git Bash. Adjust the version under test.
VER=0.8.0
ROOT="<workspace>/CandleViewer/docs/research/xstate"
VENV="<workspace>/_ref/xstate-statemachine/.venv-gate-$VER"

python -m venv "$VENV"
"$VENV/Scripts/pip" install --quiet "xstate-statemachine==$VER"
"$VENV/Scripts/pip" install --quiet psutil          # required by bench_b / bench_h

# Record the exact identity of what is under test.
"$VENV/Scripts/python" -c "import xstate_statemachine as x, sys; \
print('version', x.__version__); print('python', sys.version)"
"$VENV/Scripts/pip" hash "$(pip download xstate-statemachine==$VER -d /tmp/xsm --no-deps -q && ls /tmp/xsm/*.whl)"
```

**Record in the run log:** version string, wheel sha256, git commit sha (from the
GitHub release tag), Python version, OS, CPU model, and whether the machine was
otherwise idle. The benchmark numbers are meaningless without the last two.

> To evaluate an unreleased commit instead, clone at that sha and
> `pip install -e .` — but note the sha in the log, and never mix an editable
> install with a released-version claim.

---

## 2. Repros and probes — the correctness gate

```bash
cd "$ROOT"
"$VENV/Scripts/python" gate/run_gate.py --json "gate/run-$VER.json"
```

### How to read it

`run_gate.py` normalises three different conventions into one table. The critical
inversion to understand:

> **Repro scripts exit 1 when the defect is still present** and **0 once it is
> fixed.** The gate reports `PASS` only on exit 0. On 0.7.0 the gate therefore
> prints **34 FAILs — that is the correct expected baseline, not a broken
> harness.**

| Row kind | `PASS` means | `FAIL` means |
|---|---|---|
| `LC-xx` (repro) | Defect gone — repro exited 0 | Defect reproduced — repro exited 1 |
| `PROBE-0x` | Every probe in the file passes | A probe outside the recorded baseline regressed, or baseline failures remain |
| `BENCH-x` | Metric met its threshold | Metric missed its threshold |
| `ERROR` (any row) | — | **Harness failure, not a result.** The API the script exercises changed. Repair the script before concluding anything. |

`IMPROVED` on a probe row means a previously-failing probe now passes — a good
signal that warrants updating `PROBE_BASELINE_FAILURES` in `run_gate.py`.

### Required outcome for the gate

* Every `LC-xx` row mapped to a **Blocker** or **High** register row must be `PASS`.
* No `PROBE-0x` row may be `FAIL` due to a **regression** (a newly-failing probe id).
* Zero `ERROR` rows. An `ERROR` invalidates that row entirely.

### Useful invocations

```bash
# Re-check only the items a release claims to have fixed.
"$VENV/Scripts/python" gate/run_gate.py --only LC-01,LC-02,LC-03

# Longer timeout for slow hardware (default 900 s per script).
"$VENV/Scripts/python" gate/run_gate.py --timeout 1800
```

### 2b. Run the repros by hand when a row changes state

When a repro flips to exit 0, **read its output before believing it.** Each script
prints `OBSERVED` / `EXPECTED` lines. Confirm the defect is genuinely fixed rather
than the probe being defeated by an unrelated API change (e.g. a renamed attribute
making a check vacuously true):

```bash
"$VENV/Scripts/python" issues/repro/LC-01_action-raise-commits-transition.py
```

---

## 3. Benchmarks — the performance gate

```bash
cd "$ROOT"
"$VENV/Scripts/python" gate/run_gate.py --bench-only --json "gate/bench-$VER.json"
```

Run on an **otherwise idle machine**. These measure event-loop contention, which
is exactly what other processes perturb.

### Thresholds and their rationale

| ID | Metric | Rule | Threshold | 0.7.0 | Why this number |
|---|---|---|---:|---:|---|
| **BENCH-1** | Order path: submit→open p95 headroom vs the 300 ms budget, with 500 background machines churning | ≥ | **3.0×** | 1.81× ❌ | The engine alone consumes 165 ms p95 *before* any network. A Bybit round trip is 50–150 ms. 3× headroom is what makes the budget survive a burst rather than merely meeting it on a quiet loop. |
| **BENCH-2** | Rule-lifecycle market event rate (1,000 rule machines, 100 rules × 10 symbols) | ≥ | **2,000 ev/s** | 288 ev/s ❌ | 2,000 ticks/s × 100 rules = 200k rule evals/s required; both engines deliver ~30k. Passing this would retire the mandatory ≥99% pre-filter (LC-40). |
| **BENCH-3** | Memory per quiescent open order (500 resident) | ≤ | **8 KB** | 1.08 KB ✅ | Passes comfortably. Guards against a regression that makes resident orders expensive. |
| **BENCH-4** | Peak RSS with 10,000 live interpreters | ≤ | **1,200 MB** | 1,055 MB ✅ | A single trading process must hold a full day's order population inside a 1.2 GB working set. |
| **BENCH-5** | `after 100 ms` p95 drift, idle loop | ≤ | **25 ms** | 15.1 ms ✅ | Windows' event-loop timer granularity is ~15.6 ms — a platform floor, not the library's fault. 25 ms is that floor plus margin. |
| **BENCH-6** | `after 100 ms` p95 drift, 500 busy interpreters | ≤ | **100 ms** | 2,530 ms ❌ | **The headline risk (LC-26).** Absolute error is ~constant regardless of requested delay — loop starvation. Passing this retires the external `MonotonicScheduler` requirement (house rule A2). |
| **BENCH-7** | Single-interpreter throughput, 50k burst | ≥ | **30,000 ev/s** | ~31,000 ✅ | A regression guard, not an aspiration. Dropping below means a hot-path regression landed. |

### Interpreting a benchmark FAIL

Benchmark thresholds are **hardware-sensitive**. Before treating a marginal miss
as a gate failure:

1. Re-run it — event-loop benchmarks are noisy; take the better of three.
2. Compare against the *same host's* recorded 0.7.0 baseline, not the study's
   numbers. If no such baseline exists, produce one by installing 0.7.0 in a
   second venv and running `--bench-only` there.
3. Only BENCH-1, BENCH-2 and BENCH-6 are architectural (they decide whether a
   whole design approach is viable). BENCH-3/4/5/7 are regression guards: a miss
   there is a bug report, not an adoption decision.

---

## 4. The library's own test suite

```bash
cd "<workspace>/_ref/xstate-statemachine"
git fetch --tags && git checkout "v$VER"     # read-only checkout of the tag
"$VENV/Scripts/pip" install --quiet pytest pytest-cov pytest-asyncio
"$VENV/Scripts/python" -m pytest -q --cov --cov-branch
```

**0.7.0 baseline (verbatim):**

```
=========== 2805 passed, 2 skipped, 1 warning in 569.61s (0:09:29) ============
TOTAL: 6651 stmts, 697 miss, 2918 branch, 315 partial → 87% cover
```

Record and compare:

| Check | Baseline | Fail the step if |
|---|---|---|
| Passing tests | 2,805 | Any failure or error |
| Skips | 2 | Skips grow without explanation |
| Aggregate coverage | 87% | Drops below the CI gate of 86% |
| `base_interpreter.py` coverage | 86% | Drops — this is the largest file (890 stmts) and its misses are concentrated in exactly the rollback/cancellation branches CandleViewer leans on hardest |
| Wall clock | ~9.5 min | — (informational) |

A green suite here is **necessary but not sufficient**: 2,805 passing tests
coexisted with all 34 defects in this register. Never substitute this step for
step 2.

---

## 5. Diff the upstream documentation

```bash
cd "<workspace>/_ref/xstate-statemachine"
git diff "v0.7.0".."v$VER" -- docs/FEATURE_GAP_ANALYSIS.md
git diff "v0.7.0".."v$VER" -- CHANGELOG.md
git diff "v0.7.0".."v$VER" --stat -- src/
```

For each change, answer three questions and record the answers:

1. **Does it close a register row?** If yes, confirm with the repro (step 2b).
   A `FEATURE_GAP_ANALYSIS` row moving to "closed" is a *claim*; the repro is the
   *evidence*.
2. **Does it change behaviour a repro depends on?** If yes, the repro may now be
   measuring the wrong thing — repair it, then re-run.
3. **Does it introduce a new risk not in the register?** Particularly: changes to
   target resolution, the action-execution loop, the event queue, timer
   scheduling, or snapshot format. Add a new register row and write a repro
   before adopting.

Also check whether the snapshot format changed. Our persisted snapshots carry no
schema version (LC-21), so a format change is a **silent restore-compatibility
break** for every order persisted under the previous version. This is a
DEFER-level finding on its own until LC-21 closes.

---

## 6. Update the register

Before deciding, bring the paperwork into line with what was just measured:

1. For each closed defect: annotate its `issues/LC-xx-*.md` front-matter with
   `fixed_in: <version>` and `verified_date:`, tick its box in the meta-issue,
   and **delete the corresponding CandleViewer mitigation plus its workaround
   test** — carrying dead complexity is how a mitigation outlives its defect and
   becomes folklore.
2. Update `PROBE_BASELINE_FAILURES` in `gate/run_gate.py` for any probe that
   newly passes, so the next run treats a re-regression as a regression.
3. Recount the register by severity and update `00-README.md`.

---

## 7. Decision table

Apply in order; the **first** matching row wins.

| # | Condition | Decision |
|---|---|---|
| 1 | Any `ERROR` row in the gate output | **DEFER** — the evidence is invalid. Repair the harness and re-run; do not decide on a broken measurement. |
| 2 | Library's own suite fails, or coverage drops below 86% | **DEFER** — upstream quality signal has regressed. |
| 3 | Snapshot format changed while LC-21 (no schema version) is open | **DEFER** — silent restore-compatibility break for persisted orders. |
| 4 | Any filed **Blocker** repro still exits 1 (LC-01, LC-02, LC-03, LC-16) | **DEFER** — no live-trading path. Non-order-path prototyping is permitted in a sandbox with no real credentials. |
| 5 | All Blockers closed; **> 5 High** still open | **DEFER** — the mitigation surface is larger than the library's value. |
| 6 | All Blockers closed; **1–5 High** open, each with a mechanically enforced mitigation and a passing test in `tests/xstate_contract/`; all Medium triaged | **ADOPT with constraints** — list every open High and its enforcing mechanism explicitly in the decision record. |
| 7 | All Blockers closed; **1–5 High** open **without** enforced mitigations | **DEFER** — a documented convention is not a mitigation. |
| 8 | All Blocker and High closed; all Medium triaged; BENCH-1/2/6 not all met | **ADOPT with constraints** — the architectural constraints below apply. |
| 9 | All Blocker and High closed; all Medium triaged; all benchmark thresholds met | **ADOPT** — unconstrained, on all four lifecycle families. |

### Constraints to list under "ADOPT with constraints"

Name each one that applies, with its owner and its enforcing test. These are the
standing ones implied by the benchmark thresholds:

| If this is unmet | The constraint is |
|---|---|
| **BENCH-1** (order path headroom < 3×) | The order path runs on a **dedicated event loop / process** with no rule or market-data traffic on it. Enforced by a startup assertion on loop identity. |
| **BENCH-2** (rule rate < 2,000 ev/s) | Statecharts own rule **lifecycle only**; per-tick predicate evaluation is a plain function pass behind a **≥99% pre-filter**. Enforced by a benchmark test in CI. |
| **BENCH-6** (timer drift under load) | `after` is used only for coarse, non-critical timeouts where seconds of lateness is tolerable. All algo timing (TWAP intervals, chase repricing, iceberg release) uses an **external `MonotonicScheduler`** with absolute deadlines in context. Enforced by a linter rule banning `after` in algo machine definitions. |
| **LC-27** open (no clock injection) | Replay/backtest cannot use `after` at all; virtual time is supplied entirely by the external scheduler. |
| **LC-43** open (cross-thread send lost) | All `send()` calls originate on the owning loop; cross-thread submission goes through `run_coroutine_threadsafe`. Enforced by a contract test. |

### Record the decision

Write the outcome into `00-README.md` and the meta-issue header as:

```
Gate run <date> — xstate-statemachine <version> — DECISION: <ADOPT | ADOPT with constraints | DEFER>
  repros   : <n>/34 pass
  probes   : <n>/51 pass
  benches  : <n>/7 thresholds met
  suite    : <n> passed, <coverage>%
  blockers open: <list>   high open: <list>
  constraints  : <list, if any>
  decided by   : <name>
```

---

## 8. Escape hatch: partial adoption

If the gate says DEFER but the library is otherwise attractive, one path is
legitimate and one is not.

**Legitimate.** Adopt on a **non-order path only** — replay/backtest, or the rule
runtime's lifecycle layer — where a silent no-op costs a wrong chart, not money.
This still requires: all Blockers affecting *that* path closed, the contract
suite in place, and an explicit written boundary saying which machines may and
may not touch orders.

**Not legitimate.** Adopting on the order path with "we'll be careful" as the
mitigation. Every Blocker in this register is a *silent* failure; carefulness is
not a control that detects silence. That is the whole reason the gate exists.

---

## 9. Run log

One row per gate run. Append, never edit a recorded row.

| Date | Version | Commit | repros | probes | benches | Suite | Decision |
|---|---|---|---|---|---|---|---|
| 2026-09-15 | 0.7.0 | `42612cf` | 0/34 | 41/51 | 2/7 | 2805 P / 2 S, 87% | **DEFER** |
| 2026-09-17 | 0.8.0 | `9bf6065` | 12/34 uncond. + 9 opt-in | 43/51 | 5/7 | 3170 P / 13 S, 0 F | **ADOPT with constraints, conditional** |
| 2026-09-18 | *(unreleased, pre-0.8.1; `__version__` reports 0.8.0)* | `5327ba6` | verify 32/34 · repro 13/34 | 43/51-equiv. | 5/7 | 3234 P / 13 S, 0 F, 90% | **ADOPT with constraints, conditional** |
| 2026-09-22 | *(unreleased, pre-0.8.1; `__version__` reports 0.8.0)* | `c78ce99` | gate 163: 124 P / 39 F | sweep 527: 444 P / 83 F | BENCH-6 unmeasured (4th rd) | **not completed** (~4%); row 2 on stale 92.78% | **ADOPT with constraints — ROW 6** (down from row 8) |
| **2026-09-23** | *(unreleased, pre-0.8.1; `__version__` reports 0.8.0 — 12th rd)* | **`de2da4e`** | **gate 168: 128 P / 40 F** (6 new, all PASS) | **sweep 573: 476 P / 94 F / 3 T**; **0 true regressions** | **BENCH-1/2/6 unmeasured (BENCH-6 5th rd)** → **row 9 refused** | **3545 P / 13 S / 0 F, 92.87% — COMPLETE, at the commit** | **ADOPT with constraints — ROW 8** (up two; 0 Blocker · 0 High) |
| **2026-09-24** | **0.9.1** (tag `v0.9.1` = `45bb7f3`, PyPI, PEP 740 attested) | **`801eacd`** (≡ tag) | gate: 0 ERROR, FAIL set = baseline (167 load-flake, idle PASS) | sweep: **0 true regressions, 0 T** | BENCH-6 MET p99 92.2 ms; BENCH-1 unmeasured (last 3.17×); BENCH-2 380.9 ev/s ❌ (architectural) | **3601 P / 13 S / 0 F, 92.93%** | **ADOPT with constraints — ROW 8** (0 Blocker · 0 High · 1 Medium R14-01 → CV-C68); see `79-r14-final-readiness-verdict.md` |

### 9.1 Run 2026-09-17 — `xstate-statemachine` 0.8.0 ("Fortify")

```
Gate run 2026-09-17 - xstate-statemachine 0.8.0 (9bf6065) - DECISION: ADOPT WITH CONSTRAINTS, CONDITIONAL
  repros   : 12/34 pass unconditional; 9 verified fixed-but-opt-in; 13 stale/triaged; 0 unfixed
  probes   : 43/51 pass
  benches  : 5/7 thresholds met
  suite    : 3170 passed, 13 skipped, 0 failed, 19 warnings (463.8 s)
  blockers open: none, CONDITIONAL on LC-01/LC-03 mandated config being lint-enforced
  high open    : LC-07, LC-26, LC-38, LC-43
  new defects  : N-1..N-17 (2 High, 9 Medium, 6 Low, 0 Blocker)
  constraints  : CV-C01..CV-C15
  condition    : E29-T10 linter + tests/xstate_contract/ green before the first
                 live-path statechart. Until then the operative decision is
                 DEFER for the order path; non-order paths may proceed under section 8.
  decided by   : Architect
```

**Environment.** CPython 3.13.7, Windows 11 Pro 10.0.26200, Intel64 Family 6
Model 142 (4 physical / 8 logical cores, 1992 MHz base), 15.9 GB RAM, machine
otherwise idle. Local clone at `9bf6065`, `pip install -e .` into `.venv-gate`.
`pytest`, `pytest-cov`, `pytest-asyncio` and `psutil` were installed for the run;
library source was not modified.

**Decision-table walk.** Rows 1–3 do not trip (zero `ERROR` rows; suite green;
the snapshot format changed *and* LC-21 closed in the same release, loudly, with
`SnapshotVersionError`/`SnapshotDriftError`). Row 4 does not trip: all four filed
Blockers are closed — **but LC-01 and LC-03 only as FIXED-OPT-IN**. Row 5 does not
trip (4 High open, ≤5). **Row 6 is the match, with its precondition unmet:** each
open High has a specified enforcing mechanism, but `tests/xstate_contract/` and
the `E29-T10` linter do not exist yet, so today the honest reading is row 7 —
*"a documented convention is not a mitigation."* The conditional wording above
records exactly that, rather than claiming row 6 prematurely.

**Benchmark detail.**

| ID | 0.7.0 | 0.8.0 | Bar | Verdict |
|---|---:|---:|---:|---|
| BENCH-1 order-path headroom | 1.81x | 3.17x | ≥3.0x | PASS (was FAIL) |
| BENCH-2 rule-lifecycle ev/s | 288 | 380.9 | ≥2000 | FAIL |
| BENCH-3 500-order memory | 1.08 KB | 3.32 KB | ≤8.0 KB | PASS (headroom shrank 3x) |
| BENCH-4 10k-interp RSS | 1055 MB | 594.8–1164.9 MB | ≤1200 MB | PASS (marginal) |
| BENCH-5 idle timer drift | 15.1 ms | 14.98 ms | ≤25 ms | PASS |
| BENCH-6 loaded timer drift | 2530 ms | 174.4 ms | ≤100 ms | FAIL (14.5x improved) |
| BENCH-7 throughput guard | 30,662 | 34,467 | ≥30,000 | PASS |

**New finding that changes how BENCH-1 must be read.** `bench_j_policies.py`
(added this run) measures the mandated policies *armed but never firing*:
`actionErrorPolicy="rollback"` costs **-22.4%** throughput (35,532 → 27,586 ev/s);
`onUnhandled="defer"` costs -1.7%. So BENCH-1's 3.17x headroom is **~2.46x** in the
configuration we are required to run, which is **below the 3.0x bar**. Constraint
CV-C13 records this as accepted, and future runs must report BENCH-1 both ways.

**Probe baseline changes.** `run_gate.py::PROBE_BASELINE_FAILURES` updated:

```
01_core_transitions:             ["A3","A5","A6","A10"] -> ["A3","A6","A10","A18"]
02_invoke_timers_history:        []                     -> []
03_context_snapshot_determinism: ["C6","C7","C10","C15","C16","C17"] -> ["C6","C7","C15","C17"]
```

Removed (genuine fixes): `A5` (#31 `.child`), `C10` (#36 internal event queue),
`C16` (#40 `sendTo` by id). Added: `A18` — the deliberate `strict_targets`
default-on behaviour change, **not a regression**; the probe encoded pre-0.8.0
silent-ignore semantics the library no longer permits.

**Outputs.** `17-reeval-0.8.0-verdict.md` (verdict, mandatory configuration, new
defects, constraints), `13`–`16` (bench / probes / adversarial / diff),
`issues/verify-0.8.0/*.result.md`, `issues/new-0.8.0/` (5 drafts + repros),
`issues/followups-0.8.0/` (11 drafts). Nothing was filed upstream.

### 9.2 Standing amendments to this procedure

1. **§2's "required outcome" is amended.** "Every `LC-xx` row mapped to a Blocker
   or High must be `PASS`" is necessary but no longer sufficient, and is no longer
   sufficient in the other direction either: a `FAIL` may be a fixed-but-opt-in
   row or a stale repro. Every non-`PASS` row on a Blocker or High must be
   triaged into one of the four classifications in
   `17-reeval-0.8.0-verdict.md` §0, in writing, before the decision table is applied.
2. **The primary check set is now `issues/verify-0.8.0/*.py`**, which exercise the
   *mandated configuration*. The original `issues/repro/*.py` exercise the
   *defaults* and are retained as a secondary, informational set — they answer
   "what does an unconfigured caller get?", which is a real question but not the
   gate's question. `run_gate.py` reports both, and only the primary set is
   blocking.
3. **A FIXED-OPT-IN Blocker is closed only while its option is lint-enforced.**
   If CV-LINT-XS1/XS2 are removed, disabled or not yet shipped, LC-01 and LC-03
   revert to open Blockers and decision-table row 4 applies.
4. **BENCH-1 must be reported twice** — at defaults and with the mandated policy
   block armed. The second number is the one that governs.

### 9.3 Run 2026-09-18 — `main` @ `5327ba6` (unreleased, pre-0.8.1)

> **Baseline key.** This build is identified **by commit**. `__version__` still
> reports `0.8.0` while `CHANGELOG.md` targets `0.8.1`, so any pin, baseline or
> CI assertion keyed on the version string will silently confuse the two.
> `run_gate.py` now records and prints a commit alongside the version and keys
> its baseline on `BASELINE_COMMIT`.

```
Gate run 2026-09-18 - xstate-statemachine main @ 5327ba6 (unreleased, pre-0.8.1)
DECISION: ADOPT WITH CONSTRAINTS, CONDITIONAL (unchanged in form from 0.8.0)
  verify   : 32/34 primary pass (PRIMARY -- mandated config, blocking)
             FAILs: LC-28 (#43), LC-57 (#60/LC-52) -- both unchanged partials
  repro    : 13/34 pass (SECONDARY -- defaults, informational)
  probes   : 43/51-equivalent, identical baseline (A3 A6 A10 A18, C6 C7 C15 C17)
  adversarial: 57 purpose-built probes in 8 suites; 5 of 8 claim clusters solid
  benches  : 5/7 thresholds met -- BENCH-1 armed 2.43x (bar >=3.0x),
             BENCH-2 and BENCH-6 still missed; same pattern as 0.8.0
  suite    : 3234 passed, 13 skipped, 0 failed (was 3170)
  coverage : 90% (was 87% at 0.7.0; not separately measured at 0.8.0)
  regressions  : NONE
  blockers open: none (LC-01, LC-03 remain FIXED-OPT-IN -- closed only while
                 CV-LINT-XS1/XS2 enforce the mandated config)
  high open    : LC-07/#31 (narrowed to strict_targets=False parity), M-1, F-1, F-2
  new defects  : 13 (3 High, 6 Medium, 3 Low, 1 Info, 0 Blocker)
  constraints  : CV-C01..CV-C18
                 RETIRED: CV-C06 fresh-Event clause, CV-C14 gateway-validation clause
                 NEW    : CV-C16 (no self-send in actions), CV-C17 (chain depth),
                          CV-C18 (one MachineLogic per machine)
  condition    : E29-T10 linter + tests/xstate_contract/ green before the first
                 live-path statechart. NOTHING UPSTREAM BLOCKS NON-ORDER PATHS.
                 Order path additionally DEFERRED until M-1 is fixed upstream or
                 covered by the CV-C06 deferred_count clause.
  decided by   : Architect
```

**Environment.** CPython 3.13.7, Windows 11 Pro 10.0.26200. Local clone at
`5327ba69fb735cfe24c7b3772050dac0a71a7b3d`, `pip install -e .` into
`.venv-main`; `pytest`, `pytest-asyncio`, `pytest-cov` and `psutil` installed
for the run. Every command run with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.
Library source was not modified. No `git` command was run in the CandleViewer
repository; nothing was filed upstream.

**Decision-table walk.** Rows 1–3 do not trip (zero `ERROR` rows; suite green;
coverage rose to 90%; no snapshot-format change). Row 4 does not trip on the
merits — all four Blockers closed — but LC-01 and LC-03 remain **FIXED-OPT-IN**,
so under §9.2 amendment 3 they revert to open Blockers until the linter ships;
that keeps row 4 live **for the order path only**. Row 5 does not trip (4 High
open, ≤5). **Row 6 is the match with its precondition still unmet** — each open
High has a *specified* enforcing mechanism but `tests/xstate_contract/` and
`E29-T10` do not exist, so the honest reading remains row 7. The conditional
wording records exactly that.

**The condition is ours, not upstream's.** This is the material change from the
0.8.0 run. Every Blocker is closed; both 0.8.0-era High defects that lacked a
mitigation are fixed; two constraints retired into the library. The remaining
upstream items (#31, #43, #77, #79, #80) are each behind an opt-out we never
take, a capacity-planning line item, an ergonomics gap, or a namespace CV-C15
already bans. **Once `E29-T10` and `tests/xstate_contract/` are green, non-order
adoption is unconditional.**

**Benchmark detail.**

| ID | 0.7.0 | 0.8.0 | `5327ba6` | Bar | Verdict |
|---|---:|---:|---:|---:|---|
| BENCH-1 order-path headroom (defaults) | 1.81x | 3.17x | 2.275x* | ≥3.0x | noisy; no source change on this path |
| BENCH-1 **armed `rollback`** (governing) | — | ~2.46x | **2.43x** (2.02–2.87 over 4 runs) | ≥3.0x | FAIL — reconfirmed, not a regression |
| BENCH-2 rule-lifecycle ev/s | 288 | 380.9 | unchanged | ≥2000 | FAIL |
| BENCH-3 500-order memory | 1.08 KB | 3.32 KB | unchanged | ≤8.0 KB | PASS |
| BENCH-4 10k-interp RSS | 1055 MB | 594.8–1164.9 MB | unchanged | ≤1200 MB | PASS (marginal) |
| BENCH-5 idle timer drift | 15.1 ms | 14.98 ms | unchanged | ≤25 ms | PASS |
| BENCH-6 loaded timer drift | 2530 ms | 174.4 ms | 174.4 ms | ≤100 ms | FAIL |
| BENCH-7 throughput guard | 30,662 | 34,467 | ≥30,000 met | ≥30,000 | PASS |

\* the checked-in `bench_h` measures the **unarmed** machine on a noisier local
box than 0.8.0's number was taken on; per §9.2 amendment 4 the armed number is
the one that governs, and it is statistically unchanged.

**Rollback cost, restated precisely.** Armed `rollback` on a busy workload is
**0.778×** (34 278 → 26 657 ev/s, −22.2%), statistically unchanged from 0.8.0's
−22.4%. The new no-action checkpoint skip is real (idle machine measured
0.9978×–1.056× of baseline, versus 0.776× before) but applies **only to
transitions that declare no actions at all** — 0.949× with no actions, 0.878×
with actions on an otherwise identical machine. **No CandleViewer machine
qualifies for the skip.** CV-C13 stands unchanged.

**Probe baseline: unchanged.** `PROBE_BASELINE_FAILURES` is identical to the
0.8.0 baseline (`A3 A6 A10 A18`; `C6 C7 C15 C17`). No probe regressed and none
newly passed, so no baseline edit is warranted. `run_gate.py` keeps the 0.8.0
dict and now aliases it as the `5327ba6` baseline explicitly.

**Outputs.** `22-verify-main-verdict.md` (verdict, dispositions, new defects,
constraints CV-C01…CV-C18, recomputed config block, release-readiness note),
`18`–`19`–`21` (gate / diff / adversarial),
`issues/verify-main-5327ba6/*.result.md` + `*.py`,
`issues/verify-main/repro/f_*.py`, `probes/main-5327ba6/`,
`issues/comments-main-5327ba6/` (16 comment drafts + meta update),
`issues/new-main/` (8 new-issue drafts + repros),
`gate/result-main-5327ba6.json`. **Nothing was filed upstream.**

### 9.4 Standing amendments added by this run

5. **The primary check set is now `issues/verify-main-5327ba6/*.py` as well as
   `issues/verify-0.8.0/*.py`.** Both are blocking; `run_gate.py` runs them as
   two named check sets (`verify` and `verifyM`) so a per-set regression is
   visible without diffing totals. The `issues/repro/*.py` defaults set remains
   secondary and informational.
6. **Baselines key on the commit, not the version string.** A library whose
   `__version__` lags its CHANGELOG cannot be identified by version, and this
   one does. `run_gate.py` resolves and records the commit of the installed
   clone, and compares against `BASELINE_COMMIT`.
7. **Every gate run classifies each status delta explicitly** as *regression*,
   *improvement*, or *no change*, in a table, before the decision table is
   applied. A run that reports totals only cannot distinguish a new breakage
   from a carried-forward partial.

### 9.5 Run 2026-09-18 — `main` @ `3c527b0` (unreleased 0.8.1, merge of PR #83)

> **Baseline key.** Identified **by commit**. `__version__` still reports
> `0.8.0` while `CHANGELOG.md` targets `0.8.1` — two reviews running.
> `run_gate.py`'s `BASELINE_COMMIT` is moved to `3c527b0…`; `5327ba6` joins
> `PREVIOUS_BASELINES`.

```
Gate run 2026-09-18 - xstate-statemachine main @ 3c527b0 (unreleased 0.8.1)
DECISION: DEFER (library-adoption half of ADR-0016 Part 3)
          -- CHANGED from ADOPT WITH CONSTRAINTS, CONDITIONAL at 5327ba6
          -- decision-table row 5: 7 High open (bar: <=5)
  verify   : 33/34 primary pass (PRIMARY, mandated config, blocking)
             LC-28 FAIL -> PASS (#43 landed); LC-57 unchanged framing residual
  verifyM  : 12/15 pass (LC-07, N-3, N-8 -- pre-triaged residuals)
  verifyM2 : 3/3 pass (NEW set: issues/verify-main-3c527b0/ -- #43, #79, #80)
  repro    : 13/34 pass at defaults (SECONDARY, informational)
  probes   : identical baseline (A3 A6 A10 A18, C6 C7 C15 C17)
  suite    : 3242 passed, 13 skipped, 0 failed (was 3234/13/0)
  coverage : 90% (unchanged)
  benches  : #43 children+1 task budget CONFIRMED (1.0 tasks/child, was 2.0)
             BENCH-1 armed 1.56x-2.37x (mean ~2.03x) vs bar >=3.0x
             BENCH-2, BENCH-6 still missed
  regressions  : ONE -- G-2 (provenance does not survive a snapshot)
  blockers open: none (LC-01, LC-03 FIXED-OPT-IN -- closed only while
                 CV-LINT-XS1/XS2 enforce the mandated config)
  high open    : LC-07/#31, M-1, F-1, F-2, G-1, G-2, G-3   (7 -- over the bar)
  new findings : 24 canonical (6 High, 11 Medium, 7 Low, 0 Blocker)
                 -> 16 new issues, 8 ride-along comments
  constraints  : CV-C01..CV-C22 (CV-C15 NARROWED; CV-C06 deferred_count clause
                 WITHDRAWN AS UNSOUND; CV-C19..CV-C22 NEW)
  M-1 status   : STILL-PRESENT. Receipt shape unchanged. The deferred_count
                 mitigation is NOT SOUND -- it reads 0 at the caller's await
                 point for the deferred case AND the true-negative case.
  path forward : pre-release build. Fixing G-2 and G-3 before 0.8.1 tags
                 returns the count to 5 High and row 6 applies again.
                 ADR-0016 Parts 1 and 2 (the in-house shim) are unaffected.
  decided by   : Architect
```

**Environment.** CPython 3.13.7, Windows 11 Pro 10.0.26200. Local clone at
`3c527b0d04c0d2d0ebb565af7e9e905f7178f620`, `pip install -e .` into
`.venv-main`. Every command run with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.
Library source was not modified. No `git` command was run in the CandleViewer
repository; nothing was filed upstream.

**Decision-table walk.** Rows 1–3 do not trip (zero `ERROR` rows; suite green;
coverage 90%; the *serialised format* is unchanged — G-2/G-3 are gaps in what
is put **into** it, not in its shape, though fixing them will likely change the
format and trip row 3 next time). Row 4 does not trip on the merits — all four
Blockers closed — with the standing FIXED-OPT-IN asterisk for LC-01/LC-03.
**Row 5 matches**: 7 High open against a bar of 5. Rows 6–9 are not reached.

**Why this is arithmetic, not a re-weighting.** Three of the seven Highs are
new and all three come from PR #83 (G-1, G-2, G-3); the other four are carried
forward unchanged (LC-07/#31, M-1, F-1, F-2). Nothing was promoted in severity
to force the row. The honest response is to get G-2 and G-3 fixed upstream
before 0.8.1 tags, which returns the count to 5 and restores row 6.

**Per-issue dispositions.** 13 confirm closed · 3 REOPEN (#31 engine parity
under `strict_targets=False`; #77 raise-on-overflow; #79 provenance spoofable
and not persisted) · 1 meta update. Reopen only where an acceptance criterion
is unmet **by code** — not for wording, naming, test-file paths or
architectural framing. #43 and #60/LC-52 move to FIXED.

**Benchmark detail.**

| ID | 0.8.0 | `5327ba6` | `3c527b0` | Bar | Verdict |
|---|---:|---:|---:|---:|---|
| BENCH-1 order-path headroom (defaults) | 3.17x | 2.275x | not re-run (no source touched) | ≥3.0x | no change |
| BENCH-1 **armed `rollback`** (governing) | ~2.46x | 2.43x | **~2.03x** (1.56–2.37 over 3 runs) | ≥3.0x | FAIL — reconfirmed, noisy, no source change |
| BENCH-2 rule-lifecycle ev/s | 380.9 | unchanged | unchanged | ≥2000 | FAIL |
| BENCH-3 500-order memory | 3.32 KB | unchanged | 2.704 KB/open order | ≤8.0 KB | PASS |
| BENCH-4 10k-interp RSS | 594.8–1164.9 MB | unchanged | unchanged | ≤1200 MB | PASS (marginal) |
| BENCH-5 idle timer drift | 14.98 ms | unchanged | 23.3 ms (100ms/100-timer, undisturbed) | ≤25 ms | PASS |
| BENCH-6 loaded timer drift | 174.4 ms | 174.4 ms | 190.2 ms (busy-loop scenario) | ≤100 ms | FAIL |
| BENCH-7 throughput guard | 34,467 | ≥30,000 met | 285,485/s raw enqueue | ≥30,000 | PASS |
| **Actor task budget** | 2× children | 2× children | **children + 1** | — | **IMPROVED** — pinned by the library's own `tests/test_actor_perf.py` |

**Probe baseline: unchanged.** `PROBE_BASELINE_FAILURES` identical
(`A3 A6 A10 A18`; `C6 C7 C15 C17`). No probe regressed and none newly passed.

**Outputs.** `26-verify-3c527b0-verdict.md` (verdict, dispositions, the
consolidated 24-finding set, constraints CV-C01…CV-C22, recomputed config
block, release-readiness note), `23` / `24` / `25` (findings re-test / gate /
diff review), `issues/verify-main-3c527b0/*.result.md` + `*.py`,
`probes/main-3c527b0/` (23 probes), `issues/post-3c527b0/` (16 issue comments,
16 new-issue bodies, `meta-26.md`, `manifest.json`, `repro/`),
`gate/result-main-3c527b0.json`. **Nothing was filed upstream.**

### 9.6 Standing amendments added by this run

8. **The primary check set gains `issues/verify-main-3c527b0/*.py`** (`verifyM2`
   in `run_gate.py`), blocking, covering the issues verified in this window
   (#43, #79, #80). Each new verification wave gets its own named, commit-keyed
   set so a per-wave regression is visible without diffing totals. Older sets
   are retained and continue to run as baseline locks.
9. **A "no regressions" claim must name the boundaries it was tested across.**
   G-2 passed every gate, suite, bench and probe row on this commit and is
   still a behavioural regression, because no check existed for *"does this
   rule give the same answer either side of a snapshot/restore?"*. From this
   run on, every release that changes an event-classification, exemption or
   routing rule must be probed across the persistence boundary explicitly,
   and the gate carries a permanent check for it.
10. **Two features landing in one release are probed against each other.**
    Both new Highs in this window (G-2, G-3) are interactions between features
    that were individually correct and individually tested. The diff review
    must enumerate the *pairs* of features touched by a release and state, for
    each pair, whether they meet on a shared boundary.
11. **A proposed constraint mitigation is not adopted until it is re-tested on
    the next build.** CV-C06's `deferred_count` clause was specified at
    `5327ba6` and shown unsound at `3c527b0` — it would have shipped into
    `cv.statechart` and `tests/xstate_contract/` as a mitigation that reads the
    wrong value. Every constraint whose enforcement depends on library
    behaviour carries a re-verification line in the next gate run.


## Gate run log — 2026-09-18 main @ 5e07ba8 (round 4)
DECISION: **DEFER** (row 1: open Blockers R4-01, R4-04). Non-order paths under CV-C23–C29. Re-verification recipe: `29-r4-final-verdict.md` §8. Baseline for next run: this commit; probe expectations A10/A18/C15 are stale (now build-time rejections) and must be updated in `run_gate.py`.


## Gate run log — 2026-09-19 main @ 3ed3099 (round 5)
DECISION: **DEFER (order path) / GO (non-order paths)**. Row 1: open Blockers R5-01, R5-02, R5-04, R5-12. Suite 3322/0, cov 90 %, order-path headroom 2.65×. Constraints retired CV-C24/C25(runtime)/C26/C29; new CV-C30–C34. Exit condition: `34-r5-final-readiness-verdict.md` §9.


## Gate run log — 2026-09-20 main @ cec108b (round 6)
DECISION: **DEFER (order path) / GO (non-order paths)**. Row 1: open Blockers **R6-01** (async `always`+completed-`invoke` livelock, `send(wait=True)` never resolves) and **R6-03** (`rollback`+`invoke.onDone` unbounded re-invocation, ~1400/s, `status="running"`). 26 issues: 24 closed / 1 partial (#122) / 1 not-fixed (#157). Regressions: 3 Medium. New defects post-refutation **2 B · 2 H · 7 M · 9 L**. Gate script: verify 29/34, verifyM 10/15, verifyM2 3/3, repro 13/34, probe 1/3. Suite 3399/0, cov **92.77 %** (floor 90). Order-path fill p95 **0.057 ms** PASS; BENCH-2 410/s FAIL (unchanged class); BENCH-6 loaded-drift bench **NOT RUN** (time budget) — stated gap. Constraints **retired CV-C27/C30/C31/C34**; CV-C32 restated per-engine (does *not* retire); **new CV-C27′, CV-C31′, CV-C35, CV-C36, CV-C37**. Note: absent the two Blockers this is row 6 (2 High, both with enforced mitigations) = ADOPT WITH CONSTRAINTS — the whole gap is one upstream change to the async engine's chain/macrostep termination accounting (`interpreter.py:1427` + porting #144's rule to `_run_event_loop`). Exit condition: `39-r6-final-readiness-verdict.md` §9. New verification set added to `run_gate.py`: `issues/verify-main-cec108b` (kind `verifyM3`).


## Gate run log — 2026-09-20 main @ 221ce7c (round 7)
DECISION: **DEFER (order path) / GO (non-order paths)**. Row 4: open Blockers **R7-01** (an `async def` invoked service's completion is published on the public inbox lane at `interpreter.py:2414` — and the child-actor `onDone` at `:2882` — so it never reaches the charging site at `:2287-2288`; 28 108 service calls vs **23** for the identical chart with `def`, `last_error=None`, and arriving `from_inbox` it also resets the settle budget every lap at `:1647`; one variant settles into an **empty configuration** 10/10 reporting `ok=True`) and **R7-02** (external `send(priority=True)` charged to the chain budget: 751 of 1 500 dropped as `chain_budget`, control without `priority=True` drops zero; the drop path resets `_raise_depth` so `last_error` reads `None`). 12 issues: 7 fixed / 2 partial (#167, #168 — one defect) / 2 documentation-only (#122 correct-as-designed, our reopen withdrawn; #174 open) / 1 not-fixed (#175 Case D, whose shipped regression test passes while it is broken). Regressions: **0 true PASS→FAIL in the gate** (confirmed by direct check-by-check JSON diff vs `result-main-cec108b.json`), but **3 introduced by this round's own fix work and invisible to every existing check** — R7-02 (Blocker), R7-03 (High, from #171's untimed `gather`), R7-11 (Medium). New defects post-refutation **2 B · 4 H · 6 M · 8 L**; refutation moved 3 of 8 Blocker/High **down**, 0 up, and refuted R7-04 outright. Gate script: verify 29/34, verifyM 10/15, verifyM2 3/3, **verifyM3 24/27**, repro 13/34, probe 1/3 (`FAIL=36, PASS=80`). Suite 3418 passed / 1 flake (not reproducible standalone or under either hash seed) / 13 skipped, cov **92.64 %** (floor 90); `interpreter.py` 89 % → **91 %**. 500-order fill p95 **0.077 ms** PASS; raw `send()` **257 384 ev/s** (fastest recorded); BENCH-2 unchanged FAIL; BENCH-6 **reduced scope only** (`load_500` and `load_500+cpu_hog` NOT RUN for a second round — stated gap); `bench_h` RSS/open-order 3.10 → 5.18 KB **UNATTRIBUTED**, needs a bisected re-run. Contracts: 20/20 build clean, B1–B5 **112/112**, B6–B10 54/55 (the single FAIL is a stale harness assertion, HD-01), B11–B15 all invariants, B16–B20 byte-identical to `cec108b`; B10–B17/B19/B20 PASS on the library, B1–B9/B18 pass functionally but carry the R7-01 shape. Constraints **retired: W-04a** (#170 makes `Receipt.denied` alone a correct discriminator again), **CV-C37** (#171 fixed the children-ready race — replaced by its inverse, CV-C39), and CV-C36's original rationale (rule stands on new grounds). **New: CV-C38** (no unguarded invoke cycle), **CV-C39** (`await start()` is always bounded), **CV-C40** (no snapshot before the post-start settle observation), **CV-C41** (root-only snapshots), **CV-C42** (`priority=True` forbidden outside wrapper code). Note: absent the two Blockers this is row 6 (**4** High, each with a mechanically enforced mitigation) = ADOPT WITH CONSTRAINTS — the whole gap is **two lines of provenance accounting in `interpreter.py`**. Exit condition: `44-r7-final-readiness-verdict.md` §9. New verification set added to `run_gate.py`: `issues/verify-main-221ce7c` (kind `verifyM4`). Harness fixes required (H-1/H-2): add `150` and `probe` to `VERIFYM3_BASELINE_FAILURES`, and give the `verify` set its own baseline-failure allow-list.

### Standing amendment added by this run

12. **Every test that invokes a service must run under both service kinds, and every test of an engine-level invariant under both engines.** Round 6's failure mode was "fixed on the engine the issue was filed against"; round 7's is "fixed on the service kind the test was written against". They are the same failure one level down, and a matrix over (engine × service kind) closes both permanently. This applies to *our* gate and contract scripts as much as to upstream's suite: our own round-6 confirmation scripts declared `def` services and therefore confirmed a fix that does not hold on the lane our mandatory configuration requires. From this run on, any gate row exercising an `invoke` is parametrised over service kind, and a row that is not parametrised is not evidence.


## Gate run log — 2026-09-21 main @ 6db65d8 (round 8)

DECISION: **DEFER (order path) / GO (non-order paths under constraints)**. Row 4: **one** open Blocker — **R8-01**, the priority lane **charges by provenance and sheds by position**. `_deliver_priority` (`interpreter.py:2342-2389`) charges only on `engine_completion`, which is `False` for every public `send(priority=True)` whatever the issuer, so a priority event **issued from an action** is never charged: 2/2 cells LIVELOCK past the watchdog, `trip_observable: false`, `status="running"`, `last_error is None`, no drop hook, `start()` never returns — while the plain-lane control on an identical machine is bounded at 27 laps with `RunawayChainError` + a `chain_budget` drop. The shed test (`:1598`, `over = self._raise_depth > limit`) has **no** provenance test and operates on the same FIFO, so a genuinely **external** priority event at an already-tripped chain is destroyed as `chain_budget` — 8–9 of 2 000, `send()` accepted, `last_error is None`; the `priority=False` control loses 0 on both service kinds. It is the **regression surface of this release's own #180**, and it is one function's worth of work. 16 issues: **15 fixed in code (10 clean, 5 narrower than claimed), 1 documentation-only (#174), 0 not-fixed** — the first round with no not-fixed row. Regressions: **0 true PASS→FAIL in the gate**; the 2 deltas (`154`, `158` in `verifyM3`) are **ours** — stale fixtures that hand-build a `version: N` blob with no `machine_hash`, correctly refused by #185, reproduced and attributed directly (H-3). 1 regression introduced by this round's fix work and invisible to every existing check: R8-01; plus R8-10/R8-11 (Medium) from #179's new machinery. New defects post-refutation **1 B · 3 H · 7 M · 4 L**; refutation moved **3 of 6** Blocker/High **down** (R8-02 Blocker→High, R8-04 High→Medium, R8-06 High→Low), **0 up**. Gate script: verify 29/34, verifyM 10/15, verifyM2 3/3, verifyM3 23/27, **verifyM4 10/11**, repro 13/34, probe 1/3 (`FAIL=38, PASS=89`). Suite **3 457 passed / 2 flake subtests (3/3 standalone passes) / 13 skipped** in 878.9 s, cov **92.70 %** (floor 90). Benchmarks **NOT RUN** this pass (the coverage run alone took ~15 of the 20-minute budget) — stated gap; `bench_h`'s 3.10 → 5.18 KB RSS/open-order move is now **unbisected for two rounds**. Contracts: 20/20 build clean **on both service spellings**; B1–B5 **132/132 both lanes**; B6–B10 async **52/52**, def 49/52 (one root cause, LD-01 → R8-02); B11–B15 all invariants both lanes; **B16–B20 ALL FIVE LIBRARY-GO** — round 7's CV-221-01 Blocker closed at **identical lap counts on both lanes** (`maxIterations` 2/5/100 → 4/7/102 service calls, `max+2` exactly), the kill-switch storm plateaus at 1 002 with `last_error = RunawayChainError`, 50 concurrent external priority sends give 0 dropped / 0 charged. **B18 is no longer excluded on library grounds**; what blocks B16 and B18 is **ours** (C-04, C-07b, both Blockers on any runtime). Constraints **retired: CV-C38** (the engine bounds invoke cycles itself now; CV-LINT-XS16 downgraded from error to warning), **CV-C31′** (retired on the async lane, re-issued as CV-C31″ for plain-`def` services only), and the `maxIterations` "inert, do not rely on it" annotation. **Widened: CV-C42** — `priority=True` is now forbidden **everywhere, any origin**. **New: CV-C43** (out-of-process progress supervisor; no in-process watchdog may be the sole order-path detector), **CV-C44** (per-child bring-up bound + coroutine entry actions on invoke-bearing states), **CV-C45** (completion events never accepted from a wire; strip `DoneEvent`/`AfterEvent` from `pending_events` on restore). Note: **row 6 is otherwise satisfied** — open-High is **3** (R8-02, R8-03, R8-05) against a bar of 5, each with a mechanically enforced mitigation and a contract test — so closing R8-01 flips this to **ADOPT WITH CONSTRAINTS on the order path**. **Pin policy:** `== 0.8.1` once tagged and only if the tag is cut after R8-01 lands; until then commit `6db65d8` + source sha256, evaluation only, **vendored copy per MUST-08** for the non-order machines going live now. Exit condition: `49-r8-final-readiness-verdict.md` §10. New verification set added to `run_gate.py`: `issues/verify-main-6db65d8` (kind `verifyM5`). Harness item outstanding (H-3): add a `machine_hash` to the hand-built blobs in `issues/verify-main-cec108b/154_*.py` and `158_*.py`.

### Standing amendment added by this run

13. **Every gate row that exercises a `send` must be parametrised over *issuer provenance* (external vs issued from an action) and *chain state* (untripped vs already tripped), exactly as amendment 12 requires for service kind.** Round 6 was "fixed on the engine the issue was filed against"; round 7, "fixed on the service kind the test was written against"; round 8, "fixed on the issuer the test happened to use". R8-01 survived a fix, a pinned upstream test and a full battle round because `tests/test_round7_findings.py:413-520` only ever sends *externally* into an *untripped* chain. The general rule these three rounds are teaching: **when a fix distinguishes two cases, the test must exercise both sides of the distinction, and the arm expected to fail must be given work that can actually fail.** The corollary is the round's other finding: `tests/test_round7_findings.py:557` parametrises over `KINDS` but gives the `def` arm `time.sleep(0.05)` against the async arm's `asyncio.sleep(3.0)`, so the parametrisation is decorative and the defect it names (R8-03) shipped green. **A parametrised test whose arms are not equally capable of failing is not parametrised.** This binds our scripts as much as upstream's.

### 9.14 Run 2026-09-22 — `main` @ `f28719c` (unreleased 0.8.1, merge of PR #202)

DECISION: **ADOPT WITH CONSTRAINTS** — decision-table **row 6**, on **all four lifecycle families including the order path**. **The Blocker row is empty for the first time in nine rounds.** Round-8's sole Blocker **R8-01 is closed by #192**: the priority lane's *drop* site now knows the provenance rule its *charge* site already knew — self-issued sends charged, external ones shielded — verified on **both engines and both service kinds**, and on the real B18 kill switch (**12/12 presses accepted, 0 shed as `chain_budget`, press pre-empts the chain**). **R9-01 was refuted Blocker→Low** (every vector needs a capability that already dominates the engine — a held engine-minted event, an unexported private class, or arbitrary snapshot authorship — all documented as the intended trust boundary; XState v5 performs no provenance check at all and SCXML 6.4 treats `done.invoke.<id>` as a plain event name, so this library is stricter than both). **R9-03 was refuted outright** (its "permanent starvation" was an artefact of reading a counter after a fixed `sleep(1.0)`; poll-to-drain gives **500/500 applied, inbox 0, priority 0**, and both lanes now trip `RunawayChainError` — which *is* the #179/#201 fix; its chart is a documented-invalid unguarded `always` into its own region). **R9-05 downgraded High→Medium** (snapshot authenticity is a documented wrapper obligation, not a library defect; refiled as a docs/affordance ask). Refutation moved **3 of 5** Blocker/High candidates **down**, **0 up**.

12 issues: **11 fixed in code (9 clean, 2 narrower than claimed), 1 partial (#197), 0 not-fixed, 0 documentation-only.** Every round-8 residual we named as our own exit condition is closed (R8-01/#192, R8-03/#194, R8-08/#186, R8-09/#199, R8-10/#200, R8-11/#201). Post-refutation new defects: **0 Blocker · 2 High · 5 Medium · 8 Low** — the best position in nine rounds, and the trajectory is **4 B · 8 H at round 5 → 0 · 2 now**.

The two open Highs, both CONFIRMED and both **mechanically contained**: **R9-02** — `base_interpreter.py:4523` selects `after` transitions on the **public exported** `AfterEvent`, never on #195's `_EngineAfter`, unlike the `DoneEvent`/`ErrorEvent` branch eight lines below; the decisive vector is a forged `pending_events` record with **no `"engine"` flag** that `_enqueue_restored` (`:1768`) puts straight on the inbox, so **with `strict=True` the machine still reaches `m.expired` — a 60-second timer fired instantly from untrusted snapshot data, with no API call**. Contained by **CV-C45 (widened)**. **R9-04** — a `def` service armed by a transition an `always` rolls **forward** is still submitted: **3/6 lanes leak** (case A on `def`/async and `def`/sync; case B on `def`/sync), contradicting `production-characteristics.md:97` **verbatim** and SCXML 6.4 (`exitStates` removes the state from `statesToInvoke`); worse, `test_round8_findings.py::test_always_rollforward_matches_sync` **pins the leaking behaviour**, so the green suite certifies the inverse of the published claim. Contained by **CV-C32 + new CV-C46**, which together make all three leaking lanes unreachable.

Regressions: **0 true PASS→FAIL.** The single gate flip (`LC-42`, `send_priority` p50 < 1 ms behind 2 000 queued events) is a flaky sub-millisecond threshold — **4/5 PASS** on re-run, every other assertion green every run, `verifyM` twin green 5/5. The three pre-existing blocking FAILs (`167`, `PROBE-01`, `PROBE-03`) are **byte-identical to baseline**. **Six of our own scripts exit 1 for our own staleness**, not library behaviour, and are retired or fixed in `run_gate.py` (`R8-02/03/04/11` superseded by #193/#194/#196/#201's restated contracts; `R8-05`'s `check2` does not catch `UnknownEventError`, *which is the #195 protection firing*; `197_empty_config_wait.py` is kept and **promoted** — it is the genuine R9-08 signal and the gate's `verifyM5` cell is the weaker one).

**One reclassification worth recording.** Round 9's report escalated `TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations` (kind=`def`, 4/5 standalone failures) to "possible regression, needs root-cause". **It is neither a regression nor a library defect.** The test reads the counter at 0.6 s and again at 0.9 s and asserts equality; the `def` lane is still climbing at 0.6 s. Polled to convergence (`battle-f28719c/r9triage/t_r6_plateau.py`, new, standalone) **both lanes plateau at exactly 1003 = `maxIterations`+2 and stay there** (`def` ~1.0 s, `async` <0.5 s). The bound is solid; the test sleeps too briefly.

Suite: `tests/test_round8_findings.py` **29/29**; round6+7+8 together 83–84 passed. **Coverage NOT MEASURED** — the `--cov` run did not finish inside the 20-minute bound (~51 % of collected tests observed, all green; 92.70 % at `6db65d8`). **Row 2 keys on coverage, so this is recorded as an open measurement, not a pass**, and leads the round-10 recipe. Benchmarks partial: `bench_a` 7 605–8 195 ev/s burst, 36 026 raw sends/s; `bench_h` Budget 1 p95 **948.5 ms vs a 300 ms budget (headroom 0.32×, missed)**, Budget 2 **142.9 market ev/s vs 2 000 (missed)**, Budget 3 **2.128 KB/order**; `bench_j` rollback 0.89×, defer 1.24×. `bench_c_timers`/`bench_e_actors` not completed. **The RSS/open-order figure is now unbisected for a third round** (3.10 → 5.18 → 2.128 KB): **bisect it or replace the metric.**

Contracts: **20/20 build clean on both service spellings**, zero `InvalidConfigError`/`ImplementationMissingError`. B1–B5+B18 **138/138 async and 138/138 def**; B6–B10 async **52/52**, def **51/52** (the one FAIL is R9-04, up from 3 FAIL at `6db65d8`); B11–B15 all invariants both lanes; **B16–B20 all LIBRARY-GO**. Sync-engine parity 15/15 on configuration, action trace *and* service-call trace. All three mandated drives pass on both lanes. **The service-kind axis is flat across every battle track for the first time** — round 8's parametrisation ask worked, and the only surviving `def`/`async` divergence in the whole corpus is R9-04's.

Constraints **retired: CV-C43** (out-of-process liveness as a *mandate* — its entire ground was R8-01's unobservable livelock, now closed; downgraded to a recommendation, and `status`/`last_error` are liveness signals again) and **CV-C31″** (its ground was R8-02's residual, which #193 fixed; keeping it would misstate the reason). **Widened: CV-C45** — the restore filter now matches the **serialised record** (`kind` ∈ {`done`,`error`,`after`}) as well as the deserialised class, because R9-02's vector carries no `"engine"` flag and never passes a `send()`-time check; the gateway rejection explicitly names `AfterEvent`. **New: CV-C46** — the order path **never** runs on `SyncInterpreter` (covers 2 of R9-04's 3 leaking lanes, R9-09's sync/async lap divergence, and the `167` sync-only gate FAIL). Promoted to clauses: HMAC-tag control-plane snapshots + refuse `version < 1` (R9-05); gateway counts call-site `QueueOverflowError` refusals itself (R9-11); wrapper whitelists top-level config keys (R9-16).

**Pin policy:** `== 0.8.1` once tagged **and only if `__version__` actually reports `0.8.1` on that tag**; until then commit `f28719c` + source sha256, **vendored copy per MUST-08**. **Standing gate:** `tests/xstate_contract/` enters CI as a **blocking** gate on both service spellings — the 20 contract machines end-to-end, the three mandated drives, the R9-02/R9-04 containment tests, and a lane-matrix pin on R9-04 so an upstream fix is *detected*. New verification set added to `run_gate.py`: `issues/verify-main-f28719c` (kind `verifyM6`). **What blocks B16/B18 is OURS** (C-04, C-07b) — for the first time in the study, the binding constraint on our order path is our own catalogue, not the library. Exit condition and phased shim retirement: `54-r9-final-readiness-verdict.md` §10.

### Standing amendment added by this run

14. **When a fix introduces a trust mechanism, enumerate every call site it is meant to govern and assert the list is exhausted.** Amendments 12 and 13 taught "parametrise over the axis the defect lives on" (engine, then service kind, then issuer provenance), and round 8 followed it — which is why the service-kind axis is flat this round and why the round is as clean as it is. **Round 9's failures are a different shape: a good mechanism applied to a proper subset of its call sites.** #195 minted `_EngineDone`, `_EngineError` *and* `_EngineAfter`, wired two of three into `_select_transitions`, and shipped (R9-02). #193 moved the `def`-service handoff into the engine-held task and cancelled it on the rollback epilogue but not the roll-forward one (R9-04). Both are *second* incomplete landings of the same fix. The check that catches this class is structural, not behavioural: **assert that every `isinstance(event, <public engine class>)` in the dispatch path is paired with a provenance test, and that every epilogue that can leave a state cancels that state's pending invocations.** Applied to our own work, the same rule says: a containment constraint must name the exhaustive list of vectors it contains, and a test must exist for each — which is why CV-C45's widening spells out both the class form and the raw-record form.

15. **A test that pins current behaviour is not the same as a test that pins the documented contract, and shipping the first while claiming the second is worse than shipping neither.** `test_always_rollforward_matches_sync` is green against behaviour that `production-characteristics.md:97` says cannot happen, so the published claim has **no** coverage and the suite actively certifies its inverse. Paired with amendment 13's converse (`tests/test_round7_findings.py:557`, a parametrised test whose `def` arm could not fail), this round records **both** failure modes of a green suite in one release. **For our own gate: every contract test must cite the doc sentence or spec clause it enforces, and a test whose citation and assertion disagree is a defect in the test.** Corollary, from `TestAsyncRollbackRearmCycleBounded`: **a convergence assertion must poll to convergence, never sleep a guessed interval** — that test fails ~80 % of runs on correct behaviour, which trains readers to discount the suite.

### 9.15 Run 2026-09-22 — `main` @ `19cb1f1` (unreleased 0.8.1, merge of PR #211, commit `4dbf86e`)

DECISION: **ADOPT WITH CONSTRAINTS** — decision-table **row 8**, up from row 6 last round. Row 8 is "all Blocker **and High** closed, all Medium triaged, benchmark thresholds not all met": the constraints that remain are **benchmark-derived architectural consequences**, not containment for open library defects. **The High row is empty for the first time in ten rounds.** Round 9's §9 named row 8 as "the honest ceiling for this library in our system" — this release reaches it.

8 issues: **all eight FIXED, clean — 0 partial, 0 not-fixed, 0 documentation-only.** **This is the first round in ten where every fix landed on every axis it claimed.** The service-kind axis is now flat across the *entire* corpus, with the only surviving `def`/`async` divergence being the documented, intended one (`def` services are non-preemptable — `production-characteristics.md` §2, R10-D2) plus the documented `SyncInterpreter` + `async def` → `NotSupportedError` exclusion.

**Both round-9 Highs are closed, at the right sites.** **R9-02 → #203**: `base_interpreter.py:4624` now gates `after` selection on `isinstance(event, AfterEvent) and is_system_event(event)` — the same test the `Done`/`Error` branch already used. The discriminating control that made R9-02 a High (a public `AfterEvent` with the correct type string firing a 60 s timer instantly at the **default `strict=False`**) is refused at `send()` with a named `UnknownEventError` on both spellings. **R9-04 → #204**: invoke arming moved into the eventless settle pass per SCXML §6.1 `statesToInvoke`, closing the roll-forward half on **both engines and both service kinds** — roll-forward submissions 0/8 cells, `LD-01` **3 leaks → 0/6**, B6–B10 `def` lane 51/52 → **52/52**, drives D1–D3 13/14 → **14/14**, and `167 rollback_reinvoke_spin` (recorded at `f28719c` as a permanent expected-FAIL on the grounds that "#201 does not promise the sync re-arm") now **PASS ×5/5** on both `verifyM4` and `verifyM5`.

Post-refutation new defects: **0 Blocker · 0 High · 5 Medium · 7 Low**, plus 1 refuted outright. Trajectory: **4 B · 8 H at round 5 → 0 · 2 at round 9 → 0 · 0 now.** Refutation moved **all three** Blocker/High library candidates **down** and **none up**.

**The round's one correction: R10-01 was filed as a Blocker on seven engine-event forgery vectors, and we refuted it ourselves.** Every vector reproduces exactly as filed (n1 4/5 forged, t1 8/8, s6/u2 FAIL, d10 both kinds) and the source reads are accurate — but they partition into two classes and **neither crosses a trust boundary**. **Class A** (`engine_after` import path, `type(held)(...)`, `pickle`, `deepcopy`, private `_EngineAfter`, `_replace`) presumes attacker-controlled Python in-process; a control run shows a plain registered action with **no forgery at all** writes context arbitrarily and a live `Interpreter` exposes `_enter_states`/`_exit_states` directly — forging an `AfterEvent` is *strictly weaker than the premise*, and the per-interpreter nonce we were going to ask for would be readable by the same reach. **Class B** (forged `"engine": true` record via `restore_event`) requires blob-write — and rather than accept `events.py:414`'s claim we **tested** it: a hand-edited snapshot with **no event forgery whatsoever** restores to `{'z.late'}` with context `{'n': 999}`. The flag adds zero capability over what the blob writer already holds. The boundary #195/#203 actually target — external name/shape confusion — **holds in every probe** (V1, B and G all refused under `strict:True` + `onUnhandled:"error"`), and `engine_after`/`engine_done` are not package-root exports so reaching them is already Class A. The design is documented verbatim at `docs/api/index.md:1185-1201`. **Downgraded Blocker → Low**, filed as hardening rather than a vulnerability.

**R10-02 refuted outright.** A self-targeting `onDone` is an **internal** transition by contract: `base_interpreter.py:3021-3028` routes `source == target && !reenter` to `_execute_internal_transition`. SCXML defines `type="internal"`, and **XState v5 makes internal the default for self-transitions with `reenter: true` as the opt-in** — which this library follows and documents three times, including a troubleshooting entry naming this exact wedge shape. Verified with a standalone probe from neutral cwd, both kinds, both engines, **polled to convergence** (stable over 6×0.1 s, converged at 0.7 s): with `"reenter": True` every lane gives `entries == submits == 22 == maxIterations + 2`, `last_error = RunawayChainError`, and `on_invocation_stranded` fired; without it, `submits = 1`. Zero violations. **R10-03 downgraded High → Medium** (reproduces robustly, but is implied by the #206 changelog and `json-config.md:110`; the documented `after` idiom measures **93/92 beats in 3 s with zero drops** against 9 for the `raise(delay=)` spelling, and no doc presents self-`raise(delay=)` as a heartbeat). On the contract side **R10-C1 and R10-C2 are refuted as library defects** (both ours, with corrected charts proven to pass on both engines and both spellings), **R10-C3 High → Medium** (`stale_lockout` **is** escapable via `RECONNECTED`, so the High premise fails), **R10-C4 High → REFUTED (Low)** (sibling-only kill declaration: 1.458 s vs 0.001 s with an ancestor handler).

**THE OWED MEASUREMENT IS DISCHARGED.** The full suite finished after the bench agent's reporting bound: **3505 passed, 13 skipped, 0 failed, 566.57 s; coverage 92.78 %** (`suite-19cb1f1.log`), above the library's own 90 % floor and our 86 % gate bar, and up from 92.70 % at `6db65d8`. **Row 2 fires before any adoption row and was round 9's single largest open risk — it is now cleanly not-triggered on measured evidence rather than inference.** `tests/test_round9_findings.py` 19/19; round7+8+9 together 85/85 under `PYTHONHASHSEED` 1 **and** 2, no flake reproduced.

Regressions: **0 true PASS→FAIL.** All 15 status deltas are new lanes or improvements: `LC-42 send_receipt` FAIL → **PASS ×5/5**, `167` ×2 FAIL → **PASS ×5/5**, the `verifyM6` set appearing for the first time, and one stable FAIL (`201 lap_parity_stated_exactly`) which is a **stale repro** asserting the pre-#201/#209 shape — superseded by `209_lap_parity_sweep_1_25.py`, which passes. `PROBE-01` 16/20 and `PROBE-03` 13/17 fail on the **same cells** as baseline — no widening.

Benchmarks: **BENCH-2 still misses** (443.6 market ev/s async / 394.0 sync vs a 2 000 budget — a ~4.5× architectural gap, down from ~14× at round 9). **BENCH-6 is UNMEASURED for a second consecutive round** — `bench_c_timers` timed out at 115 s with **zero output** (it buffers all results to one JSON dump at the end, so nothing is recoverable); `bench_e_actors` not attempted. BENCH-1 reads as **met** (Budget 1 p95 **144.6 ms** vs 300 ms, 2.07× headroom, flipping round 9's 948.5 ms/0.32× miss) and `bench_a` burst_50000 moved 8 195 → **40 855 ev/s** — but **no matched-load A/B was run**, and the *ratios* between policies held steady (`rollback` 0.767×, `defer` 1.030×) while the absolute baseline moved ~5×, which is the signature of host contention, not engine change. **Neither improvement is relied upon.** Budget 3: 3.064 KB/order, back inside round 7's flagged range after round 9's low outlier — **the RSS/open-order figure is now unbisected for a fourth round: bisect it or replace the metric.**

Contracts: **20/20 build clean on both service spellings, and ZERO library defects across all four groups** — a first. B1–B5 happy paths 5/5, invariants+parity 27/27, snapshot/restore 5/5 both lanes; B6–B10 **52/52 on both lanes** with drives 14/14 (LD-01 closed); B11–B15 27/27 both lanes with CV-F28-01 and CV-F28-02 both fixed and three-lane lap parity 25/25 at plateau `limit+2`; B16–B20 10/10 clean builds, sharp edges 13/13 per lane, snapshot/restore clean on every drive, sync parity 5/5 including the service-call trace, **0 new library findings**. Every B16–B20 failure on this commit is OURS.

Constraints **retired: CV-C46** (order path never on `SyncInterpreter` — its entire ground was R9-04's sync-engine leaks, now closed; downgraded to a design preference) and **CV-C45's send-side clause** (its ground was R9-02, closed in the engine by #203 — the **restore-side clause does NOT retire** and is widened on R10-05). **CV-C32 retires as a safety rule** but the rule itself **stands**, re-grounded on R10-D2 rather than R9-04. **Widened: CV-C45 (restore side)** — strip `Done`/`Error`/`After` records matching the **serialised `kind`** as well as the class, and **re-arm deadlines explicitly from context**, because a pre-0.8.1 `after` record is now silently *refused* rather than demoted. **New: CV-C47** (no `raise(delay=)` self-paced periodic work — R10-03), **CV-C48** (0.8.0-era snapshots migrated before restore; a refused deadline must be loud in our code since it is silent in the library's — R10-05), **CV-C49** (no snapshot with an armed self-delayed debt — R10-04), **CV-C50** (`CvErrorHooks` implements `on_invocation_stranded` and samples `on_event_dropped(..., "chain_budget")`; **never poll `last_error`, which is cleared on the `async def` lane and retained on `def`** — R10-13), **CV-C4x** (kill/cancel declared on an ancestor of every invoking state, statically lintable — R10-C4).

**Pin policy:** `== 0.8.1` once tagged **and only if `__version__` actually reports `0.8.1` on that tag**; until then commit `19cb1f1` + source sha256, **vendored copy per MUST-08**. **We would pin a tag cut at this commit**, with one blocking precondition (bump `__version__`, still 0.8.0) and three doc fixes preferred in the same release (the `+2`/`+3` plateau contradiction; the overstated #209 lap-parity claim; naming #206 as a behaviour break). New verification set to add to `run_gate.py`: `issues/verify-main-19cb1f1` (kind `verifyM7`), with `BASELINE_COMMIT` moved to `19cb1f1` and `201_lap_parity_stated_exactly.py` retired.

**Phase-3 order-path shim retirement MAY BEGIN.** Both gating Highs are closed and Phase 3's one measurement precondition (coverage ≥ 86 %) is met at 92.78 %. The remaining three acceptance conditions are **entirely ours, with no library dependency**: five consecutive green nightlies of the contract suite on both spellings, lint+tests for the named constraints, and a two-week low-notional canary. **What blocks B16/B18 is still OURS** — C-04 and C-07b, open **five** rounds, and this round proved they are ours by building the corrected charts and watching them pass on every engine and every spelling. Ten rounds of library verification have converged on a state where the binding constraint on our order path is **our own catalogue, and nothing else.** Exit condition and phase gates: `59-r10-final-readiness-verdict.md` §10.

### Standing amendment added by this run

16. **Refute your own Blockers against the trust boundary, not against the repro.** Round 10 filed three Blocker/High library candidates and **all three fell** — not because the repros were wrong (every one reproduced exactly as written) but because the premise each needed already granted more than the exploit delivered. The discipline that caught it was a **control run**: before counting a forgery vector, run the *same* attacker capability with **no forgery at all** and see what it already buys. A plain registered action writes context arbitrarily; a hand-edited snapshot relocates the machine. Both controls took under a minute and both retired a Blocker. **Rule: every security finding must state the minimum capability it presumes, and must include a control showing what that capability achieves without the finding.** If the control achieves as much, the finding is hardening, not a vulnerability. The same rule applied in the other direction is why R10-C1/C2/C4 are ours: **before filing an engine defect against a chart, build the corrected chart and run it** — if the corrected chart passes on both engines and both spellings, the engine followed the chart and the defect is yours.

17. **A "fixed" claim must be tested on a shape that can fail.** #209's pin sweeps two shapes and the second — `nested_invoke` — **never exits its initial state**, so it fires exactly 2 calls at every limit 1–25 and can never trip `RunawayChainError`. It agrees across all three lanes because **a constant agrees with itself**. This is amendment 13's "a parametrised test whose `def` arm could not fail" in a new costume, and it is now the third distinct way a green suite has certified nothing in this study (13: an arm that cannot fail; 15: a pin on behaviour the docs contradict; 17: a fixture with no dynamic range). **For our own gate: every regression pin must demonstrate its own discriminating power — show the metric moving with the parameter it claims to bound, or the pin does not count as coverage.** Corollary for reading upstream claims: when a changelog says "verified on both shapes", check that both shapes *vary*.

---

## Gate run log — 2026-09-22 main @ c78ce99 (round 11, merge of PR #217, `fix/0.8.1-round10`)

```
Gate run 2026-09-22 - xstate-statemachine main @ c78ce99 (unreleased 0.8.1, __version__ reports 0.8.0)
DECISION: ADOPT WITH CONSTRAINTS -- decision-table ROW 6
          (REGRESSED one row from round 10's ROW 8 at 19cb1f1)
  gate     : exit 0; 163 checks, 124 PASS / 39 FAIL (all FAILs known-baseline or superseded)
  sweep    : 527 scripts, 444 PASS / 83 FAIL / 0 TIMEOUT; every delta re-confirmed SERIALLY
  regress  : ZERO true regressions. 1 stable PASS->FAIL delta = OUR test encoding the
             #206 rule that #212 deliberately reverses (retired)
  issues   : 5/5 FIXED (#212 #213 #214 #215 #216) -- both engines, both service spellings
  suite    : NOT COMPLETED within bound (3rd consecutive round; ~4% reached, 0 failures).
             Carried: 3505 passed / 13 skipped / 0 failed / 92.78% coverage at 19cb1f1
  benches  : 5/7 thresholds met - BENCH-2 missed (~5x), BENCH-6 UNMEASURED FOR FOUR ROUNDS
  blockers open: none (library). C-04, C-07b are OURS, open six rounds
  high open    : R11-04 (_timer_handles unbounded leak on the raise(delay=) path)
                 -> enforced by CV-C47 (already linted) + CV-C61 (new)
  medium open  : R11-06, R11-07, R11-08, R11-09 (all triaged, all constrained)
  low open     : R11-01, R11-02, R11-10, R11-11, R11-12
  refuted      : R11-03 (High->None), R11-05 (High->none), R11-01 (Blocker->Low doc nit),
                 R11-02 (High->Low)
  constraints  : CV-C01..CV-C62 (CV-C48 RETIRES; CV-C45 stripping clause RETIRES;
                 CV-C49 REWRITTEN; CV-C47 WIDENED and now LOAD-BEARING; CV-C51..CV-C62 NEW)
  decided by   : round-11 readiness review
```

**Row-by-row.** Row 1 does not fire (exit 0, no ERROR rows; the four parallel-sweep false FAILs were re-run serially and are excluded as harness artefacts, `R11-H-1`). **Row 2 does not fire but now rests on carried, one-commit-stale evidence** — round 10's 92.78 % at `19cb1f1` — because the suite did not complete for the third consecutive round; supporting evidence at this commit is `test_round10_findings.py` 15/15 and round8+9+10 65/65 under both hash seeds, with zero failures observed anywhere. Row 3 does not fire: the format **did** change (v2 → v3), which is why it was checked rather than assumed — `version`/`machine_hash`/`minimum_version`/`expected_machine_hash` all present, and #214 **upcasts** v2 rather than refusing it, so there is no silent restore-compatibility break; round 10's R10-05b migration cliff is *closed*. Row 4 does not fire (no library Blocker survives refutation; C-04/C-07b are ours). Row 5 does not fire (1 High, bar 5). **Row 6 fires.** Row 7 is not reached — and is worth recording: **had CV-C47's lint not already existed and been green, this round would be row 7, DEFER.** Row 8 is not reached because R11-04 keeps the High row non-empty.

**All five issues FIXED, on both engines and both service spellings — second consecutive round with no "fixed on one axis only" residual.** #212's parity with `after:` is **measured, not asserted** (200 machines × 1 ms ping-pong / 10 s → 0 trips, 0 drops, 200/200 beating; 2000/2000 livelock-fuzz cells; zero-delay cycles still trip). **#213's v3 round-trip is exact: 600/600** carrying the right `remaining_ms` (±0.5 ms) and `send_id`, firing not early, not late, exactly once; 300-machine property 0 failures. #214's strict-on-restore works for `pending_events`. #215's lap parity holds; 100 concurrent `start()`s settle in 0.01 s. **#216 is flawless where it looks** — 47/47, 120/120, 200/200 mutations with a correct did-you-mean every time. Four of the five carry residuals, and **every residual is a scope or composition gap, not a failure of the mechanism that shipped.**

**Round question 1 — did #212 re-open any bounded-cycle class? NO**, on three independent lines: (a) a purpose-built collateral-unboundedness probe found no previously-bounded shape that became unbounded, with watchdogs on both lanes; (b) **R11-05, the one finding that claimed otherwise, is REFUTED on a control** — plain `after:` at the same sub-millisecond delays behaves identically on the same charts (10,247 beats / 20,485 per s vs 10,539 / 21,075) and has been exempt from `maxIterations` since long before #212, so the reversal opened **no escape**, it achieved **parity** with a path the budget never bounded by design; documented in `production-characteristics.md` §2, conformant with SCXML §6.2 and XState v5, and not a liveness failure (external `send` served in 16.5/15.3 ms, the Windows timer floor); (c) the sweep is otherwise delta-free.

**Round question 2 — did snapshot v3 / the v2-upcast rule re-open the #195/#203 forgery boundary? NO.** Both candidates were filed at Blocker/High and **both died on controls.** **R11-01 (Blocker → REFUTED, Low doc nit):** the mechanism reproduces exactly — `"version": 3` → `2` mints `engine: true` onto forged `done`/`error`/`after` records, firing a 60,000 ms `after` in ~1 ms with `last_error=None` — but **an attacker who can edit `version` can equally edit `state_ids` and land in the target state directly, with no event forgery at all**; `from_snapshot` is a **documented trusted-input boundary** (#205 applies `state_ids`/`configuration`/`context` verbatim; `machine_hash` is explicitly *not a MAC*), and `minimum_version=3` raises `SnapshotVersionError` on the forged blob. **R11-03 (High → REFUTED, None):** control V1 — the only vector reachable from the **public API** — is **correctly refused with `UnknownEventError`**; V2 needs non-exported modules, V3/V4 need an already-held genuine engine event (original and pickle clone behave identically, zero escalation), V5 needs blob-write which reaches the target with **no event at all**. **R11-02 (High → Low):** equivalent-doors probe shows forging `configuration` alone reaches the same state; what survives is an **observability-grade contract inconsistency** (#214 promises restored user events get a *reported* strict refusal and `scheduled_sends` does not). **Third consecutive round that a provenance Blocker was refuted by our own control probe** — see standing amendment 18.

**The one thing that costs a row.** **R11-04 (High, CONFIRMED against every refutation avenue):** `_timer_handles` retains **1.00 handle per `raise(delay=)` beat, for ever**, on both engines and both action kinds — `_schedule_send` keys the handle under `self.id` (the **machine** id) while the only pruner pops `_timer_handles[state.id]` on **state exit**, and the machine id never exits; the `after:` path uses `owner_id=state.id` and is **flat (0.003/beat)**. Measured on the container, not inferred from RSS: **+455 MB / 24 s at 200 machines, strictly linear, no plateau**, polled to convergence at 3/6/9/12 s and 6/12/18/24 s. **No usage bounds it** — id reuse, explicit `cancel(sendId)` before re-arm, a 250 ms period and a never-exiting self-loop all measure 1.00/beat, because `_cancel` clears the clock and `_armed_self_sends` but never the handle. Not documented (#212/#213, `json-config.md`, `production-characteristics.md` and `snapshots.md` all *bless* a self-paced heartbeat of any period), and both XState v5 and SCXML disagree with the retention. **Not a new mechanism — newly unbounded:** before #212, #206's trip killed such a cycle at ~12 beats, which is why round 10's soak read +1.2 MB. **One line per engine to fix.**

**Four Mediums, all new-at-this-commit or newly sharpened.** **R11-06** — #215's `_descent_done` gate deadlocks `start()` **forever, silently** when an entry action awaits its own receipt (`last_error=None`, status `running`, legal configuration); proven causal against a gate-pre-opening subclass with **library source untouched** (3.01 s → 0.00 s), while the control shows the settle budget *does* cover the descent (`always` self-cycle returns with `RunawayChainError` at `maxIterations+1`). **R11-07** — #216 checks the **root dict only** while `KNOWN_MACHINE_KEYS` is overwhelmingly *state-level* names: **0/120 nested typos caught, and no WARNING either**, so the did-you-mean net is absent exactly where typos are most likely; `{"entryy": […], "onn": {…}}` builds a clean machine with 0 entry actions and no transitions under every strict setting. **R11-08** — restore → re-persist **without `start()`** drops every armed self-send (`_restored_self_sends` is written by neither path), which is #213's own failure mode one hop out and exactly what a journal-compaction job does. **R11-09** — a `RunawayChainError` trip reaches **only `last_error`**, which is a per-event read rather than a latch, so **one benign event erases it**; 6/40 (`def`) and 8/40 (`async`) post-mortems on a **permanently inert** machine read `running`/`last_error=None`, and post-#212 a legal heartbeat guarantees the eraser wins. It produced **99 false violations** in our own harness before the read was latched.

**Contracts: 20/20 LIBRARY-GO, ZERO library defects across all four groups, on both spellings — second consecutive round.** B1–B5 **356 checks / 0 FAIL** (178 per lane, every driver run twice); B6–B10 `def` lane 52/52; B11–B15 clean under the newly-mandatory `strictConfig: true`; B16–B20 zero new library findings. **`strictConfig: true` is now mandatory on all 20 machines and found 0 unknown root keys** — but per R11-07 its value is ~95 % unrealised until the recursion lands, since our typo surface is ~200 state nodes, not ~10 root keys. **What blocks B16/B18 is still OURS: C-04 and C-07b, open SIX rounds, both refuted as library defects in round 10, both fixable in config alone.**

**Measurement debt is now the largest open risk on the board.** The suite has not completed for **three** consecutive rounds, so row 2 — which fires *before* any adoption row — rests on a one-commit-stale number. **BENCH-6 has been unmeasured for four rounds** while **CV-C12 (`after` banned in catalogue machines) stands entirely on it**; a constraint whose ground has not been re-measured cannot be retired, so `after` remains coarse-timeouts-only and all algo timing stays on the external `MonotonicScheduler`. Round 12 must run **the full suite alone and first**, then **BENCH-6 alone**, before any other work competes for CPU.

**Constraints. RETIRED: CV-C48** (its entire ground was R10-05b, the 0.8.0 `after`-record migration cliff, which **#214's v2 upcast closes** — and the security objection to that upcast was refuted, so there is no reason to re-erect the fence) and **CV-C45's stripping clause** (records are now admitted correctly and refusals are strict-checked, so stripping is obsolete; replaced by the narrower CV-C45″). **REWRITTEN: CV-C49** — #213 persists the armed-delay debt exactly (600/600), closing its original R10-04 ground, so it becomes *"never re-persist an interpreter that has not been `start()`ed"* on R11-08's opposite hop. **STANDS, WIDENED, and NOW LOAD-BEARING: CV-C47** — its R10-03 ground (the heartbeat dies at `maxIterations`) is **gone**, closed by #212, and **R11-04 replaced it**; this is precisely the case where keeping the old justification would let a constraint rot. **CV-C12 STANDS UNCHANGED** on unmeasured BENCH-6. **NEW: CV-C51…CV-C62** plus three wrapper lints (stable `send_id`; **never register a user action colliding with a built-in** — a collision silently disarms the built-in with `beats=0` and no warning; `SimulatedClock` fires neither `after` nor restored `scheduled_sends`). **Net effect of #212 on our rules: zero relaxation, one tightening** — the reversal that made `raise(delay=)` legal is the same reversal that made it leak.

**Pin policy:** **we would pin a tag cut at `c78ce99`**, in preference to `0.8.0` and to `19cb1f1`, **with CV-C47/CV-C61 enforced in CI** — staying on `19cb1f1` keeps the #206 rule, the unpersisted-deadline gap and the migration cliff, and `19cb1f1` leaks too, merely capped because a different defect kills the cycle first. **Pin on the resolved commit sha + source sha256, never the version string** — `__version__` has been wrong for eleven consecutive rounds. Blocking precondition unchanged: bump `__version__`. `run_gate.py` updated: **added** `issues/verify-main-c78ce99` (kind `verifyM8`), `BASELINE_COMMIT` moved to `c78ce99`, and **`206_delayed_selfsend_charged.py` retired** as SUPERSEDED-BY-#212.

**Phase 3 CONTINUES.** R11-04 is contained by a green lint and touches a primitive **no catalogue machine currently uses** (K11: all 20 machines have zero `after` transitions and zero `raise(delay=)` actions), so it is not a Phase-3 gate — but it **becomes** one the moment K11 is addressed, which is the direction E50 is heading. The binding constraint is now unambiguously our own work: the CV-C5x test/lint build-out (**CV-C57's recursive validator does not exist yet** and is the least-defended item), plus C-04 and C-07b. Exit condition and phase gates: `64-r11-final-readiness-verdict.md` §10.

### Standing amendments added by this run

18. **Test every blob-write finding against the `state_ids`-only control *before* triage, not during refutation.** Three rounds, three Blockers filed against engine-event provenance, three refuted on the same control. The question is always: *what does the same writer achieve with `state_ids`/`context` alone?* If the answer is "the same thing", the finding is hardening, not a vulnerability, because `from_snapshot` is a documented trusted-input boundary and `machine_hash` is explicitly not a MAC. Promoting this from a refutation step to a **triage precondition** would have saved most of two rounds' security-track effort. Corollary: **the boundary is the HMAC tag on the blob (CV-C53); `strict` and `minimum_version` never were boundaries** and must not be described as such in our own docs.

19. **Run timing-sensitive scripts serially, or the harness manufactures regressions.** The 6-worker parallel sweep produced **four false FAILs** (`107`, `154`, `158`, `167`) that pass 5/5 serially — they poll wall-clock deadlines and are contention-sensitive — while the baseline they were diffed against was produced by a *serial* driver. A naive parallel-vs-serial diff therefore **overstates** regressions, and in a round whose headline question was "did anything regress?" that is the most expensive possible false signal. **Rule: either run timing-sensitive scripts serially, or raise their polling budgets and re-baseline; never diff a parallel run against a serial baseline.** Related: retire probes that reach into engine internals whose shape has changed (`107`/`154`/`158` still read `i._priority_queue` as if its elements were bare events; they have been `(event, bool)` tuples since round-8 `061d619`).

20. **When a fix closes a constraint's ground, re-ground the constraint or retire it — never carry it on the old justification.** This round #212 closed CV-C47's R10-03 ground and R11-04 immediately supplied a new one; #213 closed CV-C49's R10-04 ground and R11-08 supplied its mirror image; #214 closed CV-C48's ground and nothing replaced it, so it retires. Three constraints, three different outcomes, and **only an explicit re-grounding pass distinguishes them**. A constraint carried on a dead justification is indistinguishable from folklore, and the cost is paid twice — once in the complexity retained, once in the confidence misplaced. **Every round must state, per constraint: ground closed? replaced by what? or retired.**

### 9.16 Run 2026-09-23 — `main` @ `de2da4e` (round 12; unreleased 0.8.1, merge of PR #223, `fix/0.8.1-round11`)

```
Gate run 2026-09-23 - xstate-statemachine main @ de2da4e (unreleased 0.8.1;
                      __version__ still reports 0.8.0 - KEY ON THE COMMIT)
  DECISION     : ADOPT WITH CONSTRAINTS - decision-table ROW 8 (UP TWO from row 6)
  issues       : 5 verified - 5 FIXED, 0 partial, 0 not-fixed, 0 regressed-on-one-axis
                 3 of 5 carry NO scope residual at all (first time in the series)
  gate         : 168 checks - 128 PASS / 40 FAIL (6 new checks, all PASS; exit 1 BY DESIGN)
  sweep        : 573 scripts - 476 PASS / 94 FAIL / 3 TIMEOUT; TRUE REGRESSIONS: 0
  suite        : 3545 passed, 13 skipped, 0 failed, 752s - coverage 92.87% (COMPLETE RUN,
                 measured AT the commit under test - first time in four rounds)
  determinism  : 59/59 under PYTHONHASHSEED=1 and 59/59 under =2
  benches      : bench_a OK, bench_j OK; BENCH-1/2/6 UNMEASURED (timeout) -> ROW 9 REFUSED
  library      : 0 Blocker | 0 High | 3 Medium | 6 Low   (High row empty, first since round 10)
  ours         : 2 Blocker (R12-13, R12-14) | 1 High (R12-15) | 2 Medium - config-only
  refutation   : 2 Blockers REFUTED outright, 1 Blocker DOWNGRADED to Low; NONE moved up
  contracts    : 20/20 build clean under RECURSIVE strictConfig, 0 warnings, BOTH lanes
  constraints  : CV-C01...CV-C64 (CV-C47 + CV-C61 RETIRE; CV-C12 STANDS; CV-C63/C64 NEW)
  tag          : YES - cut and tag 0.8.1 at de2da4e; bump __version__ in the same commit
  decided by   : round-12 readiness review, 69-r12-final-readiness-verdict.md
```

**Round 11's regression is reversed, and reversed at the mechanism.** R11-04 was the single open High and CV-C47 was its containment; **#218 closes it at the source** — a 200-beat heartbeat holds **peak 1 handle** on every engine/kind cell, a 500× arm/cancel storm peaks at **0** with no double-release, `stop()` releases the handle, and the soak that read **+753 MB** last round reads **RSS Δ 0.00 MB over 93,168 beats** at `handles_max_per_machine = 1`. That is the difference between row 6 — *one of our constraints is containment for an open library defect* — and **row 8**, where every remaining constraint is an architectural consequence of our own benchmarks.

**The measurement debt split: one paid, one not.** **Paid** — the full suite completed for the first time in four rounds (**3545 passed, 13 skipped, 0 failed, 92.87 %**), so decision-table row 2, which fires *before* any adoption row, now rests on a number taken at the commit under test rather than a one-commit-stale carry-over. The diff weakens no test: `+794/−1` lines, no `xfail`, no `skip`, and the single test edit *strengthens* a #219 pin. **Not paid** — **BENCH-6 is unmeasured for a fifth consecutive round**; `bench_c_timers` timed out again including on a reduced-parameter retry, and `bench_h_candleviewer_budgets` timed out with it, taking BENCH-1 and BENCH-2 with it. **Row 9 is refused explicitly: *unmeasured* is not *met*, and a row requiring all thresholds met cannot be reached by absence of evidence.** The distance from row 8 to row 9 is one benchmark script that has not had a dedicated time slice in five rounds — and it is **ours**.

**The two round questions.** *Did #219 require any change to our catalogue actions?* **No — zero, verified positively rather than assumed:** 0 of 573 sweep scripts and 0 of 20 contract charts contain the refused shape, our ≈30 `wait=True` call sites all await from *outside* an action, and the three plausible determinism-track candidates were individually audited. That is **CV-C25 doing its job since round 5 — anticipation, not luck**. *Did #220's recursion reject any of our catalogue JSON?* **No — there is no rejection to adjudicate**: 20/20 build clean, 0 warnings, both lanes, with **both controls positive** (planted nested typos refused 40/40 with path-named findings; a full valid-key grammar accepted with 0 findings). The load-bearing consequence is retroactive: **nothing in B1–B20 was ever silently dropping an entry action or a transition**, which validates the contract results of rounds 4–11 and is the most valuable thing this fix bought us.

**Refutation, fifth round running, moved every candidate down and none up.** Two Blockers **refuted outright** — **R12-02** (the forged `"version": 2` upcast mint) died on its own control, because a plain v3 blob writing `configuration`/`context` verbatim reaches the identical outcome and the proposed `minimum_version=3` mitigation refuses the forgery while leaving the trivial path open, **proving the trust boundary rather than `upcast` is load-bearing**; merged sources **D11-fuzz-1, D11-semantics-1 and R11-01 fall with it**; and **R12-03** (engine-event provenance forgery), where **no vector uses only the public API**. One Blocker **downgraded to Low** — **R12-01**: the `engine` flag *is* consulted on the `scheduled_sends` path, so a forged record restores as a public `Event` with `e.data == {}` and the payload never arrives; only a narrow `_admit_restored`-bypass parity gap survives. **Fourth consecutive round in which a provenance Blocker died on the same control probe** — standing amendment 18 has now paid for itself four times.

**The row-deciding call is DE-L1, and it is argued in the open.** #219's guard rides an **inheritable `ContextVar`**, so a task spawned inside an action keeps `_ACTIVE_ACTION_OWNER` for its whole life and the **documented `ensure_future` escape hatch** is refused whenever the spawning action yields again — and a background worker born in an action is refused even 300 ms after the machine goes idle. Filed High; **resolved at Medium** on four grounds: every refused shape has a deterministic documented alternative we already mandate (CV-C25, CV-C51), the failure is **loud and immediate** where every High in this study has been *silent*, it is **strictly safer than the silent permanent `start()` deadlock it replaced** (R11-06 — scoring the improvement above its worse predecessor would be incoherent), and our corpus contains **zero** instances. The falsifier is recorded: produce a shape with no fresh-context or gateway alternative and it returns to High.

**Constraints. RETIRED: CV-C47 and CV-C61** — the **first retirement in this study driven by a defect being fixed at the mechanism** rather than by a rule being superseded. CV-C47 had two grounds and both are now closed (R10-03 by #212 in round 11, **R11-04 by #218** this round), with the fire, cancel, supersede and `stop()` paths all covered; CV-C61 existed only to narrow CV-C47's ban around R11-04 and retires with it. **The handle-count gauge survives as telemetry** under CV-C28′ — it is the instrument that let us assert `1.00 per machine` rather than "we saw no growth", and it is how a recurrence would be detected. **CV-C12 (`after` banned) STANDS UNCHANGED**: its ground is BENCH-6, and **#218 fixed a handle-RETENTION defect while saying nothing about DRIFT UNDER LOAD** — retiring it on #218's strength would answer a timing question with a memory measurement. Nothing becomes newly legal for algo timing. **CV-C52 RE-LABELLED** — `minimum_version=3` is **hygiene, not a security control** (R12-02 demonstrates it); keep it, stop calling it a defence. **CV-C51 and CV-C59 become agreements with the runtime rather than substitutes for it**, because #219 and #222 now enforce what they assert — the healthiest state a constraint can reach short of retirement. **CV-C57 re-grounded on Q-5** (#220 does not recurse into an inline-machine `invoke.src`), **CV-C49′ retained as defence in depth** though #221 closed its ground. **NEW: CV-C63** (chain-trip durability is the wrapper's job — the latch is process-local, so a restart silently resets "this machine discarded work" to zero) and **CV-C64** (no action may await *or hand out an `ensure_future` receipt for* a `send(wait=True)` on its own interpreter; **run this lint before upgrading past `c78ce99`**). **Net: 2 retired, 2 new, 62 standing — the count is flat and the character has changed.**

**Pin policy: we would pin a tag cut at `de2da4e`, with NOTHING required to land first — recommendation: cut and tag 0.8.1 at this commit.** 0 Blocker, 0 High, a complete suite at 92.87 %, zero regressions for six rounds, and no test weakened. One thing must ship **with** the tag: **bump `__version__` to 0.8.1 in the same commit**. It has been wrong for twelve consecutive rounds and has cost us nothing because we key on the commit — but a *released* build carrying a wrong version string converts a harmless local inconsistency into a **distributed** one that cannot be re-cut quietly. Until then our pin stays on the commit.

**`run_gate.py` updated:** **added `issues/verify-main-de2da4e` as kind `verifyM9`** (7 scripts, recorded baseline **7/7 PASS**, `VERIFYM9_BASELINE_FAILURES = []`; verified live this round, 6/6 rows green), with per-issue triage hints on failure — including the explicit warning that a `219_*` failure may mean the guard's **predicate was narrowed**, which is the outcome DE-L1 *requests*, and must then be rewritten rather than reported. **Added an explicit `RETIRED_OR_REWRITTEN` register that prints on every run**, listing the superseded oracles and *why*: `_RETIRED_206_delayed_selfsend_charged.py` (SUPERSEDED-BY-#212, renamed in round 11 — **and the rename worked: round 12 spent zero triage on it**), `R11-09_chain_trip_erased_by_next_event.py` (**SUPERSEDED-BY-#222** — it tests the `last_error` oracle the release deliberately retired) and `R11-07_nested_config_typos_silent.py` (**stale repro; it exits non-zero precisely because the defect is gone**).

**Phase 3 CONTINUES, and the library is no longer the binding constraint on any Phase-3 gate.** G-P3-1 (library adoption) is **met**. G-P3-2 is met for 17 of 20 charts, the three exceptions being ours. **G-P3-3 — the linter and `tests/xstate_contract/` — is NOT met and remains the single gating condition**, which matters more at row 8 than it did at row 6: the whole argument rests on constraints being *mechanically enforced*, and an unenforced rule is not a rule (MUST-09). **G-P3-4 (the order-path canary) is blocked by R12-13 and R12-14 only — both ours, both config-only, both proven fixed by a patch that passes 6/6 and 13/13.** **Six items remain open and not one is upstream.**

### Standing amendments added by this run

21. **A superseded oracle is not a regression, and it must be renamed or rewritten in the round that notices it.** Round 11 retired the `206` row by renaming the file with a `_RETIRED_` prefix; **round 12 spent zero triage on it**, which is the whole argument in one observation. Two more of our scripts are superseded at this commit — `R11-09` by #222 (which documents `last_error` as the per-step read it always was) and `R11-07` by #220's fix landing (it now fails *because the defect is gone*) — and both are now in an explicit `RETIRED_OR_REWRITTEN` register that `run_gate.py` prints on every run. **A superseded test left in place becomes a permanent, meaningless blocking FAIL that trains the reader to ignore red**, which is the most expensive failure mode a gate can develop, because it is invisible until the round a real regression hides in the noise.

22. **A row asserting a benchmark threshold may not be satisfied by absence of evidence.** BENCH-6 has been **unmeasured for five consecutive rounds** while **CV-C12 — the largest architectural constraint this study imposes — stands entirely on its stale number**. *Unmeasured* is not *met*; decision-table row 9 is refused on exactly that basis, and it must keep being refused until a number exists. The corollary is a scheduling rule, because the method has now failed five times and the effort was never the problem: **`bench_c_timers` gets a dedicated, generously-timed slice, first, before anything else competes for CPU** — as does `bench_h_candleviewer_budgets`, which took BENCH-1 and BENCH-2 down with it this round purely by sharing a timeout.

23. **Rule 19 is binding, not advisory, and the error scales with worker count.** The parallel sweep produced **11 false FAILs at 10 workers** against round 11's **4 at 6 workers**. In a round whose headline question is "did anything regress?", a harness that manufactures regressions in proportion to its own parallelism costs more triage than the parallelism saves. **Run the timing-sensitive subset serially, or retire the parallel driver for it.** Related and still outstanding: six corpus scripts reach into private internals (`i._priority_queue`, `i._timer_handles`) and are a standing source of false signal — rewrite them against the public API.

24. **When a fix closes a constraint's last surviving ground, RETIRE IT — and say so loudly.** Amendment 20 required re-grounding or retirement; this round is the first time the answer was *retire*, and it was tempting not to. CV-C47 had been re-grounded once already and had just proved its worth by containing R11-04, which makes it feel earned. But **a constraint with no surviving ground is not a safety margin — it is rot**, and rot in a lint file is what trains engineers to route around the linter. The discipline that makes retirement safe is the one applied here: retire the *rule*, keep the *instrument* (the handle gauge, demoted from mitigation to telemetry), and state explicitly what does **not** move with it (CV-C12, CV-C55, R11-W-1) so the retirement cannot be read as a general relaxation.


---

### 9.17 Run 2026-09-23 — tag **`v0.9.0` = `91bd979`** (round 13; tree `main` @ `e3a1f22`)

```
Gate run 2026-09-23 - xstate-statemachine 0.9.0 (tag v0.9.0 = 91bd979) - DECISION: ADOPT with constraints (row 6)
  repros   : all library Blockers closed (LC-01/02/03/16)
  gate     : 136 PASS / 39 FAIL / 0 ERROR of 175
  probes   : verify-v0.9.0 6/6 scripts green (#225-#235)
  benches  : BENCH-6 MET - p99 55.8 ms @ 500 busy (bar 100 ms), n=10
  suite    : 3577 passed, 13 skipped, 92.86%
  blockers open: (library) none      high open: R13-01
  constraints  : CV-C12' (relaxed), CV-C25, CV-C45'', CV-C49', CV-C55, CV-C58,
                 CV-C59, CV-C60, CV-C62, CV-C63, CV-C64' (lint), CV-C65 (new),
                 CV-C66 (new), CV-C67 (new)
  decided by   : round-13 readiness review
```

**First round keyed on a TAG rather than a branch commit**, and the pin is finally a real one. `git diff v0.9.0..HEAD --stat` = `.github/workflows/publish.yml` only (+14/−1) — no library source, no tests, no `pyproject.toml` — so every finding applies to the tag as published. **And 0.9.0 IS on PyPI**, contrary to the environment briefing: `pip download xstate-statemachine==0.9.0 --no-deps` succeeds, and we unpacked the wheel and byte-compared **all 42 `.py` modules** against the tag source after newline normalisation — **0 differ, 0 missing**, sha256 `018505a1b5e7ef1d53c6a820aa680541e87bf2b5b7ad0069e13bae12256c7c0c`. **The published artefact is the reviewed artefact**, which is the property a version-string check can never establish. `CV-V08` (vendor / pin by VCS ref) retires; the pin is `xstate-statemachine == 0.9.0` with a hash-checked lock file.

**11 of 11 fixed (#225–#235), 0 partial, 0 one-axis** — fourth consecutive round where every fix landed on every axis it claimed, and the **first in thirteen rounds with zero "fixed, but…" rows in the input set**. #231 and #235 landed **stricter than asked**. Suite **3577 passed, 13 skipped, 597.15 s, coverage 92.86 %**; **zero library regressions** across 175 gate checks and a 534-script sweep with **0 timeouts**, the two `PASS→FAIL` movements both stale repros asserting pre-0.9.0 behaviour, 13 previously-failing artefacts now passing.

**The round's headline is a correction to ourselves, and it retires the largest constraint this study imposes.** BENCH-6 was never being measured with the right tool: `bench_c_timers.py` does not reproduce upstream's "N busy machines" loaded-timer scenario, so **five rounds of "174.4 ms, still missed" answered a question nobody asked** — and amendment 22, which refused row 9 on the missing number, was refusing it for the wrong reason. Re-run on **THEIR** `benchmarks/production_characteristics.py --quick` §2, ten runs on an idle host: **min 52.1 / p50 53.4 / p99 55.8 / max 55.8 ms against a 100 ms bar — every run under, ~44 ms headroom, spread 3.7 ms**, the tightest this programme has recorded. Round 12 read ~110 ms median on the same unchanged tool; three round-13 submissions disagreed with each other (71.0 / 87.5 / 97.9) and that disagreement resolved to **host load, not library variance**. **`CV-C12` — the `after` ban standing since round 4 — retires to `CV-C12′`**, conditional on re-measurement on target hardware (**P3-G6**). `CV-C64` retires to a lint on #225's task-identity provenance. **Three constraints retired in one round**, the most this programme has ever returned to the library's credit.

**Library board: 0 Blocker · 1 High · 3 Medium · 6 Low.** The High row re-opens, but not from damage. **`R13-01`** — `drain_pending()` (`interpreter.py:1715`) reads only `_event_queue`, never `_priority_queue` (`:374`), while the sibling `_snapshot_pending_events()` (`:1675`) deliberately includes the lane (#107). Two durability views of one interpreter disagree and the one whose docstring promises **"every accepted-but-unprocessed event"** is the lossy one; `_teardown()` then calls `_priority_queue.clear()` (`:1635`), so the documented drain→persist→`stop()` recipe **permanently destroys** fired `after` timers, invoke completions and `send_priority()` traffic. Reproduced on a **live async interpreter, no snapshot, public API only**. Pre-existing — **#233 made it engine-dependent by correctly fixing the sync side.** **`R13-02` (Medium)** is the other half of #230: `on_interpreter_start` never fires on a restored interpreter, either engine, either route, because both `start()` implementations return from the resume branch above their plugin loop; `on_interpreter_stop` still fires, so plugins see an **unbalanced stop-without-start**. Two prior "documented resume semantics" defences were **overturned on the documentation's own words**.

**Row 9 was genuinely in reach and is missed on exactly one row.** All benchmark thresholds met, all library Blockers closed, all Medium triaged — a single upstream commit draining `_priority_queue` before the inbox would empty the High row and carry row 9 immediately. Row 6 applies instead, with `R13-01`'s mitigation mechanically enforced as **`CV-C65`**.

**`run_gate.py` updated:** `issues/verify-v0.9.0` added as kind `verifyV090` (6 scripts, all green at the tag); **BENCH-6 switched from `bench_c_timers.py` to `bench_c_timers_v2.py`**, a thin wrapper over upstream's own `production_characteristics.py --quick` §2, reading `summary_by_busy_level.500.p99`. `bench_c_timers.py` is retained for BENCH-5 (idle drift), which it does measure correctly.

**Phase 3 continues, and the board has inverted.** The library carries **0 Blockers and 1 High**; **we** carry **3 Blockers and 1 High** — all in our own chart definitions, all config-only, all with fixes proven green 11/11 in both spellings on this exact build, and in every case **the engine is spec-correct and the defect is ours** (`onUnhandled:'error'` on B18; a guard ranked ahead of its own action on B11, exactly as XState v5 and SCXML specify). Eight Phase-3 gates are enumerated in `74-r13-final-readiness-verdict.md` §10; **not one of them is blocked on upstream.**

### Standing amendments added by this run

25. **When a threshold sits unmet for several rounds with no mechanism story, SUSPECT THE INSTRUMENT BEFORE THE LIBRARY.** Amendment 22 correctly refused to treat *unmeasured* as *met* — but it diagnosed the wrong failure. The problem was never scheduling or CPU contention; it was that `bench_c_timers.py` **does not implement the scenario BENCH-6 names**, so five rounds of measurement were five rounds of answering a different question, and `CV-C12` — the largest architectural constraint in this study — stood that whole time on a number that never bore on it. The general rule: a benchmark row must **cite the scenario it claims to measure**, and when the library ships its own benchmark for that scenario, **ours must wrap theirs rather than reimplement it**. A reimplementation that silently diverges is worse than no measurement, because it produces a number confident enough to build architecture on. Corollary, from the three conflicting submissions this round (71.0 / 87.5 / 97.9 ms, resolved to host load): **a timing figure without a spread and a run count is an anecdote** — report `n`, min, p50, p99 and max, or do not report.

26. **A fix that closes one engine's half of a symmetric bug creates a divergence, and the round that lands it must check the other engine.** `R13-01` is not new code — `drain_pending()` has ignored the async priority lane throughout. What #233 changed is that the **sync** engine now handles its restore ordering correctly, converting a bug that was at least *uniform* into one that is **engine-dependent**, which is strictly harder to find: it will be tested on one engine and hit in production on the other. This is the parity class #233 itself exists to close. **For our gate: every row exercising a queue, a lane or an ordering must run on both engines even when the issue under test names only one** — the extension of amendments 12 and 13 (service kind, issuer provenance) to *engine* as a parametrisation axis, and the fourth distinct way this study has found a green result certifying only half a contract.

27. **Two documented views of the same state that disagree are a defect in the pair, not in either one.** `drain_pending()` and `_snapshot_pending_events()` both document themselves as the complete set of pending events and return different sets; `on_invalid_event` routes through `from_snapshot(plugins=)` while `on_interpreter_start` has no route at all on the same path. In both cases each half is individually defensible and the **pair** is what misleads — and in both cases the reader who follows the documentation faithfully gets the lossy one. **For our own artefacts: when two accessors claim the same completeness property, a test must assert they agree**, because neither accessor's own test can catch the divergence. This is also why `R13-02` is filed rather than documented: `on_interpreter_stop` firing without `on_interpreter_start` is an **unbalanced** pair, which is a stronger failure signal than an absent hook and is exactly the asymmetry a lifecycle plugin cannot defend against.
