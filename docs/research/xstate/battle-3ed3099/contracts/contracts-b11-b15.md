# Contract machines end-to-end — B11–B15 vs `xstate-statemachine` @ `3ed3099`

**Group 3 of the contract battle.** B11 `RecordingSession`, B12 `ReplaySession`,
B13 `ExchangeConnection`, B14 `IngestionPipeline` (book health), B15 `PaperMatcher`
(paper-account liquidation).

| | |
|---|---|
| **Library** | `_ref/xstate-statemachine` @ `3ed3099` (unreleased 0.8.1; `__version__` still `0.8.0`) |
| **Source of truth** | `docs/plan/28-statechart-catalogue.md` §B11–B15, JSON extracted verbatim |
| **Engine** | `Interpreter` (async) primary, `SyncInterpreter` for parity info only |
| **Clock** | `SimulatedClock` throughout |
| **Date** | 2026-09-19 |
| **Scripts** | `g3_*.py` in this directory (`g3_` prefix — the directory is shared with other groups) |

**Headline: the library is not the problem here.** Every one of the five machines
builds from the catalogue JSON unmodified, honours all six mandatory policy keys,
survives snapshot/restore at all 32 macrostep boundaries with zero divergence, and
behaves identically on both engines. **No `<B>.machine.json` fix-up copy was needed
— the catalogue JSON is valid for the library as written.**

Four defects are recorded below. **Three are OUR-CONTRACT defects** (two in B11, one
in B14, plus a scaffolding defect spanning B12+B13). **One is a genuine, narrow
LIBRARY observability gap.**

---

## 1. Result summary

| Suite | Script | Result |
|---|---|---|
| Build / policy binding | `g3_build.py`, `g3_policy.py` | 5/5 build clean |
| B11 invariants | `g3_b11.py` | 7/7 PASS |
| B11 hazard probes | `g3_b11_hazard.py` | 1/3 — **2 contract defects** |
| B12 invariants | `g3_b12.py` | 7/7 PASS |
| B13 invariants | `g3_b13.py` | 10/12 — 1 library, 1 contract |
| B13 unhandled/strict | `g3_b13_unh.py` | characterisation |
| B14 + B15 invariants | `g3_b14_b15.py` | 7/9 — 1 library, 1 contract |
| Snapshot/restore parity | `g3_snapshot.py` | **5/5 PASS, 0 `SnapshotMidStepError`** |
| Async vs sync parity | `g3_parity.py` | **5/5 PASS** |
| Wildcard root-cause | `g3_wildcard.py` | root-caused the B13 `strict` failure |
| Finding confirmation | `g3_confirm.py` | all 4 findings reproduced |

Raw JSON in `results/g3_*.json`; the standalone library repro in
`repro/g3_onunhandled_error_silent.py`.

---

## 2. Step 1 — construction and policy binding

`create_machine()` succeeds for all five machines with a stub `MachineLogic`.
**No `InvalidConfigError`. No `ImplementationMissingError`** beyond the expected
one when logic is omitted entirely (the library correctly names the first missing
action). All six mandatory keys bind to the machine object:

| Key | Machine attribute | B11 | B12 | B13 | B14 | B15 |
|---|---|---|---|---|---|---|
| `actionErrorPolicy` | `action_error_policy` | rollback | rollback | rollback | rollback | rollback |
| `onUnhandled` | `on_unhandled` | defer | defer | **error** | **error** | defer |
| `guardErrorPolicy` | `guard_error_policy` | raise | raise | raise | raise | raise |
| `strictTargets` | `strict_targets` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `strict` | `strict` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `spawnBlockingTimeout` | `spawn_blocking_timeout_ms` | 5000.0 | 5000.0 | 5000.0 | 5000.0 | 5000.0 |

A **mistyped policy value** is rejected at build with a precise message listing the
legal set (`onUnhandled: "deferr"`, `actionErrorPolicy: "rolback"`,
`guardErrorPolicy: "riase"` all raise `InvalidConfigError`). Good.

A **mistyped policy key** (`onUnhandledEvent`, `actionErrorPolicyy`, `strictTargest`)
is silently ignored, as are unknown state-level keys (`entryy`, `onn`). This is
standard permissive-config behaviour and not a library defect, but it is exactly what
**CV-LINT-XS1…XS14 exists to catch** — the linter is load-bearing, not belt-and-braces.
A machine that loses its policy block to a typo degrades to library defaults
(`onUnhandled: "ignore"`, `actionErrorPolicy: "continue"`), which is the
two-open-Blockers configuration §1.3b warns about.

