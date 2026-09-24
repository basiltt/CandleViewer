# FUZZ — fuzzing & property-based battle test of `xstate-statemachine` @ `3ed3099`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`3ed3099`** ("Merge pull request #139 from basiltt/fix/0.8.1-round4").
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`. **`__version__` still reports
`0.8.0`; this build is identified by commit.**

**Date:** 2026-09-19. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200.
**Interpreter for every command below:**
`_ref/xstate-statemachine/.venv-main/Scripts/python`, with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Track:** FUZZ, re-run of `battle-5e07ba8/fuzz.md` plus a new attack set aimed
at this round's fixes. Scripts live under
`docs/research/xstate/battle-3ed3099/fuzz/`. No library source was modified. No
`git` command was run in the adopting project's repository. GitHub was
read-only throughout.

**Standard applied.** This library is being evaluated to run an
order-management system handling real money. Every silent failure,
nondeterminism and ordering ambiguity is treated as a defect and reproduced
before it is counted.

---

## 0. Bottom line

**Round 4 is a large, real improvement on this track. Eight of the nine prior
defects are fixed; three defects remain, one of them a Blocker.**

- **D5-fuzz-1 (Blocker) — the non-termination family is not closed, it moved.**
  The prior Blocker's *exact* shape (cross-region `always` into a sibling
  region's invoking state) no longer hangs — it now trips the per-macrostep
  budget and settles into a **legal** configuration with
  `last_transition_ok=False` and a `RunawayChainError`, which is precisely what
  #102/#112 promised. But the F1 fuzzer found the same failure mode at a new
  shape on the 4 000-case run: **two nested `invoke`s whose `onDone` both
  target their common compound ancestor**. `SyncInterpreter.start()` never
  returns; it processed **121 636 events in 5 s** with *both queues empty*, so
  this is a **livelock, not a queue explosion** — and unlike the 5e07ba8
  defect, **no value of `maxIterations` bounds it** (tested 2, 10, 1 000,
  100 000 — all hang). The async engine is **also** affected and is arguably
  worse: `start()` *returns* and the machine reports `status="running"` in the
  correct state `m.a.a`, while the run loop burns **~100 % of one core
  indefinitely** (2.95 s CPU per 3 s wall, ~29 000 events/3 s, flat at 12 s).
  On an OMS this is a silently pegged core and a stalled order path on a config
  that passes every build-time check.

- **D5-fuzz-2 (High) — `from_snapshot()` still has untyped and silent paths.**
  #110 typed most of the boundary and the *dangerous* sub-case of the old
  D-fuzz-7 is genuinely fixed, but of 19 hand-picked field mutations **5 still
  raise untyped `AttributeError`/`TypeError`** from library internals
  (`actors`, `history`, and a `status` of `["running"]`), escaping the
  documented `except XStateMachineError`. F3 confirms this at scale: 5 000
  generated cases produced **38 untyped restores** across 4 distinct frames.

- **D5-fuzz-3 (High) — `strict_targets=False` reopens the old D-fuzz-2
  verbatim.** #108 rejects a root target at build under the default, and A7
  confirms all four declaration sites are covered. Pass `strict_targets=False`
  and the *entire* runtime defect returns unchanged on **both** engines: after
  one `GO`, `current_state_ids == []`, `status == "running"`,
  `last_transition_ok == True`, `last_error == None`. It snapshots and restores
  into the same inert state and keeps accepting events forever.

- **What round 4 demonstrably fixed.** Every one of D-fuzz-3, -4, -5, -7
  (dangerous sub-case), -8 and -9 is gone, and the prior repro suite now scores
  **0/6**. The three untyped-entry-point classes are typed: `send()` raises
  `InvalidEventError` on **1 500/1 500** hostile objects with zero untyped
  escapes, and **5 000 byte-level snapshot mutations produced zero untyped
  errors**. Determinism is clean: 50× byte-identical traces on both engines
  with cross-engine equality. `#105` and `#104` both hold at 16 concurrent
  producers (640/640 and 480/480 delivered, zero drops). A snapshot at **every**
  one of 2 000 quiescent points succeeded with zero `SnapshotMidStepError` and
  zero round-trip drift. A **12-minute chaos soak** pushed 14.8 M events and
  26 657 snapshot+restore round trips with zero invariant violations and flat
  RSS.

- **The residue is the same root cause as last round.** All three surviving
  defects are the library trusting a shape it did not validate: an unvalidated
  transient/completion cycle (D5-fuzz-1), unvalidated snapshot sub-objects
  (D5-fuzz-2), and a documented opt-out that disables the *only* guard
  (D5-fuzz-3). §4 and §6 say exactly what else was covered and what was not.

---

## 1. Method

### 1.1 What was re-run, and the reductions made

The brief's hard bound is ≤ 120 s per script and ~25 min total. The prior run
used 20 000 cases per fuzzer. **Reductions, stated:**

