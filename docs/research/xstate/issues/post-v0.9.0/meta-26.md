# Meta — round-13 adoption readiness report, `xstate-statemachine` 0.9.0

**NOT POSTED. Draft.** Comment #26 on the standing adoption-readiness meta-issue.

## Round 13 summary — tag `v0.9.0` = `91bd979`

All eleven round-12 issues (#225–#235) verified **FIXED**, on both engines and in both `def` and `async def` service spellings, from a neutral working directory with standalone repros. **Zero partials, zero one-axis fixes** — the first round in thirteen where the input set contained no "fixed, but…" rows at all. Two fixes (#231, #235) landed **stricter** than the issue asked for, and we prefer the stricter shape in both cases.

| | |
|---|---|
| Issues verified fixed | **11 / 11** |
| Library regressions | **0** |
| Library suite | 3577 passed, 13 skipped, 15 warnings, 597 s, coverage **92.86 %** |
| Historical script sweep | 534 scripts, **0 timeouts**; 11 previously-failing now pass |
| Our adoption gate | 136 PASS / 39 FAIL / **0 ERROR** of 175 |
| New library defects filed | **10** (1 High, 4 Medium, 4 Low, 1 Info) |
| Our decision | **ADOPT with constraints** |

## Two corrections to earlier rounds, both in your favour

**1. The timer benchmark we were failing you on was the wrong benchmark.** We had carried a constraint banning `after` in our charts since round 4, grounded on a loaded-timer figure of 174 ms against our own 100 ms bar. That figure came from a harness of ours that does not reproduce the "N busy machines" scenario. Re-measured this round with **your own** `benchmarks/production_characteristics.py --quick` §2, ten runs on an idle host:

```
after: 10 ms deadline, 500 busy machines — median lateness beyond deadline
  min 52.1 · p50 53.4 · p99 55.8 · max 55.8 ms   (n = 10, spread 3.7 ms)
```

Every run is comfortably under the bar with ~44 ms of headroom, and the spread is the tightest we have recorded. Round 12 read a median of ~110 ms on the same unchanged tool, and three separate round-13 submissions disagreed with each other (medians 71.0 / 87.5 / 97.9) — we chased that down to **host load, not library variance**. Plausible contributors on your side, though we have not isolated them: #218's clock-handle leak fix and #225 removing the ContextVar from the send hot path.

**Consequence: our `after` ban retires**, downgraded to "coarse timeouts and deadlines with ≥250 ms tolerance", conditional on re-measuring on our target hardware. That is a constraint your work removed from our architecture, which is the strongest thing we can say about a release.

**2. Our "not on PyPI" caveat is retired.** 0.9.0 is published. We unpacked the wheel and byte-compared all **42 `.py` modules** against the `v0.9.0` tag source: **0 differ, 0 missing** (sha256 `018505a1b5e7ef1d53c6a820aa680541e87bf2b5b7ad0069e13bae12256c7c0c`). The published artefact is the reviewed artefact. We now pin `xstate-statemachine==0.9.0` from the index with a hash-checked lock file, and the vendoring caveat we had carried since 0.8.0 is gone.

## Two new issues, both narrow

Filed separately with standalone repros in the body:

- **High — #239 `drain_pending()` drops the entire priority lane on the async engine**, and `stop()` then clears it, so the documented drain→persist→exit shutdown recipe permanently loses fired `after` timers, invoke completions and `send_priority()` traffic. `pending_events` on the same object disagrees with `drain_pending()` about what is pending. Reproduces on a live interpreter, no snapshot, public API only.
- **Medium — #240 `on_interpreter_start` never fires on a snapshot-restored interpreter**, on either engine, via either registration route, because both `start()` implementations return from the resume branch above their plugin notification loop. `on_interpreter_stop` still fires, so a lifecycle plugin sees an unbalanced stop-without-start. This is the other half of the hook #230 fixed.

Neither corrupts state, loses an accepted event on the normal path, or bends transition semantics in either engine. Both are observability/durability-path issues with workarounds, and both are — as far as we can tell — a few lines each.

Eight further items round out the "make it perfect" list, all filed for tracking rather than as defects blocking adoption: #241 (Medium, malformed `chain_trips`/`last_chain_error` escaping `from_snapshot` as a raw exception instead of `SnapshotCorruptError`), #242 and #243 (Medium, two docs-ordering/completeness gaps in the persistence trust-boundary writeup), #244 (Low, the #232 dropped-receipt `RuntimeWarning` isn't gateable under `-W error` because it fires from `__del__`), #245 (Low, `SyncInterpreter` has no documented queue-bound story, by design), #246 (Low, the benchmark script should record host hardware and support `--json`), #247 (Low, PyPI Trusted Publishing / attestations for the release pipeline), and #248 (Info, the one-way `_replace()` demotion added by #235 has no public re-mint path, undocumented).

## Where this leaves adoption

**One issue** now separates "adopt with constraints" from "adopt unconstrained" in our decision table: the `drain_pending()` priority-lane row. Every benchmark threshold is met, every blocker we ever filed against the library is closed, the suite is green at 92.86 % coverage, and our remaining work is our own — of the open defects on our board, **three blockers and one high are in our own chart definitions**, not in this library, and every one of them traces to us configuring `onUnhandled:'error'` or ranking a guard ahead of its own action, where the engine is behaving exactly as XState v5 and SCXML specify.

That is a notable inversion. Thirteen rounds ago the risk in this adoption was upstream; it is now almost entirely ours to discharge.

## One methodological note that cost us a round

Our contract harness wrapped every action implementation in a plain `def` for uniformity. For an `async def` action that **drops the returned coroutine** — never awaited, never run, no error. It had been silently masking our #225 probes, which read `exc=None` where they should have read `ReentrantWaitError`. We only found it by running the corpus under `-W error::RuntimeWarning`.

Entirely our bug. We mention it because building a generic action registry over this library is a natural thing to do, and this is an easy and completely silent way to get it wrong. Worth a sentence in the docs next to action registration: register coroutine functions directly.

Thank you — eleven for eleven, with two landing stricter than asked, is a good round.