---

## 3. Step 2 — invariant scenarios

### B11 RecordingSession — 7/7 stated invariants PASS, 2 hazards found

| Invariant | Verdict | Evidence |
|---|---|---|
| Happy path | **PASS** | `idle → starting → recording`, `subscribe_streams` invoked |
| **INV-B11-a** (position pins recording) | **PASS** | `position_open_for_symbol=true` → `LINGER_DUE` returns to `recording`, `unsubscribe_and_flush` never called. False → `stopping → stopped` |
| **INV-B11-a** (reasons_remain) | **PASS** | 2 reasons, remove 1 → stays `recording` |
| **INV-B11-b** (re-add cancels linger) | **PASS** | `subscribe_streams` call count stays **1** across `recording → lingering → recording`; `cancel_linger` fires. **No stream restart — confirmed** |
| **INV-B11-c** (gaps counted) | **PASS** | 5 `GAP_DETECTED` → `gap_count_24h == 5`, `emit_gap_metric` ×5, state unchanged |
| **INV-B11-d** (degraded ⇔ all healthy) | **PASS** (single stream) | enters on unhealthy, leaves only when all healthy |

#### 🔴 OUR-B11-01 — `degraded` has no `STREAM_UNHEALTHY` handler (contract defect)

`states.degraded.on` declares only `STREAM_HEALTHY` and `REASON_REMOVED`.
`recording.on` declares `STREAM_UNHEALTHY`, `degraded` does not. **A second stream
failing while the machine is already degraded matches nothing.** Under the mandated
`onUnhandled: "defer"` it is parked in the runtime buffer rather than applied.

Two observable consequences, both reproduced (`g3_b11_hazard.py`, `g3_confirm.py`):

**(a) `streams_healthy` silently lags reality.** With `{trade, kline}` both up, send
`STREAM_UNHEALTHY(trade)` then `STREAM_UNHEALTHY(kline)`. After quiescence the map
reads `{"trade": false, "kline": true}` — kline is down but the machine's own health
map says it is up, and `deferred_count == 1` indefinitely. Anything reading this
context for health reporting is reading a lie. This is a **direct INV-B11-d
violation**: "`degraded` … exited only when **all** streams report healthy" cannot
hold when the machine never learns a stream went down.

**(b) A recovery event flaps the machine through `recording`.** Continuing the
above, a single `STREAM_HEALTHY(trade)` produces this transition sequence:

```
STREAM_UNHEALTHY -> ['recording.degraded']
STREAM_HEALTHY   -> ['recording.recording']     <-- wrong: kline is still down
STREAM_UNHEALTHY -> ['recording.degraded']      <-- the parked event, replayed
```

`emit_recording_metric` fires **twice**. The machine declares itself healthy —
emitting a healthy metric downstream — while a stream is down, then corrects itself
one macrostep later. For a recorder feeding coverage rows, that is a spurious
healthy window in the middle of an outage.

The guard logic is self-consistently wrong in an interesting way: `all_streams_healthy`
is evaluated against the *stale* map, so the machine reaches the right final state
for the wrong reason, purely because the deferred event arrives to correct it. Remove
the deferral and the bug becomes permanent; keep it and you get a flap.

**Fix (our side, one line of JSON):** add to `states.degraded.on` —

```jsonc
"STREAM_UNHEALTHY": { "actions": ["mark_stream_unhealthy"] }
```

An internal, targetless transition: it updates the map, stays in `degraded`, and
removes both the stale-context window and the flap. Verified by construction — with
this handler the second failure is applied immediately and `STREAM_HEALTHY(trade)`
correctly leaves the machine in `degraded`.

> Note `B11-d-hz3` **PASSes** as written: when only `trade` recovers, the machine does
> end in `degraded`. The invariant's *outcome* survives; its *reasoning* does not, and
> the intermediate states are wrong. This is the kind of defect that a state-only
> assertion misses and a trace assertion catches.

### B12 ReplaySession — 7/7 PASS, no defects

