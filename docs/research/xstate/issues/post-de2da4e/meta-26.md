# Meta-issue #26 — round 12: the perfect checklist

**NOT POSTED. Draft.**

**Round 12. Verified build:** `main` @ **`de2da4e`** (merge of PR #223 from
`fix/0.8.1-round11`). `__version__` still reports `0.8.0` on this tree —
**identify this build by commit, never by version string** (twelfth
consecutive round). CPython 3.13.7, Windows 11, fresh venv, every repro run
from a neutral working directory.

---

## GATE

> ### ADOPT WITH CONSTRAINTS — decision-table **row 8**
> *"All Blocker and High closed; all Medium triaged; benchmark thresholds
> not all met."*

| | |
|---|---|
| Library board, post-refutation | **0 Blocker · 0 High** |
| Upstream suite at this commit | **3545 passed · 0 failed · 13 skipped** |
| Coverage | **92.87 %** (required 90.0 %) — measured, not carried |
| Regressions | **0** across 168 gate checks and 573 sweep scripts |
| Diff `c78ce99..de2da4e` | `+794 / −1`; no `xfail`, no `skip`; the one test edit *strengthens* a pin |

Up two rows from round 11's row 6, and level with round 10. The difference
between row 6 and row 8 is not cosmetic: at row 6, one of our constraints
was containment for an **open library defect**. At row 8, **every remaining
constraint is an architectural consequence of our own benchmarks** — not a
fence around someone else's bug.

