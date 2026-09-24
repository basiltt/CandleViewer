# meta-26.md — adoption audit scorecard, round 8 (`main` @ `6db65d8`)

**Update for the meta issue (#26). Draft — not posted.**

---

## Round 8 — `main` @ `6db65d8` (merge of PR #191, `fix/0.8.1-round7`; unreleased 0.8.1)

Identified **by commit**: `__version__` still reports `0.8.0` on this tree while
`CHANGELOG.md [Unreleased]` targets 0.8.1. Eight verification rounds have now keyed on
commits for this reason. CPython 3.13.7, Windows 11, fresh venv,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified.

**Method:** 16 issue verifications re-run live; full regression sweep; library suite +
coverage; diff review `221ce7c..6db65d8`; 8 battle tracks re-run with new attacks aimed at
this round's own machinery; 20 contract machines driven end-to-end **on both service
spellings**; then triage → dedupe → **independent adversarial refutation of every Blocker
and High candidate**. Nothing counted without a standalone repro on a clean interpreter.

### Headline

**This is the best round of the eight, and the gap is now one function.**

- **16 issues: 15 fixed in code (10 clean, 5 narrower than claimed), 1 documentation-only
  (#174), 0 not-fixed.** First round with no "not fixed" row.
- **Post-refutation: 1 Blocker · 3 High · 7 Medium · 4 Low.** Refutation moved **3 of 6**
  Blocker/High candidates *down* and **none up**.

| Round | Commit | Blocker | High | Medium | Low |
|---|---|---|---|---|---|
| 5 | `3ed3099` | 4 | 8 | 8 | 1 |
| 6 | `cec108b` | 2 | 2 | 7 | 9 |
| 7 | `221ce7c` | 2 | 4 | 6 | 8 |
| **8** | **`6db65d8`** | **1** | **3** | **7** | **4** |

### What landed, and it is a lot

**The one change we asked for in round 7 shipped, and the effect is measurable.**
`tests/test_round7_findings.py` parametrises over `KINDS = ("def", "async def")` and
cross-checks both engines. Consequences at this commit:

- async livelock config fuzz: **58/120 RUNAWAY at `221ce7c` → 0/120 here**;
- determinism sweep, 500 configs × 2 spellings × 2 engines: **0 hangs, 0 silent runaways,
  0 lap mismatches**;
- `maxIterations` is a real bound again and **lane-independent**: 2 / 5 / 100 → 4 / 7 / 102
  service calls, `max + 2` exactly, identical cell for cell;
- the kill-switch-shaped machine that produced **3 547 service calls in 3.0 s** at
  `221ce7c`, still accelerating, now **plateaus at 1 002** with
  `last_error = RunawayChainError`;
- an 80 s / 200-machine async soak: 12 350 external priority events, **0 dropped, 0 wedged,
  0 torn snapshots, 0 task leaks**;
- suite 3 457 passed, coverage **92.70 %**.

Both round-7 Blockers (R7-01, R7-02) are closed. `#189`'s receipt fix and `#182`/`#183`/
`#184`'s snapshot work all verify clean on both engines and both spellings.

### The one Blocker

**R8-01 — the priority lane charges by provenance and sheds by position.** #180 taught the
charge site (`interpreter.py:2342-2389`) to decide by *who issued* an event; the shed site
(`:1598`) still decides by *where the event sits in the queue*, over a single FIFO carrying
external sends and engine completions together. Both halves reproduced fresh, both
spellings:

- a priority send **issued from an action** is never charged → unbounded livelock,
  `status="running"`, `last_error is None`, no drop hook, `start()` never returns. The
  plain-lane control on an identical machine is bounded at 27 laps with `RunawayChainError`.
- an **external** priority event at an already-tripped chain is destroyed as
  `chain_budget` — 8–9 of 2 000, `send()` accepted, `last_error is None`. The
  `priority=False` control loses 0.

It is the regression surface of this release's own #180, and it is one function's worth of
work. **Please do not cut 0.8.1 until it lands.**

### Before the tag

1. **Land R8-01.** See above.
2. **Bump `__version__`** in the same commit that tags — otherwise the
   "key on the commit, never the version" escape hatch survives into a released artefact.
3. **Two shipped tests pass while their defect is live**, and one is vacuous by
   construction: `tests/test_round7_findings.py:557` parametrises the `children_timeout`
   test over `KINDS` but gives the `def` arm `time.sleep(0.05)` against the async arm's
   `asyncio.sleep(3.0)`, so the `def` branch cannot fail — and R8-03 is exactly the defect
   it is named for. `:413-520` covers only externally issued priority sends into an
   untripped chain, which is how R8-01 got through.

### The pattern, stated for the third time

Rounds 6, 7 and 8 have each been **"fixed on the axis the test was written against"** —
engine, then service kind, now **issuer provenance and chain state**. Each round's fix was
real; each round's *claim* was one axis wider than its test. The matrix that ends the
pattern is **(engine × service kind × issuer × chain state)**, with the `def` arm of every
cell given work that can actually exceed the bound.

### Our position

**DEFER on the order path; GO on the non-order paths under constraints.** Decision-table
row 4 (non-empty Blocker row) wins. Row 6 — ADOPT WITH CONSTRAINTS — is otherwise
satisfied: open-High is 3 against a bar of 5, each with a mechanically enforced mitigation.
**Closing R8-01 flips the verdict.**

Also worth recording in the other direction: our B16–B20 control machines are now all
**LIBRARY-GO**, and the two things still blocking two of them are **ours**, not the
library's. For those machines, we are the blocker now.

Full write-up: round-8 readiness verdict and findings register (links in the audit repo).
Per-issue comments and new-issue drafts with standalone repros accompany this update.
