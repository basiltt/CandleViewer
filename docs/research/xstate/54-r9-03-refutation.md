# R9-03 adversarial refutation — "always -> invoke -> onDone starves external priority traffic permanently (async def lane)"

Library: `_ref/xstate-statemachine` @ `f28719c` (unreleased 0.8.1; `__version__` still 0.8.0).
Runner: `.venv-main/Scripts/python`, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.
Source claim: D9-fuzz-3, filed **high**. Predecessor: R8-04 (`49-r8-04-refutation.md`, downgraded high -> medium at `6db65d8`).

## Verdict: REFUTED (residual is a documented-misuse detectability nit, already carried as the R8-04 medium)

Every load-bearing element of the R9-03 sentence fails at `f28719c`:

| claim | status at f28719c |
|---|---|
| "starves ... **permanently**" | **false** — drains fully in 15.3 s; 500/500 applied |
| "external items **never** drain" | **false** — inbox=0 priority=0 at rest |
| "**silent**: no error" | **false** — `RunawayChainError` is now raised on the async lane |
| "**R8-04 half-fixed**" (parity gap) | **closed** — both lanes now trip |
| "async def applied 126/500" | true *as a 1 s snapshot*, and not a defect |

## 1. Repro as filed, re-run verbatim

`battle-6db65d8/fuzz/r18_ext_starvation_repro.py`, unmodified, at `f28719c`:

```
  SYNC engine, plain def:  EXT sent=500 APPLIED=500 (100.0%) status=running last_error=None
  plain def                received=500 APPLIED=500 (100.0%)  inbox=423 priority=1
  async def                received=128 APPLIED=128 (25.6%)   inbox=499 priority=372
  ablation A (no always)   both kinds  APPLIED=500/500        inbox=0 priority=0 err=None
  ablation B (no invoke)   both kinds  APPLIED=500/500        err=RunawayChainError
```

The reporter's headline number reproduces (25.6% vs the filed 25.2%). Note ablation B
has **changed since `6db65d8`**: it was `1/500 + RunawayChainError`, it is now
`500/500 + RunawayChainError`. The reporter's own ablation table is stale.

## 2. "Permanently" — REFUTED. The script measures a 1-second window.

The repro applies its 500-event burst and then waits exactly `asyncio.sleep(1.0)`
before reading the counter. The reported 25% is the producer-burst snapshot, not a
terminal state. `battle-f28719c/fuzz/r9_03_drain.py` (standalone; same chart, the
*only* change is polling until both queues empty):

```
  plain def settle<=  1s  drained_after= 1.00s APPLIED=500/500 inbox=435 prio=1  err=None
  plain def settle<= 30s  drained_after= 8.77s APPLIED=500/500 inbox=0  prio=0   err=RunawayChainError
  async def settle<=  1s  drained_after= 1.00s APPLIED= 77/500 inbox=499 prio=423 err=None
  async def settle<= 30s  drained_after=15.33s APPLIED=500/500 inbox=0  prio=0   err=RunawayChainError
```

The async lane reaches **500/500 applied, both queues zero**. "External items never
drain" is false; the lane is slower under a runaway chart, not blocked. The word
"permanently" is an artefact of the measurement window. `r22_r8_04_fate.py` agrees
independently: `async def sent=300 recvEXT=300 APPLIED=300 LOST=0 state=['m.a']`
— and that row is itself a **regression fix** since `6db65d8`, where it read
`APPLIED=300->1 LOST=299`.

## 3. "Silent: no error" and "R8-04 half-fixed" — REFUTED

The R8-04 medium had two parts. Both are now closed on the observable:

- **Parity (#179/#201).** At `6db65d8` the runaway tripped `RunawayChainError` on
  the `def` lane and **never** on `async def`. At `f28719c` both lanes trip
  (§2, 30 s rows; `r18` ablation B, both kinds). The reporter's "R8-04 half-fixed"
  is backwards — the parity half is exactly what the round-8 work fixed.
- **Drop-hook / loss.** "no drop hook" is correct and correctly *uninteresting*:
  nothing is dropped, so there is nothing for `on_event_dropped` to report. Zero
  events are lost (§2).

What remains is the narrow R8-04 residual, unchanged and already registered:
`r21_r8_04_signal.py` shows `last_error` is `None` throughout the burst on the async
lane (`{'None': 400}`) even though the chart is a runaway, i.e. the signal surfaces
late rather than never. That is a detectability lag on an invalid chart, not
starvation, and it is already carried at **medium** from round 8.

## 4. The chart is the documented infinite-loop misuse — correct usage is clean

Unchanged from `49-r8-04-refutation.md` §2 and re-verified at `f28719c`
(`r20_r8_04_refutation.py`):

```
Q1 unguarded always, ZERO external traffic:  always-fired=50 in 1s, err=RunawayChainError (both kinds)
Q1 guarded   always, ZERO external traffic:  always-fired=0,        err=None              (both kinds)
Q2 guarded always + invoke:  EXT applied=300/300 (100%) inbox=0 prio=0 err=None (both kinds)
Q3 no always, fast invoke cycle: EXT applied=300/300 (100%) inbox=0 prio=0 err=None (both kinds)
```

`b.always -> b2` is unguarded and targets a state inside its own source region, so it
is re-enabled by its own effect — a runaway with **no external producer at all**.
`docs/api/index.md:1788` names "a cross-region `always` keeps re-arming an invoke" as
a cause of `RunawayChainError`; `docs/FEATURE_GAP_ANALYSIS.md:212` cites XState v5.31.0
`maxIterations` infinite-loop detection as the matched feature; `docs/_guide/faq.md:278`
documents `always` for decision states and shows the guarded form. SCXML §3.13 gives
eventless transitions their own settle pass — a self-re-enabling one never lets the
pass converge, which is the definition of an ill-formed chart, not a scheduler defect.
Q2/Q3 show correct usage — including a fast legitimate `invoke -> onDone -> re-enter`
cycle — starves nothing, on **both** service kinds.

## 5. Why REFUTED rather than DOWNGRADE

R9-03 is not a new finding. It is R8-04 re-filed at high severity with a claim
("permanently", "never drain") that the round-8 fixes have since falsified, on
ablation numbers that no longer hold. The surviving observable — a runaway chart
converges slowly on the coroutine lane, and `last_error` lags the burst — is exactly
the R8-04 medium already in `48-r8-findings-register.md`. Nothing on a correct machine
is affected. No new issue should be opened.

## Artefacts

- `battle-6db65d8/fuzz/r18_ext_starvation_repro.py` (as filed, re-run at f28719c)
- `battle-f28719c/fuzz/r9_03_drain.py` (**new**, standalone — the permanence test)
- `battle-6db65d8/fuzz/r20_r8_04_refutation.py`, `r21_r8_04_signal.py`, `r22_r8_04_fate.py` (re-run)
- Predecessor: `49-r8-04-refutation.md`
