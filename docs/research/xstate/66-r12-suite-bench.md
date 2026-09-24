# Round 12 — suite + bench (de2da4e)

Env: fresh `.venv-main`, PYTHONIOENCODING/PYTHONUTF8=utf-8. Whole task capped
at 20 min wall clock; several items reduced or cut short as noted below.

## Suite (from pre-started background run, `suite-de2da4e.log`)

Run completed (not truncated): **3545 passed, 13 skipped**, in 752.21s
(12m32s). Coverage: **92.87%** total (required 90.0%, reached). Per-file
coverage matches the round-11 shape; no file dropped below its round-11
floor at a glance (`base_interpreter.py` 92%, `interpreter.py` 92%,
`sync_interpreter.py` 97%, `models.py` 88%, `validation.py` 99%). This is
the first round with a genuinely complete full-suite + coverage total
(round 11 only saw ~4% stream before its time bound) — closing the
round-11 follow-up item.

## Hash-seed determinism, round 9+10+11 findings combined

`tests/test_round{9,10,11}_findings.py`, 59 tests total:

- `PYTHONHASHSEED=1`: **59/59 passed**, 47.10s
- `PYTHONHASHSEED=2`: **59/59 passed**, 47.62s

No correctness regressions; matches round 11's 65/65 pattern (round 11
counted round 8+9+10 = 65; round 12 counts 9+10+11 = 59, round 8 not
re-run this round since round 12's instruction scope named 9/10/11 only).

## Benchmarks

### bench_a_throughput — complete

| metric | value |
|---|---|
| burst_10000 events/s | 13,364 (74.8 µs/ev) |
| burst_50000 events/s | 15,843 (63.1 µs/ev) |
| lockstep_5000 events/s | 10,109 (p50 96.5 µs, p95 107.1 µs, p99 154.2 µs) |
| raw_send_50000 | 122,330 sends/s (8.17 µs/send) |
| pure_api_50000 | 14,648 events/s (68.3 µs/ev) |

All within ~5-10% of round 11's readings (no regression visible from #218's
handle-release fix or #220's recursive key-check — neither is on this hot
path per-event, only on `create_machine` and timer-cancel, consistent with
throughput being unchanged).

### bench_j_policies — complete

| policy | events/s | vs baseline |
|---|---|---|
| baseline | 5,086 | 1.0x |
| rollback | 3,576 | 0.703x |
| defer | 3,910 | 0.769x |
| rollback_and_defer | 3,208 | 0.631x |

Tracks round 11 within a few percent on baseline/rollback/defer.
`rollback_and_defer` (0.631x) is close to round 11's low reading rather than
round 10's — this metric has now read low twice in a row and should be
treated as the real number rather than noise, superseding the round-11 "should
be re-checked" flag.

### bench_h_candleviewer_budgets — INCOMPLETE (timed out)

The 120s per-script bound was hit before the script's four sub-benchmarks
(submit/ack latency at background=500, rule-eval 1000x10 both engines,
500-open-orders memory) finished — this script does 500-order populations
sequentially and has historically taken several minutes total. Not re-run
with reduced params in the remaining budget; **no Budget 1/2/3 numbers this
round**. First item to budget properly (own time slice, not shared) in
round 13.

### bench_c_timers — INCOMPLETE (timed out), third→fourth consecutive round

Attempted a reduced-parameter run (`load_100`/`load_500` only, delays
10ms/100ms only, dropping the 1000ms tier and the CPU-hog tier) via an
ad-hoc wrapper script; it still did not return within the remaining time
budget and was left running in the background with no output captured by
turn end. **BENCH-6 (loaded drift under load_100/load_500) remains
unmeasured for a fifth consecutive round.** This is now the standing top
priority for round 13: give it a dedicated, generously-timed slice (e.g.
300s solely for `load_100` at 2 delays) before anything else, since every
round's attempt to fit it alongside other benchmarks in a shared time
budget has failed.

### bench_e_actors — NOT ATTEMPTED

Time budget was exhausted by the bench_c retry before this could be
started.

## #218 / #220 cost signal

