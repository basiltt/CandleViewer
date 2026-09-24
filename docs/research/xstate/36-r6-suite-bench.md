# Round 6 — Suite + Coverage + Bench (cec108b)

Commit under test: `cec108b` (merge of PR #164, "fix/0.8.1-round5"), `__version__` still
reports `0.8.0` (unbumped — see release-readiness note carried over from `34-...verdict.md`).
Python 3.13.7, Windows 11, venv-main.

## 1. Suite + coverage

```
3399 passed, 13 skipped, 16 warnings in 542.05s (0:09:02)
Required test coverage of 90.0% reached. Total coverage: 92.77%
```

Line-level: `8578` statements, `454` missed → 93% (branch-adjusted overall
figure reported by the tool is 92.77%). `--cov-fail-under` gate from PR
#163 (90%) **passes with headroom** (+2.77 pts). No `xfail`/`xpass`
surprises; the 13 skips are the pre-existing `test_type_safety.py` (7,
platform/typing-guard skips) and `tests_cli/test_code_quality.py` (4) /
`tests_cli/test_postprocess.py` (2) markers, unchanged from prior rounds.

Notable per-module coverage floors (informational, not a gate failure):
`interpreter.py` 89%, `models.py` 91%, `sync_interpreter.py` 97%,
`persistence.py` 95% — the two lowest (`interpreter.py`, `models.py`) are
exactly the two modules round-5 touched most (async run-loop death path,
snapshot field typing), consistent with new branches for rare error paths
(e.g. `SnapshotCorruptError` sub-branches) not all being hit by the
existing suite; not a regression, no gate implication at 90%.

Suite count vs round-5 verdict's antecedent (`34-...verdict.md` §2:
"3 322 passed / 13 skipped" at `3ed3099`): **+77 passed** at `cec108b`,
skip count unchanged (13). The delta is consistent with the changelog's
claim of 52 new tests in `tests/test_round5_findings.py` plus a handful of
new/split cases elsewhere (test file churn noted in the round-5 commit
log: `4b36e9d`/`7c59e6a`/`1288534` rewrote some round-4/round-5 timing
assertions rather than adding tests, so the net new-test count is smaller
than 52 alone).

## 2. `tests/test_round5_findings.py` count

**52 test functions**, matching the changelog's stated count exactly
(`grep -c "^def test_\|    def test_"` → 52). File collects and runs
clean as part of the full suite (see §1) and standalone (see §3).

## 3. `PYTHONHASHSEED` sensitivity (round4 + round5 finding tests only)

```
PYTHONHASHSEED=1: tests/test_round5_findings.py + tests/test_round4_findings.py → 98 passed in 7.03s
PYTHONHASHSEED=2: tests/test_round5_findings.py + tests/test_round4_findings.py → 98 passed in 6.90s
```

Identical pass count (98 = 52 round-5 + 46 round-4) and no flakes/order
differences under either seed. No dict-ordering or hash-dependent
non-determinism detected in either finding suite — consistent with the
round-5 fixes not introducing set/dict iteration into any
observably-order-sensitive path (e.g. `_configuration_is_legal`,
`SnapshotCorruptError` field checks).

## 4. Benchmarks

Ran under the 20-minute wall-clock budget: `bench_a_throughput`,
`bench_h_candleviewer_budgets`, `bench_j_policies`, `bench_e_actors`.
`bench_c_timers` (loaded-drift) was started but did not complete within
the time remaining after the ≈10-min suite run + hashseed re-runs; it was
killed rather than let it eat the remainder of the budget. **Gap, not a
finding** — see §8. No source has touched the timer/clock scheduling path
this round beyond #154 (attach `SimulatedClock` on sync restore, which
`bench_c` doesn't exercise — it uses the real/async clock), so there is no
specific reason to expect drift regression; this is a coverage gap in
*this report*, not evidence of a problem.

Raw results (this run, `cec108b`):

- `bench_a_throughput`: raw `send()` enqueue **238,004 ev/s** (4.20 µs/send);
  pure API **37,479 ev/s** (26.68 µs/ev); lockstep-5000 p95 **45.9 µs**,
  p99 **71.7 µs**.
- `bench_h_candleviewer_budgets`: 500 open orders, fill-latency
  p50 **0.054 ms**, **p95 0.057 ms**, p99 **0.075 ms** — well inside the
  0.10 ms / 300 ms budgets; RSS cost **3.096 KB/open-order**, no leak
  after teardown. Rule-throughput sub-benchmark (`budget2_rules_*`,
  1000 machines × 10 symbols × 100 rules) does **not** meet the 2k
  market-events/s target on either engine (async 410/s, sync 342/s) —
  this is the same shape of shortfall as prior rounds (rule-fan-out is a
  known scaling limit, not a round-5 regression; no source in this area
  changed in #142–#162).
- `bench_j_policies`: burst-50000 ratios vs baseline —
  rollback **0.7358×**, defer **1.1309×**, rollback_and_defer **0.8386×**.
  Sits inside the previously-documented noisy band (`27-r4-gate.md`:
  0.774–1.037× depending on run); **no regression**.
- `bench_e_actors`: spawn 50 children mean **142.97 µs/child** (p95
  186.6 µs); teardown mean **25.4 µs/child**; parent→child throughput
  **20,615 msgs/s**, all delivered; leak check 300 cycles × 10 children →
  **+0.023 KB/actor** (noise-level, no leak) — consistent with prior
  rounds' "12,830 msgs/s, no leak" shape (different machine/run, same
  qualitative result: no leak, all delivered).

