# Battle track: SEMANTICS @ `f28719c`

**Library:** `_ref/xstate-statemachine` @ `f28719c` (merge of #202; unreleased
0.8.1, `__version__` still reports 0.8.0 — keyed on the commit).
**Scope:** round-9 re-verification of every round-8 semantics defect, a full
re-run of the prior suite on **both service lanes**, plus new attacks aimed at
this round's machinery: the provenance-carrying priority lane (#192), the
engine-held def-service handoff (#193), per-child `children_timeout` (#194),
the private engine event subclasses (#195), eventless-only `always` selection
(#196), versioned-payload both-fields (#198), `on_interpreter_start` in the
in-flight window (#199), the task-keyed owed ledger (#200) and lap parity
(#201).
**Scripts:** `battle-f28719c/semantics/{p_persistence,c_concurrency,f_fuzz}.py`
(new, standalone), `rerun/` (prior suite + `runall.py` driver), repro under
`repro/`, machine-readable results under `results/`.

Financial-OMS standard applied throughout: nothing is counted as a defect
without a standalone repro that reproduces on a clean interpreter, and every
service-bearing check runs with **both `def` and `async def`** services.

---

## 1. Prior-defect table (round 8 → round 9)

### 1a. Method

Two passes over the prior suite (`battle-6db65d8/semantics/`), driven by
`rerun/runall.py`:

1. **Unmodified** — every script run as-is (`def` services).
2. **Coroutine lane** — every script re-run under `asyncify.py`, which patches
   `MachineLogic.__init__` so every plain-`def` *service* becomes an `async def`
   wrapper around the original.

Each prior-suite failure was then re-examined by hand against the #192–#201
changelog to separate a genuine regression from a **stale assertion** (an
attack whose pass criterion encoded the *old*, defective behaviour) or a
**harness artefact**.

### 1b. Round-8 canonical defect

| Prior | Title | R8 severity | **R9 status** | Evidence |
|---|---|---|---|---|
| **D8-semantics-1** | An EXTERNAL `send(priority=True)` is still shed as `chain_budget` when an unrelated self-generated chain trips — provenance honoured at the charge site, ignored at the shed site | Medium | **FIXED** | `c_concurrency::C1` — **10,000** external priority sends per kind at ~14k/s during a live self-generated invoke chain: `EXTERNAL_shed_as_chain_budget = 0` and `actions_fired == sent` on **both** `def` and `async def`. The round-8 repro `battle-6db65d8/semantics/repro/d8_s1_priority_shed.py` now exits **0**, 3/3 runs, `external_LOST: 0` on both kinds. Fix is at `interpreter.py:1675` — the shed predicate is now `self._raise_depth > limit and self_generated`, with provenance carried on the lane **item** (`interpreter.py:355`, `:2478`) rather than inferred from FIFO position. |

**Every round-7 defect (R7-01 … R7-16) closed at 6db65d8 remains closed** — see
§1c; no prior-suite attack regressed.

### 1c. Prior-suite whole-run

| Suite | `def` lane | `async def` lane | Note |
|---|---|---|---|
| `n1_persistence` | 6/6 PASS | 6/6 PASS | — |
| `n2_concurrency` | 7/7 PASS | 5/7 | 2 **transform artefacts** (N2-01, N2-07 assert *executor offloading*, inapplicable once the service is a coroutine) |
| `n3_semantics` | 7/7 PASS | 7/7 PASS | — |
| `n4_determinism` | 5/5 PASS | 4/5 | 1 **transform artefact** (N4-03 asserts the async trace equals the *executor-backed* sync trace) |
| `n5_fuzz_obs_sec` | 7/7 PASS | 7/7 PASS | — |
| `n7_chain_owed` | 3/4 | 3/4 | 1 **stale assertion** — see below |
| `n8_persist_sem_sec` | 6/6 PASS | 6/6 PASS | — |
| `na_determinism_obs` | 0/2 | 0/2 | 2 **harness artefacts** — see below |
| `nb_observability` | 4/4 PASS | 4/4 PASS | — |
| `s1_persistence_hooks` | 2/2 PASS | 2/2 PASS | — |
| `s2_concurrency_obs` | 5/5 PASS | 4/5 | 1 **transform artefact** (S2-03 asserts `pool_size=8` beats `pool_size=1`) |
| `s4_semantics_det_sec` | 6/6 PASS | 6/6 PASS | — |
| `n9_livelock_determinism`, `s3_fuzz_livelock` | TIMEOUT @115 s | TIMEOUT @115 s | exceed this task's per-script bound at their original parameters; **superseded** by `f_fuzz::F1` (500 configs × 2 kinds × 2 engines, re-implemented within bounds) |

**Prior-suite verdict: no regressions on either lane.** Every delta is
accounted for:

- **`n7::A2` — stale assertion.** Its criterion is `chain_budget_drops == 0`
  counting **all** drops by reason only. On f28719c the external loss is
  **zero** (`actions_fired == sent == 2000` on both kinds); the single
  remaining drop is `done.invoke.pp.b` — a *self-generated* completion being
  cut, which is #192 working exactly as designed. Re-running the same scenario
  with a **type-aware** count (`c_concurrency::C1`, 5× the volume) passes.
- **`na::D1` / `na::D2` — harness artefacts.** Both use a fixed `asyncio.sleep(0.25)`
  as the cutoff before harvesting the trace. That window is shorter than the
  22-lap chain takes on this machine, so runs are sampled mid-chain and the
  *trace lengths* differ while the semantics do not. The reported trip laps
  already agreed (`22 / 22 / 22`, `def_vs_asyncdef_agree: true`,
  `sync_vs_async_engine_agree: true`). Re-run with a 1.0 s cutoff:
  **1 distinct trace per lane, 22 laps, `RunawayChainError` on every run**, for
  both kinds. Not a library defect.
- **4 transform artefacts** (N2-01, N2-07, N4-03, S2-03) — all assert executor
  offloading, which an `async def` service correctly never performs.

---

## 2. New attacks on this round's machinery

| ID | Attack | Result |
|---|---|---|
| `P1` | `restore_event` provenance: `"engine": true` -> engine-minted, absent -> public class, `"engine": "true"` (truthy **string**) -> must NOT be trusted | **PASS** -- flag compared with `is True` (`events.py:414`); a truthy string does not launder |
| `P2` | Forged pending record under `strict` and under `onUnhandled:"error"` | **FAIL -> D9-semantics-2** -- `onUnhandled` is honoured; `strict` is inert on the restore path |
| `P3` | v0/v1/v2 x {both fields, `state_ids`-only, either field emptied, contradictory} restore matrix (#198/#186) | **PASS** -- 8/8 cells correct: v0 `state_ids`-only accepted; **every** v1/v2 blob with a missing *or emptied* field is `SnapshotCorruptError`; contradictory pair refused |
| `P4` | `get_persisted_snapshot()` from inside `on_interpreter_start` (#199), both engines | **PASS** -- `SnapshotMidStepError` on **both**; #182's in-flight guard is up before the hook |
| `C1` | External priority producer **10,000 sends/kind at ~14k/s** during a live self-generated invoke chain, both kinds | **PASS** -- **0** external shed as `chain_budget`; all 10,000 actions fired; only self-generated completions are cut |
| `C2` | An **action-issued** `send(priority=True)` must be *charged* and trip (#192), both kinds | **PASS** -- both lanes trip `chain_budget` and stay bounded (laps far below 400) |
| `C3` | `children_timeout` with 50 children, `def` and `async def` entry actions | **PASS** -- coroutine lane settles in **0.44 s** against a 0.5 s **per-child** bound where the aggregate would be 12.5 s; the non-pre-emptible `def` lane runs to 12.6 s **but emits the WARNING**, which is the #194/#181 documented contract |
| `C4` | 200 concurrent `def`-service **arm-then-rollback** (#193) | **PASS** -- `service_callable_submitted = 0` across all 200; the handoff inside the engine-held task cancels before submission |
| `F1` | **Livelock fuzz: 500 configs x {def, async def} x {sync, async}** = 1,500 runs, 3 shapes (invoke cycle / `always` cycle / `raise` cycle), 5 s watchdog | **PASS** -- **0 hangs, 0 unbounded, 0 silent runaways, `def_vs_asyncdef_lap_mismatch = 0`, `async_vs_sync_engine_lap_mismatch = 0`** |
| `S1` | `always` at a **deeper** depth vs a named handler at a **shallower** depth, both engines (#196) | **PASS** -- named handler's action fires **exactly once**; the spinning `always` never consumes it; both engines trip at the **same lap (16)** |
| `S2` | Engine-provenance forgery sweep: public class / import path / `type(held)(...)` / `_replace` / deepcopy / pickle / `Event` + `_ENGINE_MARK` | **FAIL -> D9-semantics-1** -- `_replace` on a genuinely-received completion **preserves the private subclass** |

---

## 3. Defects

### D9-semantics-1 -- a genuine engine completion can be RE-TYPED into any other completion, defeating #195 (**High**)

**Repro:** `repro/d9_sem_1_replace_forgery.py` -- exit 1 == reproduced.
Deterministic, **3/3 runs identical** on the coroutine lane.

```
{'kind': 'async', 'forged_is_system_event': True,
 'state': ['oms.settled'],
 'booked': [('done.invoke.fill', {'qty': 999999})],
 'last_error': None, 'REPRODUCED': True}
```

**Root cause.** #195 moves provenance from *spelling* to *type identity*:
`_EngineDone` / `_EngineError` / `_EngineAfter` are private `NamedTuple`
subclasses (`events.py:567-588`) and `is_system_event` requires one
(`events.py:286`). The changelog states the classes "have no public name;
construct through the `engine_*` helpers only."

But a `NamedTuple` subclass's `_replace` returns **`self.__class__`**, and the
comment at `events.py:558-562` explicitly accepts this -- "`_replace`, pickle
and deepcopy all behave the same **and preserve the subclass**" -- as a
property needed for legitimate copying. The gap is *who holds an instance*.
The changelog assumes user code cannot obtain one; in fact **every ordinary
`onDone` / `onError` handler is handed a genuine engine-minted event as its
`event` argument** -- that is the documented way user code consumes a
completion. From there:

```python
def on_ping_done(interp, ctx, event, action):   # event IS _EngineDone
    forged = event._replace(type="done.invoke.fill",
                            data={"qty": 999999}, src="fill")
    assert is_system_event(forged)              # True
    interp.send(forged)                          # drives the REAL onDone
```

The machine in the repro is `strict: true` and the genuine `fill` service is
still running (3 s). The forged completion:

- passes `is_system_event` -> exempt from `strict` (`send` refuses a *public*
  `DoneEvent` with `UnknownEventError`; the re-typed one sails through),
- passes `onUnhandled`,
- drives `done.invoke.fill`'s real `onDone`, booking **999,999** against an
  order whose venue fill has not returned.

This is, verbatim, the scenario #195 says it closes: "a hand-built
`DoneEvent("done.invoke.fill", ...)` bypassed `strict` and `onUnhandled` and
drove a real `onDone` while the genuine service was still running." #195
closed the *construct-from-nothing* path and left the
*re-type-what-you-were-given* path open -- which is strictly easier, because
it requires no private name.

Two adjacent (lesser) surfaces confirmed by the same sweep: `type(held)(...)`
also mints a trusted instance, and the private classes remain importable as
`xstate_statemachine.events._EngineDone`. Those need a deliberate reach for a
private name; `_replace` does not -- it is public NamedTuple API on an object
the engine handed over.

**Why High, not Blocker.** It requires the application's own action code to do
this, so it is not reachable by external traffic alone; it is a
*defence-in-depth failure*, not a remote hole. It is High rather than Medium
because the property #195 advertises -- "only what the engine produced is
system traffic" -- does not hold, and a wrapper cannot restore it (the wrapper
cannot intercept `_replace` on an object already passed to user code).
**`file:line`: `src/xstate_statemachine/events.py:558-588`** (subclass
definition and the comment sanctioning subclass-preserving `_replace`); trust
site `src/xstate_statemachine/events.py:286` (`is_system_event`).

**Remedy shape (for the maintainer).** Carry provenance in a field the
`_replace`-produced copy cannot keep consistent -- e.g. bind the marker to the
`(type, src)` pair at mint time and verify it at the trust site -- or override
`_replace` on the private subclasses to return the **public** class.

### D9-semantics-2 -- `strict` does not gate events restored from a snapshot's `pending_events` (**Low**)

**Repro:** `p_persistence.py::P2` (`results/p_persistence.json`).

```
strict/bare_done             status=running err=None recv=['done.invoke.q']
strict/plain_undeclared      status=running err=None recv=['BOGUS']
onUnhandled/bare_done        status=error   err=UnhandledEventError
onUnhandled/plain_undeclared status=error   err=UnhandledEventError
```

`events.py:403-414` states that a record **without** `"engine": true` restores
as "user traffic, subject to `strict` / `onUnhandled`". `onUnhandled` is
honoured; `strict` is not -- `_check_strict` runs at the `send()` call site
(`interpreter.py:907`), and the restore path re-enqueues through
`_enqueue_restored` -> `_put_inbox` (`base_interpreter.py:1767`,
`interpreter.py:1490-1492`), bypassing it. An undeclared *plain* event
survives the same way, so this is a general property of the restore path, not
specific to #195.

**Low**, not higher: a caller who can write `pending_events` already controls
`state_ids` and `context` outright -- the trust boundary `events.py:405-413`
itself draws -- and `onUnhandled:"error"` does catch it. The defect is that
the documented sentence over-promises. **`file:line`:
`src/xstate_statemachine/base_interpreter.py:1767`**.

---

## 4. Not covered

| Area | Why |
|---|---|
| 12-minute soak (200 machines, chaos snapshot, external producer) | Exceeds this task's 20-minute wall-clock bound once the 1,500-run fuzz and the dual-lane prior-suite re-run are included. The round-8 full soak at `battle-6db65d8/semantics/nc_soak_async.py` passed (169.4k events, 0/3.39M external dropped, +8.8 MB RSS); its dominant risk -- external shed under a tripping chain -- is the very thing `C1` now proves closed at 5x the round-8 volume. **Recommend re-running `nc_soak_async.py` unchanged on f28719c before the gate.** |
| Property >=300 random machines incl. parallel + children | Covered by re-run `n1::N1-01` (300 random **parallel** machines, snapshot at every quiescent point) and `s1::S1-01/S1-02` (300 random machines), both **PASS on both lanes** -- not re-implemented. |
| Hash-seed sweep | `na::D2` re-run; its variance is the same 0.25 s harness-window artefact as `D1`, and `f_fuzz::F1` covers lap agreement deterministically across 1,500 runs. |
| Thread-leak / sync-child-reaping check | Not instrumented this round; #196's `SyncInterpreter` child-reaping change is exercised indirectly by `F1`'s sync lane (500 `always`-cycle runs, no hang) but **not** directly counted. Gap. |
| Redaction, `__slots__` | `__slots__` confirmed present on the engine subclasses (`()`, inheriting the NamedTuple layout) during the `S2` sweep; redaction not re-attacked (passed at 6db65d8, untouched by #192-#201). |
| RAISE loop-side exactly-once | Covered by re-run `s2::S2-04` and `nb::E2`, **PASS on both lanes**; not re-implemented. |

---

## 5. Verdict

**The round-8 fix set holds, and the one open round-8 defect is closed.**
D8-semantics-1 -- external priority sends shed by a chain they had no part in
-- is **FIXED** structurally: provenance now rides on the lane *item*, so the
charge site and the shed site ask the same question. At 10,000 external sends
per service kind during a live tripping chain, loss is **zero**. The
lap-parity claim of #201 is the strongest evidence in this report: across
**1,500 fuzz runs** spanning three cycle shapes, the lap at which a machine
trips is identical for `def` and `async def` **and** identical between the two
engines, with zero hangs and zero silent runaways. #193 (0/200 rollback
submissions), #194 (per-child bound honoured on the pre-emptible lane, WARNING
always), #196 (a spinning deeper `always` never consumes a shallower named
event, same lap both engines), #198 and #199 all verify clean.

**One new High is open: D9-semantics-1.** #195's central property -- that only
engine-produced objects are system traffic -- does not hold, because `_replace`
on a completion the engine *legitimately handed to a user action* preserves the
private subclass. The forged completion bypasses `strict`, bypasses
`onUnhandled`, and drives a real `onDone` while the genuine service is still
outstanding: the exact failure #195 is written to close, reached by an easier
route than the one it blocked. A second, Low finding (D9-semantics-2) records
that `strict` does not gate snapshot-restored `pending_events`, contradicting
the docstring at `events.py:403-414`.

**Gate impact (this track's input only): conditional pass.**
D9-semantics-1 is not remotely reachable and does not block, but it cannot be
absorbed by a wrapper, so it should be fixed before the provenance model is
relied upon as a security boundary. The wrapper rules this track carries
forward are unchanged from round 8 (`on_event_dropped` as the reliable drop
channel, not `last_error`), plus one new rule: **never re-type an engine event
with `_replace`** -- construct a fresh user `Event` instead. The two gaps in
section 4 (the 12-minute soak, the thread-leak check) should be closed before
the final verdict.