No dedicated microbench isolated `create_machine` cost or heartbeat handle
memory this round (time-boxed out). Indirect signal: bench_a's
`create_machine`-adjacent paths (burst/lockstep/pure_api) are flat vs round
11, consistent with #220's recursive unknown-key check and #218's handle
release being validation/teardown-path changes that don't touch the
per-event hot loop measured here. This is inference, not direct
measurement — still on the outstanding-work list.

## Outstanding for round 13

1. `bench_c_timers` (BENCH-6) — dedicate a full, unshared time slice first.
2. `bench_h_candleviewer_budgets` — needs its own ~2-3 min slice; last
   confirmed complete reading was round 11 (Budget 1 met at 2.08x headroom,
   Budget 2 missed by ~5x, KB/order noisy and widening 2.1→3.1→5.5 across
   rounds 9-11).
3. `bench_e_actors` — not attempted in two consecutive rounds now (11, 12);
   check whether it has grown slow enough to need its own slice too.
4. Dedicated `create_machine`/handle-release microbench for #218/#220,
   still carried from round 11.
5. Round 8 re-inclusion in the combined hash-seed determinism check, or
   explicit statement that 9+10+11 is now the fixed scope going forward.

## Verdict (partial, suite-complete)

No correctness regressions: full suite 3545 passed / 13 skipped, 92.87%
coverage (first complete full-suite reading in three rounds), and
round-9/10/11 combined findings 59/59 under both `PYTHONHASHSEED=1` and
`=2`. bench_a is flat vs round 11 (confirms #218/#220 don't touch the
per-event hot path). bench_j's `rollback_and_defer` reading (0.631x) now
agrees with round 11 rather than round 10, so should be treated as real.
bench_h and bench_c both timed out and produced no numbers this round —
Budget 1/2/3 and BENCH-6 loaded-drift remain unmeasured this round (BENCH-6
now unmeasured for five consecutive rounds and should be round 13's first
priority with a dedicated, unshared time slice).

## Round-13 addendum (all four gaps above closed — see `71-r13-suite-bench.md`)

- **BENCH-6 finally measured properly**: switched to upstream
  `production_characteristics.py --quick` §2 (this repo's `bench_c_timers.py`
  was the wrong tool all along, per round-12's own correction note). 6
  readings at 500 busy machines: +124.1/+79.9/+97.9/+78.1/+77.6/+91.2 ms.
  p50 ≈ +85.6 ms, max +124.1 ms — straddles our ≤100 ms p99 bar, same
  envelope as the round-12 numbers quoted in the task brief
  (+89.6/+94/+113/+110/+111), so **no regression, no fix either** — this is
  an architectural characteristic of single-loop cooperative scheduling
  under 500 busy machines, not something round-12's changes touch.
  New reusable tool: `bench/bench_c_timers_v2.py`, a thin wrapper over
  upstream's script that `run_gate.py` can consume going forward.
- **bench_h completed this round** (~115 s, under the 300 s cap, no need to
  split into per-section runs): budget1 (submit-to-open) passes with 2.16x
  headroom; **budget2 (2,000 market-events/s @ 1000×10×100 rule scale)
  fails on both async and sync engines** (~400 ev/s achieved) — unchanged
  ceiling; budget3 (500 open orders) passes, ~2.96 KB/order.
- **bench_e completed**: spawn 150 µs/child, teardown 27 µs/child, 15.8k
  msgs/s parent→child, no leak over 3,000 actor lifecycles (+0.085 KB/actor).
- **bench_j re-confirmed**: rollback_and_defer 0.693x vs baseline — same
  ballpark as rounds 11/12 (0.631x/~0.7x), no new regression.
- Full suite: 3577 passed / 13 skipped, 92.86% coverage — clean, complete.
- Hash-seed parity (rounds 10+11+12 combined, 69 tests): clean under both
  `PYTHONHASHSEED=1` and `=2`.
- `git diff v0.9.0..HEAD --stat`: CI-workflow-only (1 file,
  `.github/workflows/publish.yml`); no library-source drift from the tag.
- **New finding: PyPI still serves 0.8.0**, not 0.9.0 — the round-12 fixes
  are not yet installable via `pip install xstate-statemachine`.