| Invariant | Verdict | Evidence |
|---|---|---|
| Happy path | **PASS** | `created→buffering→paused→playing→paused→(step)→paused→finished→destroyed` exactly as specified |
| **INV-B12-b** (cursor monotonic) | **PASS** | 500 → 999 forward via `STEP`; only `SEEK` rewinds (→200), and only through `buffering` |
| **INV-B12-c** (slow ≠ lossy) | **PASS** | 3× `CONSUMER_SLOW` → speed 1.0→0.125, `on_event_dropped` never fired, stays `playing` |
| **INV-B12-d** (gaps explicit) | **PASS** | `coverage_gaps` from `seek_and_prime` surfaced verbatim, no interpolation |
| **INV-B12-a** (loop) | **PASS** | `RANGE_END` + `loop_enabled` → re-buffers, `reset_cursor_to_start` fires |
| **INV-B12-e** (destroyed final) | **PASS** | terminal; later `PLAY` dropped with a clear log, state unchanged |
| `CANCEL` during `buffering` | **PASS** | a slow `seek_and_prime` cancelled mid-flight **never lands**: cursor stays 0, not 4242. The abandoned invoke cannot mutate state after cancellation |

That last one is worth calling out — it is the classic replay-session race (user
seeks away while a prime is in flight) and the library handles it correctly.

### B13 ExchangeConnection — reconnect/resync fully verified

| Invariant | Verdict | Evidence |
|---|---|---|
| Happy path, public | **PASS** | `disconnected→connecting→subscribing→live`, `ws_auth` skipped |
| Happy path, private | **PASS** | `is_private` inserts `authenticating`: `open_socket, ws_auth, subscribe_in_batches` |
| **INV-B13-a** (budget before socket) | **PASS** | `connection_budget_exhausted` → `budget_blocked`, **`open_socket` never called**; `BUDGET_RECHECK` → `disconnected` |
| **INV-B13-b** (backoff) | **PASS** | 500→1000→2000→4000→8000→16000→30000, **capped**, monotonic; resets to 500 **only** on reaching `live` |
| **INV-B13-c** (topics) | **PASS** | `subscribed_topics == pending_topics`; `TOPICS_CHANGED` re-subscribes and converges |
| **INV-B13-c** (partial batch) | **PASS** | a failing `subscribe_in_batches` → `backing_off`, **never `live`**, `subscribed_topics` empty |
| **Reconnect/resync (full)** | **PASS** | `live →SOCKET_CLOSED→ backing_off →BACKOFF_DUE→ connecting → subscribing → live`; topics restored identically; `emit_feed_degraded` and `notify_dependents_degraded` each fire exactly once |
| **INV-B13-e** (pong) | **PASS** | `PONG` stamps + re-arms; `PONG_DEADLINE` → `backing_off` with `record_pong_timeout` |
| `TOPIC_STALE` | **PASS** | forces reconnect |
| `SHUTDOWN` | **PASS** | `live → closing → closed` (final), `close_socket` invoked |

The reconnect/resync sequence the brief asks about is **correct end-to-end**,
including the degraded-notification fan-out and topic restoration.

### B14 book health

| Invariant | Verdict | Evidence |
|---|---|---|
| Happy path | **PASS** | deltas 5,6,7 buffered; `SNAPSHOT(seq=6)` installs and replays **only seq 7** — strictly after `snapshot_seq`, exactly per INV-B14-d |
| **INV-B14-c** (no delta across a gap) | **PASS** | `SEQUENCE_GAP` → `desynced` → (`always`) → `snapshot_pending`; buffer cleared, `resync_count` bumped, `desynced_since_us` stamped, **no further `apply_delta`** |
| **INV-B14-e** (resync visible) | **PASS** | `SNAPSHOT_TIMEOUT` re-enters `snapshot_pending` (`reenter: true` works), bumps `resync_count`, re-requests |
| **INV-B14-d** (buffer bounded) | 🔴 **FAIL** | see below |

#### 🔴 OUR-B14-01 — the bounded buffer is prose-only (contract defect)

INV-B14-d requires the pending-delta buffer to be **bounded** (C-2.18). 1000 `DELTA`
events sent with `wait=True` while in `snapshot_pending` produced
`len(buffered_deltas) == 1000` — growth is exactly 1:1 with input, with no engine-level
drop. Searching the B14 JSON for `max`/`bound`/`limit`/`cap` returns **nothing**.

This is not a library defect: `buffer_delta` is our action, and the library faithfully
runs it. But the invariant is **entirely unenforced by the contract** — it is
delegated, silently, to an implementation that does not exist yet. A symbol that never
receives its snapshot buffers unboundedly until the process dies. On the ingestion
path, during an exchange incident, that is the worst possible moment.