| Script | Prior | This run | Reduction | Justification |
|---|---|---|---|---|
| `f1_machine_config.py` | 20 000 | **4 000** | 5× | Still hit a fresh A4 non-termination case (1 in 233 valid configs), so the defect density is high enough that 4 000 is decisive for *finding*; it is **not** enough to restate the prior run's 8.9 % / 14.8 % incidence rates, and this report does not. |
| `f2_events.py` | 20 000 | **4 000** | 5× | Found zero defects at 4 000 after the oracle fix. A null result at 4 000 is weaker than at 20 000 — noted in §6. |
| `f3_snapshot.py` | 20 000 | **5 000** | 4× | Found 38 untyped restores across 4 frames — sufficient to characterise D5-fuzz-2; the exact rate is not comparable to the prior run's 1 750/20 000. |
| `repros.py` | full | **full** | none | Cheap; run verbatim. |
| new `n5_soak.py` | — | **12 min** | as briefed | Per the brief's "12-min reduced run with chaos". |
| new `n3_new_attacks.py` | — | full | none | A1 at 2 000 events, A9 at 1 500 objects, A10 at 5 000 mutations, A5 at 50×2 traces — all as briefed. |

Everything else (`n1`, `n2`, `n4`, `n6`–`n10`) is new and deterministic.

### 1.2 The oracle sets had to be updated — and that matters

The prior harness's `ALLOWED_*` tuples predate this round's new exception
classes. Run unmodified against `3ed3099`, `f2_events.py` reported **87
"untyped send errors"** that were in fact the *new, correct* `InvalidEventError`
(#113) — a false-positive rate that would have inverted the verdict. The same
applied to `SnapshotCorruptError`, `SnapshotMidStepError`,
`SnapshotSerializationError` and `RootTargetError`.

`common.py` was therefore amended (this is harness, not library source) to
score the **current** contract:

```python
ALLOWED_BUILD_ERRORS   += (RootTargetError,)
ALLOWED_SEND_ERRORS    += (InvalidEventError, SnapshotMidStepError,
                           SnapshotSerializationError)
ALLOWED_RESTORE_ERRORS += (SnapshotCorruptError,)
```

After the amendment F2 reports **NO DEFECTS** on the same 4 000 cases. Every
number in this report is post-amendment. This is the single most important
methodological note in the document: *a stale oracle makes a fixed library look
broken*, and §2's "prior defect" verdicts all depend on getting it right.

### 1.3 Adapting scripts that assumed superseded behaviour

Three prior repros no longer *set up*, because the behaviour they exercised is
now rejected earlier. Each was assessed against the original defect's **intent**,
not its mechanics:

| Prior repro | What happens now | Does the new behaviour meet the intent? |
|---|---|---|
| `d2` (always → `#m`) | `create_machine()` raises `InvalidConfigError` naming the root target and suggesting `#m.a` | **Yes, at the default.** But `strict_targets=False` restores the defect in full — filed as **D5-fuzz-3**. |
| `d7` (empty-configuration snapshot) | `get_persisted_snapshot()` raises `SnapshotCorruptError("status is 'running' but the configuration is empty")` — i.e. the corrupt blob can no longer even be *produced* by the library | **Yes.** Re-probed the restore side independently (`n6`, `n7`): the fully-empty blob is typed-rejected, and a *partially* emptied one recovers the correct state from the redundant field rather than loading garbage. |
| `d10` (nested always → `#m`) | Same build-time rejection as `d2` | Same as `d2`. |

`repros.py` was left **unmodified** so its "harness error" lines remain visible
evidence of the build-time rejection; the follow-up probes live in `n6`.

A fourth adaptation: the A1 attack was written expecting `SnapshotMidStepError`
to be *possible* at quiescence and counts it as a failure if it ever fires. It
never fired in 2 000 attempts — the intent of #102 (refuse mid-step, permit
quiescent) is met exactly.

### 1.4 Two harness bugs found and corrected before filing

Both would have produced false defects; both are recorded because a reader
should know the failures in §3 survived this filter:

1. **A2** used `SimulatedClock.advance(5000)`, which does not exist, then
   `increment(5.0)` — but `increment()` takes **milliseconds**, so 5.0 ms never
   reached a 1 000 ms deadline and `restart_timers=True` looked broken.
   Corrected to `increment(5000)`; `n4_restart_timers.py` then shows #128
   behaving identically and correctly on both engines.
2. **A3/A4** originally used a two-state ping-pong machine, so an arbitrary
   interleaving of 16 concurrent producers legitimately lost bumps to
   *transition ordering*, not delivery — 625/640 and 465/480. Replaced with an
   order-independent self-looping counter (`COUNTER`), where every event is
   handled from every state; both then score a clean 640/640 and 480/480. A
   concurrency oracle must measure delivery, not ordering luck.

### 1.5 The anti-hang instrument

`spin_oracle.py` is retained unchanged: a budgeted `_select_transitions` that
raises a sentinel after 20 000 selections, monkey-patched **in the fuzzer's
process only**. It is what makes an A4 non-termination oracle affordable. Its
continued necessity is itself evidence for D5-fuzz-1.

