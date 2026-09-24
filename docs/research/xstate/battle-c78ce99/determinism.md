# Battle-test track: DETERMINISM — `xstate-statemachine` @ `c78ce99` (unreleased 0.8.1, round-10 fixes #212–#216)

**Scope note (as in prior passes):** the brief's full spec (property
≥300 machines, concurrency at scale, 12-min soak, full fuzz/security
matrices) exceeds the ~20-min wall-clock bound by roughly an order of
magnitude. This pass (a) re-runs the entire inherited determinism script
suite against `c78ce99` on both service kinds where the script parametrises
one, (b) runs the pinned round-10 regression suite
(`tests/test_round10_findings.py`, 15 tests), and (c) adds **two new,
round-10-targeted attacks**: `i1` (the #212 delayed-raise-ping-pong
semantics reversal, both engines, 30 ms + 1 ms periods + a zero-delay
trip control) and `i2` (the v2-upcast-minting security question the brief
calls out as *the* question this round). Full-scale
concurrency/fuzz/soak per the letter of the brief is **not covered** —
see §4.

---

## 0. Bottom line

All inherited determinism-suite defects previously marked FIXED remain
FIXED on `c78ce99`. No regression observed in `d1`–`d10b`, `e1`, `f1`,
`f4`, `f5`, `g1`, `g6`, `n5b`, `n6`, `h1`, `h2`. The 15 pinned round-10
tests (`tests/test_round10_findings.py`) all pass. The two new attacks:

- **`i1` confirms #212 exactly as documented**: a 1 ms and a 30 ms
  `raise(delay=)` self-ping-pong runs indefinitely on both engines,
  exceeding `maxIterations` many times over with `last_error is None`;
  CPU is clock-bounded (the 1 ms sync case only reached ~575 beats in a
  1 s window because the sync engine's `tick()` must be pumped by the
  caller — see the caveat in §3.1); a zero-delay ping-pong control still
  trips `RunawayChainError` on both engines, confirming #212 did not
  weaken the same-step chain budget it was never meant to touch.
