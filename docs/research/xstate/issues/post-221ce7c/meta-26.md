# Meta-issue #26 refresh — round-7 verification of `main` @ `221ce7c`

**Build:** `main` @ `221ce7c` (merge of PR #178 on top of #177 and the hot-path
PRs #165/#176). Unreleased 0.8.1; **`__version__` still reports `0.8.0`, so every
claim here keys on the commit.** CPython 3.13.7, Windows 11 Pro. No library source
was modified. Every finding was reproduced in a fresh process before it was
counted.

**Method:** 12 issue verifications · full regression sweep (the gate plus every
standalone verify/repro/probe script) · library suite + coverage · benchmarks ·
a full read of the `cec108b..221ce7c` diff (~1.7k lines of `src/`) · 8 battle
tracks re-run with new attacks · 20 contract machines driven end-to-end · then
triage, dedupe, and **independent adversarial refutation of every Blocker and
High candidate**.

---

## The 12 issues

| Result | Issues |
|---|---|
| **FIXED** (7) | #157 · #166 · #169 · #170 · #171 · #172 · #173 |
| **PARTIAL** (2) | #167 · #168 — bounded for plain `def` services, completely unbounded for `async def`. **One defect, not two.** |
| **DOCUMENTED-ONLY** (2) | #122 — correctly closed as working-as-designed; our repro encoded a false expectation and we withdraw our reopen. · #174 — documented, behaviour unchanged. |
| **NOT-FIXED** (1) | #175 Case D — 160/160 receipts resolved as ordinary success, and the shipped regression test passes while it is broken. |

## Counts after refutation

**2 Blocker · 4 High · 6 Medium · 8 Low.** Refutation moved **three** of eight
Blocker/High candidates *down* and **none** up; one was refuted outright, leaving
only a narrower documented residual. Pre-refutation the round stood at
3 Blocker · 5 High · 5 Medium · 7 Low.

| Sev | ID | One line |
|---|---|---|
| **Blocker** | R7-01 | An `async def` service's completion is published on the public inbox lane, so self-generated invoke cycles are unbounded — 28 108 calls vs 23 for the identical chart with `def`. One variant settles into an **empty configuration** reporting `ok=True`. |
| **Blocker** | R7-02 | External `send(priority=True)` is charged to the chain budget — 751 of 1 500 external sends dropped as `chain_budget`; the control without `priority=True` drops zero. |
| High | R7-03 | `await start()` hangs unboundedly on a slow invoked child (untimed `gather`). |
| High | R7-05 | Async `start()` never sets the in-flight flag, so the mid-step snapshot refusal is inert for the whole initial-entry window. |
| High | R7-07 | A root snapshot harvests a child actor's half-applied context; the torn blob restores clean. |
| High | R7-08 | `_await_settled_for_snapshot` spins `time.sleep` on the event-loop thread, so the child it waits for cannot progress — 501 ms blocked per call. |
| Medium | R7-06, R7-09, R7-10, R7-11, R7-12, R7-13 | See individual issues. |
| Low | R7-14…R7-20 + the R7-04 residual | Ride along here rather than as separate issues. |

## The pattern of this round, in one sentence

**WHO issued an event has been replaced by WHEN it arrived.** Self-generated work
escapes the budget on the coroutine completion lane (R7-01); external work is
charged on the priority lane (R7-02). Two lines in `interpreter.py`, opposite
halves of one mistake.

## What we would ask for first, before any individual fix

**Parametrise every service-invoking test over service kind.**

```python
@pytest.mark.parametrize("kind", ["def", "async def"])
```

All three pinned regression tests for the invoke-cycle family
(`tests/test_round6_findings.py:124/184/486`) declare `def svc`. Six independently
filed findings on our side collapse into R7-01, and **all six would have been
caught by that one line** before the fixes shipped.

It is the same lesson as last round, one level down. Last round: *fixed on the
engine the issue was filed against.* This round: *fixed on the service kind the
test was written against.* A matrix over (engine × service kind) on the invoke and
snapshot suites would close both classes permanently.

**Second ask:** two shipped tests pass while their defect is live — #175's
regression test pins only `ok == applied`, and `tests/test_persistence.py` has no
null/absent-`machine_hash` case. Both are cheap to strengthen.

## Pre-tag checklist for 0.8.1

1. **Bump `__version__`.** Seven verification rounds have now keyed on commits
   because the tree reports `0.8.0` while the CHANGELOG describes 0.8.1.
2. **Do not tag until R7-01 and R7-02 land.** A tag cut at `221ce7c` releases two
   silent Blockers, both in code this release added, neither wrappable.
3. Land the one-liners while you are in the file: R7-05 (mirror
   `sync_interpreter.py:370-374`), R7-08 (`await asyncio.sleep`), R7-06 (gate on
   `version >= 1`), R7-11 (clear the sibling collection), R7-03 (a timeout knob).
4. Re-run the memory benchmark: RSS per open order moved 3.10 KB → 5.18 KB across
   this round. We are explicitly **not** calling that a regression — single run,
   no bisection — but it deserves a bisected re-run rather than a shrug.

## What is good, and it is a lot

The `send(wait=True)` hang is genuinely dead: 6/6 hangs → 0, on every ablation,
and 500 fuzzed cyclic configs across both engines produce zero livelocks with the
trip observable at the same lap count on both. The root-level snapshot refusal
holds across 320 generated parallel machines and 7 622 attempts from 8 windows
with zero raw exceptions. The receipt matrix is injective. The threadsafe counter
balances against a deliberately hostile race. Raw `send()` throughput is the
fastest we have recorded at 257 k ev/s. Coverage is 92.64 % against the new 90 %
floor, with `interpreter.py` up from 89 % to 91 %. No tests were deleted and no
`xfail` or `skip` was added anywhere in the diff.

The direction is right. The gap is two lines of provenance accounting and one line
of test parametrisation.