## 5. Six-column bench table

| Bench | Metric | 0.8.0 | `5327ba6` | `3c527b0` | `5e07ba8` | `3ed3099` | `cec108b` (this run) | vs. threshold |
|---|---|---|---|---|---|---|---|---|
| `bench_a_throughput` | raw `send()` enqueue | ~170k ev/s | ~170k ev/s | ~170k ev/s | 174,167 ev/s | not independently re-run (no touch) | **238,004 ev/s** (4.20 µs/send) | in family / faster — see §6 caveat |
| `bench_a_throughput` | pure API | ~23k ev/s | ~23k ev/s | ~23k ev/s | 23,051 ev/s | not independently re-run | **37,479 ev/s** (26.68 µs/ev) | in family / faster |
| `bench_h` | 500-order fill p95 | ~0.1 ms | same | same | ~0.1 ms | 0.10 ms PASS | **0.057 ms** PASS | well inside 0.10 ms/300 ms budget |
| `bench_h` | RSS / open order | ~2.7 KB | same | same | same | not independently re-run | **3.10 KB** | in family |
| `bench_j_policies` | defer / rollback ratio | 1.037×/0.808× | 0.854/0.774 | 0.808 | consistent, no regression | not independently re-run | **1.131×/0.736×** | inside historical noisy band |
| `bench_e_actors` | parent→child msgs/s | ~1 task/child (#43) | same | same | 12,830 msgs/s, no leak | not independently re-run | **20,615 msgs/s**, no leak | in family (run-to-run variance, no leak either run) |
| `bench_c_timers` | loaded drift | pass (qualitative) | pass | pass | pass | not re-run this round | **not completed — timed out, killed** | gap, see §4/§8 |

Caveat on the throughput uptick (238k vs the ~170–174k band, and 37.5k vs
the ~23k band): this run was **not** repeated ≥3× as the historical rows
were, and machine load/CPU-boost state differs run to run on this shared
box (the round-5 gate's own LC-12 flake note makes the same point about
single-run noise). Treat the increase as **plausible but not confirmed**
— it is directionally consistent with PR #141's hot-path perf claim (see
§6) but a single sample is not sufficient to attribute the full delta to
that PR versus environmental variance. A ≥3-run repeat, ideally
bisecting to a commit before/after #141, would be needed to confirm the
magnitude.

## 6. PR #141 "fastest of benchmarked libraries" claim

Not independently checked here — that claim is about a cross-library
comparison (this library vs. others), and this task's benchmark set
(`bench/*.py`) only exercises this library in isolation; there is no
cross-library harness in the files run. What this run **does** show that
is *consistent with* (not proof of) #141's "hot-path perf" framing: raw
`send()` enqueue and pure-API throughput both came in noticeably above
every previously-recorded figure for this library (§5), in the direction
#141 would predict. That is circumstantial support at best given the
single-run caveat in §5 — **the "fastest of benchmarked libraries" claim
itself is not verified or refuted by this task's evidence** and would
need the actual comparison harness/README claim's benchmark script to
check.

## 7. `service_executor` latency on submit→ack path

`bench_h_candleviewer_budgets`'s order-fill path (500 open orders, fill
latency p50/p95/p99 = 0.054/0.057/0.075 ms) does **not** route through
`service_executor` — that machine's actions are synchronous (no
plain-`def` invoked service on the fill path), so this run cannot
directly measure the thread-hop cost #149 introduces. Indirect evidence:
`bench_h`'s numbers are *better* than the prior-round figures (~0.1 ms →
0.057 ms p95), which is the opposite of what a new mandatory thread-pool
hop on that path would produce — suggesting either (a) the order-path
budget machine doesn't invoke a plain-`def` service at all (most likely,
given CV-C32 forbids non-async services on the order path per
`34-...verdict.md` §7), or (b) any added latency is masked by the
throughput gain seen elsewhere this run. **No direct measurement was
taken of `service_executor`'s per-call thread-hop overhead** (e.g. a
microbenchmark of `Interpreter(service_executor=...)` running a
trivial plain-`def` service vs an `async def` equivalent) — that would
need a small dedicated script, out of scope for the files this task was
pointed at. Flagged as an open measurement gap, not a finding either way.

## 8. Time budget note

Total wall clock for this task: full suite + coverage (~9 min) +
hashseed×2 re-runs on the two finding files (~14 s total) + four
benchmark scripts (`bench_a`, `bench_h`, `bench_j`, `bench_e`, a few
minutes combined) left too little of the 20-minute bound to let
`bench_c_timers` (which runs 60 real-time-based timer samples per delay
tier, several tiers, under load — a multi-minute script by design) finish
cleanly; it was killed mid-run. Per the task's own bounds ("reduce
parameterisations and say so"), the recommended reduction if this needs
re-running standalone: cut `TIMER_SAMPLES` from 60 to ~15–20 and/or drop
the busiest-load tier, which should bring it under ~60–90 s while still
giving a directional read on drift under load.