- **`i2` confirms the v2-upcast trust boundary does exactly what #214
  documents, including for `done`/`error` (not just `after`)**: a
  version-2, unflagged `done.invoke.<id>` / `error.platform.<id>` record
  with a matching `src` **is** upcast as engine-minted and drives
  `onDone`/`onError` even though no real invocation was ever pending
  that result; the identical record at the CURRENT version (v3) is
  correctly refused (stays parked in `wait`, `onDoneFired`/`onErrFired`
  stay 0). This is the intended, documented v2→v3 migration contract
  (`persistence.upcast`, "a v2 writer had exactly ONE minter... so a v2
  record of those kinds IS an engine completion") — **not a new
  defect** — but it is worth stating plainly as the answer to the
  brief's "does downgrading version alone... let a forged
  `done.invoke.*` drive an onDone that was never armed" question:
  **yes, if the caller also forges `version: 2`,** because v2 payloads
  by definition predate the untrusted-record possibility and are
  upcast unconditionally. A caller who does not trust the source
  snapshot must use `from_snapshot(minimum_version=3, ...)` (or
  `expected_machine_hash=`) to refuse a downgraded/legacy payload
  outright — confirmed working in a direct check (see §3.2).

**No new `D11-determinism-n` defects are raised this pass.**

---

## 1. Prior-defect re-run table (inherited d/e/f/g/h/n suite, on `c78ce99`)

| ID / script | Status on `19cb1f1` | Status on `c78ce99` | Evidence |
|---|---|---|---|
| `d1_replay.py` | STABLE | **STABLE** | exit 0, no diff |
| `d2_receipt_deferred.py` | 0/400 false positives, both engines | **UNCHANGED** — 0/400 both engines | |
| `d3_perturb.py` | STABLE | **STABLE** | 20/20 arrival order preserved, 0 lost |
| `d4_ordering.py` | all windows STABLE | **UNCHANGED** — C1–C10 STABLE incl. C9/C9s FIFO defer replay, C10 AFTER-before-DONE | |
| `d5_hashseed.py` | config/actors/value_keys seed-stable; raw parallel ordering varies by seed (expected) | **UNCHANGED** — same shape, 6 distinct raw orderings | |
| `d6_cross_engine.py` | 100% agreement | **UNCHANGED** — context/state/trace agree, S1–S5 | |
| `d7_hook_parity.py` | byte-identical hook trace | **UNCHANGED** — identical: True, 0 async/sync-only records | |
| `d9_snapshot_replay.py` | known constraint: resume-vs-straight-through diverge under heavy concurrent traffic | **UNCHANGED (same constraint)** | |
| `d10_concurrent.py` | T1/T2 ordered+drained; T3 unordered (constraint) | **UNCHANGED** — T1/T2 10/10 ordered/drained, T3 0/10 ordered (documented `send_threadsafe` constraint), 0 lost both | |
| `d10b_threadsafe_order.py` | 0/8 FIFO (constraint) | **UNCHANGED** — 0/8 FIFO, 8 distinct orderings | |
| `e1_internal_forgery.py` | 200/200 accepted (by design) | **UNCHANGED** — 200/200, 0 QueueOverflowError | |
| `f1_chain_vs_external.py` | tripped `RunawayChainError`, external accepted concurrently | **UNCHANGED** — tripped, 186 external accepted concurrently (count is workload-timing noise, not a regression signal) | |
| `f4_raise_dropped_hook_parity.py` | refused == hook fires | **UNCHANGED** — 4 accepted, 236 refused == 236 hook fires, parity True | |
| `f5_nested_parallel_snapshot_refusal.py` | all 3 windows REFUSED both engines | **UNCHANGED** — all 3 windows REFUSED both engines, ctx 999/888 | |
| `g1_async_chain_charged.py` | both kinds trip at n=1002 | **UNCHANGED** — both kinds trip at n=1002, parity True | |
| `g6_hash_and_config_fuzz.py` | 300/300 mutated snapshots refused | **UNCHANGED** — 100/100 null-hash, 100/100 absent-hash, 100/100 config/state_ids-mismatch, all refused | |
| `n5b_corrupt_escapes.py` | 0/9 untyped escapes | **UNCHANGED** — 0/9, all typed `SnapshotCorruptError` | |
| `n6_observability.py` | S2 API surface OK | **UNCHANGED** — leaked_keys=[], API surface OK; `version_string: 0.8.0` (package `__version__` not yet bumped — matches task framing) | |
| `h1_statestoinvoke_snapshot.py` | informative-not-decisive (round-9 caveat) | **UNCHANGED, same caveat** — pre_restore_calls=1, post_restore_calls=0, state=m.done, both kinds | Not re-litigated: still cannot capture genuinely pre-settle via public API. |
| `h2_snapshot_trust_boundary.py` | PASS | **UNCHANGED — PASS** — all 5 opt-in vectors behave as documented | |

**Zero-delay vs delayed raise, stated explicitly (round-10-specific):**
`f1` and `g1` both use **zero-delay** same-step self-raise/send chains
(confirmed by inspection: neither script's config contains a `delay`
key on its `raise`/`send`), so #212's supersession of #206 does **not**
apply to either — both correctly still trip `RunawayChainError`, exactly
as before. No script in the inherited suite exercised a *delayed*
self-raise ping-pong, so none needed relabeling SUPERSEDED; that gap is
what `i1` (new, below) fills.

Scripts not carried forward from the inherited suite this pass (same as
the `19cb1f1` pass, for the same time-budget reason): `f2`/`f2b`, `f3`,
`g2`–`g5`, `g7` (livelock fuzzer). No reason to expect regression;
unverified this pass (listed again in §4).

---

## 2. Round-10 pinned regression suite

```
C:/.../xstate-statemachine/.venv-main/Scripts/python -m pytest tests/test_round10_findings.py -q
15 passed in 8.04s
```

All 15 tests covering #212–#216 pass fresh at `c78ce99`, run as-is.

---

## 3. New attacks this pass

### 3.1 `i1_delayed_raise_pingpong.py` — #212 semantics matrix

Attack: build a two-state `raise(delay=<p>)` ping-pong (matching the
pinned test's exact `raise_cfg` shape) at `p=30` and `p=1`, run each on
both `Interpreter` (async) and `SyncInterpreter` for a 1 s real-time
window, and confirm (a) no `RunawayChainError`/`last_error`, (b) the
beat count exceeds `maxIterations=8` by a wide margin (the #212 claim),
(c) beats stay bounded by the clock period (not a busy-loop explosion).
A zero-delay ping-pong control (`maxIterations=50`) must still trip on
both engines.

```json
{
  "delayed_30ms_1s_window": {
    "async_n": 31, "sync_n": 33, "async_err": null, "sync_err": null,
    "must_not_trip": true, "must_exceed_maxIterations": true
  },
  "delayed_1ms_1s_window": {
    "async_n": 66, "sync_n": 554,
    "async_wall_s": 1.015, "sync_wall_s": 1.002,
    "must_not_trip": true, "beats_bounded_by_clock": true
  },
  "zero_delay_control": {
    "async_tripped": true, "sync_tripped": true,
    "must_trip_both": true
  }
}
```

Result: **confirms #212 exactly as documented on `c78ce99`.** Both
engines run the delayed heartbeat indefinitely past `maxIterations`
(31–66 beats in 1 s at 30 ms/1 ms nominal period — real-time jitter,
GIL and event-loop scheduling account for the sync engine's higher count
at 1 ms, since its `tick()` is pumped in a tight Python loop rather than
gated by an actual OS timer the way the async engine's `call_later` is);
neither reports an error. The zero-delay control still trips on both
engines with the documented `RunawayChainError` message ("exceeded 50
chained self-generated events in one macrostep"), confirming the
same-step chain budget #212 was never meant to touch is intact.

**Caveat:** `SyncInterpreter` has no autonomous timer thread — its
`raise(delay=)` only fires when something calls `.tick()` (documented
in `sync_interpreter.py`'s own docstring). The probe pumps `tick()` in
a tight `while` loop with a 1 ms `time.sleep()`, which is why its 1 ms
case (554 beats) ran faster than the async engine's own `asyncio`
`call_later`-driven case (66 beats) — this is a probe-harness artifact
of how the two engines are driven, not a defect; the async engine's
count is the one directly comparable to the pinned test's own
`test_reporter_cells` (`n >= 30` at period 30, 1.5 s window).

### 3.2 `i2_v2_upcast_forgery.py` — the v2-upcast minting security question

Attack (the brief's explicit "the question this round"): forge a
`done.invoke.<id>` / `error.platform.<id>` `pending_events` record with
no real invocation ever having produced it, at `src` matching the
declared invoke id (`inv.wait`), and vary only `version` (2 vs the
current v3) to see whether the engine treats the record as
engine-minted. Uses the ASYNC engine with a service that `await
asyncio.sleep(60)` — genuinely still pending at snapshot time, asserted
before the snapshot is taken — so any `onDone`/`onError` firing after
restore is necessarily the forged record, not a real completion racing
the snapshot.

```json
{
  "v2_forged_done_invoke": {"value": "done", "onDoneFired": 1, "last_error": null},
  "v3_forged_done_invoke": {"value": "wait", "onDoneFired": 0, "last_error": null},
  "v2_forged_error_platform": {"value": "failed", "onErrFired": 1, "last_error": null},
  "v3_forged_error_platform": {"value": "wait", "onErrFired": 0, "last_error": null}
}
```

Result: **the v2 forgery succeeds; the v3 forgery is refused.** This
matches `src/xstate_statemachine/persistence.py::upcast` precisely: for
`version < 3`, every `pending_events`/`deferred` record of kind
`done`/`error`/`after` gets `engine: True` set unconditionally (the
comment states the rationale explicitly: "a v2 writer had exactly ONE
minter of `done`/`error`/`after` records — the engine itself... so a v2
record of those kinds IS an engine completion"). `restore_event` then
builds `_EngineDone`/`_EngineError` instead of the public `DoneEvent`/
`ErrorEvent`, `is_system_event()` returns `True`, and
`_completion_is_for_live_invocation` — which does **not** check
liveness, only provenance (its own docstring: "a genuine completion is
by construction for a live invocation; a completion that reaches this
point for a state that was exited is impossible" — an argument that
holds for a *genuine* engine-minted record but not for a forged v2
one) — lets it through. At v3 the same record (no `engine` flag) stays
the public class, `is_system_event()` is `False`, and it is correctly
refused.

**This is not a new defect** — it is the documented, intentional
behavior of the v2→v3 migration boundary, and the library's own pinned
`test_v3_record_without_engine_flag_is_user_traffic` /
`test_pre_081_after_record_is_upcast_and_fires` establish the same
contract for `after`. What `i2` adds is confirmation that the *same*
unconditional-trust boundary applies to `done`/`error` completions too
— i.e., **a caller who can write `version: 2` into a snapshot they
control can mint an arbitrary `onDone`/`onError` transition that was
never armed**, exactly as the brief asks. This is squarely inside the
documented trust model stated in `from_snapshot`'s own docstring and
`SnapshotDriftError` remedy (#205): *a snapshot is trusted input by
contract*. A caller who does not trust the snapshot source has the
remedy already in hand and it works as advertised — confirmed directly:

```python
SyncInterpreter.from_snapshot(json.dumps(blob), m, minimum_version=3)
# -> SnapshotVersionError: "Snapshot version 2 is below the caller's
#    minimum_version=3. A payload this old carries no drift fingerprint;
#    refuse it, or lower the floor if the source is trusted."
```

`minimum_version=3` (or `expected_machine_hash=`) refuses the v2-shaped
forgery outright — the caller who opts in is protected; the caller who
does not opt in (the overwhelming majority, per the `19cb1f1` pass's
`h2` finding that this is opt-in, not default-on) is exposed to exactly
this vector. **Register note:** this is the same "DESIGN-CONSTRAINT,
wrapper obligation" framing the round-9 register gave #205 — restated
here because the v2-upcast path is a *second*, independent way the same
trust gap is reachable (not just a stale/mismatched hash, but a
deliberately downgraded `version` field), and it is not obviously
covered by anyone reading only the `after`-timer framing of the #214
changelog entry, which does not mention `done`/`error` by name in its
headline sentence.

---

## 4. Not covered this pass (explicit gaps against the brief)

- **Persistence:** the ≥300-random-machine v3 round-trip property
  (armed delayed self-sends at random remaining delays + `SimulatedClock`
  exactness); the full v2-fixture upcast matrix across all four record
  kinds × user-record control (only `done`/`error` forged-vs-legitimate
  was probed in `i2`; `after` is already pinned by the library's own
  suite); lane restore ordering under adversarial interleavings beyond
  the pinned `test_priority_lane_round_trips`; `machine_hash` coverage
  of `scheduled_sends` specifically (not independently probed — only the
  existing `g6` config/state_ids-mismatch fuzz ran).
- **Concurrency:** 200 machines × 1 ms `raise(delay=)` ping-pong for
  10 s (only a single-machine, 1 s version ran in `i1` — CPU-bounded
  claim not verified at the 200-machine / 10 s scale the brief asks
  for); mixed delayed+zero-delay chain trip check (not run this pass,
  though `i1`'s zero-delay control plus the inherited `f1`/`g1` give
  partial coverage of "zero-delay still trips"); `start()`
  descent-settle wait under 100 concurrent starts with `always` cycles;
  concurrent restore of 200 v3 snapshots with `scheduled_sends`.
- **Fuzz:** the livelock fuzzer at ≥500 configs × kinds × engines with
  the new delayed-raise-is-legal oracle (not run — `g7` was already
  dropped from the carried-forward suite in the `19cb1f1` pass for time,
  and updating its oracle for #212 plus running it at scale is a
  larger, separate task); the #216 config-key fuzzer (misspellings at
  top level and nested state level) — not run this pass at all.
- **Determinism:** the 50×-trace comparison across both engines/kinds
  including `scheduled_sends` restore and hash-seed — the inherited
  `d1`/`d3`/`d4`/`d5`/`d6`/`d7` give 20–25-run coverage of the
  non-`scheduled_sends` case only; no script this pass exercises a
  `scheduled_sends`-bearing snapshot through the determinism suite's
  replay/perturb/cross-engine harnesses.
- **Semantics:** the full #212 rule matrix (delay 0 / 1 ms / `sendTo`
  child / `cancel(id)` / delayed raise from an external send) vs the
  `after`-rule parity claim — `i1` covers delay 0 and delay 1 ms/30 ms
  self-raise only; `sendTo`-to-child and `cancel(id)` interaction with
  the new timer semantics are pinned by the library's own
  `test_cancelled_send_leaves_no_record` but not independently
  re-attacked here. The #214 restore-strict matrix beyond
  `done`/`error`/`after` (e.g. a forged `lane` field on restore,
  redaction of forged data) — the `restore of forged lane field`
  security item from the brief was **not** independently probed this
  pass.
- **Observability:** `on_invalid_event` on restore exactly-once,
  `last_error`/receipt semantics under a forged record, and the #216
  warning-text/did-you-mean-hint wording — none independently
  re-verified this pass (covered only by the pinned suite's own
  assertions, e.g. `test_restore_applies_strict_to_restored_events`).
- **Security:** `strict_config` bypass via an `x-`-prefixed key;
  redaction of a forged/sensitive field in a snapshot surfaced through
  a plugin hook — neither attacked this pass.
- **Soak:** the 12-minute, 200-machine run with `raise(delay=)`
  heartbeats at 10–50 ms + external priority producer + chaos
  snapshot/restore at quiescence every 2 s — entirely out of scope for
  this pass's time budget, as in the prior round.
- Re-run of `f2`/`f2b`/`f3`/`g2`–`g5`/`g7` from the inherited suite —
  skipped for time in both this and the prior pass; no reason to expect
  regression, but unverified across two consecutive rounds now.

---

## 5. Verdict

**Regression check: PASS.** Nothing in the inherited determinism suite
(`d1`–`d10b`, `e1`, `f1`, `f4`, `f5`, `g1`, `g6`, `n5b`, `n6`, `h1`,
`h2`) regressed on `c78ce99`. `f1`/`g1` are zero-delay chains and
correctly unaffected by #212's supersession of #206; the `d9`/`d10`/
`d10b` documented concurrency constraints are unchanged in shape.

**Round-10 pinned suite: PASS** (15/15,
`tests/test_round10_findings.py`).

**Round-10-specific new-attack verification: CONFIRMS BOTH CLAIMED
BEHAVIORS, ONE OF WHICH IS A SECURITY-RELEVANT DESIGN CONSTRAINT WORTH
FLAGGING FORWARD, NOT A REGRESSION.**

1. `i1`: #212's delayed-raise-is-a-timer semantics reversal holds on
   both engines at both a 30 ms period (matching the pinned test) and a
   1 ms period (the brief's specific ping-pong case); the same-step
   zero-delay chain budget #212 was never meant to touch is intact
   (control still trips). **No defect.**
2. `i2`: the v2-upcast trust boundary (#214) is confirmed to apply to
   `done`/`error` completions exactly as it does to `after` — a
   version-2-labeled, unflagged forged completion record with a
   matching `src` mints an untriggered `onDone`/`onError` transition
   that was never armed by any real invocation. **This is the
   documented, intentional migration contract, not a new defect**, and
   the opt-in remedy (`from_snapshot(minimum_version=3, ...)` /
   `expected_machine_hash=`) is confirmed to close it. It is flagged
   here, as the brief specifically asked "does downgrading version
   alone... let a forged `done.invoke.*` drive an onDone that was never
   armed" — answer: **yes**, and the register should carry this
   forward explicitly under #214/#205 as a second reachable path to the
   same opt-in trust gap (not a new Blocker; same severity class and
   remedy as the existing hash-drift gap).

**No new `D11-determinism-n` defects raised.**

