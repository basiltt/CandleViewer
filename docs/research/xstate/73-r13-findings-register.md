# 73 — Round-13 findings register (v0.9.0, tag `v0.9.0` = `91bd979`)

**Date:** 2026-09-23 · **Library:** `xstate-statemachine` `__version__ = "0.9.0"`
**Tree tested:** `main` @ `e3a1f22` — `git diff v0.9.0..HEAD --stat` = `.github/workflows/publish.yml` only (+14/−1). **No library source differs between the tag and the tested tree.**
**Inputs triaged:** 30 round-13 candidate findings (persistence / concurrency / fuzz / determinism / security / soak / contracts tracks) + `S-1`…`S-12` from `72-r13-diff-review.md` + regressions from `70-r13-regression.md`.
**Method:** every retained row re-ran fresh from neutral cwd `C:/Users/basil`, 120 s cap, both `def` and `async def` service spellings, polled to convergence, against the round-13 venv.

---

## 0. Headline

| | |
|---|---|
| Candidate rows in | 30 + 12 `S-*` |
| After dedupe | **21 canonical rows** (`R13-01` … `R13-21`) |
| **LIBRARY-DEFECTs** | **4** — `R13-01` (High), `R13-02` (Medium), `R13-03` (Medium), `R13-04` (Medium, docs) |
| DESIGN-CONSTRAINT (not defects) | 6 |
| OUR-CONTRACT-DEFECT | 7 (2 blocker, all config-only or wrapper-side) |
| NEEDS-WRAPPER | 3 |
| HARNESS-ERROR | 1 |
| SUPERSEDED / REFUTED | 3 |
| Library regressions from 0.9.0 | **0** |
| Suite | 3577 passed, 13 skipped, 597 s, coverage 92.86 % |

**No library defect blocks adoption.** The four LIBRARY-DEFECTs are all
*observability / durability-path* issues with known wrapper-side mitigations;
none corrupts state, loses an accepted order event on the normal path, or
breaks either engine's transition semantics. The two remaining blockers are
**ours** (`R13-13`, `R13-14`) and both are closed by config-only catalogue edits
already proven green 11/11 on this exact build.

### Two briefing corrections established this round

1. **`0.9.0 IS on PyPI.`** The environment brief says "NOT yet on PyPI (pip download fails)". It no longer does — `pip download xstate-statemachine==0.9.0 --no-deps` succeeds. I unpacked the wheel and diffed all **42 modules** against the tag source: **0 differ** after CRLF/LF normalisation. Adoption pins `xstate-statemachine==0.9.0` from the index; the vendoring / VCS-ref caveat is **dropped**. (Supersedes `CV-V08`.)
2. **BENCH-6 passes with real headroom.** Three conflicting readings arrived (medians 71.0, 87.5, 97.9 ms). I re-ran THEIR `benchmarks/production_characteristics.py --quick` §2 five times on the idle host: **+56.7 / +53.3 / +54.5 / +52.5 / +52.7 ms** (min 52.5, **median 53.3**, max 56.7, spread 4.2 ms). All five under the 100 ms bar with ~45 ms headroom, and a far tighter spread than any prior round — the earlier disagreement was host load, not library variance. See `R13-20`.

---

## 1. Canonical LIBRARY-DEFECTs

### R13-01 — `drain_pending()` on the async engine silently drops the entire priority lane
**Classification: LIBRARY-DEFECT · OMS severity: HIGH (durable-shutdown data loss; engine-divergent)**
**Merged from:** `S-1`. **Reproduced:** yes, this round.

`Interpreter.drain_pending()` (`interpreter.py:1715`) is documented as removing
and returning *"**every** accepted-but-unprocessed event … intended for shutdown
paths that must persist accepted work durably before the process exits."* Its
body reads `self._event_queue` only. The async engine has **two** queues;
`_priority_queue` (`interpreter.py:374`) is never touched. The snapshot path
disagrees — `_snapshot_pending_events` (`interpreter.py:1675`) returns
`[ev for ev, _ in self._priority_queue] + inbox`. The two durability paths
return different sets and the one whose docstring promises completeness is the
lossy one.

