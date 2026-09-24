# FUZZ — fuzzing & property-based battle test of `xstate-statemachine` @ `cec108b`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`cec108b`** ("Merge pull request #164 from basiltt/fix/0.8.1-round5").
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`. **`__version__` still reports
`0.8.0`; this build is identified by commit.**

**Date:** 2026-09-19. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter:**
`_ref/xstate-statemachine/.venv-main/Scripts/python`, with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Track:** FUZZ, re-run of `battle-3ed3099/fuzz.md` plus a new attack set aimed
at round 5's fixes (#142–#162, reopened #118/#122/#125/#133/#134, plus #141 and
#149). Scripts live under `docs/research/xstate/battle-cec108b/fuzz/`. No
library source was modified. No `git` command was run in the adopting
project's repository. GitHub was read-only throughout.

**Standard applied.** This library is being evaluated to run an
order-management system handling real money. Every silent failure,
nondeterminism and ordering ambiguity is treated as a defect and reproduced
before it is counted.

---

## 0. Bottom line

**Round 5 closed the whole prior FUZZ defect list — and the async engine
regressed into a new Blocker that is worse than the one it replaced.**

- **All three prior defects are FIXED.** D5-fuzz-1's sync livelock is gone
  (`start()` now returns in 6 s at every `maxIterations`, settling legally with
  `last_transition_ok=False` / `RunawayChainError`); D5-fuzz-2's untyped
  restore paths are typed (5 000 structural mutations → **typed=5000,
  untyped=0**, and all 7 hand-picked field mutations are now
  `SnapshotCorruptError`); D5-fuzz-3 is closed non-downgradably (**8/8**
  site × `strict_targets` combinations raise `RootTargetError`). The prior
  repro suite still scores **0/6**.

- **D6-fuzz-1 (Blocker) — `await Interpreter.send(EV, wait=True)` never
  resolves, and the loop burns a full core.** An event that re-enters a
  compound state whose `always` descends into a child carrying an `invoke`
  livelocks the async run loop once that invoke has completed. **8 lines of
  config, 100 % reproducible, both `maxIterations=1` and `=1000`.** The
  interpreter stays `status="running"`, `stop()` still returns, the inbox
  stays at `qsize=1` — so the *receipt* is simply never delivered while
  ~12 000 events/s pass through `_process_event` (2.8 s CPU per 3 s wall, RSS
  flat at 32 MB). **The sync engine returns in 0.06 s on the identical
  config.** The prior round's nested-`invoke`-`onDone`-to-ancestor shape
  (D5-fuzz-1) is *also* still live on async by the same mechanism, so this is
  the same family the sync engine was fixed for, left open on the other
  engine. On an OMS this is an `await send(...)` on the order path that never
  returns, plus a silently pegged core.

- **D6-fuzz-2 (High) — #149 broke #116's engine parity for plain-`def`
  services.** #116's contract is that a plain-sync `invoke` completes at the
  same point on both engines; #149 moved those services onto a
  `ThreadPoolExecutor` and claims the entering macrostep awaits the result.
  It does not await it across `start()`: the sync engine returns from `start()`
  already in `m.b` (invoke done), the async engine returns in `m.a` (invoke
  pending), **10/10 trials**. An event sent immediately after `start()`
  therefore lands in a different state on each engine. The narrower
  `(GO, CANCEL)×10` oracle from the prior round still shows parity, which is
  why this needed a new probe.

- **Everything else this round checks out.** 320 random *parallel* machines
  × 6 quiescent points = **1 920 snapshots, zero raises, zero round-trip
  drift**; history+parallel restore is faithful through a subsequent `BACK`;
  a v1 upcast carrying a torn or root-only configuration is refused
  (`SnapshotCorruptError`) while a legal v1 blob loads; an
  `actionErrorPolicy: "fail"` machine is `stopped` with the configuration
  cleared and its snapshot is refused on restore; `guardErrorPolicy: "raise"`
  takes the unguarded fallback (`m.c`) and records the `ValueError`;
  `Receipt.denied` distinguishes guard-denied from unhandled, matching
  `on_unhandled_event(disposition="guard_denied")`; 3 000 hostile event
  objects → **0 untyped**; 200 concurrent plain-`def` services complete
  200/200 in 1.5 s with the loop still turning and no thread growth;
  `send_threadsafe` under `RAISE` across 16 threads applies **960/960** with
  zero untyped escapes and no hung threads; 500 start/stop cycles leak
  nothing; `__all__` is 78 names with no dangling entries. A **5-minute chaos
  soak** pushed 7.96 M events and 14 298 snapshot+restore round trips with
  flat RSS and **zero invariant violations**.

- **The residue is one engine, one mechanism.** Both new defects are the
  *async* engine's handling of work that the sync engine performs inline:
  a self-generated `always` chain that the loop never drains (D6-fuzz-1) and
  an executor result the macrostep does not actually wait for (D6-fuzz-2).
  §4 and §6 state what else was covered and what was not.

---

## 1. Method

### 1.1 What was re-run, and the reductions made

The brief's hard bound is ≤ 120 s per script and ≤ 20 min total. **Reductions,
stated:**

| Script | Prior run | This run | Reduction | Justification |
|---|---|---|---|---|
| `repros.py` | full | **full** | none | Cheap; run verbatim, 0/6. |
| `f1_machine_config.py` | 4 000 | **1 500** | 2.7× | Zero A4 non-termination hits (prior run: 1 per 233 valid configs). A null result at 1 500 is weaker; noted in §6. |
| `f2_events.py` | 4 000 | **800** | 5× | Found the B2 class at 800 (6 hits) — decisive for *finding*; the rate is not comparable to the prior run. |
| `f3_snapshot.py` | 5 000 | **1 200** | 4× | **NO DEFECTS** at 1 200. The 5 000-case budget was spent instead on the structural mutation fuzzer `m2.B1`, which is the sharper instrument for the same contract. |
| `n5_soak.py` | 12 min | **5 min** | 2.4× | Wall-clock budget. 7.96 M events / 14 298 round trips is still a real soak, but it does **not** restate the prior 12-min result. |
| new `m2`, `m10`, `m12` | — | as briefed | none | B1 at 5 000 mutations, B2 at 3 000 events, E1 at 320 parallel cases, C3 at 200 services, C4 at 16×60 threads, C5 at 500 cycles. |

`n1_repro.py`, `n2_restore_untyped.py`, `n8_strict_targets_root.py`,
`n10_async_spin.py` were re-run verbatim as the prior-defect oracles.

### 1.2 Oracle updates and harness bugs corrected before filing

Three harness faults were found and fixed *before* any defect was counted.
Each would have produced a false positive, and the reader should know §3
survived this filter:

1. **`from_snapshot()` takes a JSON string, not a dict.** The first run of
   `m12` reported `E1 restore:SnapshotCorruptError 320/320`,
   `E3 SnapshotCorruptError` and an apparently-broken v1 upcast. The library
   was right and the harness was wrong — it passed `json.loads(...)`. With
   `json.dumps(...)` all three pass. **A stale harness makes a correct library
   look broken**; this is the same lesson as the prior round's oracle sets.
2. **`Receipt` is only returned for `send(..., wait=True)`** on the sync
   engine. `m2.B4` initially reported `denied=MISSING` for both events; with
   `wait=True` it reports `denied(DENY)=True denied(NOPE)=False`, exactly as
   #153 documents. Not a defect.
3. **Plugin hooks are positional, not `**kwargs`.** `m12.E6`'s probe silently
   recorded nothing because its `on_unhandled_event(self, i, ev, reason=None)`
   did not match the real
   `(interpreter, event, active_state_ids, disposition)`. Corrected, and
   subclassed from `PluginBase` rather than duck-typed.

`common.py`'s `ALLOWED_*` tuples were **not** changed this round — round 4's
amendment already scores the current contract, and `cec108b` adds no new
exception class at these boundaries.

### 1.3 Adapting scripts that assumed superseded behaviour

| Prior script | What happens now | Adaptation |
|---|---|---|
| `n8_strict_targets_root.py` | `create_machine(..., strict_targets=False)` raises `RootTargetError` at line 13, so the script *cannot set up* | **Left unmodified.** Its traceback is the evidence that D5-fuzz-3 is fixed. The contract is re-probed systematically in `m2.B6` (4 sites × 2 flag values). |
| `repros.py` `d7`, `d10` | build/snapshot rejected before the defect can be staged | Left unmodified, as last round — the "harness error" lines are the evidence. |
| `m6_budget_torn.py` `maxIterations=None` | `models.py:1447` does `int(config.get("maxIterations", 1000))`, so an explicit `None` raises a bare `TypeError` | Removed `None` from the sweep. **Not filed** — `None` is not a documented value for the key; the sweep covers 1…20 instead. |

### 1.4 The anti-hang instrument, and why it did not matter this time

`spin_oracle.py` (a budgeted `_select_transitions` raising a sentinel after
20 000 selections, monkey-patched **in the fuzzer's process only**) is retained
unchanged. This round it was verified to be *load-bearing in neither
direction*: re-running `f2_events.py --cases 800` with `SPIN_LIMIT` raised to
10⁸ produced the **same 6 B2 hits**, so the illegal-configuration class is not
an artefact of the instrument.

### 1.5 Exact commands

```bash
cd docs/research/xstate/battle-cec108b/fuzz
PY="_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1

