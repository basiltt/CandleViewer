# R12-05 — DE-A11 refuted: the library already ships a bounded timer-drift benchmark

**Status: REFUTED as drafted. Not filed.**
**Commit:** `de2da4e`

## The claim as drafted

> `bench_c_timers` (in the library's `benchmarks/` tree) exercises timer
> drift under load ... In our runs it reliably exceeds a 120s budget ...
> BENCH-6 remains unmeasured for a fifth consecutive round.
>
> Requested: split or parameterize `bench_c_timers` so a caller can select
> a small, fast tier ... consider a `--quick` / `--tiers=...` style flag.

## Why it is refuted

**`bench_c_timers` is ours, not the library's.** It lives at
`docs/research/xstate/bench/bench_c_timers.py` in our own harness. The
library's `benchmarks/` tree contains exactly two entries:

```
benchmarks/competitors/
benchmarks/production_characteristics.py
```

There is no `bench_c_timers` upstream. The draft asks the library to fix a
timeout in a script the library does not own — the entire premise is
misattributed.

### The requested feature already exists

`benchmarks/production_characteristics.py` §2 measures exactly what BENCH-6
wants — `after: 10` lateness across a 0/10/100/500 busy-machine ladder —
and it already has the `--quick` flag the draft asks for
(`production_characteristics.py:28`, `QUICK = "--quick" in sys.argv`,
consumed at lines 76 and 114).

### It completes well inside budget, and it produces the number

Run from the library root, `PYTHONPATH=src`, `.venv-main`:

| mode | wall clock | `busy=500` lateness |
|---|---|---|
| `--quick` | **5.6 s** | +89.6 ms |
| `--quick` (repeat) | ~6 s | +94.1 ms |
| `--quick` (repeat) | ~6 s | +113.3 ms |
| `--quick` (repeat) | ~6 s | +110.0 ms |
| full matrix | **18.2 s** | +111.2 ms |

Both modes finish in a small fraction of the 120 s budget. The number the
draft calls "unmeasured for five consecutive rounds" takes **six seconds**
to obtain.

## What this actually tells us

BENCH-6's bar is **≤100 ms p99 lateness at 500 machines**. Four fresh runs
on `de2da4e` give a median lateness at `busy=500` of **+89.6 / +94.1 /
+113.3 / +110.0 ms**, and the full matrix gives **+111.2 ms**. That
straddles the bar — two of five runs under it, three over, on a loaded
developer laptop, and note these are *median* figures where BENCH-6 is
specified on p99.

So the honest statement is not "unmeasured for five rounds" but: **BENCH-6
is now measured, and it sits marginally over our bar on this host**, a
very large improvement on the 2530 ms at 0.8.0 and consistent with the
174.4 ms captured at `5327ba6`. The gate row should be corrected from
*unmeasured* to *measured, marginally missed, host-dependent* — and the
correction is ours to make, not the library's.

## Verdict

The library-facing ask evaporates: the benchmark exists, is bounded, has
the requested `--quick` flag, and yields a current number in seconds. The
five-round "unmeasured" record was a property of our harness pointing at
our own over-parameterised script instead of the upstream one. **Not
filed.** Corrected on our side instead.

## Follow-on (ours, not the library's)

1. Re-point BENCH-6 at `benchmarks/production_characteristics.py --quick`.
2. Re-state the threshold on the metric the script reports (median) or
   extend our harness to compute p99 from it.
3. Update `69-r12-final-readiness-verdict.md` row 9 and the CV-C12
   constraint's ground: it no longer rests on an unmeasured benchmark.