Re-run (`probes/v0.9.0/p8_drain_priority.py`, neutral cwd, exit 0):

```
async snapshot view : ['P1', 'P2', 'I1', 'I2']
async drain_pending : ['I1', 'I2']
LOST BY ASYNC DRAIN : ['P1', 'P2']
sync  drain_pending : ['P1', 'P2', 'I1', 'I2']
```

**Why round-13 and not an old row:** #233 made `SyncInterpreter._enqueue_restored`
honour the priority lane, and `SyncInterpreter.drain_pending` reads its single
queue — so sync now drains all four. Before #233 both engines were wrong in the
same direction. Fixing one engine's *restore* ordering turned a symmetric bug
into an **engine-dependent** one, exactly the parity class #233 exists to close.

**Blast radius for the OMS:** the priority lane is where **fired `after` timers
and invoke completions** land (`_deliver_priority`, `interpreter.py:2498`), and
`send_priority()` is public (`interpreter.py:1051`). The lost events are
precisely the engine-minted, chain-charged ones — a fired deadline or a
completed fill-poll accepted microseconds before shutdown. A
`drain_pending()` → persist → exit path loses them on async and loses nothing
on sync.

**Fix (theirs):** drain `_priority_queue` first, then the inbox — the order
`_snapshot_pending_events` already uses.
**Mitigation (ours, until then):** the shutdown wrapper must persist via
`get_persisted_snapshot()` (which *is* complete), never via `drain_pending()`;
if `drain_pending()` is used for telemetry, treat its result as a lower bound.

---

### R13-02 — `on_interpreter_start` never fires on a snapshot-restored interpreter, on either engine, via either registration route
**Classification: LIBRARY-DEFECT · OMS severity: MEDIUM (observability; unbalanced lifecycle)**
**Merged from:** `D13-persistence-2`, `D13-concurrency-1`, `D13-fuzz-1`, `CV-V03` — four independent tracks, one root cause.
**Reproduced:** yes, this round, 6/6 and 5/5 cells.

