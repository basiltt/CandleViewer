# Battle de2da4e — OBSERVABILITY track (round-11 re-verification)

Library `_ref/xstate-statemachine` @ `de2da4e` (unreleased 0.8.1). Round-11
fixes #218–#222 per `CHANGELOG.md [Unreleased]`. Standalone script:
`battle-de2da4e/observability/attacks.py` (stdlib + `xstate_statemachine`
only, run from neutral cwd `C:/Users/basil`, pinned venv). Whole task
time-boxed to 20 min wall clock; each script ≤120 s. **Full run: 15/15
attacks PASS, 5.9 s wall.** The background pytest+coverage run
(`suite-de2da4e.log`) completed independently: **3545 passed, 13 skipped,
92.87% coverage** — no failures, consistent with these findings.

## Prior-defect re-run (battle-c78ce99/observability, round-10 attacks A–G)

The round-10 script's attacks A–F all targeted #212/#213/#214/#216, which
are unchanged by round-11 (#218–#222 are additive: timer-handle release,
`ReentrantWaitError`, recursive key check, parked-scheduled-sends
re-persist, chain-trip latch). None of round-10's own attacks exercised a
self-`send(wait=True)` shape, so **none are SUPERSEDED** by #219's new
`ReentrantWaitError` behaviour — that instruction's precondition did not
apply to any prior script in this track.

