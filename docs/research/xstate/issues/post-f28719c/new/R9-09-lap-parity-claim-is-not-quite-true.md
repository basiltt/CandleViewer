---
r9: R9-09
severity: Medium
verified: true
build: f28719c
relates_to: [201]
labels: [documentation, severity/medium, tests]
repro: new/repro/R9-09_lap_parity_odd_limit_mismatch.py
---

# #201's "all three lanes agree at every limit tested" is not quite true: sync runs exactly two laps more than async at every *odd* `maxIterations` on the `def` lane

**Severity (ours):** Medium (documentation)
**Build:** `main` @ `f28719c` (merge of PR #202, unreleased 0.8.1; `__version__` still reports `0.8.0` — keyed on the commit)
**Environment:** CPython 3.13.7, Windows 11, fresh venv
**Relates to:** #201 — narrower than claimed: the fix itself is real and holds; the changelog sentence describing its scope over-states what the sweep supports.

---

## Summary

A documentation-accuracy item, not a behaviour complaint.

#201 fixed the real problem — seeding initial-descent completions rather than charging them — and async lap counts now match the sync engine for the cases that motivated the fix. We re-verified it and it holds. The CHANGELOG wording, though, claims more than the measurement supports.

`CHANGELOG.md:90-91` (quoted verbatim):

> Fixed; all three lanes now agree at every limit tested.

They do not, on one axis: **the sync engine runs exactly two laps more than async at every *odd* `maxIterations` on the `def` lane, on the `rollback_ondone` shape.** The offset is deterministic and small, which is why it reads as an off-by-one-pair in the parity accounting rather than a semantic divergence.

## Root cause

The changelog entry for #201 (`CHANGELOG.md:86-94`) itself already discloses the relevant caveat one line below the "all three lanes" sentence: *"What is not promised: on `rollback + onDone` the sync engine does not re-arm a rolled-back invoke inside the same drain and stops after the first rollback with that `RuntimeError`, while both async lanes trip `RunawayChainError` at the same lap."* That caveat correctly flags a **different-shaped** disagreement (an error-type mismatch at low limits), but the changelog's own summary sentence ("all three lanes now agree at every limit tested") is written as an unqualified universal and does not carry that caveat into its wording. The measured lap-count table below shows the disagreement is systematic across the whole odd/even axis on `def`, not just an edge case at one limit — `sync_laps` and `async_laps` differ by exactly 2 at every odd `maxIterations` (1, 3, 5, 7, 9, 15, 25) and agree at every even one (2, 4, 6, 8, 10, 20), on the `rollback_ondone` shape with a plain-`def` service.

## Impact

**General:** the claim as written ("all three lanes... at every limit tested") is the kind of sentence a downstream adopter writes a conformance assertion against. When it turns out to hold "except at odd limits on one spelling on one shape", the assertion fails in CI and costs a triage cycle to chase down — as it did for us; we initially mis-triaged this as a possible regression before isolating it as a docs-only mismatch.

**Order-management:** no runtime consequence for callers whose order path never runs on `SyncInterpreter` (ours does not) — the divergence is entirely between `SyncInterpreter` and `Interpreter` lap-count bookkeeping on the `def` service spelling; both engines still bound the storm and both still raise `RunawayChainError`. The risk is purely in a written contract a caller might rely on for cross-engine consistency testing.

## Minimal reproduction

`R9-09_lap_parity_odd_limit_mismatch.py` (attached; stdlib + `xstate_statemachine` only, inlined from the round-9 evidence script `g2_lap_parity.py`, run from a neutral cwd). Sweeps `maxIterations` 1-10, 15, 20, 25 across two shapes (`nested_invoke`, `rollback_ondone`) × two service kinds (`def`, `async def`) × two engines (`SyncInterpreter`, `Interpreter`), and prints the full lap table. Exits 1 if the def-lane/`rollback_ondone` odd-limit-mismatch-of-exactly-2 pattern is present.

## Observed (fresh run)

```
rollback_ondone / def
    mi=1   sync_laps=3     async_laps=1     DIFFER
    mi=2   sync_laps=3     async_laps=3     SAME
    mi=3   sync_laps=5     async_laps=3     DIFFER
    mi=4   sync_laps=5     async_laps=5     SAME
    mi=5   sync_laps=7     async_laps=5     DIFFER
    mi=6   sync_laps=7     async_laps=7     SAME
    mi=7   sync_laps=9     async_laps=7     DIFFER
    mi=8   sync_laps=9     async_laps=9     SAME
    mi=9   sync_laps=11    async_laps=9     DIFFER
    mi=10  sync_laps=11    async_laps=11    SAME
    mi=15  sync_laps=17    async_laps=15    DIFFER
    mi=20  sync_laps=21    async_laps=21    SAME
    mi=25  sync_laps=27    async_laps=25    DIFFER

VERDICT: def-lane odd-limit mismatch confirmed (claim false, as filed)
```
Exit code: 1. (Both lanes raise `RunawayChainError` at every row shown — the bound itself is intact; only the lap *count* differs.)

Total lap-parity mismatches across the full sweep (both shapes, both kinds): 33 — the `nested_invoke`/`async def` and `rollback_ondone`/`async def` mismatches are a separate, expected divergence (`SyncInterpreter` raises `NotSupportedError` for an `async def` service outright, since it cannot run one), not part of this finding; this finding is specifically the `def`-lane, `rollback_ondone`-shape, odd-limit pattern.

## Expected

`CHANGELOG.md:86-94` and #201's own PASS/FAIL framing describe the parity claim as holding universally ("all three lanes now agree at every limit tested"). A documentation claim of this shape should either hold as stated, or be scoped to the cases actually measured, per ordinary changelog-accuracy practice — there is no external spec (SCXML has no notion of "sync" vs. "async" engine lap parity) to cite here beyond the library's own stated claim, which is the artefact under review.

## Suggested resolution

Either fix the two-lap offset (align the sync engine's `rollback + onDone` re-arm counting with the async engine's on odd limits), or restate the changelog sentence as e.g. *"the async and sync engines agree at even limits on `rollback + onDone`/`def`; odd limits differ by exactly two laps, because [reason]; both still bound and raise `RunawayChainError`."* Either is fine from our side — under our own constraints the order path never runs on `SyncInterpreter`, so the divergence has no runtime consequence for us, and we would accept either the fix or the more accurate sentence.

## Proposed fix

Investigate the sync engine's lap-counting for `rollback + invoke.onDone` re-arm at odd limits (`sync_interpreter.py:747-825`, the `max_iterations` per-chain counting logic referenced there) to see whether the +2 discrepancy at odd limits traces to a boundary-inclusive vs. boundary-exclusive counting difference in how the sync drain counts the rollback-triggered re-arm versus how `interpreter.py`'s `_raise_depth` counts the equivalent async completion. If root-caused as a genuine off-by-two in one engine's counting, fix that engine's count; if it is an inherent artefact of the two engines' different re-arm timing (sync re-arms within the same drain call, async spans a task boundary), narrow the changelog sentence instead, per the suggested resolution above.

## Acceptance criteria

- `test_lap_parity_changelog_claim_is_scoped_or_fixed` — either (a) the attached sweep shows `sync_laps == async_laps` at every `maxIterations` 1-25 on `rollback_ondone`/`def` (fix landed), or (b) `CHANGELOG.md`'s #201 entry is updated to state the odd/even distinction explicitly (doc fix verified by a simple string-presence check in a docs lint, not a runtime test).
- `test_lap_parity_bound_holds_regardless_of_offset` (regression guard) — regardless of which resolution is chosen, both engines must still raise `RunawayChainError` at every `maxIterations` in the sweep; the two-lap discrepancy must never let either engine exceed its own configured limit without tripping.
- Reference: `tests/test_round6_findings.py::TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations` should switch its 0.6 s/0.9 s fixed-sleep sampling to poll-to-convergence (see below) as part of the same pass, since it sits in the same test family and shares the root confusion between "still climbing" and "wrong."

## A related, separate observation on the same test family

`tests/test_round6_findings.py::TestAsyncRollbackRearmCycleBounded::test_service_calls_bounded_by_max_iterations` reads its call counter 0.6 s after start and asserts it equal to the count at 0.9 s. On a normal host the `def` lane is **still climbing at 0.6 s** and converges around 1.0 s, so the test fails roughly 80% of runs while the behaviour it tests is **correct**. Polled to convergence, both lanes plateau at exactly **1003 = `maxIterations` + 2** and stay there:

```
kind=def   series=[(0.5,781),(1.01,1003),(1.52,1003),(2.03,1003),(2.54,1003),(3.05,1003)]
kind=async series=[(0.51,1003),(1.02,1003),(1.53,1003),(2.03,1003),(2.54,1003)]
```

The bound is solid; only the test's sleep is too short. We mention it here because we initially mis-triaged it as a possible regression in this same area, and a longer or poll-based wait would stop it misleading the next reader.

## Verification

- Date: 2026-09-22
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `f28719c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- cwd used: `<home>` (neutral, outside both repos)
- Exit codes: `R9-09_lap_parity_odd_limit_mismatch.py` → **1** (def-lane/`rollback_ondone` odd-limit mismatch of exactly 2 laps confirmed at mi=1,3,5,7,9,15,25; agreement confirmed at mi=2,4,6,8,10,20; `RunawayChainError` raised on both engines at every row)