# prior-defect oracles
$PY -u repros.py                          # -> 0/6 reproduce
$PY -u n1_repro.py                        # D5-fuzz-1 sync: returns at every mi
$PY -u n10_async_spin.py                  # D5-fuzz-1 async: still burns a core
$PY -u n2_restore_untyped.py              # D5-fuzz-2 field-level
$PY -u n8_strict_targets_root.py          # D5-fuzz-3 (now cannot set up)
$PY -u f1_machine_config.py --cases 1500
$PY -u f2_events.py         --cases 800
$PY -u f3_snapshot.py       --cases 1200

# new work
$PY -u m1_illegal_config.py    # shape ablation for the F2 B2 class
$PY -u m2_new_attacks.py       # B1-B6: mutation/event fuzz, #152/#153/#145/#147
$PY -u m3_b2_replay.py         # replay the saved B2 repro, both engines
$PY -u m4_b2_flaky.py 40       # is it timing-dependent?
$PY -u m5_b2_shrink.py         # automatic shrinker
$PY -u m6_budget_torn.py       # chain-budget / torn-configuration sweep
$PY -u m8_send_hang.py 6       # D6-fuzz-1 ablation from the captured case
$PY -u m9_send_hang_min.py     # D6-fuzz-1 MINIMAL repro
$PY -u m10_remaining.py        # C1-C6: determinism, executor, threads, API
$PY -u m11_116_parity.py       # D6-fuzz-2
$PY -u m12_persist_livelock.py # E1-E6: parallel snapshots, livelock, hooks
$PY -u n5_soak.py --minutes 5
```

---

## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

`repros.py` verbatim: **0 of 6 runnable repros reproduce** (three more cannot
set up because the config is rejected at build — itself the fix).

| ID | Prior severity | Verdict | Evidence |
|---|---|---|---|
| **D5-fuzz-1** nested `invoke`s whose `onDone` targets their common ancestor livelock `SyncInterpreter.start()`; no `maxIterations` bounds it | Blocker | **FIXED on sync / STILL-PRESENT on async** | `n1_repro.py`: sync `start_alive=False` at `maxIterations` ∈ {None, 10, 1000}, settling in `m.a.a` with RSS flat at 43 MB — the #144 "chain ends only when nothing self-generated remains" fix works. The **async** engine is unchanged: `n10_async_spin.py` still shows `start()` returning `running` in `m.a.a` while burning **2.88–2.97 s CPU per 3 s wall** across 165 196 events at 12 s, RSS flat. `m12.E5` confirms `await send(GO, wait=True)` then never resolves. Carried forward as part of **D6-fuzz-1**. |
| **D5-fuzz-2** `from_snapshot()` has untyped and silent paths | High | **FIXED** | `m2.B1`: 5 000 structural mutations → `typed=5000 accepted=0 untyped=0`, zero frames. `n2_restore_untyped.py`: all 7 previously-untyped field mutations (`history=str`, `history={'m':None}`, `actors={'a':None}`, `actors=7`, `deferred=[None]`, `state_ids=None`) now `SnapshotCorruptError`. `f3_snapshot.py --cases 1200`: **NO DEFECTS**. |
| **D5-fuzz-3** `strict_targets=False` reopens the #108 root-target hole | High | **FIXED** | `n8_strict_targets_root.py` can no longer set up: `create_machine(..., strict_targets=False)` raises `RootTargetError` from `validation.py:287`. `m2.B6` generalises it: **8/8** of {`on`, `always`, `after`, `onDone`} × {`strict_targets=True`, `False`} raise `RootTargetError`. #147 holds. |
| D-fuzz-3/4/5/6/8 (round-3 residue) | — | **still FIXED** | `repros.py` 0/6; `m2.B2` extends the event boundary to 3 000 hostile objects over 23 shapes: `typed=2475 accepted=525 untyped=0`. |
| D-fuzz-9 settle trip leaves a non-tree configuration | High | **still FIXED** | `m1_illegal_config.py`: all three `always`-to-ancestor shapes give `start='LEGAL' after_GO='LEGAL'` on both engines. `m6`'s `maxIterations` sweep (1, 2, 3, 5, 20) never produces a torn node: `torn=[]` in all 10 runs. |

**Score: 3 of 3 prior defects fixed on the sync engine; 1 of the 3 survives on
the async engine and is refiled, widened, as D6-fuzz-1.**

### 2.1 One note on `n2`'s last line

`n2_restore_untyped.py` reports `configuration=None -> LOADED SILENTLY
(config=['m.a'], status=running)`, i.e. 1 of 7 "non-contractual outcomes". This
is **not** filed. It is the documented redundancy between `configuration` and
`state_ids`: the restore recovers the *correct* state from the surviving field
rather than loading garbage, which was already assessed as acceptable last
round (`n7_silent_restore.py`). `m12.E4` confirms the dangerous direction is
closed — a blob whose configuration is torn or root-only **is** refused.

---

## 3. New attacks

`m2` **6/6 PASS**, `m10` **6/6 PASS**, `m12` **6/6 PASS after the harness
corrections of §1.2** — with two of the "passes" being probes that led
directly to the defects in §3.1/§3.2 once driven at a different point.

| # | Attack | Targets | Result | Observation |
|---|---|---|---|---|
| B1 | 5 000 structural snapshot mutations (junk/drop/inject across all 16 top-level keys, incl. `NaN`, emoji, nested nulls) | #146, #158 | **PASS** | `typed=5000 accepted=0 untyped=0`. Every mutation is caught. |
| B2 | 3 000 sends over 23 hostile event shapes, strict ∈ {False, True} | #161, #113 | **PASS** | `typed=2475 accepted=525 untyped=0`. The 525 accepted are well-formed `{"type": "GO"}`-shaped variants. |
| B3 | `guardErrorPolicy="raise"` on an `invoke.onDone` with a throwing guard and an unguarded fallback | #152 | **PASS** | Lands in `m.c` (the fallback is taken), `last_transition_ok=False`, `last_error=ValueError`. The completion is no longer lost. |
| B4 | `Receipt.denied` vs unhandled vs deferred | #153 | **PASS** | `denied(DENY)=True denied(NOPE)=False` (with `wait=True`, see §1.2). |
| B5 | `actionErrorPolicy="fail"` → status / configuration / snapshot | #145 | **PASS** | `status='stopped' states=[]`; the snapshot is *produced* with `status='stopped'` and **refused on restore** (`SnapshotCorruptError`) — the bricked-but-resumable hole is closed. |
| B6 | Root target in `on`/`always`/`after`/`onDone` × `strict_targets` ∈ {True, False} | #147 | **PASS** | 8/8 `RootTargetError`. Non-downgradable, as claimed. |
| C1 | 50× traces per engine, incl. a plain-`def` (executor) service | determinism, #116 | **PASS (but see D6-fuzz-2)** | `distinct sync=1 async=1` — each engine is *internally* deterministic. `cross_equal=False` is what §3.2 is about. |
| C2 | `PYTHONHASHSEED` ∈ {0, 1, 12345} in fresh subprocesses | determinism | **PASS** | `distinct=1`. No dict-ordering dependence. |
| C3 | 200 concurrent plain-`def` services on `service_executor`; `stop()` mid-service on 20 more | #149 | **PASS** | `completed=200/200 wall=1.5s`, the loop ticked all 20 scheduled times *while* services ran (the #149 blocking fault is genuinely gone), `stop()` mid-service raised nothing, `threads 1->1`. |
| C4 | `send_threadsafe(internal=True)` under `OverflowPolicy.RAISE`, `max_queue_size=4`, 16 threads × 60 | #150, #157 | **PASS** | `applied=960/960`, `untyped={}`, `hung_threads=0`. The bounded inbox absorbed the load without a single drop or a `QueueOverflowError` at this rate; the point is that **no untyped error escaped the call site**. |
| C5 | 500 start/send/stop cycles | leaks | **PASS** | `threads 1->1`, one residual task (the harness's own). |
| C6 | Exported API surface | #137, #138 | **PASS** | `__all__=78`, no dangling names, all 7 round-4/5 exception classes present. Dumped to `out/api_surface.json` for the next round's diff. |
| E1 | **320 random parallel machines** (2–4 regions, optional shallow/deep history), snapshot + round-trip at **every** quiescent point | #142, #143 | **PASS** | `quiescent_snapshots_ok=1920 drift=0 raised={}`. Not one `SnapshotMidStepError` at quiescence, not one byte of drift modulo `taken_at`. This is the strongest single result in the report. |
| E2 | `get_persisted_snapshot()` from inside an **entry action** | #102 | **PASS (with a caveat)** | Returns `PRODUCED (mid-step window)` — the snapshot succeeds. Assessed as **not a defect**: by the time an entry action runs the entry set is being applied and `_configuration_is_legal` is satisfied. Flagged in §6 as a contract the documentation should state explicitly. |
| E3 | history + parallel restore, then a further transition | #143 | **PASS** | `before=restored=['m.r0.s1','m.r1.t1']`; after `BACK` the restored and live machines agree exactly. |
| E4 | v1 upcast carrying a **torn** configuration | #143, #162 | **PASS** | torn → `SnapshotCorruptError`; root-only → `SnapshotCorruptError`; legal v1 → `ACCEPTED states=['m.a.x']`. Refusal is targeted, not blanket. |
| E5 | Livelock config fuzzer, 3 shapes × 2 engines, **10 s watchdog** | #144, #151 | **FAIL** | sync 3/3 settle; async **2/3 HANG**. See §3.1. |
| E6 | Hook matrix for the new dispositions | #153, #133, #134, #159 | **PASS** | `guard_denied` and `ignored` both fire, **exactly once each**, no duplicates. |
| — | 5-min chaos soak | all | see §5 | |

### 3.1 D6-fuzz-1 — `await send(..., wait=True)` never resolves and the async loop burns a core — **Blocker**

**Found by:** `f2_events.py --cases 800`, class `B2-illegal-configuration`
(6 hits in 800 cases, all on the async engine). The oracle fired on
`active=['m','m.a','m.a.a'] state_ids=[] status=running ok=True` — a compound
node with zero active children.

**How it was reduced.** The saved repro would not replay (`m3`: `LEGAL` on
both engines for the recorded `['GO','GO']`; `m4`: 0/160 across sync, async
and three settle grids; `m5`'s shrinker correctly refused to shrink a
non-reproducing baseline). Capturing the *exact* interpreter state at the
oracle instead (`out/b2_cap.json`) showed the config carried
`maxIterations: 1` and a **self-targeting `after`** on the torn node. Driving
that config with a sleep past the deadline (`m8`) did not reproduce the torn
configuration — it hung the send instead, **6/6**. The torn observation is
therefore a *transient sample of the same livelock*, taken while the loop
spun; the hang is the stable, filable form.

**Repro:** `m9_send_hang_min.py` — 8 lines of config, no timers, no
`maxIterations` dependence.

```python
CFG = {
    "id": "m", "initial": "a",
    "on": {"GO": {"target": "#m.a", "internal": True}},
    "states": {"a": {
        "initial": "a",
        "always": {"target": "#m.a.a", "guard": "g"},
        "states": {"a": {"invoke": {"id": "i", "src": "svc"}}}}},
}
# g = lambda c, e: True ; svc = lambda i, c, e: {"ok": 1}   (plain def)
```

`await it.start()`; `await asyncio.sleep(0.02)` (let the invoke finish);
`await it.send("GO", wait=True)` → **never returns.**

```
async maxIterations=1        HANG (no receipt after 5.0s)  status=running stop() ok
async maxIterations=1000     HANG (no receipt after 5.0s)  status=running stop() ok
sync  baseline               returned in 0.06s states=['m.a.a'] ok=False err=RunawayChainError
```

**Necessity ablation** (`m9`, and independently `m8` on the generated case):

| Variant | Result |
|---|---|
| baseline | **HANG** |
| `always` removed | resolved in 0.00 s |
| `invoke` removed | resolved in 0.03 s |
| `internal: false` on `GO` | **HANG** |
| no settle (invoke still running) | resolved in 0.25 s |
| `maxIterations` 1 → 1000 | **HANG** either way |
| `maxIterations=1000` on the generated case (`m8`) | **HANG** |
| self-targeting `after` removed from the generated case (`m8`) | **HANG** — the `after` is *not* the cause |

Both the `always` and the `invoke` are necessary; the deadline and the
iteration budget are irrelevant. The trigger is that the invoke has already
completed when the re-entering event arrives.

**It is a livelock, not a queue explosion.** Instrumenting
`BaseInterpreter._process_event` while the send is pending:

```
t=3s events=12191 cpu=2.80s rss=31MB qsize=1 done=False
t=6s events=23782 cpu=5.64s rss=32MB qsize=1 done=False
t=9s events=36305 cpu=8.75s rss=32MB qsize=1 done=False
```

~4 000 events/s through the loop, **~97 % of one core**, inbox pinned at a
single entry, RSS flat. The awaited future is never completed.

**The prior round's shape is the same defect.** `m12.E5` drives
D5-fuzz-1's `nested_invoke_onDone_ancestor` config through a 10 s watchdog:
`sync=ok`, `async=HANG/TIMEOUT`, with 2.03 s CPU consumed in a 3 s idle window
*before* the send is even issued. `n10_async_spin.py` reproduces the prior
round's numbers unchanged (165 196 events, 2.97 s CPU per 3 s, at 12 s). #144
fixed the chain-budget accounting on `SyncInterpreter` only.

**Severity: Blocker.** An `await send(...)` on an order path that never
returns, on a config `create_machine()` accepts without a warning, with a
pegged core as the only external symptom, and a sync engine that behaves
correctly on the same chart (so it will not be caught by a sync-engine test).

### 3.2 D6-fuzz-2 — #149 broke #116's plain-`def` service parity across `start()` — **High**

**Found by:** `m10.C1`, whose 50× determinism traces were internally
deterministic on each engine but differed *between* them:

```
sync  = (init, done.invoke.i, done.invoke.i, 'GO', 'm.c')
async = (init, done.invoke.i, done.invoke.i,        'm.b')
```

**Repro:** `m11_116_parity.py`.

```
#116 (GO,CANCEL)x10     sync={'ok':10,'cancel':0}  async={'ok':10,'cancel':0}  PARITY
start()-settles-invoke  sync=(after_start=['m.b'], after_GO=['m.c'])
                        async divergent 10/10 sample=(['m.a'], ['m.b'])