All five round-11 fixes (#218–#222) verified FIXED, on both engines and
both service spellings. Third consecutive round with no "fixed on one axis
only" residual anywhere in the corpus.

---

## What stands between row 8 and perfect

This is the whole list. Twelve rounds in, the library is adopted and
running; everything below sits between *adopt with constraints* and
*nothing open*. Nothing here is a blocker, and most are small.

### Medium (3)

1. **<DE-L1> — the `#219` guard is wider than its documented contract.**
   `_ACTIVE_ACTION_OWNER` is a `ContextVar`, and `ensure_future` /
   `create_task` copy the current context, so a task spawned inside an
   action inherits the owner **for its whole life**. The escape hatch
   `interpreters.md:519` annotates `# fine: awaited elsewhere` is refused
   whenever the spawning action awaits again — and a background worker is
   refused 300 ms after the machine went quiet. The predicate answers
   "does this task *descend from* one of my actions?", where only "is this
   task *inside* one of my actions?" implies a deadlock. The sync engine
   already uses the right predicate (`sync_interpreter.py:584`, the
   instance flag `_is_processing`).

2. **<P-1> — the `#222` chain-trip latch is not persisted.** `chain_trips`
   and `last_chain_error` are documented as the *sticky* signal that work
   was discarded. Neither is a snapshot key, so a process that trips the
   guard, is snapshotted and restarts comes back reporting `(0, None)` — a
   clean machine, with no trace that the previous process threw work away.
   Stickiness that stops at the process boundary stops at the one boundary
   a supervisor is most likely watching across.

3. **<P-2> — `strict` is not applied to restored `scheduled_sends`.**
   `#214` routed restored `pending_events` through `_admit_restored`; the
   sibling list `#213` added did not get the same treatment. The
   **identical** record dict is refused in one lane and armed and
   delivered to the run loop in the other, on a machine with
   `strict: True`. Looks like a one-line fix.

### Low (3)

4. **<DE-L2> — inline-dict `invoke.src` fails with an opaque `TypeError`.**
   The shape is unsupported, which is fine; it says so as
   `TypeError: unhashable type: 'dict'` from `logic_loader.py:229`, naming
   no machine, no state and no key, under every strict setting. A
   well-formed config with no typo anywhere fails the same way. One
   type-check in the invoke loop routes it through `#220`'s existing
   path-named `InvalidConfigError` voice.

5. **<DE-L3> — a `def` action calling `send(wait=True)` gets the guard
   object, unawaited, silently.** No exception, no warning, no usable
   receipt; the call is silently useless rather than working or failing
   loudly. The sync engine raises for the analogous shape, so the two
   engines disagree.

6. **<DE-L5> — the priority lane is dropped on sync-engine restore.**
   `SyncInterpreter._enqueue_restored` accepts `priority` and ignores it,
   always appending. The async engine honours the same persisted record
   correctly (`interpreter.py:1613`). A service-kind asymmetry on a record
   both engines are handed identically.

### Release (1)

7. **<DE-A10> — bump `__version__` and tag 0.8.1.** Twelve rounds of gates
   and issue reports have been pinned to commit hashes because
   `__version__` has read `0.8.0` since round 3 while `CHANGELOG.md`
   `[Unreleased]` has targeted 0.8.1 for the same span. `#218`–`#222` are
   all verified fixed on this tree; a tag is what lets downstream users
   depend on them by version.

### Test quality (1)

8. **<DE-A12> — an inert pin in `tests/test_round9_findings.py`.** The
   `nested_invoke` shape fires **exactly 2 service calls at every limit
   from 1 to 25** — a constant agreeing with itself. Its sibling
   `rollback_ondone` produces 8 distinct values across the same ladder.
   The shape never exits state `a`, so the assertion cannot fail however
   the runaway-chain accounting changes.

### Docs (2)

9. **<DE-A13> — two production facts not written down.** (a) The
   `ensure_future` escape hatch's real precondition — the spawning action
   must return without awaiting again — is absent from both
   `interpreters.md:519` and the `#219` CHANGELOG entry. (b) That
   `chain_trips` / `last_chain_error` do not survive a restore is absent
   from `snapshots.md`, which already handles the analogous timer and
   service cases well. *We withdrew a third item from this list on
   checking the tree: the `from_snapshot` trust boundary **is**
   documented, at `snapshots.md:247` and `api/index.md:726`. We were
   wrong.*

10. **<DE-L7> — engine mint-helper naming and `_replace` typing (Info).**
    `engine_done` / `engine_error` / `engine_after` are unprefixed public-
    looking names in an importable module, while the `_Engine*` classes
    beside them signal internality with an underscore; and `_replace` on
    an engine-minted event returns another engine-minted event. No
    exploit — we refuted our own forgery claim — this is the residual
    hardening option that refutation itself named.

### Bench — *ours, not yours*

11. **No library item.** We had drafted a benchmark-maintenance ask about
    a timer-drift script timing out for five rounds. It was wrong: the
    script is **ours**, and the library's own
    `benchmarks/production_characteristics.py` already has the `--quick`
    flag we were about to ask for. See "Our refuted claims" below.


---

## A structural note, so the list above is read correctly

Two things about this checklist that we would rather state than have
inferred.

**1. "Unmeasured" is not "met", and it was not the library's fault.** Our
gate held row 9 (unconstrained adopt) shut for five rounds on the grounds
that one benchmark threshold — loaded timer drift — was *unmeasured*. A
row requiring all thresholds met cannot be reached by absence of evidence,
so that was correct as far as it went. What was not correct was the
attribution: we were timing out our **own** over-parameterised script and
recording the library as the thing that had not produced a number. The
upstream benchmark produces it in **six seconds**. That correction is
ours, it is embarrassing, and it is in the refuted list below rather than
in the issue queue.

**2. Our coverage is deep on our shapes, not broad on yours.** Everything
we report is verified hard — standalone repros, neutral cwd, both engines,
both service spellings, polled to convergence — but it is verified against
the shapes *our* adoption exercises. Twenty production-shaped charts and a
573-script sweep is a lot of depth through a narrow aperture. The absence
of a finding in an area we do not exercise (deep parallel-region history,
the CLI, the pythonic API surface beyond what we call) is not evidence of
correctness there. Please read this list as "what one demanding adopter
found", not "what remains".

---

## Trend, rounds 5 → 12

| Round | Commit | Gate row | Blocker | High |
|---|---|---|---|---|
| 5 | `3ed3099` | ADOPT WITH CONSTRAINTS | 0 | 2 |
| 6 | `cec108b` | ADOPT WITH CONSTRAINTS | 0 | 1 |
| 7 | `221ce7c` | ADOPT WITH CONSTRAINTS | 0 | 1 |
| 8 | `6db65d8` | ADOPT WITH CONSTRAINTS | 0 | 1 |
| 9 | `f28719c` | ADOPT WITH CONSTRAINTS | 0 | 1 |
| 10 | `19cb1f1` | ADOPT WITH CONSTRAINTS — **row 8** | 0 | 0 |
| 11 | `c78ce99` | ADOPT WITH CONSTRAINTS — row 6 | 0 | **1** |
| 12 | `de2da4e` | ADOPT WITH CONSTRAINTS — **row 8** | **0** | **0** |

Round 11's dip was a single High (`_timer_handles` unbounded leak) and
round 11's verdict predicted that closing it would flip the row back.
**#218 closed it at the mechanism and it flipped.** Refutation has moved
every Blocker/High candidate **down and none up for five consecutive
rounds**.

---

## Full checklist, #27 → #222

Every issue we have filed against this library, by current status.

**Closed and verified fixed by us (the whole list):** #27, #28, #31, #37,
#39, #43, #44, #48, #49, #50, #51, #54, #56, #60, #75, #76, #77, #78, #79,
#80, #107, #110, #115, #116, #117, #119, #125, #128, #135, #145, #153,
#154, #167, #170, #179, #180, #181, #182, #183, #184, #185, #186, #187,
#188, #189, #190, #192, #193, #194, #195, #196, #197, #198, #199, #200,
#201, #203, #204, #205, #206, #207, #208, #209, #210, #212, #213, #214,
#215, #216, **#218, #219, #220, #221, #222**.

**Open:** none of ours.

**Filed this round (new):** the ten items listed above — 3 Medium, 3 Low,
1 release, 1 test-quality, 2 docs/Info.

The five verified this round in detail:

| Issue | Verdict | The number that convinced us |
|---|---|---|
| **#218** | FIXED at the mechanism | 93,168 beats, **RSS Δ 0.00 MB**, 1.00 handles/machine (was +753 MB) |
| **#219** | FIXED and correctly narrow | 100/100 deferred receipts resolve; in-step await refused on both engines |
| **#220** | FIXED, sound **and** complete | 638/640 injected typos caught to 11/11 depth; **0** false positives on 400 valid charts |
| **#221** | FIXED, exact | 640/640 property cases byte-identical across 1–4 compaction hops |
| **#222** | FIXED, correct | latch survives every benign event; hook fires exactly once per trip |

---

## Our refuted claims this round

We run every Blocker and High candidate through an independent refutation
pass before it reaches you. Five went in this round; **three died**, and we
are reporting them because a list of what we got wrong is the only thing
that makes the list of what we got right worth reading.

| ID | Claimed | Outcome |
|---|---|---|
| **R12-01** | A forged `scheduled_sends` record mints engine-only events with an attacker-chosen payload | **Downgraded Blocker → Low.** The `engine` flag *is* consulted: the forged record restores as a public `Event` with `data == {}`; the payload never arrives. Minting requires *adding* `"engine": true`, which is identically reachable through `pending_events` inside the documented `from_snapshot` trust boundary. What survived is the narrow strict-parity gap now filed as **<P-2>** — no security content. |
| **R12-02** | A forged `"version": 2` blob gets `engine: true` stamped by `upcast` and drives a transition v3 would refuse | **Refuted.** Reproduced exactly, then killed by its own control: a plain v3 blob writing `configuration`/`context` verbatim reaches the **identical** outcome with no forged record. The proposed mitigation refuses the v2 shape and leaves the equivalent v3 write untouched — which proves the **trust boundary**, not `upcast`, is load-bearing. Three merged findings fell with it. |
| **R12-03** | Engine-event provenance is forgeable through the public API | **Refuted (Info).** No vector uses only public API — each needs a private `_`-prefixed import, poking a frozen dataclass's private slot, already holding an engine-minted event (reachable only from code inside the machine's own actions, which can transition it arbitrarily anyway), or unpickling attacker bytes. `is_system_event(DoneEvent(...))` is correctly `False`. Residual: the Info-level naming/`_replace` item filed as **<DE-L7>**. |
| **R12-04** | `SimulatedClock` does not fire a restored `after` timer | **Refuted, ours.** Correct, documented, opt-in behaviour: `from_snapshot` restarts no timers by default, `restart_timers=True` fires it on schedule, and `has_dormant_timers` reports the state. Our root-cause guess (clock-binding order) was the bug #154 already fixed. An `after` deadline is not a `scheduled_sends` record, so the mechanism we blamed was never involved. |
| **R12-05** | The library's timer-drift benchmark times out; please add a `--quick` tier | **Refuted, ours, and the most useful thing we learned.** `bench_c_timers` is **our** script, not yours. `benchmarks/production_characteristics.py` already measures exactly this and already has `--quick`: **5.6 s**, or 18 s for the full matrix. See below. |