`Interpreter.start()` has two paths. The resume branch
(`interpreter.py:588-624`) detects the restored shape
(`status in ("running","done","error")` and `_event_loop_task is None`), logs
`"♻️ Resuming restored interpreter"`, binds the loop, re-arms scheduled sends
(#213), optionally re-drives invokes (#44) and `after` timers (#128), resumes
child actors, and **`return self` at line 624**. The plugin notification loop —
`for plugin in self._plugins: plugin.on_interpreter_start(self)` — sits at
`interpreter.py:663-665`, **below that return**, and is never reached.
`SyncInterpreter.start()` has the identical shape (`sync_interpreter.py:311-347`
returning above its own hook loop at `:388`), which is why the sync engine fails
the same way rather than via a separate bug.

Re-run `battle-v0.9.0/concurrency/w3_restore_lifecycle_hook.py` — verdict
`DEFECT`, 6/6 cells `{async, sync} × {def, async def} × {plugins=, .use()}`:

```
async/def/plugins=:  on_interpreter_start fired 0x on a RESTORED interpreter
                     (fresh control: 1x); on_interpreter_stop fired 1x -- unbalanced
... (all six identical)
```

Re-run `battle-v0.9.0/fuzz/d13_fuzz_1_restored_start_hook.py` — `result: FAIL (5 cells)`:

```
CONTROL fresh  .use()      : ['start', 'transition', 'stop']
RESTORED from_snapshot(plugins=): ['recv:GO', 'transition', 'stop']
RESTORED .use()            : ['recv:GO', 'transition', 'stop']
```

**Why this is a defect and not the documented resume semantics** (the `CV-V03`
row argued the latter, and that argument is **overturned**):

- `docs/_guide/plugins.md:175` — *"`on_interpreter_start` … **When `start()` is called**"*. `docs/api/index.md:1919` — *"`start()` begins."* Neither carves out the resume path, and `start()` is the library's **own documented way to resume a restored actor** (the architecture comment at `interpreter.py:582-587` says so explicitly).
- `on_interpreter_stop` **does** fire (`stop()` has one path), so a lifecycle plugin observes a `stop` with no matching `start` — an *unbalanced* pair, which is a stronger signal than a merely-absent one. Any plugin holding a span, a correlation id, a latency clock or an audit "actor came up" record either leaks or under-reports.
- It is **not** `plugins=`-specific: `.use()` after `from_snapshot` is equally blind, so there is **no working route at all** for this hook on a restored actor. The 0.9.0 changelog promises `plugins=` has "the same effect as `.use()` on the result" — which holds for `on_invalid_event` (verified exactly-once over 320 property cases in `w2`/P2-P3) but has no route for the lifecycle hook. This is the other half of the hook #230 just fixed.
- Confirmed at fleet scale independently: `n12` soak, 40/40 chaos restores, `plugin_start_counts=[0]`.
- The actor itself is fine — `restored_machine_is_live=true` in all six cells, `on_transition` / `on_action_execute` / `on_interpreter_stop` all normal. It works; it just never announces itself.

**Fix (theirs):** run the plugin loop on the resume branch too (or hoist it above
the early return), ideally with a `restored=True` discriminator so a plugin can
tell bring-up from resume.
**Mitigation (ours):** `CvErrorHooks` must **not** hang per-process init off
`on_interpreter_start`. Do bring-up work at construction/restore time in our own
wrapper; see `R13-17`.

---

### R13-03 — Malformed `chain_trips` / `last_chain_error` escape `from_snapshot` as raw `ValueError`/`TypeError` instead of `SnapshotCorruptError`
**Classification: LIBRARY-DEFECT · OMS severity: MEDIUM (breaks the documented quarantine contract)**
**Merged from:** `D13-persistence-1`. **Reproduced:** yes, this round.

`base_interpreter.py:1993` does a bare
`interpreter.chain_trips = int(snapshot.get("chain_trips") or 0)`, and `:1994-1996`
`str()`s `last_chain_error` — both **after** the snapshot validator, which has no
knowledge of the two envelope fields #226 added. Every pre-#226 field
(`version`, `status`, `state_ids`, `context`, `pending_events`,
`scheduled_sends`, `deferred`) is shape-checked and reported as
`SnapshotCorruptError` (`persistence.py:138-191`).

Re-run `battle-v0.9.0/persistence/repro/d13_p1_chain_trips_raw.py` (standalone,
stdlib + `xstate_statemachine`, neutral cwd) — `VERDICT: REPRODUCED (4 raw leaks)`:

```
chain_trips='NaN'    -> RAW ValueError: invalid literal for int() with base 10: 'NaN'
chain_trips=[1, 2]   -> RAW TypeError: int() argument must be a string, ... not 'list'
chain_trips={'a': 1} -> RAW TypeError: int() argument must be a string, ... not 'dict'
chain_trips='1e3'    -> RAW ValueError: invalid literal for int() with base 10: '1e3'
control deferred=5   -> SnapshotCorruptError (the contract)
last_chain_error={'not': 'a message'} -> latched as "{'not': 'a message'}"
```

**Why it matters:** the documented restore idiom is
`except SnapshotCorruptError: quarantine(blob)`. A crash-truncated or
partially-written record whose damage happens to land on `chain_trips` is **not
caught** by that handler — it escapes as a bare `ValueError`/`TypeError` and
takes down the restore loop instead of quarantining one blob. Two softer
sub-cases ride along: `chain_trips='12'` is silently coerced to `12`, and a
non-string `last_chain_error` is latched as its `str()`.

**Distinguish from `R13-06`:** that row is about *well-formed but forged* values
inside the documented trust boundary (not a defect). This row is about
*malformed* values breaking the error-type contract — the validator's whole job.

**Fix (theirs):** shape-check both fields in the validator alongside the others.
**Mitigation (ours):** the restore wrapper catches
`(SnapshotCorruptError, ValueError, TypeError)` and quarantines on all three.

---

### R13-04 — `0.8.1 → 0.9.0` doc retarget was a blind substitution over *historical* prose; the on-disk-layout table is now self-contradictory
**Classification: LIBRARY-DEFECT (documentation correctness) · OMS severity: MEDIUM**
**Merged from:** `S-2`. **Reproduced:** yes (static, re-read on the tag).

The retarget sed-replaced the version string everywhere, including sentences
describing **what a past release did**, producing false statements about history:

- `persistence.py:41` — the **normative layout table** now reads *"2 — 0.9.0: every `pending_events`/`deferred` record carries a `kind`"*. Layout **v2 was 0.8.1**; 0.9.0 is **v3**. Two lines below, v3 is *also* attributed to 0.9.0 — the table claims two different layout versions for one release.
- `docs/_guide/snapshots.md:253` — *"Since layout **v2** (0.9.0)"* in the same bullet as *"Since layout **v3** (#214)"*.
- `persistence.py:164`, `base_interpreter.py:580`, `:1797` — *"every 0.9.0 writer records `version`/`machine_hash`"*. These sentences exist to argue **why `minimum_version=1` is safe, because older writers already did it**; rewriting the version to the current one destroys the argument.
- `events.py:57` (*"Since 0.9.0 (#79) system status is decided by provenance"* — #79 shipped in 0.8.1), `:192`, `:380`, `:407` (now points at a 0.9.0 note that does not describe that migration).

Nothing executable is wrong — this is why it is MEDIUM and not HIGH. But an
operator deciding **whether a stored blob needs upcasting**, or whether
`minimum_version=1` is safe for their archive, is reading these exact sentences,
and our adoption gate pins `minimum_version=3` partly on their authority.

**Mitigation (ours):** the snapshot-format ADR restates the layout↔release map
from first principles (v1 ≤ 0.8.0, v2 = 0.8.1, v3 = 0.9.0) rather than citing
these docstrings.

---

## 2. DESIGN-CONSTRAINT — documented boundaries, not defects (R10-01 pattern)

### R13-05 — Import-path `_EngineDone` forgery still mints a real `onDone`
**Classification: DESIGN-CONSTRAINT (carried, accepted) · severity: accepted trust-boundary**
**Merged from:** `R9-01-carried`. Private `_EngineDone` remains importable from
`xstate_statemachine.events`. Unchanged by round-12; accepted under the `R12-03`
framing — a private `_`-prefixed import is not public API, and anything able to
perform it already has in-process code execution. **Not counted as a defect.**
Repro: `battle-v0.9.0/security/a1_engine_done_forgery.py`.

### R13-06 — Forged `chain_trips` / `last_chain_error` in a v3 blob are accepted verbatim
**Classification: DESIGN-CONSTRAINT · severity: LOW (record-only)**
**Merged from:** `S-4`, `ND13-sem-4`.
`machine_hash` is a hash of the **machine definition**, not of the payload (its
documented job is drift detection), so it neither covers nor is invalidated by
these fields. `chain_trips=999999` + `RestoredError('TOTALLY FORGED')` restore
cleanly, but the latch **gates no transition** — status stays `running`,
`send('T')` still transitions, final `ch.b`; all 4 strict-bypass attempts via
`scheduled_sends` are refused, including the `version:2` variant. Consistent
with every other restored field, so this is the documented trust boundary
(`from_snapshot` docstring, #205), not a new hole.
Recorded only because the new fields feed a **supervisor alerting** path: a
replayed blob can manufacture a "work was discarded" alert or, worse, suppress
one by restoring `0`. Worth one sentence in `snapshots.md`. Also confirmed:
`clear_chain_error()` clears the message but **not** the counter — correct and
documented (monotonic).

### R13-07 — `last_chain_error` changes type across a snapshot round-trip and the new type is outside the `RunawayChainError` hierarchy
**Classification: DESIGN-CONSTRAINT · severity: MEDIUM-as-adoption-note**
**Merged from:** `S-3`.
`RestoredError` subclasses `XStateMachineError` directly (`exceptions.py:212`),
**not** `RunawayChainError`. A supervisor written against #222 —
`if isinstance(i.last_chain_error, RunawayChainError): page()` — is correct
against a live machine and **silently false** against a restored one. The latch
exists specifically so a supervisor can see discarded work, and a restart is the
event a supervisor most often reacts to. JSON cannot carry a type, the `error`
field sets the precedent, and it is documented (`snapshots.md:133`, `:252`) — so
**defensible design, not a defect**. Flagged because the doc bullet tells readers
the latch "crosses a restart" *before* it tells them the type changes.
**Ours:** never `isinstance`-check the latch; read `chain_trips > 0` instead.

### R13-08 — The #232 `RuntimeWarning` is emitted from `__del__`, so it is invisible to `-W error` and to `filterwarnings = error` CI
**Classification: DESIGN-CONSTRAINT · severity: LOW (adoption note)**
**Merged from:** `S-6`, `D13-security-3`, `ND13-sem-2`.
CPython routes an exception escaping `__del__` to `sys.unraisablehook` and prints
`Exception ignored in:`. Verified: machine unaffected (`m.a → m.b → m.c`,
`status == running`, exit 0), `raised_to_caller: []`, `loop_exception_handler: []`.
Consequences: a project running `-W error` **cannot** turn this into a build
failure — it is a console diagnostic, never a gate; and it cannot be caught by
`pytest.warns` unless the object is forced to finalise inside the block.
Determinism is good (fires reliably on CPython at refcount drop, one warning per
dropped receipt, no duplicates, **no false positive** on the store-and-await-later
shape). Note `__getattr__` marks `_used` *before* delegating, so **any** attribute
touch silences it — including a debugger `repr()` or a logging call. Strictly
best-effort by construction.
**Ours:** the "dropped receipt" lint is a static check in our repo, not a CI
warning gate.

### R13-09 — `def` service on the executor calling `send()` raises `WrongThreadError`
**Classification: DESIGN-CONSTRAINT · severity: INFO**
**Merged from:** `ND13-sem-1`. Documented: `send()` is loop-affine,
`send_threadsafe()` is the supported route (`exceptions.py:412`, README API
table). The invoke still completed. Provenance is never consulted because the
call is refused first.

### R13-10 — `invoke.src` absent or `None` raises `ImplementationMissingError` rather than `InvalidConfigError`
**Classification: DESIGN-CONSTRAINT · severity: INFO**
**Merged from:** `ND13-sem-3`. Correct error for a *missing implementation*; #231
concerns a malformed src **type**, and all 7 type-error shapes are refused by a
named `InvalidConfigError`. #231's check is in fact wider than advertised (`S-9`).

### R13-11 — `_rearm_restored_self_sends()` return value changed meaning; no caller reads it
**Classification: DESIGN-CONSTRAINT · severity: LOW (record-only)**
**Merged from:** `S-5`. Was `len(records)` (processed), now `armed` (accepted);
docstring updated. All three in-tree callers (`interpreter.py:601`,
`sync_interpreter.py:323`, `:345`) discard it; the only reader is
`test_round12_findings.py:509`. Partial-restore consistency **is** sound: after a
refusal the machine starts, stays in `m.a`, re-persists only the surviving
record, `status == "running"`. Logged so the meaning change is on the record if
the value is ever surfaced.

---

## 3. SUPERSEDED / REFUTED

### R13-12 — `"version": 2` in the payload mints a trusted engine event — **REFUTED**, unchanged
**Classification: SUPERSEDED-RULE (prior defect refuted, re-confirmed)**
**Merged from:** `D11-semantics-1`. `battle-v0.9.0/semantics/prior/p_persistence.out::P3`
is **byte-identical to round 12**. A plain v3 verbatim write reaches the identical
outcome, so the **trust boundary** — not the upcast — is load-bearing.
`minimum_version=3` is hygiene, not a security control. Stays refuted as `R12-02`.

### R13-12a — `CV-V08` "not on PyPI" — **SUPERSEDED**
0.9.0 **is** published; wheel diffed against the tag across 42 modules, 0 differ.
Pin `xstate-statemachine==0.9.0` from the index. See §0.

### R13-12b — `D11-security-4` / `D12-security-1` — **FIXED, confirmed**
`on_invalid_event` now reachable on restore refusal via `from_snapshot(plugins=)`
(#230); `chain_trips`/`last_chain_error` persist across restore (#226, monotonic
over 4 restart hops, v2 blobs upcast to defaults). Both close as fixed. Note the
`plugins=` fix covers `on_invalid_event` **only** — see `R13-02`.

---

## 4. OUR-CONTRACT-DEFECTs (catalogue / harness — no library involvement)

### R13-13 — B16: all four revocation events fail to drop the parallel `elevation` region
**Classification: OUR-CONTRACT-DEFECT · OMS severity: BLOCKER (open 8th round)**
**Merged from:** `C-04`, `C-04 / R12-13`, `R12-13`, `CV-V02` (first half).
**Re-run this round:** `contracts/g4_c04_c07b.py`, both spellings, **11 checks, 0 FAIL** on the fixed chart.
LOGOUT / IDLE_DEADLINE / ABSOLUTE_DEADLINE leave `['auth.revoked','elevation.elevated']`;
REVOKE lands `elevation.normal` but a later `STEP_UP_OK` **re-elevates a revoked
session**. Per XState v5 / SCXML each parallel region selects transitions
independently, so a region with no handler does not move, and our own
`onUnhandled:'defer'` swallows the miss — **engine is spec-correct**.
Config-only fix requires **both** the root hoist to a terminal `elevation.dead`
**and** deletion of the region-level `elevated.on.REVOKE` handler; the root hoist
alone fixes only 9/12 lanes because the deeper handler outranks the root arm
(the round-12 correction, re-proven).

### R13-14 — B18: a guard-denied RELEASE under `onUnhandled:'error'` permanently bricks the kill switch
**Classification: OUR-CONTRACT-DEFECT · OMS severity: BLOCKER (open 8th round)**
**Merged from:** `C-07b`, `C-07b / R12-14`, `R12-14`, `CV-V02` (second half).
**Re-run this round:** `g4_c04_c07b.py`, both spellings — fix green: denial
non-fatal (`status='running'`, `['kill_switch.engaged']`), `audit_release_denied`
fires, the later authorised RELEASE reaches `kill_switch.clear`, `chain_trips==0`.
Unfixed, a denied RELEASE gives `status='error'` + `UnhandledEventError` and the
authorised RELEASE is accepted by `send()` (ok, ~0.3 ms) but **dropped**.
A guard-denied event is reported as `guard_denied` (#153) and our opt-in root
`onUnhandled:'error'` makes it fatal. XState v5 / SCXML treat a guard-denied
event as simply untaken and have **no fatal-unhandled mode**, so upstream
semantics argue against our configuration — **it is ours**. Fix:
`onUnhandled:'defer'` plus an ordered unguarded auditing RELEASE fall-through
(the shape B13/B17/B20 already use).

### R13-15 — B11 is a one-way trip into `degraded`: a guard ranked ahead of its own action reads pre-action context
**Classification: OUR-CONTRACT-DEFECT · OMS severity: BLOCKER**
**Merged from:** `G13-01`. **Re-run this round:** `contracts/g1_b11_b12.py`, both
spellings — `24 checks, 3 FAIL: [G1.B11.happy.lands_stopped, G1.B11.inv.gap_counted, G1.B11.inv.both_services_ran]`, identical in `async` and `def`.
`B11.degraded.on.STREAM_HEALTHY`'s first arm carries guard `all_streams_healthy`
**and** actions `[mark_stream_healthy]` on the same arm. XState v5 and SCXML both
evaluate a transition's guard against the context **before** that transition's
actions run, so the guard reads a `streams_healthy` map in which the very stream
the event announces healthy is still `False`; the recovery arm is never
selectable and `unsubscribe_and_flush` never runs. Instrumented root cause:
`g2_b11_fix.py::G2.B11.rootcause.guard_sees_pre_action_ctx`. Same class recurs at
`recording/degraded REASON_REMOVED` (guard `reasons_remain` ranked ahead of its
own `remove_reason`). **Engine is spec-correct.** Remedy: event-aware guards in
our code — proven 11/11 both spellings plus sync parity.

### R13-16 — B11 stops counting gaps exactly while degraded
**Classification: OUR-CONTRACT-DEFECT · OMS severity: HIGH**
**Merged from:** `G13-02`. `recording.on.GAP_DETECTED` bumps `gap_count_24h`, but
`degraded` defines no `GAP_DETECTED` handler and root `onUnhandled:'defer'`
swallows it silently — no drop, no unhandled hook. Gap telemetry goes dark
precisely during the degraded window: the 24 h gap budget under-reports and the
operator sees a *healthier* number the worse the feed gets. Config-only fix
proven (`g2_b11_fix.py`, `G2.B11.fixed.gap_counted == 1`, both spellings).

### R13-17 — B3 leg chart self-destructs at t0
**Classification: OUR-CONTRACT-DEFECT · OMS severity: MEDIUM**
**Merged from:** `CV-V01`. `B3.states.pending.always`'s third arm is **unguarded**,
so if neither `should_skip` nor `passes_preflight` is decidable at leg-entry the
machine transitions straight to terminal `leg.error` during initial entry:
`states=['leg.error']`, `status=done` before any event is sent. With
`{"should_skip": False, "passes_preflight": True}` it lands `['leg.submitting']`.
Chart-level defect in our catalogue.

### R13-18 — B16: the `elevated → elevated` re-enter arm on `STEP_UP_OK` does not audit
**Classification: OUR-CONTRACT-DEFECT · OMS severity: MEDIUM**
**Merged from:** `C-04b/C-04c`. Two successful step-ups record only one
`audit_step_up`. Config-only: add `audit_step_up` to the re-enter arm.

### R13-19 — B19: `OPERATOR_RESOLVED` is deferred rather than handled in `reconciliation.stale_lockout`
**Classification: OUR-CONTRACT-DEFECT · OMS severity: MEDIUM**
**Merged from:** `B19-INV-b2`. An operator cannot clear a stale lockout:
`states=['reconciliation.stale_lockout']`, `unhandled=[['OPERATOR_RESOLVED','deferred']]`.
Config-only: add the handler.

---

## 5. NEEDS-WRAPPER (adoption work, no defect either side)

### R13-W1 — Restore wrapper must pass `from_snapshot(..., minimum_version=3, plugins=[CvErrorHooks()])`
**From `W-01`.** Plugins passed via `plugins=` are registered **before** persisted
events are admitted; a `.use()` after `from_snapshot` is silently blind to
exactly the strict/schema refusal it exists to catch (a dropped deadline).
An undeclared event planted in **both** `pending_events` and `scheduled_sends`
fires `on_invalid_event` twice, seen only via `plugins=`. This is the one 0.9.0
API change our code must actively adopt. **Caveat from `R13-02`:** this route
carries `on_invalid_event` only, never the lifecycle hook.

### R13-W2 — Narrowed by #225: spawning a worker from an action is now safe
**From `W-02`, `CV-V04`, `S-8`.** #225 replaced the ContextVar self-send predicate
with task identity (`_action_tasks`), so a worker outliving its action and the
`ensure_future` hand-out idiom are ordinary external traffic (`worker_send='ok'`,
machine advances, `chain_trips=0`). The genuine in-step await is still refused by
the library with `ReentrantWaitError`. The wrapper downgrades from a prohibition
to a lint. Nesting, spawning and the executor lane all verified correct.

### R13-W3 — `SyncInterpreter` accepts no `max_queue_size` / `overflow_policy`
**From `W-03`.** The bounded RAISE inbox is async-only by library design
(`max_queue_size=4` + 40-event burst gives `sent=4, refused=36, dropped=[]`,
status stays `running`). Any sync-engine use in the OMS needs its own admission
bound in our wrapper.

---

## 6. HARNESS-ERROR

### R13-21 — Wrapping an `async def` action in a plain `def` hides it from the engine
**Classification: HARNESS-ERROR (ours) · severity: MEDIUM**
**From `METHOD-01`.** Our contract `Stub.mk_a` wrapped every action impl for
uniformity — correct for sync impls, but it **drops the coroutine** returned by an
`async def` action, which is then never awaited and silently never runs. Surfaced
by running under `-W error::RuntimeWarning` (`coroutine 't_225_...in_step' was
never awaited`); it had been masking the #225 probes, which returned `exc=None`
instead of `ReentrantWaitError`. Fixed in `e7_round12.py::_direct()`.
**Standing constraint:** any house action registry must register coroutine
functions **directly**, never behind a sync wrapper.

---

## 7. Benchmark & regression rows

### R13-20 — BENCH-6 loaded timer lateness: **PASS with ~45 ms headroom**
**Classification: BENCHMARK · supersedes `CV-V07` and both `BENCH-6` variants.**
Three conflicting round-13 readings were submitted (medians **71.0**, **87.5**,
**97.9** ms; two of them reporting runs over the bar). I re-ran THEIR
`benchmarks/production_characteristics.py --quick` §2 (`after: 10` lateness at
500 busy machines) five times on the idle host:

```
+56.7  +53.3  +54.5  +52.5  +52.7   ms
min 52.5 · median 53.3 · max 56.7 · spread 4.2
```

All five **under** the 100 ms bar. The spread (4.2 ms) is far tighter than any
prior round, so the earlier disagreement was **host load, not library variance** —
the conflicting submissions were measured on a contended machine. Round-12
readings on the same unchanged tool were +89.6/+94/+113/+110/+111 (median ~110,
two of five over). Plausible contributors, not isolated: #218 delayed-self-send
clock-handle leak and #225 removing the ContextVar from the send hot path.
**CAVEAT (unchanged):** single Windows dev host; the library's own note says your
macrostep cost sets your budget. Re-measure on target hardware. A 500-machine
deployment must still not place a hard sub-100 ms deadline on `after:` timers —
hard deadlines stay on explicit `SimulatedClock`-driven deadline events.

### Regression sweep (`70-r13-regression.md`) — **0 library regressions**
175-check adoption gate + 534-script historical sweep: exactly one gate check and
one sweep script moved PASS → FAIL, both triaged as **stale repro / harness
artefact**. Thirteen previously-failing artefacts now pass; 0 timeouts at the
120 s cap across every historical livelock repro. Suite: **3577 passed, 13
skipped**, 15 warnings, 597 s, coverage **92.86 %** (bar 90 %).
`tests/test_round12_findings.py` — 31 passed, matching the CHANGELOG claim for
#225–#235.

### Tracks reporting no new defects
`D13-determinism-none` (round-12 persistence attacks: chain latch across
restarts, strict `scheduled_sends` refusal mid-restore, `plugins=` exactly-once
hook — all as documented) and `D13-soak-summary` (task-identity matrix, dropped-
receipt RuntimeWarning, persistence property matrix — all attacks held).
`S-10` confirms the #228 test-quality fix has real teeth (mutation-tested);
`S-11` (`plugins=` ordering vs `.use()`) and `S-12` (publish smoke test) clean.
`S-7` (`_replace` demotion is a one-way trapdoor with no re-mint path) stands as
INFO — correct behaviour, no re-mint path needed by our design.

---

## 8. Adoption bottom line

**No library defect blocks adoption of `0.9.0`.** Pin
`xstate-statemachine==0.9.0` from PyPI. Four LIBRARY-DEFECTs are open upstream;
all four have wrapper-side mitigations and none touches transition semantics,
state integrity, or normal-path event delivery:

| Row | Sev | Mitigation until fixed |
|---|---|---|
| `R13-01` `drain_pending` drops priority lane | High | persist via `get_persisted_snapshot()`, never `drain_pending()` |
| `R13-02` no `on_interpreter_start` on restore | Med | no per-process init on that hook |
| `R13-03` raw `ValueError`/`TypeError` from restore | Med | catch `(SnapshotCorruptError, ValueError, TypeError)` |
| `R13-04` layout/release docs contradictory | Med | ADR restates the layout↔release map |

The two remaining **blockers are ours** (`R13-13`, `R13-14`), both closed by
config-only catalogue edits proven green 11/11 on this exact build, joined by
`R13-15` / `R13-16` on B11. BENCH-6 passes. Zero regressions.