```

The prior round's `(GO, CANCEL)×10` oracle **still passes** — the divergence is
not in the steady state, it is across `start()`. The sync engine runs the
plain-`def` service inline and returns from `start()` already in `m.b`; the
async engine returns in `m.a` with the executor result still in flight, so the
very next event is evaluated against a different configuration. `m10.C1`'s
probe with an explicit settle confirms the mechanism:

```
settle=0     after_start=['m.a'] before_GO=['m.a'] after_GO=['m.b']   log=[init, done, done]
settle=0.05  after_start=['m.a'] before_GO=['m.b'] after_GO=['m.c']   log=[init, done, done, 'GO']
```

The CHANGELOG states "the entering *macrostep* awaits the result, so #116's
ordering holds". For a service invoked by the **initial** entry set it does
not. This is the #116 defect returning at a different point, and it is exactly
the class of divergence an OMS cannot carry: the same chart, the same script,
two different states depending on which engine is deployed.

**Severity: High.** Silent, deterministic, and invisible to the prior round's
regression oracle.

### 3.3 What did *not* turn out to be a defect

Recorded so the next round does not re-litigate them:

- **`maxIterations: None`** raises a bare `TypeError` from
  `models.py:1447`. `None` is not a documented value for the key; the
  documented way to disable the bound is to omit it. Not filed; noted in §6 as
  a validation gap of the lowest priority.
- **Snapshot inside an entry action succeeds** (`m12.E2`). Consistent with
  #102's window definition. Documentation gap, not a defect.
- **`configuration=None` restores from `state_ids`** (`n2`). Redundancy, not
  garbage — see §2.1.
- **`f1`'s `A3-invalid-config-accepted`** (7 hits: `unknown_logic`,
  `dangle_target`): `create_machine()` accepts a config whose `entry` names an
  unimplemented action, and fails loudly with `ImplementationMissingError` at
  runtime. That is the documented behaviour (`repros.py` labels it
  "not a defect"). `f1`'s `A1-valid-config-rejected` (430 hits) is the
  generator emitting root targets that #108/#147 now correctly reject — a
  **generator** staleness, not a library defect.

---

## 4. Defects filed this round

| ID | Severity | Title | Engine | Repro | Reproduced |
|---|---|---|---|---|---|
| **D6-fuzz-1** | **Blocker** | `await send(EV, wait=True)` never resolves and the run loop burns a core when an event re-enters a compound whose `always` descends into a child with a completed `invoke`; subsumes D5-fuzz-1's surviving async half | async only | `m9_send_hang_min.py` (8-line config); ablations `m8_send_hang.py`; prior shape `m12_persist_livelock.py::E5`, `n10_async_spin.py` | **yes — 100 %**, `maxIterations` ∈ {1, 1000}, internal and external transitions alike |
| **D6-fuzz-2** | **High** | #149's `service_executor` breaks #116 parity: a plain-`def` `invoke` in the initial entry set is complete when `start()` returns on sync, still pending on async | async vs sync | `m11_116_parity.py` | **yes — 10/10** |

**File:line for D6-fuzz-1.** The livelock is in the async run loop's
self-generated-work accounting, the async counterpart of #144's
`SyncInterpreter` fix. The sync fix lives in the shared chain-budget logic in
`base_interpreter.py`; the async engine's drain is
`interpreter.py::_run_event_loop` (the receipt is constructed at
`interpreter.py:1560`, which is never reached). The stack is not a single
frame — it is an unbounded sequence of `_process_event` calls at ~4 000/s — so
the actionable pointer is the macrostep-termination condition, not a line.

**File:line for D6-fuzz-2.** `interpreter.py` service dispatch for
non-coroutine `src` (the `service_executor` hop added by #149); the awaited
completion is not joined to the macrostep that entered the initial
configuration during `start()`.

---

## 5. Soak

`n5_soak.py --minutes 5` (reduced from 12 per §1.1):

```
soak: 5 min, cycles=42896 events=7961633 snapshots=14298 restores=14298
      chaos_raises=33675
  RSS start=28MB end=29MB max=29MB growth=0MB
  I1: OK []   I2: OK []   I3: OK []   I5: OK []   I4 (RSS bounded): OK
