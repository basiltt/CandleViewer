# R8-04 adversarial refutation — "always -> invoking child -> onDone re-entry starves the inbox permanently"

Library: `_ref/xstate-statemachine` @ `6db65d8` (unreleased 0.8.1).
Runner: `.venv-main/Scripts/python`, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

## Verdict: DOWNGRADE high -> medium

The observable (async-def lane applies 1/500 external priority events) reproduces
exactly as filed. Both of the claim's load-bearing characterisations do not survive.

## 1. Reproduced as filed

`fuzz/r18_ext_starvation_repro.py` (300-500 events, both service kinds, both engines):

| lane | EXT applied | inbox | priority | last_error |
|---|---|---|---|---|
| SYNC, plain def | 500/500 | - | - | None |
| async engine, plain def | 490/500 | 466 | 1 | None (see §4) |
| async engine, **async def** | **1/500** | 499 | 400 | **None** |
| ablation A (no `always`), both kinds | 500/500 | 0 | 0 | None |
| ablation B (no `invoke`), both kinds | 1/500 | 0 | 0 | RunawayChainError |

Ablations confirmed necessary, as claimed.

## 2. The chart is the documented infinite-loop misuse — `fuzz/r20_r8_04_refutation.py`

The repro's `b.always -> b2` is **unguarded and targets a state inside its own
source region**, so it is re-enabled by its own effect: permanently enabled, for
ever. Q1 ran the chart with **one `GO` and zero external traffic**:

```
unguarded always  plain def  always-fired=50 in 1s (no external traffic) err=RunawayChainError
unguarded always  async def  always-fired=50 in 1s (no external traffic) err=RunawayChainError
guarded  always   plain def  always-fired=0                              err=None
guarded  always   async def  always-fired=0                              err=None
```

The chart is a runaway with no external producer at all. This is precisely what
`maxIterations` exists for — `docs/FEATURE_GAP_ANALYSIS.md:212` cites XState
v5.31.0 `maxIterations` "infinite-loop detection" as the matched feature, and
`docs/api/index.md:1788` lists "a cross-region `always` keeps re-arming an
invoke" as a **named cause** of `RunawayChainError`. `docs/_guide/faq.md:278`
documents `always` for *decision* states and shows the guarded form. XState v5
likewise raises on an infinite eventless microstep loop.

Correct usage (guard the `always` so it is enabled at most once per entry)
removes the symptom entirely, on **both** service kinds:

```
Q2 guarded always  plain def  EXT applied=300/300 (100%) inbox=0 prio=0 err=None
Q2 guarded always  async def  EXT applied=300/300 (100%) inbox=0 prio=0 err=None
Q3 no always       plain def  EXT applied=300/300 (100%) inbox=0 prio=0 err=None
Q3 no always       async def  EXT applied=300/300 (100%) inbox=0 prio=0 err=None
```

Q3 shows a legitimate fast `invoke -> onDone -> re-enter` cycle at full rate
starves nothing. The `always` misuse, not the invoke cycle, is the cause.

## 3. "Starves permanently" / "no fairness bound in `_next_event`" — REFUTED

`fuzz/r22_r8_04_fate.py` (long settle, 12 s after the producer stops):

```
plain def  sent=300 recvEXT=300 APPLIED=299 LOST=1   inbox=0 prio=0 state=['m.a'] drops={}
async def  sent=300 recvEXT=300 APPLIED=300->1 LOST=299 inbox=0 prio=0 state=['m.a'] drops={}
```

Every external event is dequeued and **delivered** (`on_event_received` 300/300),
both queues drain to zero, and the machine returns to a stable `m.a`. The
claimed live-lock — "events the queued events never escape" — does not exist;
r19's `STUCK` verdict came from a 10 s window too short for the backlog, and
the same script's async row already printed `DRAINED`. There is no missing
fairness bound: the inbox is served, the events simply do not *apply*.

## 4. What actually survives (the medium)

`fuzz/r23_r8_04_why.py` pins it — the events are received in `m.b.b2` and the
root `EXT` handler silently does not run because the **settle budget is tripped**:

```
recv sites: {'recv@m.b.b2:EXT': 99, 'recv@m.b.b2:GO': 99, ...}
settle_tripped=True settle_iters=52 raise_depth=0 chain_tripped=False  applied=1
```

`fuzz/r21_r8_04_signal.py` (poll `last_error` every 10 ms through the run):

```
plain def  last_error samples={'None': 373, 'RunawayChainError': 27}  applied=299/300
async def  last_error samples={'None': 400}                            applied=1/300
```

Two real defects, both narrower than filed:

- **Engine/service-kind parity (#179 promise).** With an `invoke` in the cycle
  the runaway trips `RunawayChainError` on the `def` lane but **never** on the
  `async def` lane. `docs/api/index.md:1788` promises charging "whether the
  service is `def` or `async def`". Cause is the chain-end reset at
  `interpreter.py:1725-1735`: the coroutine service's completion lands on a lap
  where the step "raised nothing, armed nothing, owes nothing", clearing
  `_raise_depth` every lap.
- **Silent settle trip.** `_settle_tripped` is set and events are then received
  but not applied, with `last_error=None`, no `on_event_dropped`, and
  `status="running"`. A trip that suppresses user-event handling should surface
  on the same hook surface the chain budget uses.

## Why medium, not high

The trigger is a chart the library documents as an error and detects correctly
on three of the four (engine x service-kind) combinations; correct usage is
clean on all four; nothing is permanently stuck and nothing is lost from the
queues. The residual is a **detectability and parity gap on an already-invalid
chart** — it delays the author's discovery of their own bug, it does not
compromise a correct machine. Not a production-blocking OMS risk; should be
fixed for the #179 promise it contradicts.

## Artefacts

- `battle-6db65d8/fuzz/r18_ext_starvation_repro.py` (as filed, re-run)
- `battle-6db65d8/fuzz/r19_starvation_drain.py` (as filed, re-run)
- `battle-6db65d8/fuzz/r20_r8_04_refutation.py` (chart validity + correct usage)
- `battle-6db65d8/fuzz/r21_r8_04_signal.py` (signal polling)
- `battle-6db65d8/fuzz/r22_r8_04_fate.py` (drain/fate)
- `battle-6db65d8/fuzz/r23_r8_04_why.py` (settle-budget cause)
