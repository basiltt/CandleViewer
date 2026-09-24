# FUZZ — fuzzing & property-based battle test of `xstate-statemachine` @ `f28719c`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`f28719c`** ("Merge pull request #202 from basiltt/fix/0.8.1-round8").
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`. **`__version__` still reports
`0.8.0`; this build is identified by commit.**

**Date:** 2026-09-22. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`
with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Track:** FUZZ, re-run of `battle-6db65d8/fuzz.md` plus a new attack set aimed
at round 8's fixes (#192–#201, reopened #181/#186). New scripts live under
`docs/research/xstate/battle-f28719c/fuzz/`. No library source was modified.
No `git` command was run in the adopting project's repository. GitHub was
read-only throughout.

**Standard applied.** This library is being evaluated to run an
order-management system handling real money. Every silent failure,
nondeterminism and ordering ambiguity is treated as a defect and reproduced
before it is counted. **Every service-related check was run with both `def`
and `async def` services.**

---

## 0. Bottom line

**Round 8's priority-lane work is genuinely done: the shed side is now
provenance-aware and this track's headline Blocker (R8-01) is gone on every
cell measured. Two of round 8's own claims do not hold as written — the
engine-event provenance boundary (#195) is forgeable three ways, and the lap
parity sentence (#201) is false at small `maxIterations`. The async-lane
starvation shape (R8-04) is half-fixed.**

- **R8-01 / D8-fuzz-2 is FIXED.** `battle-6db65d8/fuzz/r8_ext_shed_loss.py`
  verbatim: **600 sent, 600 applied, 0 lost, 0 `chain_budget` drops** on all
  four cells (`def`/`async def` × `wait=True`/fire-and-forget); prior round
  lost 8/600. Confirmed independently by `g3_concurrency.py` §A (600/600 on
  both kinds, during a live self-generated invoke chain) and by
  `g6_observability_soak.py` §A: when the chain trips, the item shed is
  `SELF` — the self-generated one — on **both engines**, while all 40
  external priority sends are applied.

- **NEW D9-fuzz-1 (Blocker) — #195's engine-event provenance boundary is
  forgeable three ways.** `is_system_event` keys on being an instance of the
  private `engine_done` subclass, but NamedTuple machinery reconstructs the
  subclass: `ed._replace(data=...)`, `pickle.loads(pickle.dumps(ed))`, and a
  **hand-written snapshot record carrying `"engine": true`** all yield
  `is_system_event=True`. Each drives a real `onDone` under `strict=True`,
  landing `{'filled': 999999}` in context **while the genuine service is
  still running** — the exact scenario #195 was filed for. Only the one
  vector the changelog names (a hand-built `DoneEvent`) is refused.
  `g7_forgery_repro.py`: 3 successful forgery vectors.

- **NEW D9-fuzz-2 (Medium) — #201's lap-parity sentence is false at small
  limits.** The changelog says "all three lanes now agree at every limit
  tested". `g2_lap_parity.py` sweeps `maxIterations` 1–10, 15, 20, 25 on two
  cycle shapes: on `rollback_ondone` with a `def` service the sync engine
  runs **two laps more than async at every ODD limit** (mi=1: 3 vs 1; mi=5: 7
  vs 5; mi=25: 27 vs 25) and agrees at every even one. Reproduced by the
  prior round's `r11_livelock_matrix.py` independently (7 mismatches / 24
  configs, all `plaindef`).

- **D8-fuzz-3 (R8-04) is CHANGED, not fixed.** `r18_ext_starvation_repro.py`:
  the `plain def` lane now applies **500/500** external priority sends (was
  the same shape starving). The `async def` lane applies **72/500 (14.4 %)**
  with `status="running"`, `last_error=None`, no drop hook — and
  `r19_starvation_drain.py` confirms it is still **STUCK 10 s after the
  producer stops** (applied 181/500, priority queue 319, 66 % of one core).
  Refiled as **D9-fuzz-3 (High)**, async-lane only.

- **D8-fuzz-1 is STILL PRESENT, unchanged.** `r3_empty_repro.py` verbatim:
  `await send(EV, wait=True)` resolves at an instant when
  `current_state_ids == []`, `last_transition_ok=True`, `last_error=None`,
  `status="running"` — **11/15 laps** (was 7/15), `async def` + async engine
  only; `plain def` 0/15, sync engine clean. Refiled **D9-fuzz-4 (Medium)**.

- **D8-fuzz-4 (R8-08) is FIXED.** `r10_186_asymmetry.py`: all 8 mutations
  (emptied `state_ids`, missing `state_ids`, `configuration=None`, missing
  `configuration`, both cross-forgeries, both emptied) are now
  `SnapshotCorruptError`. **0 accepted-despite-disagreement**, down from 3/9.

- **D8-fuzz-5 (R8-14) is STILL PRESENT.** `r14_observability.py` §C: a
  `SnapshotMidStepError` raised from an invoked child's entry action still
  reports `child=False` on both service kinds. Low.

- **Everything else round 8 built verifies clean.** #196's eventless
  selection is exact — the **full 3×3 depth matrix** (`always` shallower /
  same / deeper than the named handler) is 9/9 PASS on both engines, and 120
  fuzzed named-event charts with an `always` present lose **0** transitions.
  #193's rollback-before-submission holds under 200 concurrent arms
  (**0 callable submissions**). #194's per-child bound is real on the
  coroutine lane (50 children, D=0.1 s → `start()` = 0.13 s) and the WARNING
  fires on the non-preemptible `def` lane exactly as documented. #199's hook
  is inside the in-flight window (snapshot from `on_interpreter_start` →
  `SnapshotMidStepError`). #198's v1 rule refuses a `state_ids`-only v1
  payload while v0 still loads. The persistence property over **300 random
  machines × both engines × both kinds** is **7 752 refusals, 1 068 legal
  snapshots, ZERO torn**. Determinism is total including a `PYTHONHASHSEED`
  sweep. A **75 s / 40-machine soak** is CPU-bounded (10 % of 8 cores), leaks
  no threads (1 → 1), drops nothing, and takes 11 945 clean chaos snapshots.

- **The pattern.** Round 8 fixed the *behavioural* half of its findings
  cleanly. What it did not do is make its two new *claims* true: the
  provenance type-boundary is a Python type check that Python itself
  reconstructs, and the parity sentence was generalised from the limits that
  happened to be tested.

---

## 1. Method, and the reductions made

Hard bounds: ≤ 120 s per script, ≤ 20 min total wall clock. **Reductions,
stated explicitly:**

| Script | Brief asked | This run | Why |
|---|---|---|---|
| `r11_livelock_matrix.py` | ≥ 500 configs × 2 kinds × 2 engines | **24 configs** (96 cells) | Measured throughput on this build is ~3.7 s/config (24 configs = 92 s). 160 and 500 both exceeded the 120 s bound with no output. The matrix's three properties (P1 termination, P2 observability, P3 lap parity) are each decided within 24 configs: 0 non-settling, 0 unobservable, 7 parity mismatches. Parity is separately swept exhaustively by `g2_lap_parity.py` over 52 limit/shape/kind cells. |
| Soak | 12 min, 200 machines | **75 s, 40 machines** | 12 min alone exceeds the whole-task bound. Load shape preserved: async services + external priority producer + rollback+onDone + always→invoke + chaos snapshot at quiescence, all four concurrently. 95 560 external sends and 11 945 snapshots taken in the window. |
| `g5` §A2 named-event fuzz | ≥ 300 charts | **120 charts** | Each chart starts and stops a real interpreter (~0.2 s). The 3×3 depth matrix in §A is the exhaustive form of the same property. |
| Persistence property | ≥ 300 machines | **300 machines** (full) | Ran within budget (`r4_persist_property.py`, 96 s). |

**Every new script is standalone** — stdlib plus `xstate_statemachine` only,
with any helper inlined. The prior round's `common.py` importers
(`f1`/`f2`/`f3`, `m9b`, `m9c`, `n1_ref6`, `n1_repro`, `r11`, `r17`) were
checked: `r11` and `r17` match only on `collections.Counter.most_common`, not
an import, so no inlining was needed for anything re-run here.

### 1.1 Adaptation for documented-superseded behaviour

`g2`/`r11` score `sync engine + async def service` as a lap-parity mismatch
purely because `SyncInterpreter` raises `NotSupportedError` for a coroutine
service. That is the **documented** contract, not a defect, and those 13+13
cells are excluded from the D9-fuzz-2 count; only `def`-service mismatches are
counted.

`g3_concurrency.py` §C was written against a `children_timeout` constructor
kwarg; on this build the parameter is `start(children_timeout=)`. Corrected,
and the section was rewritten as `g4_children_timeout.py` using **real
invoked child machines** rather than parallel regions (the first version
measured the wrong thing and its result is discarded).

---

## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

| Prior ID | Register | Severity then | Verdict @ `f28719c` | Evidence |
|---|---|---|---|---|
| D8-fuzz-2 | R8-01 | High (Blocker merge) | **FIXED** | `r8_ext_shed_loss.py`: 600/600 applied, 0 lost, 0 hook drops, on all 4 cells (was 592/600, 8 lost). Cross-checked by `g3` §A and `g6` §A (shed item is `SELF`, not the external send, on both engines). |
| D8-fuzz-3 | R8-04 | High | **CHANGED** → **D9-fuzz-3** | `r18_ext_starvation_repro.py`: `def` lane now **500/500 (100 %)**; `async def` lane **72/500 (14.4 %)**, `last_error=None`, no drop hook. `r19_starvation_drain.py`: still 181/500 after 10 s idle at 66 % of one core — permanent, not slow. |
| D8-fuzz-1 | R8-07 | Medium | **STILL-PRESENT** (slightly worse) | `r3_empty_repro.py`: empty configuration at the `wait=True` resolution instant **11/15** laps (was 7/15), `ok=True err=None status=running`, snapshot `REFUSED:SnapshotMidStepError`, heals within 500 ms to `['m.a.c']`. `async def` + async engine only. Refiled **D9-fuzz-4**. |
| D8-fuzz-4 | R8-08 | Medium | **FIXED** | `r10_186_asymmetry.py`: 8/8 disagreement mutations now `SnapshotCorruptError`; **accepted-despite-disagreement = 0** (was 3/9). |
| D8-fuzz-5 | R8-14 | Low | **STILL-PRESENT** | `r14_observability.py` §C: `{'root': None, 'child': 'REFUSED child=False'}` on both service kinds. |
| D7-fuzz-1 (invoke-cycle livelock) | — | Blocker, fixed r7 | **STILL FIXED** | `r11_livelock_matrix.py 24`: 96/96 cells settle, **0 RUNAWAY, 0 unobservable trips**. |
| #179 async-lane charging | — | fixed r7 | **STILL FIXED** | `r14_observability.py` §A: `chain_budget` hook fires **exactly once** with `RunawayChainError` on all four engine/kind cells. |
| #157 queue_full loop-side | — | fixed | **STILL FIXED** | `r14_observability.py` §B: 640 futures, 638 errors, hook `queue_full=638`, 0 call-site raises — exactly-once on both kinds. |
| Determinism / hash-seed | — | clean | **STILL CLEAN** | `r12_determinism.py`: 50× identical traces → **1 distinct outcome** per cell, cross-engine equal, trip lap = 6 everywhere; `PYTHONHASHSEED` 0/1/12345 → 1 distinct result. |
| Persistence torn-snapshot property | — | clean | **STILL CLEAN** | `r4_persist_property.py`: 300 machines × 2 engines × 2 kinds → refused 7 752, produced 1 068, **TORN = 0**. |

---

## 3. New attacks on round-8 machinery

### 3.1 Persistence — `g1_persist_provenance.py`

| Attack | Result |
|---|---|
| Priority-lane item round-trip, external vs self-generated provenance, resume and re-send | **PASS** both: resume at `g1.a`, the post-resume `EXT` is applied (`n 1→2`) |
| Genuine `done.invoke` record → `restore_event` | carries `engine: true`, restores system |
| **Hand-written record with `"engine": true`** | **`is_system_event=True` — FAIL, see D9-fuzz-1** |
| Record without the flag | `is_system_event=False` — PASS |
| `version=1` with both configuration fields | loaded |
| **`version=1`, `state_ids`-only (configuration removed)** | `refused:SnapshotCorruptError` — #198 PASS |
| `version=0` (no `version` key), `state_ids`-only | loaded — the documented v0 shape, PASS |
| Snapshot taken inside `on_interpreter_start` | `REFUSED:SnapshotMidStepError` — #199 PASS |

Plus the full property: `r4_persist_property.py`, 300 random machines
(including parallel states and invoked children) × both engines × both
service kinds, snapshotting from action / guard / `on_transition` sites:
**7 752 refusals, 1 068 legal snapshots, 0 torn**, no untyped failure other
than the documented `sync + async def` `NotSupportedError`.

### 3.2 Concurrency — `g3_concurrency.py`, `g4_children_timeout.py`

| Attack | `def` | `async def` | Verdict |
|---|---|---|---|
| External priority producer, 600 sends **during a live self-generated invoke chain** | 600/600 applied, 0 dropped | 600/600 applied, 0 dropped | **PASS** (#192 shed-by-provenance) |
| **Action-issued** priority send must be charged and trip | async `RunawayChainError`, sync `RunawayChainError` | async `RunawayChainError` | **PASS**, both engines where the kind is supported |
| `def` service armed then **rolled back**, 200 concurrent `ARM` | **0 callable submissions**, ends at `d.idle` | n/a | **PASS** (#193) |
| `children_timeout`, **50 invoked child machines**, entry 0.10 s, `T=0.20 s` | `start()` = **5.07 s** (≈ N·D), WARNING **fires** | `start()` = **0.13 s** (≈ D — per child), WARNING absent | **PASS as documented** |

The `def` row is the case the changelog explicitly carves out: a
non-yielding `def` entry action cannot be pre-empted on the event-loop
thread, so the bound cannot hold — and #194's requirement is precisely that
the WARNING fire anyway, which it does, naming the 0.200 s allowance and the
5.072 s actual. The coroutine lane shows the bound is genuinely **per
child**: 50 children × 0.1 s settle in 0.13 s, not 5 s. Both halves of #194
hold.

### 3.3 Semantics — `g5_semantics_security.py`

**SCXML §3.13 eventless-selection matrix (#196).** An `always` placed
shallower than / at the same depth as / deeper than a named `EV` handler,
all nine combinations, both engines:

```
  always@shallow  handler@{shallow,same,deep}   async_hit=1 sync_hit=1  PASS
  always@same     handler@{shallow,same,deep}   async_hit=1 sync_hit=1  PASS
  always@deep     handler@{shallow,same,deep}   async_hit=1 sync_hit=1  PASS
  matrix failures = 0
```

The round-7 defect — a deeper `always` outranking a shallower named handler
and swallowing the event — is gone in every cell. The **fuzz** form agrees:
120 randomly-shaped named-event charts that all contain a spinning `always`
(half with a random `maxIterations` of 5/50/500) lose **0** named
transitions.

**Private-subclass isinstance semantics (#195).** `engine_done(...)` *is* an
`isinstance` of the public `DoneEvent` (so user `isinstance` checks keep
working) while `is_system_event` is `True`; a hand-built `DoneEvent` is an
`isinstance` too but `is_system_event` is `False`. `__slots__` on the private
class is `()` — correct, it adds no dict. That part of #195 is exactly as
designed. What fails is the boundary itself; see next.

### 3.4 Security — `g5` §D and `g7_forgery_repro.py`

Four ways to obtain an object that `is_system_event` trusts, each then sent
to a `strict=True` machine whose real `svc` is still sleeping:

| Vector | `is_system_event` | `send(...)` under `strict` | drove `onDone`? |
|---|---|---|---|
| `engine_done(...)` via import path | True | ACCEPTED | yes (legitimate — the mint function is private-by-convention only) |
| **`ed._replace(data={'filled': 999999})`** | **True** | **ACCEPTED** | **yes → `s.b`, attacker payload in context** |
| **`pickle.loads(pickle.dumps(ed))`** | **True** | **ACCEPTED** | **yes → `s.b`, attacker payload in context** |
| **`restore_event({... "engine": true})`** | **True** | **ACCEPTED** | **yes → `s.b`, attacker payload in context** |
| hand-built `DoneEvent(...)` | False | `REFUSED:UnknownEventError` | no — the one vector the changelog names |

### 3.5 Observability and soak — `g6_observability_soak.py`

```
== A: shed-by-provenance drops + settle trip, both engines ==
  async  EXT applied=40/40 lost=0 err=RunawayChainError drops={'drop:chain_budget': 1} shed_types={'droptype:SELF': 1}  PASS
  sync   EXT applied=40/40 lost=0 err=RunawayChainError drops={'drop:chain_budget': 1} shed_types={'droptype:SELF': 1}  PASS
```

The drop hook fires **exactly once**, on **both** engines, and the event it
names is `SELF` — the self-generated one. Every one of the 40 external
priority sends is applied. This is the direct positive statement of R8-01's
fix at the hook layer.

**Soak (75 s, 40 machines, mixed shapes):**

```
  elapsed=75.0s machines=40 running_at_end=40/40
  cpu=61.1s (10.2% of 8 cores)
  EXT sent=95560 applied=31057 drops={}
  errors={}
  chaos snapshots={'ok': 11945}
  threads 1 -> 1  PASS(no leak)
```

CPU-bounded (no spin), **zero** dropped external events, every machine still
`running` at the end (no livelock or wedge), 11 945 chaos snapshots at
quiescence all clean, and the thread count returns to 1 — the sync-child
reaping added in #196's surfacing holds. The 31 057/95 560 applied figure is
backpressure, not loss: the producer outruns the consumers by design and the
undelivered remainder is still queued at `stop()`, with `drops={}`.

---

## 4. Defects

### D9-fuzz-1 — Blocker — an engine completion is forgeable three ways, defeating #195

**Repro:** `battle-f28719c/fuzz/g7_forgery_repro.py` (standalone; 3 forgery
vectors succeed).
**Site:** `src/xstate_statemachine/events.py:272` (`is_system_event`),
`events.py:414` (`trusted = record.get("engine") is True`),
`events.py:561-604` (the private subclasses and mint functions).

**What #195 claims.** *"The engine now mints private subclasses … a
user-built one is refused under `strict` with a message naming it as an
engine-generated name, and persisted completions carry `"engine": true` so a
genuine round-trip keeps its provenance while a forged record restores as
user traffic."*

**What happens.** The boundary is `isinstance(ev, engine_done)`. Python
reconstructs that class through ordinary NamedTuple machinery, so three
cheap vectors produce a genuine `engine_done` carrying attacker data:

```
  NamedTuple._replace on any engine event
     is_system_event=True  send->ACCEPTED  drove_onDone=1  ids=['s.b']
     attacker payload landed in context = {'filled': 999999}   genuine service still running = True
  pickle round-trip of an engine event
     is_system_event=True  send->ACCEPTED  drove_onDone=1  ids=['s.b']
  hand-written snapshot record, engine:true
     is_system_event=True  send->ACCEPTED  drove_onDone=1  ids=['s.b']
  hand-built DoneEvent (#195 closed this)
     is_system_event=False  send->REFUSED:UnknownEventError  drove_onDone=0  ids=['s.a']
```

Each accepted vector lands the attacker's `{'filled': 999999}` in context and
moves the machine to the `onDone` target **while the genuine service is still
running** — which is verbatim the scenario #195 was filed for. `strict=True`
does not refuse them. The first two require only an `engine_*` instance to
already exist, which any plugin/`on_transition` hook observing a real
completion has; the third requires nothing but the ability to author a dict.

**On the changelog's stated rationale for the third vector** — *"a caller who
can write arbitrary snapshot records already controls `state_ids` and
`context` outright (#185), so this is the correct trust boundary."* That is
no longer true on this build: #198 (this same round) **refuses** a forged
`configuration`/`state_ids` payload — `r10_186_asymmetry.py` shows 8/8
mutations now `SnapshotCorruptError`. The state channel was hardened and the
event channel was not, so the event record is now strictly the weaker door,
and the rationale that justified leaving it open has been invalidated by the
adjacent fix in the same release.

**Why Blocker for an OMS.** A forged `done.invoke.fill` with an attacker's
fill quantity is accepted as the exchange's own confirmation, and the real
fill is still outstanding.

### D9-fuzz-2 — Medium — #201's "all three lanes agree at every limit" is false at small `maxIterations`

**Repro:** `battle-f28719c/fuzz/g2_lap_parity.py` (sweep 1–10, 15, 20, 25).
Independently: `battle-6db65d8/fuzz/r11_livelock_matrix.py 24` → 7 mismatches.

On `rollback_ondone` with a `def` service the sync engine runs **exactly two
laps more than the async engine at every ODD limit**, and agrees at every
even one:

```
    mi=1   sync_laps=3   async_laps=1    DIFFER
    mi=2   sync_laps=3   async_laps=3    SAME
    mi=3   sync_laps=5   async_laps=3    DIFFER
    mi=5   sync_laps=7   async_laps=5    DIFFER
    mi=15  sync_laps=17  async_laps=15   DIFFER
    mi=25  sync_laps=27  async_laps=25   DIFFER
    mi=20  sync_laps=21  async_laps=21   SAME
```

Both lanes trip `RunawayChainError`, so this is a **reporting/accounting**
discrepancy, not an unbounded livelock — hence Medium. But `maxIterations`
is the OMS's runaway budget, and the same configured budget admits a
different number of transitions depending on which engine is running. The
changelog sentence should be narrowed to the even/large-limit case or the
odd-limit off-by-two fixed. Note the changelog *does* already carve out
`rollback + onDone` for a different reason (the sync engine not re-arming a
rolled-back invoke); this measurement shows the carve-out is incomplete —
the divergence is a lap **count**, at every odd limit, with both lanes
tripping the same error.

### D9-fuzz-3 — High — the `always`→invoke→`onDone` shape still starves external priority traffic, `async def` lane only

**Repro:** `battle-6db65d8/fuzz/r18_ext_starvation_repro.py` (re-run
verbatim) and `r19_starvation_drain.py`.
**Change from R8-04:** the `plain def` lane is **fixed** (500/500 applied,
was starving); the `async def` lane is not.

```
  SYNC engine, plain def:  EXT sent=500 APPLIED=500 (100.0%)
  plain def                EXT sent=500 APPLIED=500 (100.0%)
  async def                EXT sent=500 received=72 APPLIED=72 (14.4%)
                            status=running last_error=None drops={}
                            queues at end: inbox=499 priority=428
```

Every health signal is green: `status="running"`, `last_error=None`, no
`on_event_dropped`. Permanence confirmed after the producer stops:

```
  after 10.0s idle: applied=181/500 inbox=499 priority=319 cpu=6.6s (66% of one core) => STUCK
```

Both ablations remain necessary and still discriminate: without the `always`
both kinds apply 500/500; without the `invoke` both kinds apply 500/500 **and**
report `RunawayChainError`. Only the combination starves, and only silently,
and now only on the coroutine lane.

### D9-fuzz-4 — Medium — `await send(EV, wait=True)` still resolves over an empty configuration

**Repro:** `battle-6db65d8/fuzz/r3_empty_repro.py` (284-byte chart, verbatim).
Unchanged from D8-fuzz-1 / R8-07, and marginally more frequent: **11/15** laps
(was 7/15).

```
  == async engine, async def svc: EMPTY config 11/15 ==
     EMPTY   ok=True   err=None   status=running
     snapshot=REFUSED:SnapshotMidStepError
     +500ms ids=['m.a.c']
```

`async def` + async engine only (`plain def` 0/15; sync engine clean). The
window heals in ~500 ms, and `get_snapshot()` correctly refuses during it —
so the *persistence* boundary is sound. What is wrong is that the caller's
own "your step is complete" signal resolves at exactly the instant the
configuration is empty, with every health field reporting success. A
post-`send` read of `current_state_ids` — the natural OMS idiom for "what is
the order's state now" — returns `[]`.

### D9-fuzz-5 — Low — `SnapshotMidStepError` from an invoked child reports `child=False`

**Repro:** `battle-6db65d8/fuzz/r14_observability.py` §C. Unchanged from
D8-fuzz-5 / R8-14; both service kinds report `REFUSED child=False` when the
snapshot is attempted from inside an invoked child machine's entry action.
Diagnostic quality only.

---

## 5. Not covered

Stated plainly so the gaps are not mistaken for passes.

- **The livelock matrix at full scale.** 24 configs (96 cells), not 500.
  P1/P2 were decided unanimously within that sample (0 non-settling, 0
  unobservable), but a rare shape that only appears past config ~100 would
  not have been seen. P3 is covered exhaustively elsewhere (`g2`).
- **The 12-minute / 200-machine soak.** Run at 75 s / 40 machines. A slow
  leak with a time constant above ~1 minute, or a contention effect that
  only appears past 40 concurrent interpreters, is out of scope of this run.
- **Timer/`after` interaction with the priority lane.** The round-8 changes
  touch `engine_after`, but no `after`-under-load attack was run here; the
  forgery matrix covers `engine_after`'s *type* boundary only.
- **`SyncInterpreter` + `async def` service** is `NotSupportedError` by
  design; every such cell is excluded rather than scored, so the sync engine
  is only measured on `def` services.
- **Redaction of event payloads in logs** was not measured — logging is
  disabled in every script for throughput, and the one WARNING captured
  (`children_timeout`) carries no payload. Not a pass, simply unmeasured.
- **Multi-process / cross-host snapshot exchange.** The forgery finding is
  in-process plus the `restore_event` door; an actual persisted-store
  round-trip through a real serializer was not exercised beyond
  `persist_event`/`restore_event`.
- **Hypothesis-driven shrinking** of the D9-fuzz-4 chart was not re-run; the
  prior round's 284-byte shrink is reused verbatim.

---

## 6. Verdict

**Round 8 is a real improvement and is not adoption-ready.**

What it got right is substantial and is confirmed here rather than taken on
trust: the priority lane now sheds by provenance on both engines
(`SELF` is cut, the external sends survive — 600/600, 40/40, 0 drops); the
eventless-selection rule is exact across the full 3×3 depth matrix and 120
fuzzed charts; `rollback` cancels a `def` invoke before submission under 200
concurrent arms; the per-child `children_timeout` bound is genuinely per
child on the coroutine lane and warns loudly on the lane it cannot bound;
`on_interpreter_start` is inside the in-flight window; #198 closed the
`state_ids`/`configuration` asymmetry completely (8/8); and the torn-snapshot
property is clean over 300 random machines on every engine/kind cell.

What blocks adoption is that **the round's two new claims are the two things
that do not hold.**

1. **#195's provenance boundary does not exist in any meaningful sense**
   (D9-fuzz-1, Blocker). A type check cannot be a trust boundary when the
   type is reconstructible by `_replace` and by `pickle`, and the snapshot
   door is open by explicit design on a rationale that this same release's
   #198 invalidated. For an order-management system this is the worst shape
   of defect available: a forged fill confirmation, accepted as the
   engine's own, under `strict=True`, with the real order still live. The
   fix is not another `isinstance` — provenance has to be carried by
   something the engine mints and holds (a per-interpreter token or an
   identity set of in-flight invocations), checked against the invocation
   that is actually outstanding.

2. **#201's parity sentence is false as written** (D9-fuzz-2, Medium) at
   every odd `maxIterations` on the `def` lane. Low blast radius, but it is
   a *documented guarantee* about the runaway budget, and the budget is a
   safety control.

Alongside those, **R8-04 is half-fixed** (D9-fuzz-3, High): the shape now
starves only the `async def` lane — the lane the documentation recommends —
and still does so silently, permanently, at 66 % of a core with every health
signal green. And **R8-07 is untouched** (D9-fuzz-4, Medium): the success
signal still resolves over an empty configuration.

**Recommendation for this track: do not adopt at `f28719c`.** Required
before re-evaluation: a provenance mechanism for engine completions that is
not a Python type check (D9-fuzz-1), and either a fix or an honest narrowing
of the lap-parity claim (D9-fuzz-2). D9-fuzz-3 should be fixed or the
`always`→invoke→`onDone` shape documented as unsupported with a startup
validation error; D9-fuzz-4 and D9-fuzz-5 are acceptable as known issues if
documented.

The trajectory across rounds 7 and 8 is good — each round's *behavioural*
findings are being fixed properly and stay fixed, and this round's
regressions are zero. The recurring failure mode is narrower and fixable:
claims in the changelog are being generalised beyond what was measured. Two
of round 8's five new claims failed the first adversarial reading of the
claim itself.

---

## 7. Artefacts

New, all standalone (stdlib + `xstate_statemachine`), under
`docs/research/xstate/battle-f28719c/fuzz/`:

| File | Covers |
|---|---|
| `g1_persist_provenance.py` | priority-item round-trip with provenance; `engine:true` forgery in records; v1/v0 restore; snapshot from `on_interpreter_start` |
| `g2_lap_parity.py` | #201 lap-parity sweep, `maxIterations` 1–25, 2 shapes × 2 kinds × 2 engines |
| `g3_concurrency.py` | external priority producer during a self-generated chain; action-issued priority sends charged; `def` arm-then-rollback under 200 concurrent |
| `g4_children_timeout.py` | `children_timeout` per child vs N·D, 50 invoked children, both entry kinds, WARNING presence |
| `g5_semantics_security.py` | SCXML §3.13 3×3 eventless matrix; 120-chart named-event fuzz; private-subclass isinstance/`__slots__`; forgery matrix end-to-end under `strict` |
| `g6_observability_soak.py` | shed-by-provenance drop hook both engines; 75 s / 40-machine soak with chaos snapshots |
| `g7_forgery_repro.py` | **D9-fuzz-1 minimal repro**, 4 vectors, 3 succeed |

Re-run verbatim from `battle-6db65d8/fuzz/`: `r3_empty_repro.py`,
`r4_persist_property.py`, `r8_ext_shed_loss.py`, `r10_186_asymmetry.py`,
`r11_livelock_matrix.py`, `r12_determinism.py`, `r14_observability.py`,
`r18_ext_starvation_repro.py`, `r19_starvation_drain.py`,
`r20_lap_parity.py`.