```

**7.96 M events and 14 298 snapshot+restore round trips, zero invariant
violations, 1 MB of RSS movement over 5 minutes.** The 33 675 `chaos_raises`
are the chaos driver's deliberately-hostile snapshots being typed-rejected —
the intended outcome, and consistent with B1's `typed=5000 untyped=0`.

This soak uses the **sync** engine, so it does not exercise D6-fuzz-1.

---

## 6. Not covered

Stated so the verdict is not read as stronger than the evidence:

1. **The async engine was not soaked.** `n5_soak.py` is sync-only. Given
   D6-fuzz-1, an async soak is the single highest-value missing run — it would
   establish whether the livelock is reachable from ordinary order-like charts
   or only from the `always`+`invoke` re-entry shape.
2. **`f1` at 1 500 cases found no non-termination.** The prior round found one
   per 233 valid configs at 4 000. A null result at 1 500 is weak evidence of
   absence, and in fact `m12.E5` shows the family is still live on async — so
   read `f1`'s silence as a coverage gap, not a clean bill.
3. **`f2`/`f3` are at 800/1 200, not 4 000/5 000.** Rates in §3 are not
   comparable to the prior round's.
4. **D6-fuzz-1's blast radius is uncharacterised.** I did not determine
   whether an `always` chain *without* an `invoke` but with another source of
   self-generated work (a `sendTo` to self, a spawned actor's `onDone`)
   reaches the same state, nor whether a parallel region can trip it.
5. **`OverflowPolicy.RAISE` never actually overflowed** in C4 (960/960
   applied, 0 raised). The attack proved *no untyped escape*, not that
   `QueueOverflowError` surfaces at the call site under genuine pressure. A
   slower consumer is needed to force the trip.
6. **`escalate` paths, `_die` under double cancel, `internal=True` forgery,
   redaction of `get_snapshot`'s DEBUG log, and executor thread-context
   leakage** were briefed for this track but not reached inside the wall-clock
   bound. The concurrency, security and observability tracks cover them
   independently.
7. **Documentation gaps, not defects:** the snapshot-inside-an-entry-action
   contract (§3.3), and `maxIterations: None`.
8. **Hypothesis was available but E1 uses a seeded `random.Random(4242)`
   generator**, not `@given`. The 320 cases are reproducible but not shrunk by
   Hypothesis.

---

## 7. Verdict

**Round 5 is a genuine, complete fix of everything this track filed against
`3ed3099` — on the sync engine. The async engine is not ready.**

The positive result is large and should be stated plainly: the entire prior
FUZZ defect list is closed, the snapshot boundary is now **fully typed** across
5 000 structural mutations and 1 200 generated cases with zero escapes, 1 920
snapshots over 320 random parallel machines round-trip byte-identically, the
root-target hole is closed non-downgradably at 8/8 combinations, `"fail"`
semantics and `Receipt.denied` and `guardErrorPolicy: "raise"` all behave
exactly as the CHANGELOG claims, the new `service_executor` carries 200
concurrent services without blocking the loop or leaking a thread, and a
5-minute chaos soak moved 8 M events with flat memory and no invariant
violation.

Against that: **`await send(..., wait=True)` can never return**, on an
eight-line chart that builds without a warning, with a fully-pegged CPU core as
the only symptom, on the engine an async OMS would actually deploy. The fix
that closed this family (#144) was applied to `SyncInterpreter` only, and the
prior round's Blocker shape still hangs the async engine unchanged. Alongside
it, the round's own new feature (#149) reopened the #116 parity defect at a
point the existing regression oracle does not probe.

**Adoption recommendation for this track: NO-GO for the async engine.** The
sync engine is in materially good shape on every contract this track tests.
`D6-fuzz-1` must be fixed and `D6-fuzz-2` resolved before an async deployment,
and the async engine needs the soak listed in §6.1 before the next verdict.
