---
id: BENCH-01
title: "Feature: production_characteristics.py should record host hardware/OS and support --json"
labels: [enhancement, performance, perf, docs]
severity: Low
repro_script: null
commit: "v0.9.0 (91bd979)"
---

## Summary

Not a defect — filed for tracking so adopters can gate CI on the published
numbers rather than eyeballing console output. `benchmarks/production_characteristics.py`
is exactly the kind of transparency this workspace wants — "the guide quotes
numbers... Numbers without the script that produced them are folklore; this
file IS the method" (the script's own header comment) — and re-running it
ourselves confirmed the method is sound (`R13-20`: five runs, 52.5-56.7 ms,
spread 4.2 ms, comfortably under the 100 ms bar). The one gap is that §2's
published median (55.8 ms, n=10, one Windows dev host per this workspace's own
measurement) is not machine-checkable: the script prints `platform.platform()`
and `platform.processor()` to stdout (`production_characteristics.py:143-144`)
but never writes them, or the measured numbers, to a structured file, so a
downstream CI job can observe the console text but cannot assert on it without
scraping stdout.

## Environment

- `xstate_statemachine` v0.9.0 (91bd979), `benchmarks/production_characteristics.py`.
- Python 3.x, Windows, stdlib only (the benchmark script itself has no
  third-party dependencies).

## Current state

Running `python benchmarks/production_characteristics.py --quick` prints
human-readable tables for §1 (throughput) and §2 (`after: 10` timer lateness),
followed by three lines of host info (`platform.python_version()`,
`platform.platform()`, `platform.processor()`) and a one-line method note.
Nothing is machine-readable: no `--json` flag, no file output, no exit-code
threshold. The README/production-characteristics guide quotes specific
numbers (e.g. "p99 55.8 ms") without stating which host/OS produced them.

## Requested change

1. **Docs (small):** state in `docs/_guide/production-characteristics.md`
   (or wherever the quoted numbers live) which hardware/OS the published
   figures were measured on — the script already prints `platform.platform()`
   and `platform.processor()`, so this is a one-time paste of that output next
   to the numbers it accompanies, not new instrumentation.
2. **Feature (small):** add a `--json` flag to
   `benchmarks/production_characteristics.py` that emits a single JSON object
   to stdout (or a `--json-file PATH` to write one) containing, at minimum:
   `{"python_version": ..., "platform": ..., "processor": ..., "throughput":
   [{"n": ..., "aggregate_ev_s": ..., "per_interpreter_ev_s": ...}, ...],
   "timer_lateness_ms": [{"busy_machines": ..., "lateness_ms": ...}, ...]}`.
   This lets an adopter's CI run the benchmark on its own target hardware and
   assert (e.g.) `lateness_ms < 100` as a gate, instead of parsing the
   human-readable table.

## Root cause analysis

N/A — feature/docs request, not a defect. Current script has no
`argparse`/JSON output path; `QUICK = "--quick" in sys.argv` (line 28) is the
only flag parsed today.

## Impact

Low, but compounding: every downstream adopter who wants to make the
`after:` timer budget a CI gate (this workspace already plans to,
`73-r13-findings-register.md` §7 `R13-20`: "A 500-machine deployment must
still not place a hard sub-100 ms deadline on `after:` timers... Re-measure on
target hardware") currently has to write their own stdout-scraping wrapper
around the benchmark script to do so. A `--json` flag removes that
boilerplate for every adopter, not just us.

## Proposed fix

Add `--json` / `--json-file` to `production_characteristics.py`'s existing
`argparse`-free `sys.argv` handling (or introduce `argparse` alongside it),
serializing the already-collected `throughput` and `timer lateness` result
lists plus the three `platform.*` values. Add the one-line hardware/OS
sentence to the production-characteristics guide next to the currently quoted
numbers.

## Acceptance criteria

- [ ] `docs/_guide/production-characteristics.md` (or equivalent) states the
      hardware/OS the published §1/§2 numbers were measured on.
- [ ] `benchmarks/production_characteristics.py --json` (or `--json-file`)
      emits a structured object containing host info, per-N throughput, and
      per-busy-count timer lateness, suitable for a CI assertion.

## Related

`73-r13-findings-register.md` §7 `R13-20` (BENCH-6 re-run, host-load caveat,
"single Windows dev host; the library's own note says your macrostep cost
sets your budget. Re-measure on target hardware").