**Fourth consecutive round in which a provenance Blocker died on its own
control probe.** Our standing rule — test every blob-write finding against
the `state_ids`-only control *before* triage — has now paid for itself four
times.

### The benchmark correction, stated plainly

BENCH-6 (loaded timer drift) is the threshold our gate has called
"unmeasured for five rounds", and it is the single thing holding row 9
shut. Running the library's own benchmark at `de2da4e`:

| mode | wall clock | median lateness at 500 busy machines |
|---|---|---|
| `--quick` | **5.6 s** | +89.6 ms |
| `--quick` ×3 more | ~6 s each | +94.1 / +113.3 / +110.0 ms |
| full matrix | **18.2 s** | +111.2 ms |

Against our ≤100 ms bar that is *straddling*, not missing — and it is a
very large improvement on the 2530 ms we measured at 0.8.0. The honest
statement is **"measured, marginally over bar on this host"**, not
"unmeasured". Correcting our own gate row is round 13's first task, and it
is ours, not yours.

---

## The only Blockers left are ours

Worth stating explicitly, because it is the clearest summary of where this
library now sits in our adoption.

Two Blockers and one High survived refutation this round. **All three are
defects in our own catalogue JSON** — fixable in configuration alone, with
no library change, no library workaround, and no library-readiness impact:

- two catalogue charts whose declared transitions disagree with the order
  lifecycle they model;
- one chart whose guard set admits a state the downstream consumer cannot
  represent.

**For the second consecutive round, the binding constraint on our order
path is our own catalogue, not the library.** Row 9 is held shut by a
measurement we owe ourselves (above), and the Blockers are held open by
configuration we wrote. Neither is yours.

---

## Thank you — twelve rounds

Twelve rounds, 73 issues closed, and not one of them closed by argument
rather than by a fix. That is an unusual record and we would like to say
so directly.

What has been most valuable is not the fix rate but the *shape* of the
fixes. #218 was closed at the mechanism rather than under the load we
reported it under. #220 was widened to a recursive check that
retroactively established that twenty of our production charts had never
been silently dropping an action — a fact we could not have established
any other way. #222 added a latch beside `last_error` instead of changing
`last_error`'s semantics, which was the harder and better of the two
available fixes. Several of these landed with tests that are stronger than
the repro we supplied.

We have also been wrong in public repeatedly — three times this round
alone, twice about things we had blamed on the library — and the
refutation discipline that catches that exists partly because the quality
of the responses here made it worth building.

### One ask to close on

**Please tag 0.8.1.** `#218`–`#222` are all verified fixed on this tree.
`__version__` has read `0.8.0` since round 3 while `CHANGELOG.md`
`[Unreleased]` has targeted 0.8.1 for the same span, and every gate and
issue report we have written for twelve rounds has had to be pinned to a
commit hash for that reason. A tag is what lets everyone downstream depend
on this work by version instead of by SHA. It is filed as **<DE-A10>** and
it is the single highest-leverage item on the list above.