Note the library *does* bound its own deferral buffer (`DEFER_MAX = 1000`, evicting
oldest and reporting via `on_event_dropped(reason=...)`). Our contract's buffer has no
such discipline.

**Fix (our side):** the bound belongs in the `buffer_delta` implementation *and* in the
contract as an explicit, reviewable constant — plus a drop/resync policy when it is hit
(re-request the snapshot rather than silently discard, so INV-B14-c is not violated by
the overflow path itself). Recommend a `maxBufferedDeltas` key in the B14 `context` so
the linter can see it.

### B15 paper-account liquidation — 4/4 PASS

| Invariant | Verdict | Evidence |
|---|---|---|
| Happy path | **PASS** | `active → margin_call → active` on band change; `emit_margin_warning` once |
| **INV-B15-b** (terminal) | **PASS** | once `liquidated`, a favourable `MARK_UPDATE` **cannot revive**; state stays `liquidated` |
| **INV-B15-c** (journal before settle) | **PASS** | `_journal == ["haircut", "journal"]` — both entry actions complete on `liquidating` before the `always` lands on `liquidated`. **A liquidation is always journalled** |
| **INV-B15-a** (kill-switch preemption) | **PASS** | 50 queued non-liquidating marks + one `send_priority` liquidating mark → machine reaches `liquidated`; the priority lane preempts a busy inbox as required |

The `send_priority` result is the B18-style kill-switch mechanism the brief asks about,
demonstrated on the machine in this group that has a genuine safety-critical preemption
requirement. It works.

---

## 4. Step 3 — snapshot / restore at every macrostep

`g3_snapshot.py`. For each machine: run the script uninterrupted, then run it again
**snapshotting at quiescence after every macrostep, stopping the interpreter,
restoring into a fresh one via `from_snapshot(..., restart_timers=True)`, and
resuming from there.** Compare state ids and context at every mark.

| Machine | Macrosteps | `SnapshotMidStepError` | State divergences | Context divergences | Restore drift | Final state (both runs) |
|---|---|---|---|---|---|---|
| B11 | 6 | **0** | 0 | 0 | 0 | `recording.stopped` |
| B12 | 7 | **0** | 0 | 0 | 0 | `replay.finished` |
| B13 | 6 | **0** | 0 | 0 | 0 | `ws_conn.closed` |
| B14 | 6 | **0** | 0 | 0 | 0 | `book.live` |
| B15 | 2 | **0** | 0 | 0 | 0 | `paper_account.margin_call` |