### 1.6 Exact commands

```bash
cd docs/research/xstate/battle-3ed3099/fuzz
PY="_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1

$PY -u repros.py                          # prior suite -> 0/6 reproduce
$PY -u f1_machine_config.py --cases 4000
$PY -u f2_events.py         --cases 4000
$PY -u f3_snapshot.py       --cases 5000

$PY -u n1_a4_probe.py        # F1's A4 case hangs in wall clock
$PY -u n1c.py                # shape ablation
$PY -u n1e.py                # livelock: 75k events, both queues empty
$PY -u n1_repro.py           # D5-fuzz-1, sync + async + maxIterations sweep
$PY -u n2_restore_untyped.py # D5-fuzz-2, field-level
$PY -u n3_new_attacks.py     # A1-A14, the new attack set
$PY -u n4_restart_timers.py  # #128 both engines
$PY -u n6_prior_defects.py   # prior-defect status sweep
$PY -u n7_silent_restore.py  # does a silent restore land on the wrong state?
$PY -u n8_strict_targets_root.py  # D5-fuzz-3
$PY -u n9_livelock_scope.py  # maxIterations sweep + shape ablation
$PY -u n10_async_spin.py     # async CPU burn
$PY -u n5_soak.py --minutes 12
```

---

## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

`repros.py` verbatim: **0 of 6 runnable repros reproduce**. Three more could
not set up because the config is now rejected at build. Full status, with the
follow-up probe that established each verdict:

| ID | Prior severity | Verdict | Evidence |
|---|---|---|---|
| **D-fuzz-1** `start()` non-terminating, unbounded inbox | Blocker | **CHANGED — not fixed** | The prior shape now settles legally (`n6`: `states=['m.A.a1','m.B.b1']`, `last_transition_ok=False`, `last_error=RunawayChainError`) — #102/#112 work as advertised. But F1 found the family alive at a new shape, with a *worse* profile: a livelock no `maxIterations` bounds, on **both** engines. Refiled as **D5-fuzz-1**. |
| **D-fuzz-2** `always` → machine root empties the configuration | High | **CHANGED — fixed at the default, reopened by an opt-out** | `create_machine()` now raises `InvalidConfigError` for root targets in `on`/`always`/`after`/`onDone` (A7: 4/4 typed). With `strict_targets=False` the runtime defect is byte-for-byte the prior one on both engines (`n8`). Refiled as **D5-fuzz-3**. |
| **D-fuzz-3** `send()` to a stopped sync machine is silent | Medium | **FIXED** | `repros.py`: `sync hooks=([],[],[('GO','not_running')])`, `async hooks=([],[],[('GO','not_running')])` — exact parity (#123). |
| **D-fuzz-4** dict event with non-`str` `type` → bare error | High | **FIXED** | All 4 strict×payload combos now raise typed `InvalidEventError` (#113). A9 extends this: 1 500 hostile objects, **0 untyped**. |
| **D-fuzz-5** non-event objects → bare `TypeError` | Medium | **FIXED** | All 5 object types → typed `InvalidEventError`. |
| **D-fuzz-6** `from_snapshot()` → bare `KeyError`/`AttributeError`/`TypeError` | High | **CHANGED — partially fixed** | 6 of 8 prior mutations now typed `SnapshotCorruptError`; **`history={'m': null}` and `actors={'a': null}` still raise untyped `TypeError`/`AttributeError`**. Widened in `n2`/`n6` and refiled as **D5-fuzz-2**. |
| **D-fuzz-7** `from_snapshot()` loads garbage silently | High | **FIXED (dangerous sub-case) / CHANGED (residue)** | The empty-configuration blob can no longer be *produced* (`get_persisted_snapshot()` raises `SnapshotCorruptError`) nor loaded (`configuration=[]` **and** `state_ids=[]` → typed). `status` of `5`/`None`/`"banana"` and `context` of `42`/`None`/`"str"` are all typed now. Residue: a *partially* emptied blob still loads — but `n7` shows it recovers the **correct** state (`m.b`) from the redundant field, so it is no longer *garbage*, and `status=["running"]` is untyped, folded into D5-fuzz-2. |
| **D-fuzz-8** self-referential config → `RecursionError` | Low | **FIXED** | Typed `InvalidConfigError` (#136). |
| **D-fuzz-9** settle trip leaves a non-tree configuration | High | **FIXED** | `n6` on the exact prior shape: `orphans (active node with inactive parent): []`, and the trip is now observable (`last_transition_ok=False`, `last_error=RunawayChainError`) exactly as #112 claims. |

**Score: 6 fixed, 3 changed (of which 2 carry a live defect forward and 1 is a
genuine fix with an opt-out hole).**

---

## 3. New attacks

`n3_new_attacks.py` — 15 assertions, **14 PASS / 1 FAIL**. Plus `n4`–`n10`.

| # | Attack | Targets | Result | Observation |
|---|---|---|---|---|
| A1 | Snapshot at **every** quiescent point of a 2 000-event run; 5 % round-tripped | #102 | **PASS** | `midstep_raises=0 roundtrip_drift=0` — `SnapshotMidStepError` never fires at quiescence, and every round-trip is stable modulo `taken_at`. |
| A2 | `restart_timers=` / `has_dormant_timers` with `SimulatedClock`, sync engine | #128, #117 | **PASS** | no-restart → `has_dormant_timers=True`, `+5 s` leaves `m.a`; `restart_timers=True` → `False`, `+5 s` reaches `m.b`. |
| A2′ | Same, both engines side by side (`n4`) | #128 | **PASS** | sync and async agree exactly; a fresh sync control confirms the baseline. |
| A3 | 16 concurrent producers × 40 sends, `maxIterations=50` | #105 | **PASS** | `context.n=640/640`, **0 dropped** — an external producer is no longer charged to the chain budget. |
| A4 | `OverflowPolicy.BLOCK`, 16 producers × 30 sends, `max_queue_size=8` | #104 | **PASS** | `applied=480/480`, 0 dropped, no deadlock, 0.1 s. |
| A5 | 50× traces on each engine, compared byte-for-byte and cross-engine | determinism | **PASS** | `distinct sync=1 async=1 cross_engine_equal=True`. |
| A6 | `(GO, CANCEL)×10` against a plain-`def` inline service | #116 | **PASS** | `sync={'ok':10,'cancel':0}` == `async={'ok':10,'cancel':0}` — the exact prior divergence, now identical. |
| A7 | Root target in `on` / `always` / `after` / `onDone` | #108 | **PASS** | 4/4 `InvalidConfigError` at build. (See D5-fuzz-3 for the opt-out.) |
| A8a | `done.invoke` payload from a child with both `output` and a secret context | #109 | **PASS** | both engines deliver `{'result': 42}`; `secret_leak=False`. |
| A8b | `escalate` from an invoked child → parent `onError` | #130 | **PASS** | parent reaches `d`, receives an `ErrorEvent`. |
| A9 | 1 500 sends over 21 hostile event types (`None`, `bytes`, `object()`, `{'type': []}`, 20 kB str, …) | #113 | **PASS** | **0 untyped escapes.** |
| A10 | 5 000 byte-level mutations of a real snapshot (flip/delete/insert, 1–3 per case) | #110 | **PASS** | `typed=3937 accepted=1063 untyped=0`. The 1 063 "accepted" are mutations that landed in cosmetic fields and still parse — not a defect. |
| A11 | `async def` hook on the sync engine; `on_plugin_error` / `last_plugin_error` | #127 | **PASS** | `on_plugin_error` fires with `('on_transition', 'TypeError')`; `last_plugin_error` populated. |
| A12 | `LoggingInspector` against 9 sensitive context keys | #126 | **PASS** | `leaked=[]` — `password`, `api_key`, `token`, `secret`, `authorization`, `ssn`, `card_number`, `private_key`, `client_secret` all `'***'` in 2 604 bytes of DEBUG log. |
| A13 | Exported provenance API + marker through `deepcopy`/`pickle` | #137, #138 | **PASS** | all 9 names present **and in `__all__`**; `is_system_event` True for original, deepcopy and pickle round-trip. |
| A14a | Non-JSON data on a pending event | #131 | **PASS** | typed `SnapshotSerializationError`. |
| A14b | Non-JSON value in **context** | — | **FAIL** | See §3.4 — assessed as **not a defect**, but worth stating. |
| — | 12-min soak with chaos (`n5`) | all | see §5 | |

### 3.1 D5-fuzz-1 — nested `invoke`s whose `onDone` targets their common ancestor livelock **both** engines; `maxIterations` does not bound it — **Blocker**

**Found by:** `f1_machine_config.py --cases 4000`, class `A4-start-does-not-terminate`,
1 hit in 233 valid configs. Shrunk by hand (`n1c.py`) from a 4-level generated
chart to 7 lines.

**Repro:** `n1_repro.py`, `n9_livelock_scope.py`, `n10_async_spin.py`.

```python
CFG = {"id": "m", "initial": "a", "states": {"a": {
    "initial": "a",
    "invoke": {"id": "i1", "src": "svc_ok", "onDone": {"target": "#m.a"}},
    "states": {"a": {
        "invoke": {"id": "i2", "src": "svc_ok", "onDone": {"target": "#m.a"}}}}}}}
```

Both services are trivial (`lambda i, c, e: {"ok": 1}`). `create_machine()`
accepts it without a warning.

**Sync engine — `start()` never returns:**

```
maxIterations=None    hang=True events_processed= 83326 inbox=0 internal=2
maxIterations=2       hang=True events_processed=118350 inbox=0 internal=0
maxIterations=10      hang=True events_processed=121636 inbox=0 internal=0
maxIterations=1000    hang=True events_processed=119012 inbox=0 internal=0
maxIterations=100000  hang=True events_processed= 99466 inbox=0 internal=0
```

`inbox=0 internal=0` while ~120 000 events pass through `_process_event` in 5 s
is the signature of a **livelock, not a queue explosion**: RSS is flat at 43 MB.
That distinguishes it from the 5e07ba8 D-fuzz-1, whose inbox grew to 125 000
entries and 97 MB. It is also why `maxIterations` cannot help — the budget is
per chain and **resets whenever a macrostep leaves both queues no longer than it
found them**, which this cycle does on every iteration.

**Stack at the 4 s mark** (`n1d_stack.py`):

```
sync_interpreter.py:339   start -> self._process_event_queue()
sync_interpreter.py:784   _process_event_queue -> self._drive(self._process_event(...))
base_interpreter.py:2023  _process_event -> transitions = self._select_transitions(event)
base_interpreter.py:4139  _select_transitions -> max(eligible, key=lambda t: t.source.depth)
```

**Event census during the hang** (`n1e.py`) — the two completions feed each
other forever, in lockstep:

```
{'done.invoke.i1': 74478, 'done.invoke.i2': 74478}  inbox 0  internal 0
```

`#94` guarantees completions are "never discarded" and are exempted from the
trip; that guarantee is exactly what makes this cycle unbreakable, because
every event in it *is* a completion.

**Async engine — worse, because it looks healthy** (`n10_async_spin.py`):

```
start() returned; states=['m.a.a']
t= 3s events_total= 27948 delta=27948 cpu_delta=2.92s rss=43MB status=running
t= 6s events_total= 55494 delta=27546 cpu_delta=2.95s rss=43MB status=running
t= 9s events_total= 84225 delta=28731 cpu_delta=2.95s rss=43MB status=running
t=12s events_total=113348 delta=29123 cpu_delta=2.97s rss=43MB status=running
```

`start()` returns, the configuration is the correct `m.a.a`, `status` is
`running`, and there is **no error surface at all** — while one core runs at
~99 % forever. A health check, a `last_transition_ok` probe, and the CV-F08
post-transition legality assertion all pass. Nothing short of CPU monitoring
detects this.

**Shape ablation** (`n9`) — the cycle requires *both* nested invokes pointing at
the shared ancestor:

| Shape | Hangs? |
|---|---|
| outer `invoke` only, `onDone` → `#m.a` | no (3 531 events, settles) |
| inner `invoke` only, `onDone` → `#m.a` | no (7 510 events, settles) |
| both, but inner `onDone` → its **own** state `#m.a.a` | no (2 267 events) |
| both, `onDone` → `#m.a` (above) | **yes** |
| 3-deep nest, all three `onDone` → `#m.a` | **yes** (91 593 events, `internal=12480` — this variant *also* grows a queue) |

**Root cause.** Re-entering `#m.a` exits and re-enters the compound ancestor,
which re-arms *both* invokes; both are inline-completing services, so both mint
a `done.invoke` in the same macrostep; each completion re-enters `#m.a` again.
The chain budget at `sync_interpreter.py:802-807` resets `generated`/`tripped`
whenever a macrostep does not grow the queues — and this cycle consumes exactly
as many events as it produces, so it resets the budget on **every** iteration
and never reaches `limit`. `validation.py`'s `_is_dead_always_loop` requires
`target is t.source` and is structurally blind to an `onDone` that targets an
*ancestor*. The same reset logic was cited in the 5e07ba8 triage as D-fuzz-1's
mechanism; round 4 fixed the shapes that grew a queue, and left the shape that
does not.

**Location.** `sync_interpreter.py:802-807` (the queue-neutral budget reset), `:784`
(`_process_event_queue` drive loop), `base_interpreter.py:2023` /
`:4139` (`_select_transitions`), `validation.py:132-151`
(`_is_dead_always_loop`, blind to ancestor targets).

**Why Blocker.** Non-termination on `start()` with no timeout, no interrupt and
no `maxIterations` that helps, on a config that passes every build-time check —
plus a silent 100 % CPU burn on the async engine that reports healthy. This is
the register's money-loss bar directly: a stuck or starved order-placement path.

### 3.2 D5-fuzz-2 — `from_snapshot()` still raises untyped errors on `actors`, `history` and a list `status` — **High**

**Repro:** `n2_restore_untyped.py`, `n6_prior_defects.py`; at scale
`f3_snapshot.py --cases 5000`.

Of 19 field-level mutations of a **real** snapshot: 9 typed, 5 loaded, **5
untyped**.

```
status=['running']   -> UNTYPED TypeError: unhashable type: 'list'
actors={'a': None}   -> UNTYPED AttributeError: 'NoneType' object has no attribute 'get'
actors=7             -> UNTYPED AttributeError: 'int' object has no attribute 'items'
history='junk'       -> UNTYPED AttributeError: 'str' object has no attribute 'items'
history={'m': None}  -> UNTYPED TypeError: 'NoneType' object is not iterable
```

F3 at 5 000 cases independently reaches the same four frames:

| Frame | Hits |
|---|---|
| `base_interpreter.py:1495` (`from_snapshot`) `AttributeError: 'NoneType' object has no attribute 'get'` | 11 |
| `base_interpreter.py:1481` `AttributeError: 'str' object has no attribute 'items'` | 7 |
| `events.py:369` (`restore_event`) `AttributeError: 'NoneType' object has no attribute 'startswith'` | 6 |
| `base_interpreter.py:1466` `TypeError: 'NoneType' object is not iterable` | 6 |
| `base_interpreter.py:1493` `AttributeError: 'int' object has no attribute 'items'` | 5 |
| `base_interpreter.py:1484` `TypeError: 'NoneType' object is not iterable` | 2 |

**Root cause.** #110 added a shape check for the top-level scalar fields
(`status`, `context`, `configuration`, `state_ids`) and for the event records,
but `_actor_snapshots`/`actors` and `history` are still walked with bare
`.items()` / `.get()` / iteration and no type guard; the `status` check uses set
membership, which raises before it can reject an unhashable value.

**Location.** `base_interpreter.py:1466`, `:1481`, `:1484`, `:1493`, `:1495`;
`events.py:369`.

**Why High, not Blocker.** A snapshot arrives from Redis/disk/a queue and is
untrusted by construction — that is #45's own stated premise — and
`from_snapshot`'s docstring tells callers to catch `XStateMachineError`. But the
process crashes *loudly*, so an OMS can fail-fast rather than proceed on bad
state. It is an uncatchable-boundary bug, not silent corruption.

**Note on severity movement:** this is a genuine improvement over D-fuzz-6 —
6 of the prior 8 mutations are now typed, and the byte-level fuzzer
(A10, 5 000 mutations) finds **zero** untyped errors. The residue is entirely
in *structurally valid JSON with wrong types in sub-objects*, which byte-level
mutation rarely produces but a schema-drifting producer absolutely will.

### 3.3 D5-fuzz-3 — `strict_targets=False` reopens the root-target configuration-emptying defect on both engines — **High**

**Repro:** `n8_strict_targets_root.py`.

```python
CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "#m"}}, "b": {}}}
m = create_machine(CFG, logic=L(), strict_targets=False)   # accepted
```

```
sync, strict_targets=False:
  before GO: ['m.a']
  after  GO: states=[] status=running last_transition_ok=True last_error=None
  snapshot: configuration=['m'] state_ids=[] status=running
  restored: states=[] status=running
  further send accepted; states=[] status=running
async, strict_targets=False:
  after GO: states=[] status=running last_transition_ok=True last_error=None
```

This is the 5e07ba8 D-fuzz-2 unchanged: an empty active configuration, a machine
that reports `running` with `last_transition_ok=True` and `last_error=None`, and
which accepts events forever without ever transitioning again. It **snapshots
and restores into the same inert state** — and note that the snapshot here is
*not* refused, because `configuration=['m']` is non-empty even though
`state_ids=[]`, so #110's "status is running but the configuration is empty"
guard does not fire.

**Root cause.** #108's root-target rejection lives in `validation.py`, which
`strict_targets=False` skips wholesale. The flag's documented purpose is to
tolerate *unresolvable* targets at build and surface them at runtime (that is
#31's contract, and it works: a dangling target yields
`StateNotFoundError` on the receipt with `last_transition_ok=False`). A root
target is different in kind — it resolves perfectly well, to a node that cannot
be a leaf — so it slips through the runtime surface too and produces no error
at all.

**Location.** `validation.py:293` (rejection, skipped when
`strict_targets=False`); the runtime path leaves no error surface in either
engine.

**Why High.** It requires an explicit opt-out, so it is not the default path —
but `strict_targets=False` is a *documented, legitimate* setting a team may
adopt for unrelated reasons (late-bound targets), and adopting it silently
re-arms a silent-corruption bug with no runtime signal. It is the register's
"silent state corruption" shape, gated behind a flag.

### 3.4 A14b — non-JSON context passes through `get_persisted_snapshot()` — **not filed**

`get_persisted_snapshot()` returns a dict containing the raw `object()`;
`json.dumps()` on it then fails in the *caller's* code with a plain `TypeError`.

**Assessed as not a defect.** #131 is explicitly scoped to *pending event data*,
and A14a confirms that path raises `SnapshotSerializationError` correctly. The
method returns a **dict**, not a string, so it never claims to have produced
JSON; serialising is the caller's step. Recorded here only because the asymmetry
is surprising — pending-event payloads are validated, context values are not —
and a team assuming "the library validates JSON-ability" would be wrong. A
project-side guard belongs in the adoption gate, not in the defect register.

---

## 4. Not filed — checked and found sound

Stated so the verdict's scope is legible:

- **Every prior untyped-entry-point class.** `send()` (D-fuzz-4/-5) across
  1 500 hostile objects: 0 untyped. `create_machine()` (D-fuzz-8): typed.
  `from_snapshot()` under 5 000 byte-level mutations: 0 untyped.
- **Engine parity on the paths this round touched.** `send()` to a stopped
  machine (#123), the inline sync service completion point (#116), `#109`
  output delivery, `#128` timer re-arm, and D5-fuzz-3's failure mode are all
  *identical* on both engines. The only parity gap found is D5-fuzz-1's
  *surface* (hang vs. silent CPU burn) — the underlying livelock is shared.
- **Determinism.** 100 traces (50 per engine) collapse to one string each and
  the two strings are equal. No ordering nondeterminism was observed anywhere,
  including under the 16-producer concurrency attacks.
- **The settle-trip is observable and leaves a legal configuration.** The exact
  D-fuzz-9 shape now reports `last_transition_ok=False` with a
  `RunawayChainError` and zero orphan nodes. #112 is satisfied.
- **`SnapshotMidStepError` does not over-fire.** 2 000 quiescent snapshots, 0
  raises. The concern that #102 might make routine persistence flaky is not
  borne out.
- **Redaction and the exported API.** No secret leaked into 2 604 bytes of DEBUG
  logging; all 9 provenance/exception names are present *and* in `__all__`; the
  engine marker survives `deepcopy` and `pickle`.
- **F2 found nothing at 4 000 cases** once the oracle was corrected — no
  illegal configuration, no incoherent `status`/`last_error`, no accepted event
  without a hook, across the full policy matrix.

---

## 5. Soak

`n5_soak.py --minutes 12`. A `SyncInterpreter` on an OMS-shaped chart
(`idle → pending → working`, with an `invoke`, an `after` and a cancel path)
under continuous mixed load: 200 events per cycle from a hostile alphabet (8 %
of sends are non-`str`/malformed objects), a snapshot **and full
restore-replacing-the-live-machine** every 3rd cycle, and a `Chaos` plugin that
raises from `on_transition` 2 % of the time.

Invariants checked every cycle: I1 no untyped exception escapes any public call;
I2 the active configuration is a legal tree; I3 `status` stays in the documented
set; I4 RSS bounded; I5 a quiescent snapshot never raises
`SnapshotMidStepError`.

**Result — clean on all five invariants** (`out/soak12.txt`, exit 0):

```
soak: 12 min, cycles=79971 events=14843978 snapshots=26657 restores=26657
      chaos_raises=63054
  RSS start=28MB end=28MB max=29MB growth=-1MB
  I1: OK []   I2: OK []   I3: OK []   I5: OK []
  I4 (RSS bounded): OK
```

**14.8 million events, 26 657 snapshot+restore round trips and 63 054 contained
plugin failures**, with zero untyped exceptions, zero illegal configurations,
zero undocumented `status` values, zero spurious `SnapshotMidStepError`, and RSS
flat at 28 MB (net −1 MB after GC). This is the strongest single result in the
re-run: the persistence and plugin-containment work holds under sustained,
hostile, restore-heavy load. Note the scope limit in §6.7 — one chart shape, so
it would not surface D5-fuzz-1.

---

## 6. What this track covered — and what it did not

**Covered.** All three prior fuzzers re-run at reduced scale against corrected
oracles; all nine prior defects individually re-probed; 15 new attacks against
the round-4 fixes spanning persistence (#102, #107, #110, #117, #118, #128,
#131), concurrency (#104, #105), determinism and engine parity (#116),
semantics (#108, #109, #130), typed errors (#113), observability (#126, #127),
and the exported API surface (#137, #138); a 12-minute chaos soak.

**Not covered — and the reader should discount accordingly:**

1. **Scale.** 4 000/4 000/5 000 cases instead of 20 000 each, per the time
   bound. Null results (notably F2's) are correspondingly weaker, and **no
   incidence rate from this run is comparable to the prior document's.** The
   8.9 % and 14.8 % figures in `battle-5e07ba8/fuzz.md` are *not* restated
   here because 4 000 cases cannot establish them.
2. **D5-fuzz-1's true prevalence is unknown.** 1 hit in 233 valid configs is a
   finding, not a rate. Whether the catalogue's B1–B20 charts contain the
   triggering shape (nested invokes with an `onDone` targeting a shared
   ancestor) was **not** checked — that is the single most important follow-up.
3. **`on_resolve_error` (#134) was not exercised.** A11 registers the hook but
   no attack drove a resolve failure into it; the hook matrix is therefore
   incomplete for that one class. `on_plugin_error` (#127) *was* driven.
4. **#133 (`sendTo` with no live target →
   `on_event_dropped("unresolved_target")`) and #106/#125 (`Receipt.deferred`
   bookkeeping) were not attacked.** They are in the round-4 set and this track
   did not reach them.
5. **Child actors and `spawnChild` were only lightly touched** (A8's invoked
   child machines). The brief's "#105 per-task gate under create_task/threads/
   child actors" was covered for asyncio tasks (A3) but **not** for OS threads
   or spawned child actors.
6. **`SyncInterpreter` under real OS-thread concurrency** was not fuzzed;
   `WrongThreadError` paths are untested here.
7. **The 12-min soak uses one chart shape.** It would not surface a
   config-shape-dependent defect such as D5-fuzz-1.
8. **No fault injection below the library** (clock skew, `MemoryError`,
   interpreter shutdown mid-snapshot).

---

## 7. Defects filed

| ID | Severity | Title | Repro | Primary location |
|---|---|---|---|---|
| **D5-fuzz-1** | **Blocker** | Nested `invoke`s whose `onDone` targets their common compound ancestor livelock `start()` on the sync engine and burn 100 % CPU indefinitely on the async engine; no `maxIterations` bounds it | `fuzz/n1_repro.py`, `fuzz/n9_livelock_scope.py`, `fuzz/n10_async_spin.py` | `sync_interpreter.py:802-807`, `:784`; `base_interpreter.py:2023`, `:4139`; `validation.py:132-151` |
| **D5-fuzz-2** | **High** | `from_snapshot()` raises untyped `AttributeError`/`TypeError` for junk in `actors`/`history` and for a non-hashable `status`, escaping the documented `except XStateMachineError` | `fuzz/n2_restore_untyped.py`, `fuzz/n6_prior_defects.py`, `fuzz/f3_snapshot.py --cases 5000` | `base_interpreter.py:1466`, `:1481`, `:1484`, `:1493`, `:1495`; `events.py:369` |
| **D5-fuzz-3** | **High** | `strict_targets=False` reopens the root-target defect verbatim: configuration silently emptied, `status="running"`, `last_transition_ok=True`, `last_error=None`, on both engines; survives snapshot/restore | `fuzz/n8_strict_targets_root.py` | `validation.py:293` (skipped); no runtime error surface on either engine |

---

## 8. Verdict

**Round 4 substantially hardened this library against the FUZZ track. Six of
nine prior defects are fixed outright, the three public entry points are now
typed, determinism and engine parity are clean, and 14 of 15 new attacks aimed
directly at the round-4 fixes pass.** The quality of the persistence work in
particular (#102, #110, #128) is evident: 2 000 quiescent snapshots with zero
false refusals and zero drift, and 5 000 byte-level mutations with zero untyped
errors.

**The track nevertheless does not clear the adoption gate, on one Blocker.**
D5-fuzz-1 is the prior Blocker's family, not a new one, and its new form is
harder to defend against than the old: it is a livelock rather than a memory
explosion, so `maxIterations` cannot bound it and RSS monitoring will not see
it; it affects **both** engines; and on the async engine it presents as a fully
healthy machine — correct configuration, `status="running"`, no error — while
pegging a core forever. Every mitigation the prior round's register prescribed
(CV-F08 post-transition legality assertion, health checks, watchdogs on
`status`) passes cleanly while the defect is active.

For an order-management system the two operative facts are: (a) a config that
passes every build-time check the library has can still make `start()` never
return, and (b) the async engine gives no signal at all. Adoption should be
gated on D5-fuzz-1 being fixed at the *validation* layer — `_is_dead_always_loop`
extended to ancestor-targeting completion cycles — rather than on a budget,
since this defect demonstrates that a chain budget which resets on
queue-neutral macrosteps is not a backstop. D5-fuzz-3 should be fixed by moving
the root-target check out of the `strict_targets` opt-out, and D5-fuzz-2 by
extending #110's shape validation to `actors` and `history`.

---

## 9. Artefacts

All under `docs/research/xstate/battle-3ed3099/fuzz/`:

| File | What it is |
|---|---|
| `common.py` | Shared oracles — **amended** for this round's new exception classes (§1.2) |
| `f1_machine_config.py`, `f2_events.py`, `f3_snapshot.py`, `gen_config.py` | The three fuzzers, re-run at reduced scale |
| `repros.py` | Prior defect suite, unmodified — scores 0/6 |
| `spin_oracle.py`, `shrink_spin.py`, `shrink_hang.py` | Anti-hang instrument and shrinkers |
| `n1_a4_probe.py`, `n1c.py`, `n1d_stack.py`, `n1e.py`, `n1_repro.py`, `a4.json` | D5-fuzz-1 discovery → shrink → stack → event census → full repro |
| `n2_restore_untyped.py` | D5-fuzz-2, field-level |
| `n3_new_attacks.py` | The A1–A14 attack set (14/15 pass) |
| `n4_restart_timers.py` | #128 on both engines |
| `n5_soak.py`, `out/soak12.txt` | 12-minute chaos soak |
| `n6_prior_defects.py` | Prior-defect status sweep |
| `n7_silent_restore.py` | Does a silently-accepted restore land on the wrong state? (No.) |
| `n8_strict_targets_root.py` | D5-fuzz-3 |
| `n9_livelock_scope.py`, `n10_async_spin.py` | D5-fuzz-1 `maxIterations` sweep, shape ablation, async CPU burn |
