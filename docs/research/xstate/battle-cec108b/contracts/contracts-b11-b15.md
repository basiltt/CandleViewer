# Contract machines end-to-end — B11–B15 vs `xstate-statemachine` @ `cec108b`

**Round-6 re-run of the group-3 contract battle** against the round-5 fix set
(#142–#162 + reopened #118/#122/#125/#133/#134, PR #141, PR #163).

| | |
|---|---|
| **Library** | `_ref/xstate-statemachine` @ `cec108b` (merge of #164, `fix/0.8.1-round5`; unreleased 0.8.1, `__version__` still `0.8.0`) |
| **Machines** | B11 `RecordingSession`, B12 `ReplaySession`, B13 `ExchangeConnection`, B14 `IngestionPipeline`, B15 `PaperMatcher` |
| **Source of truth** | `battle-3ed3099/contracts/<B>.machine.json` — byte-identical to the JSON re-used here as `g3_<B>.json` (verified) |
| **Engine** | `Interpreter` (async) primary, `SyncInterpreter` parity-info only |
| **Clock** | `SimulatedClock` throughout |
| **Config** | rollback / onUnhandled defer (order) + error (control) / guardErrorPolicy raise / strictTargets / strict / bounded inbox RAISE |
| **Date** | 2026-09-20 |
| **Scripts** | `g3_*.py` (prior suite, re-run verbatim), `r5_probes*.py` (new), `repro/*.py` (standalone) |

---

## 0. Headline

**The prior round's verdict holds: all five machines build from the catalogue
JSON unmodified and pass every stated invariant.** The 3ed3099 suite re-runs
with identical results — 32/32 snapshot/restore cycles clean, 5/5 engine parity,
zero `SnapshotMidStepError`.

**But probing the round-5 fixes on these machines surfaced three new LIBRARY
findings, one of them a Blocker**, plus a correction to a prior finding that was
a harness artefact rather than a library defect.

| ID | Class | Severity | One line |
|---|---|---|---|
| **LIB-R6-01** | LIBRARY | 🔴 **Blocker** | `actionErrorPolicy: "rollback"` + a raising entry action behind an `invoke.onDone` = unbounded hot re-invocation loop (~1300 service calls/sec, forever). Async only; sync is correct. |
| **LIB-R6-02** | LIBRARY | 🟠 High | `send_threadsafe` under `OverflowPolicy.RAISE` checks the bound against a stale `qsize()`, so the inbox bound is bypassed **precisely while the loop is busy**; excess events are accepted and silently never run, with no `on_event_dropped`. |
| **LIB-R6-03** | LIBRARY | 🟡 Low | Snapshot legality is validated via `state_ids` only; `configuration` — the second copy of the same fact — can be emptied independently and still restores live. |
| **LIB-01** (prior) | LIBRARY | 🟠 High | *Still open.* An `onUnhandled: "error"` kill is invisible to the sender: `Receipt(error=None, changed=False, deferred=False, denied=False)`. #153's new `denied` flag does not cover it. |
| **OUR-B11-01** (prior) | OUR-CONTRACT | 🟠 High | *Still open.* `degraded` has no `STREAM_UNHEALTHY` handler. #153 now makes it **detectable at the call site** (`denied=False, deferred=True`). |
| **OUR-B14-01** (prior) | OUR-CONTRACT | 🟠 High | *Still open.* INV-B14-d's "bounded buffer" is prose-only; 1000 deltas buffer 1:1. |
| ~~B13-strict~~ | **RETRACTED** | — | Prior round reported `strict` as a false negative on B13. It was a **harness defect** — see §5. |

**CV-C32 (all services `async def`) can be relaxed**: #149 is genuinely fixed —
see §4.

---

## 1. Re-run of the 3ed3099 suite (regression check)

Every prior script re-run unmodified on `cec108b`:

| Suite | Script | 3ed3099 | cec108b |
|---|---|---|---|
| Build / policy binding | `g3_build.py` | 5/5 | **5/5** |
| B11 invariants | `g3_b11.py` | 7/7 | **7/7** |
| B11 hazards | `g3_b11_hazard.py` | 8/10 | **8/10** (same 2 = OUR-B11-01) |
| B12 invariants | `g3_b12.py` | 7/7 | **7/7** |
| B13 invariants | `g3_b13.py` | 10/12 | **10/12** (1 = LIB-01, 1 = harness, §5) |
| B14 + B15 | `g3_b14_b15.py` | 7/9 | **7/9** (1 = OUR-B14-01, 1 = LIB-01) |
| Snapshot/restore | `g3_snapshot.py` | 5/5 | **5/5, 0 mid-step errors** |
| Async vs sync parity | `g3_parity.py` | 5/5 | **5/5** |

**No regressions.** All six mandatory policy keys still bind
(`spawn_blocking_timeout_ms == 5000.0` on every machine — it is exposed on the
machine object, not under the name the old probe looked for, hence the
`"ABSENT"` in `results/g3_build.json`; verified directly).

---

## 2. 🔴 LIB-R6-01 — rollback + `invoke.onDone` into a failing entry = unbounded spin

**Classification: LIBRARY. Severity: Blocker.**
**Repro:** `repro/rollback_invoke_respawn_spin.py` (40 lines, library only).
**Probes:** `r5_probes4.py` → `R5-RB1`, `R5-RB4`.

`actionErrorPolicy: "rollback"` is **mandated on every contract machine** by
§1.3b. B11's shape is the trigger:

```
starting --invoke subscribe_streams--> onDone --> recording
recording.entry = [cancel_linger, emit_recording_metric]
```

Let `emit_recording_metric` raise — a metrics sink being down is a mundane,
recoverable failure. Rollback undoes the transition and returns the machine to
`starting`. Re-entering `starting` **re-arms the invoke**, `subscribe_streams`
runs again, completes, `onDone` fires, entry raises, rollback, … with nothing
bounding the loop.

Measured on B11 (`R5-RB1`, `emit_recording_metric` attempts sampled every 250 ms):

```
315 → 648 → 974 → 1309 → 1635 → 1975 → 2303 → 2640     (still growing)
state = ['recording.starting']   status = 'running'   queue_depth = 1
subscribe_streams invocations = 2641
```

**~1300 real service invocations per second, indefinitely, for one user event.**
`subscribe_streams` is an exchange subscription. This is a self-inflicted DoS on
the venue, and the machine reports `status="running"` throughout.

Nothing catches it. `R5-RB4` confirms: no `RunawayChainError`, no settle-budget
trip, `interpreter.error is None`. The chain budget does not apply because every
lap is a *separate macrostep* driven by a genuine engine completion
(`done.invoke.sub`), not a self-generated event — precisely the case the #144
fix ("a chain ends only when nothing self-generated remains queued") excludes by
construction.

Worse for triage: the machine stays *responsive*. `R5-RB4` sends an unrelated
`REASON_ADDED` mid-spin and it is served in 0.00 s with `changed=True`. Liveness
probes, health checks and the inbox all look perfectly healthy while the spin
runs. The only symptom is CPU and outbound call volume.

### Policy and engine matrix

Minimised machine, 1 s of wall clock:

| `actionErrorPolicy` | `Interpreter` (async) | `SyncInterpreter` |
|---|---|---|
| **`rollback`** (mandated) | **1440 invocations**, `starting`, `running` | **2 invocations**, `starting`, `running` |
| `continue` | 1, `recording`, `running` | 1, `recording`, `running` |
| `fail` | 1, `[]`, `stopped` | 2, `[]`, `stopped` |

Two things fall out:

1. **The spin is specific to the policy our contract mandates.** `continue` and
   `fail` are both bounded.
2. **It is an engine-parity break.** The sync engine retries exactly once and
   stops; the async engine retries for ever. `g3_parity.py` still reports 5/5
   because the parity script drives only happy paths — parity on the *failure*
   path was never covered.

`R5-RB2` (B15 `liquidating.entry` raising, `always` target) and `R5-RB3` (B14
`desynced.entry` raising) both **terminate correctly**. The spin needs the
`invoke` re-arm; a plain `always` does not reproduce it. That is why 32 clean
snapshot cycles and 7/7 B11 invariants missed it — it only appears when an entry
action on an invoke's `onDone` target fails, which no happy-path scenario does.

### Blast radius on the catalogue

Every machine with `invoke.onDone → state-with-entry-actions` is exposed:
**B11** (`starting→recording`, 2 entry actions), **B12**
(`buffering→paused`/`stepping→paused`, `drain_deferred`), **B13**
(`connecting→…`, `subscribing→live` with **4** entry actions incl.
`emit_feed_healthy`), **B14/B15** indirectly. B13's `live` entry is the worst
case: a failing `emit_feed_healthy` would spin `open_socket` +
`subscribe_in_batches` against the exchange at four-figure rates.

### Required mitigation (NEEDS-WRAPPER until fixed upstream)

Until the library bounds this, `cv.statechart` **must not** rely on rollback
alone. Minimum viable guard:

- A supervisor that counts entries into any given state per unit time and halts
  the interpreter past a threshold (the catalogue's explicit `halted` states are
  the right landing zone).
- Entry actions on invoke-completion targets must be **total** — wrap every
  metrics/telemetry emit in a `try/except` at the implementation level so it can
  never be the thing that raises. This is the cheap fix and it is worth doing
  regardless.

Upstream, the fix is to charge a rolled-back transition to a budget so repeated
rollback of the *same* transition trips `RunawayChainError`, matching the sync
engine's behaviour.

---

## 3. 🟠 LIB-R6-02 — the threadsafe inbox bound is checked against a stale depth

**Classification: LIBRARY. Severity: High.**
**Repro:** `repro/threadsafe_bound_bypassed_when_loop_busy.py`.
**Probes:** `r5_probes5.py` → `R5-157`; `r5_probes6.py` → `R5-157b`, `R5-157c`.

§1.3b mandates a **bounded inbox with `OverflowPolicy.RAISE` on the order path**.
#157 moved the refusal to the calling thread, which is right. But
(`interpreter.py` ~1118):

```python
if not self_issued and self._overflow_policy is OverflowPolicy.RAISE \
        and self._inbox_is_full():
    raise QueueOverflowError(...)
```

`_inbox_is_full()` reads `self._event_queue.qsize()`. The **enqueue** happens
later, in `_deliver()`, dispatched via `asyncio.run_coroutine_threadsafe`. While
the loop thread is busy no `_deliver` runs, so `qsize()` stays at its pre-burst
value and every check passes regardless of how many sends are already in flight.

B15 with `max_queue_size=3, RAISE`, 3000 cross-thread `MARK_UPDATE` sends:

| loop state during the burst | accepted | `QueueOverflowError` | actually processed |
|---|---|---|---|
| **blocked 1.0 s** | **3000** | **0** | **3** |
| idle (yields between sends) | 26 | 2974 | 24 |

The bound works when nothing is happening and **fails when the system is under
load** — the exact inversion of what backpressure is for. And the excess is not
merely late: 497 of 500 events in the standalone repro were accepted, never ran,
and **`on_event_dropped` never fired**. From the caller's side those sends
succeeded.

This is silent event loss on a path our contract designates as the order path.
The pinned test (`test_round5_findings.py::test_raise_policy_raises_at_call_site_when_full`)
pre-fills the queue with awaited `send()`s from the loop thread itself, so
`qsize()` is accurate when the worker thread checks it — the idle-loop case,
which does work.

`R5-157c` confirms the **async `send()` path is correct**: 50 un-awaited sends
into a 3-slot RAISE inbox gave 47 `QueueOverflowError` at the call site, because
that path enqueues synchronously. The defect is specific to `send_threadsafe`.

**Mitigation:** `cv.statechart` should not use `send_threadsafe` for order-path
ingress. Route foreign threads through a bounded queue the wrapper owns and
drain it from a loop-side task using `await send(...)`.

---

## 4. ✅ #149 verified — CV-C32 ("all services `async def`") can be relaxed

**Probes:** `r5_probes.py` → `R5-149a`, `R5-149b`. Both PASS.

CV-C32 exists because #116 made plain-`def` services run inline on the loop.
#149 moved them to `Interpreter(service_executor=...)`. Tested on B11 with
`subscribe_streams` as a blocking `def` that sleeps 600 ms:

- **`R5-149a`** — an independent coroutine ticked **49 times in 500 ms** while
  the service ran. The loop kept turning. The machine still reached
  `recording.recording`.
- **`R5-149b`** — a `REASON_ADDED` sent mid-service returned in **0.00 s**
  (service duration 500 ms) and was applied in order: `reasons == ["alerts",
  "chart"]`. #116's ordering guarantee survives; the inbox is not stalled.

**Verdict:** CV-C32 may be downgraded from a hard rule to a preference. Keep
`async def` where the work is genuinely I/O-bound (it avoids an executor hop),
but a blocking third-party client in a service is no longer a liveness hazard.
Note the executor is a small **owned `ThreadPoolExecutor`** by default — pass an
explicit, sized executor if services can be slow and concurrent.

---

## 5. Retraction — the prior "B13 `strict` false negative" was a harness defect

The 3ed3099 report recorded `strict=true` failing to reject undeclared event
names on B13 (`NOT_A_REAL_EVENT`, `after.party`, `done.invoke.bogus`,
`xstate.bogus` all "ACCEPTED"). **That was our bug, not the library's.**

`g3_b13_unh.py` reuses one interpreter: it first sends a `CONNECT` into `live`,
which under `onUnhandled: "error"` **kills the machine** (`status="error"`). All
four subsequent sends were dropped by the not-running guard, which runs *before*
`_check_strict`, so they never reached the strict check.

`r5_probes3.py::R5-strict` re-tested on a **fresh** machine per name and still
showed ACCEPTED — because the probe itself repeated the kill. `r5_probes2.py::R5-153b`
settled it incidentally: on a live B15, `send("NO_SUCH_EVENT")` raises

```
UnknownEventError: Event 'NO_SUCH_EVENT' is not declared by machine
'paper_account'. Known events: MARK_UPDATE.
```

**`strict` works correctly at the call site.** The prior finding is retracted.

The real lesson is a hazard worth keeping: **once `onUnhandled: "error"` has
killed a machine, every later `send` is silently dropped** — no raise, no strict
check, only a WARNING log. Combined with LIB-01 (§6) a caller can kill a machine
and keep sending into the void without a single call-site signal.

---

## 6. Round-5 fixes confirmed on the contract machines

| Fix | Probe | Result |
|---|---|---|
| **#153 `Receipt.denied`** | `R5-153a` (B15, both `MARK_UPDATE` guards false) | ✅ `denied=True`, stays `active`, **not** parked by `onUnhandled: defer`. Declared-but-denied is now distinct from undeclared. |
| **#153 on OUR-B11-01** | `R5-153c` | ✅ `STREAM_UNHEALTHY` in `degraded` → `denied=False, deferred=True, deferred_count=1`. The contract defect now has a **caller-visible signature**, which it did not at 3ed3099. |
| **#152 guard raise, engine-driven** | `R5-152` (B13, `is_private` raises on `connecting.onDone`) | ✅ unguarded fallback taken → `subscribing`; completion **not** lost; exception on `last_error`/`last_transition_ok`; machine still running. |
| **#152 guard raise, caller-driven** | `R5-152b` (B15) | ✅ `RuntimeError` delivered to the `await send(wait=True)` call site; interpreter survives. |
| **#145 `actionErrorPolicy: "fail"`** | `R5-145` (B11) | ✅ `status="stopped"`, configuration `[]`, `TransitionFailedError` retained on `.error`, and the snapshot records `status=stopped` + empty config — not resumable-looking. |
| **#146/#143 hostile snapshots** | `R5-142b` (B13, 10 mutations) | ✅ 8/10 rejected with precise `SnapshotCorruptError` messages (`status` non-str, `error` status with no error, `version`/`deferred`/`history`/`actors` wrong type, non-`str` pending `type`). 2 gaps → LIB-R6-03. |
| **#162 pending-event provenance** | `R5-162` (B11) | ✅ a deferred `STREAM_HEALTHY` round-trips as a user event with its payload intact. |
| **rollback, contained cases** | `R5-rollback`, `R5-RB2`, `R5-RB3` | ✅ context and state correctly restored; machine stays usable; B14/B15 `always` shapes terminate. (B11's invoke shape does not — §2.) |

---

## 7. 🟡 LIB-R6-03 — `configuration` is never cross-validated against `state_ids`

**Classification: LIBRARY. Severity: Low.**
**Repro:** `repro/snapshot_configuration_unchecked_when_state_ids_present.py`.

A persisted snapshot stores the active configuration **twice**:

```
state_ids     : ['m.b']            (leaves)
configuration : ['m', 'm.b']       (ancestors + leaves)
```

#142/#143's read-side legality check keys on `state_ids`. Mutating both keys is
correctly refused; mutating **only `configuration`** is not:

| mutation | result |
|---|---|
| both emptied | `SnapshotCorruptError` ✅ |
| both set to a non-leaf | `SnapshotCorruptError` ✅ |
| `configuration` emptied, `state_ids` intact | **ACCEPTED**, restores live in `m.b` |
| `configuration` garbled to an unknown id | `StateNotFoundError` (incidental) |
| `configuration` not a list | `SnapshotCorruptError` ✅ |

Not a blocker: `state_ids` is what drives the restore, so the machine is
functionally correct. But the library has promised to detect an illegal
configuration on the read side, and a snapshot carrying an internal
contradiction walks through. Cheap fix: assert `set(state_ids) ⊆
set(configuration)` during `from_snapshot`.

---

## 8. Still-open prior findings (re-confirmed on `cec108b`)

### 🟠 LIB-01 — an `onUnhandled: "error"` kill is still invisible to the sender

`r5_probes3.py::R5-unh-recv`, B13 in `live`, sending a declared-but-unhandled
`CONNECT`:

```
receipt : Receipt(state_ids={'ws_conn.live'}, changed=False,
                  error=None, deferred=False, denied=False)
status  : error
.error  : UnhandledEventError("Event 'CONNECT' is not handled ...")
.last_error : None
hook    : on_unhandled_event -> ('CONNECT', 'errored')
```

#153's `denied` flag reports `False` here — correct by its own definition
(nothing was guard-denied) but it means the receipt is **still byte-identical to
a benign no-op** for the send that killed the machine. #159's
`on_invalid_event`/`on_snapshot_error` hooks do not cover this path either; only
`on_unhandled_event` fires, and a receipt-holding caller never sees it.

**Affects B13 and B14**, both mandated `onUnhandled: "error"`. Combined with the
§5 hazard (post-kill sends are dropped silently), a control-path caller can kill
a machine and keep sending with zero call-site feedback.

**Mitigation (NEEDS-WRAPPER):** `cv.statechart`'s send wrapper must check
`interpreter.status` after every `wait=True` send on an `onUnhandled: "error"`
machine and raise on `"error"`. This is mandatory, not optional.

### 🟠 OUR-B11-01 — `degraded` has no `STREAM_UNHEALTHY` handler

Unchanged and still reproducing (`g3_b11_hazard.py`, 8/10). A second stream
failing while already `degraded` is parked, `streams_healthy` lags reality, and
the next `STREAM_HEALTHY` flaps the machine through `recording` — emitting a
healthy metric mid-outage. Fix is one line of JSON:

```jsonc
"STREAM_UNHEALTHY": { "actions": ["mark_stream_unhealthy"] }
```

in `states.degraded.on`. **#153 upgrade:** the failure is now detectable at the
call site (`denied=False, deferred=True`), so the wrapper can assert on it.

### 🟠 OUR-B14-01 — INV-B14-d's "bounded buffer" is prose-only

Unchanged: 1000 `DELTA` events in `snapshot_pending` → `len(buffered_deltas) ==
1000`, no engine drop, and no `max`/`bound`/`limit` key anywhere in the B14 JSON.
The bound belongs in `buffer_delta` **and** as a reviewable `maxBufferedDeltas`
context key so the linter can see it, with a re-snapshot (not a silent discard)
on overflow.

---

## 9. Classification summary

| Finding | LIBRARY | OUR-CONTRACT | NEEDS-WRAPPER |
|---|---|---|---|
| LIB-R6-01 rollback/invoke spin | ✅ Blocker | — | ✅ until fixed: total entry actions + re-entry supervisor |
| LIB-R6-02 threadsafe bound stale | ✅ High | — | ✅ own the cross-thread queue, don't use `send_threadsafe` on the order path |
| LIB-R6-03 `configuration` unchecked | ✅ Low | — | — |
| LIB-01 `onUnhandled: error` receipt | ✅ High | — | ✅ check `.status` after every send |
| OUR-B11-01 `degraded` handler | — | ✅ | — |
| OUR-B14-01 unbounded delta buffer | — | ✅ | — |
| B13 `strict` | **retracted** | harness defect | — |

**Adoption impact.** The catalogue JSON remains valid and the library's
happy-path and invariant behaviour on all five machines is correct. But
**LIB-R6-01 is a new Blocker against the §1.3b mandated configuration** — the
combination of `actionErrorPolicy: "rollback"` and `invoke.onDone → entry
actions` is present on four of the five machines in this group, and an entry
action failing is not an exotic condition. The gate cannot pass on rollback
alone until this is bounded upstream or a re-entry supervisor is in place.