**32 snapshot/restore cycles, zero mid-step refusals, zero divergence.** The
requirement — "must never raise `SnapshotMidStepError`" — **holds**. This is the
#102 contract working as designed: quiescence (`queue_depth == 0 and
deferred_count == 0`) is a sufficient precondition for a legal snapshot, which is
precisely what **CV-C20** mandates. The round-4 fix is doing its job on real
contract machines, including across invoke boundaries (B11's `subscribe_streams`,
B13's four services) and a transient `always` (B14 `desynced`, B15 `liquidating`).

> ⚠️ **Harness note worth recording:** `Interpreter.from_snapshot()` returns an
> **unstarted** interpreter. Omitting the subsequent `await it.start()` hangs every
> later `send(wait=True)` until timeout. This is correct and documented behaviour,
> but it is an easy and silent-until-timeout mistake — `cv.statechart.persistence`
> should wrap restore+start as one call so no caller can get it wrong.

---

## 5. Step 4 — engine parity (informational)

`g3_parity.py`. Identical scripts on `Interpreter` and `SyncInterpreter`,
comparing the full state sequence, final context, and the complete ordered action trace.

| Machine | States match | Context match | **Action trace match** |
|---|---|---|---|
| B11 | ✓ | ✓ | ✓ |
| B12 | ✓ | ✓ | ✓ |
| B13 | ✓ | ✓ | ✓ |
| B14 | ✓ | ✓ | ✓ |
| B15 | ✓ | ✓ | ✓ |

**5/5 full parity, including action ordering.** The round-4 parity work (#116, #99,
#120, #122–#124, #129) holds up on these five machines. Sync remains
parity-info-only per house rules, but nothing here argues against it.

---

## 6. Defect register

### 🟠 LIB-01 — an `onUnhandled: "error"` kill is invisible to the sender

**Classification: LIBRARY defect (observability). Narrow but sharp.**
**Affects B13 and B14** — both mandated `onUnhandled: "error"` by §1.3b.

Standalone repro, no project machinery: `repro/g3_onunhandled_error_silent.py`
(20 lines, `create_machine` + `MachineLogic()` only).

When an event matches nothing under `onUnhandled: "error"`, the library calls
`_fail(UnhandledEventError(...))`: status → `"error"`, the run loop stops, the
machine is dead. Correct and intended. **But the `Receipt` returned by the
`send(wait=True)` that caused it reports:**

```
Receipt(state_ids=frozenset({'m.b'}), changed=False, error=None, deferred=False)
```

`error=None`, `changed=False`, `deferred=False` — **byte-identical to a benign
no-op**. `interpreter.last_error` is also `None` (it is gated on
`last_transition_ok`, which this path never clears).

The error *is* observable — `interpreter.error` holds the `UnhandledEventError` and
`status == "error"` — so this is **not** a silent-data-loss bug, and the correction
matters: my first pass over-claimed here before checking `.error`. But a caller
holding a receipt has no reason to poll `.status` after a send that reports success.
The *next* send is honest (`InterpreterStoppedError`), so the failure surfaces one
event late — after the caller has already acted on a clean receipt.

Reproduced identically on B13 (`CONNECT` re-sent in `live`) and B14
(`UNSUBSCRIBE` in `snapshot_pending`): both die, both return a clean receipt, both
leave `last_error is None`.

**Why it matters for us:** this is the same shape as the withdrawn CV-C06 clause and
`M-1-deferred-event-receipt-false-negative` — *the receipt cannot distinguish
outcomes that matter*. §1.3b already bans `changed=False, error=None` as a gate on
`defer` machines. **This finding extends the identical prohibition to `error`
machines**, where the stakes are higher: on `defer` the machine survives, here it is
already dead.

**Suggested library fix:** populate `receipt.error` with the `UnhandledEventError`
for the event that triggered `_fail`. The information exists at the call site; it is
simply not threaded into the receipt.

**Wrapper spec (required regardless — do not wait for the library):**
`cv.statechart.gateway.send()` must, after every `wait=True` send to a machine
configured `onUnhandled: "error"`, assert `interpreter.status == "running"` and
raise if not, attaching `interpreter.error`. Cheap (one attribute read), and it
converts a one-event-late failure into an immediate one. Register as **CV-C23**.

### 🔴 OUR-01 — B11 `degraded` drops concurrent stream failures

**Classification: OUR-CONTRACT defect. Violates INV-B11-d.** Full analysis in §3.
Fix is one internal transition in `states.degraded.on`. Not a library issue —
the library deferred the event exactly as `onUnhandled: "defer"` instructs.

### 🔴 OUR-02 — B14's bounded buffer is unenforced prose

**Classification: OUR-CONTRACT defect. INV-B14-d is not expressed in the contract.**
Full analysis in §3. Unbounded memory growth on a stalled resync.

### 🔴 OUR-03 — the "dead but harmless" A3 wildcard silently disables `strict`

**Classification: OUR-CONTRACT defect. Refutes a standing claim in §1.3b (E50-T09).**

`g3_b13.py::B13-strict` found that on B13 — `strict: true`, the most locked-down
policy in the catalogue — **every** garbage event name is accepted without error:
`NOT_A_REAL_EVENT`, `after.party`, `done.invoke.bogus`, `xstate.bogus`.

Root-caused in `g3_wildcard.py`. It is **not** a library bug. `MachineNode.known_events`
collects declared descriptors; `is_known_event()` returns `True` immediately if
`"*" ∈ known_events`. The leftover **A3 scaffolding `"*": {"actions": ["defer"]}`
handler** — which §1.3b describes as *"dead but harmless"* and defers removal to
E50-T09 — puts `"*"` into `known_events`. **One wildcard anywhere in the machine makes
every event name known machine-wide, so `strict` becomes a no-op for the entire
machine.**

Measured across the group:

| Machine | has `"*"` | wildcard location | `is_known_event("TYPO_XYZ")` | `strict` effective? |
|---|---|---|---|---|
| B11 | no | — | `False` | ✅ yes |
| **B12** | **yes** | `buffering` | **`True`** | ❌ **defeated** |
| **B13** | **yes** | `subscribing` | **`True`** | ❌ **defeated** |
| B14 | no | — | `False` | ✅ yes |
| B15 | no | — | `False` | ✅ yes |

Deleting the one dead `"*"` handler from B13's `subscribing` state restores correct
behaviour immediately — all three garbage names then raise `UnknownEventError`
(`STAR-3` PASS).

**This is the more serious of the two B13 findings.** The scaffolding is *not*
harmless: it silently disables one of the six mandatory policy keys on the two
machines that carry it, and it does so invisibly — the key is present in the JSON,
binds correctly to `machine.strict == True`, and does nothing. On B13, a control
machine with `onUnhandled: "error"`, that also means a typo'd event name reaches the
unhandled path and **kills the machine** (LIB-01) instead of being rejected at the
call site where it belongs.

**Fix:** E50-T09 is not cosmetic cleanup and should not wait for the conformance
harness. Strip the `"*"` handler (and the `defer`/`drain_deferred` actions) from
B12 and B13 now; the runtime's `onUnhandled: "defer"` buffer already does this job.
Add **CV-LINT-XS15**: *no machine may declare a bare `"*"` descriptor while
`strict: true`* — the two are mutually exclusive by construction, and the linter can
prove it statically.

---

## 7. Verdict

**The library is fit for these five contracts.** No `InvalidConfigError`, no JSON
fix-up copy required, all six policy keys honoured, snapshot/restore clean at every
macrostep across 32 cycles, full async/sync parity including action ordering, and
every reconnect/resync, linger, buffering, liquidation and backoff invariant holding
as specified. The round-4 fixes (#102 mid-step refusal, #116 parity, #128
`restart_timers`) demonstrably work on real contract machines.

**Three of the four defects are ours.** Two are ordinary contract gaps (B11's missing
handler, B14's unenforced bound). The third — OUR-03 — is the one to act on: a piece
of scaffolding the catalogue explicitly documents as harmless is disabling `strict`
on two machines, including the one control machine where a rejected typo is the
difference between an exception at the call site and a dead connection manager.

**One library defect (LIB-01)** is real but narrow, and the wrapper for it is two
lines. It is worth filing because it is the third instance of the same
receipt-cannot-distinguish-outcomes pattern (with #84 and the withdrawn CV-C06
clause), which suggests the receipt contract deserves a design pass rather than a
third point fix.

### Actions

| # | Action | Owner | Priority |
|---|---|---|---|
| 1 | Strip the A3 `"*"` scaffolding from B12 + B13; add **CV-LINT-XS15** (`"*"` ⊕ `strict`) | catalogue / linter | **high** |
| 2 | Add `STREAM_UNHEALTHY` internal transition to B11 `degraded` | catalogue | **high** |
| 3 | Express B14's delta-buffer bound in the contract + define the overflow→resync policy | catalogue | **high** |
| 4 | **CV-C23**: gateway asserts `status == "running"` after every `wait=True` send to an `onUnhandled: "error"` machine | `cv.statechart` | **high** |
| 5 | File LIB-01 upstream: thread `UnhandledEventError` into the triggering `Receipt` | library | medium |
| 6 | `cv.statechart.persistence` wraps `from_snapshot` + `start()` as one call | `cv.statechart` | medium |
| 7 | Amend §1.3b: the A3 scaffolding is **not** "dead but harmless" — it defeats `strict` | catalogue | medium |

### Scripts

| File | Purpose |
|---|---|
| `g3_harness.py` | stub `MachineLogic`, trace plugin, scenario runner |
| `g3_B11..B15.json` | contract JSON extracted verbatim from the catalogue |
| `g3_build.py` / `g3_policy.py` | construction + policy-key binding |
| `g3_b11.py` / `g3_b11_hazard.py` / `g3_b11_defer.py` | B11 invariants + the deferral hazard |
| `g3_b12.py` | B12 invariants |
| `g3_b13.py` / `g3_b13_unh.py` | B13 invariants + `onUnhandled`/`strict` characterisation |
| `g3_b14_b15.py` | B14 + B15 invariants |
| `g3_snapshot.py` | snapshot/restore at every macrostep vs uninterrupted run |
| `g3_parity.py` | async vs sync engine parity |
| `g3_wildcard.py` | root-cause of OUR-03 |
| `g3_confirm.py` | independent re-confirmation of all four findings |
| `repro/g3_onunhandled_error_silent.py` | standalone LIB-01 repro, no project code |