| Prior finding (round 10, `c78ce99`) | Status on `de2da4e` |
|---|---|
| A — #212 timer-rule direct repro (1 ms self-ping-pong, 500 ticks, no trip) | **Unchanged** — not re-run verbatim, but subsumed/strengthened by new attack A below (200-beat heartbeat, both engines, asserts `handles_held<=1` **and** `chain_trips==0`, which round-10's version did not check). |
| B — v3 `scheduled_sends` round-trip property (60 trials) | **Unchanged**, superseded in scope by new attack B (320 trials, adds the restore→re-persist→restore→start chain that round-10's B did not cover — that chain is exactly what #221 fixed). |
| C — v2→v3 upcast, `after` record fires | Not re-run this round (out of scope for #218–#222; no changelog entry touches `upcast()` this round). **Not independently re-verified.** |
| D — forged v3 `pending_events` record, mismatched after-id does not fire | Not re-run this round (same reason as C). **Not independently re-verified.** |
| E — concurrency, 200 machines × 1 ms heartbeat, 200 beats each | **FIXED (strengthened).** New attack F re-runs this exact shape and additionally asserts `_timer_handles` stay flat at ≤1 per machine across all 200 — this is precisely the #218 leak the round-10 attack could not have caught (the bug postdates it). |
| F — livelock fuzzer (60 configs, delay∈{0,1,2,5,10,50}) | Not re-run this round (out of scope; #218–#222 do not touch the chain-budget/timer split rule from #212, only the handle-release side-effect and the trip's observability). **Not independently re-verified.** |
| G — #216 config-key fuzzer spot check (top-level only; nested confirmed silently ignored, logged as a gap not a defect) | **FIXED.** #220 is exactly this gap. New attack C re-runs it at the state/transition/invoke nesting levels the round-10 note flagged as unimplemented: 240/240 nested typos now caught under `strict_config=True` (were 0/0 caught, i.e. silently accepted, on `c78ce99`), 0/120 false positives on the full valid-key grammar including `x-`/`meta`/`description`/`tags` at every level. |

## New attacks run

**A — #218 timer-handle release + #222 latch across a 200-beat heartbeat,
both engines.** `raise(delay=10)` up/down heartbeat, 200 ticks via
`SimulatedClock`, both `def`/`async def` action bodies on the async engine
plus the sync engine. Asserts `sum(len(v) for v in i._timer_handles.values())
<= 1` and `i.chain_trips == 0` after 200 beats.
**3/3 PASS** (`held=1` in every cell, `beats=201`, `chain_trips=0`).

**B — persistence property: parked+armed `scheduled_sends` across
restore→persist→restore→start (320 cases, reduced from the requested
≥300→"as many as fit"; ran the full 320).** Random delay ∈
{50,100,500,1000,5000} ms, random elapsed-before-snapshot. Per case: (1)
snapshot mid-flight, assert exactly 1 `scheduled_sends` record with the
right `remaining_ms`; (2) restore, do **not** `start()`, re-persist —
assert the parked record round-trips verbatim (#221's fix); (3) restore
that parked blob again into a fresh interpreter+clock and call `start()`
— assert exactly one record is armed, at the same remaining delay; (4)
advance the clock just short of the deadline (must not fire), then past it
(must fire exactly once, `scheduled_sends` cleared after). **320/320
clean, 0 failures.**

**C — #220 recursive unknown-key fuzzer (240 typo cases + 120 valid-grammar
cases, reduced from ≥500 for the time budget).** Base chart exercises every
level: root (`maxIterations`), state (`entry`/`exit`/`on`/`after`/
`invoke`), transition (`target`/`actions`/`guard`), invoke (`onDone`/
`onError`), with a full `MachineLogic` (actions/guards/services) supplied
so failures are validation failures, not missing-implementation noise.
Typo fuzzer mutates one random key at one random level
(`maxIteratoins`, `entyr`, `acitons`, `onDonee`) and asserts
`InvalidConfigError` under `strict_config=True`. Valid-grammar generator
adds every accepted metadata/vendor key (`meta`, `tags`, `description`,
`x-*`) at every level as noise and asserts zero rejections.
**240/240 typos caught; 0/120 false positives.**

**D — #219 `ReentrantWaitError` matrix.** (D1) async action awaits its own
`send(..., wait=True)` in-step → raises `ReentrantWaitError` naming the
event and "deadlock"; the send itself still lands (machine reaches `"y"`,
status stays `"running"`, not hung). (D2) sync engine refuses the identical
shape, same exception type, machine stays parked at `"x"` (the sync engine
doesn't drive the queued event after an in-step exception the way the
async run loop's task boundary does — consistent with #219's "sync engine
refuses too" wording, not treated as a discrepancy here). (D3) the
documented escape hatch — `asyncio.ensure_future(i.send(..., wait=True))`
then awaiting the future *outside* the action — succeeds, run under **100
concurrent interpreters simultaneously** doing this shape (100/100 clean,
no cross-talk, no spurious `ReentrantWaitError`). (D4) a child
interpreter's action awaits `wait=True` on its **parent's** `send()` (not
its own interpreter) — succeeds, not reentrant, because the guard is keyed
on `_ACTIVE_ACTION_OWNER is self` where `self` is the interpreter whose
action is running, not any interpreter reachable from it.
**4/4 PASS.**

**E — #222 chain-trip latch, exactly-once semantics, `on_event_dropped`
ordering, and persistence contract.** Reruns the changelog's own trip
scenario (`maxIterations=6` self-raise cycle) on both engines, both
action kinds, and additionally captures `on_event_dropped` via a plugin
alongside `on_chain_budget_exceeded`. Confirms: exactly 1 trip
(`chain_trips==1`), `last_chain_error` set immediately, three subsequent
benign handled events do **not** advance `chain_trips` and do **not**
clear `last_chain_error` (the #222 fix — pre-#222 `last_error` would have
been erased by the first benign event), `last_error` (the per-step,
non-latched read) is cleared by the first benign event as documented,
`clear_chain_error()` nulls the latch without touching the monotonic
counter, and the hook fires **exactly once**, with `on_event_dropped(...,
"chain_budget")` firing for the discarded `LAP` event immediately before
`on_chain_budget_exceeded` — a real, previously-undocumented **ordering
fact** (drop-notification precedes trip-notification), not a defect: a
supervisor listening on both hooks in that order sees the lost event
named before it sees the trip counted. Separately confirmed the
persistence contract: `chain_trips`/`last_chain_error` are **not** part of
`get_persisted_snapshot()`'s payload (no such keys in the blob) and a
freshly-restored, freshly-started interpreter starts at `chain_trips==0`
— i.e. the latch is process-local and does not survive a restore, which
is the correct reading of "sticky ... across a 200-beat heartbeat" (sticky
within a run, not across a persistence boundary the docs never claim it
crosses). **5/5 PASS** (3 latch cells + ordering + persistence contract).

**F — concurrency: 200 heartbeat machines, handle count flat (100 beats
each, reduced from "10 s wall" for the time budget — 100 beats completed
in well under 1 s per machine, so this is a beat-count-bound rather than
wall-clock-bound version of the same property).** 200 independent
`SyncInterpreter`s, each a `raise(delay=1)` up/down heartbeat, driven via
per-machine `SimulatedClock`. After 100 ticks each: `max(handles held
across all 200) <= 1` and `sum(chain_trips across all 200) == 0`.
**PASS** (`max_handles_held=1`, `total_chain_trips=0`).

## Defects found

**None.** All 15 attack cells (A×3, B, C×2, D×4, E×5, F) passed against
the documented #218–#222 contract. No `D12-observability-n` entries are
raised this round.

## Not covered (time-boxed out; do not read as clean)

- Prior round-10 attacks C, D, F (upcast/forgery pair, livelock fuzzer) —
  not re-run; out of scope for this round's changelog delta but not
  independently re-confirmed on `de2da4e` either.
- B run at 320 cases (met the ≥300 floor) but not the fuller property-based
  scale (shrinking, adversarial delay values near clock-tick boundaries,
  concurrent restores of the same blob).
- C run at 240/120 (reduced from ≥500); did not fuzz parallel-region
  configs, `always`, or history-state `target` specifically, nor multiple
  simultaneous typos in one document.
- 200-machine soak reduced to 100 beats / SimulatedClock (no wall-clock RSS
  probe — psutil is explicitly excluded from the standalone-repro
  constraint); the requested "10 s wall, RSS flat" variant is not covered.
- D: `sendTo` self (as opposed to bare `send`), and the "after-fired
  handler" shape from the semantics matrix, were not attempted.
- 12-minute soak (out of the 20-min whole-task budget entirely; the
  background suite run's 12.5-minute wall clock was consumed by pytest, not
  available for a second soak).
- security sub-items (strict_config bypass beyond attack C's `x-`/case
  coverage was not extended to case-variant key smuggling; snapshot
  forgery of `scheduled_sends`/`lane`/`engine` was not re-attempted this
  round — carried from round-10's D/prior findings, not independently
  re-verified against #218–#222).
- determinism (50× trace comparisons) — not run this round.

## Verdict

All five round-11 observability fixes (#218 timer-handle release, #219
`ReentrantWaitError`, #220 recursive key check, #221 parked-scheduled-send
re-persist, #222 chain-trip latch) hold under the attacks run here,
including the two prior round-10 gaps they were meant to close (the
100%-nested-typo-miss noted as "not covered, worth flagging" in
`battle-c78ce99/observability.md`'s attack G, and the unbounded
`_timer_handles` growth that attack E's own reduced-N run could not have
caught). This is a **partial, time-boxed confirmation**: 15/15 executed
attacks passed with no regressions and no new defects found, but the Not
Covered list above (full-scale fuzzing beyond the reduced Ns, the upcast/
forgery pair, livelock fuzzer, wall-clock soak, determinism, most of the
security matrix) means several requested items are genuinely unexercised
this round, not merely re-affirmed clean.
