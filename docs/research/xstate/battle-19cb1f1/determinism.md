# Battle-test track: DETERMINISM — `xstate-statemachine` @ `19cb1f1` (unreleased 0.8.1, round-9 fixes #203–#210)

**Scope note (stated up front, as the prior pass also stated):** the brief's
full spec (property ≥300 machines, 5–10k/s concurrency, 12-min soak, full
fuzz/security/observability matrices) exceeds the 20-min wall-clock bound
given for this task by roughly an order of magnitude, same as the f28719c
pass. This report (a) re-runs the **entire prior determinism script suite
unchanged** against `19cb1f1`, (b) runs the pinned round-9 regression suite
(`tests/test_round9_findings.py`, 19 tests), and (c) adds **two new,
round-9-targeted, light-weight probes** (persistence of statesToInvoke
mid-macrostep, and the `#205` snapshot trust-boundary remedy). Full-scale
concurrency/fuzz/soak per the letter of the brief is **not covered** — see §4.

---

## 0. Bottom line

All inherited determinism-suite defects previously marked FIXED remain FIXED
on `19cb1f1`. No regression observed in `d1`–`d10b`, `e1`, `f1`, `f4`, `f5`,
`g1`, `g6`, `n5b`, `n6`. The 19 pinned round-9 tests
(`tests/test_round9_findings.py`) all pass. The two new probes both behave
as documented: `#204`'s statesToInvoke settle-then-arm holds across a
persist/restore round trip (invoke arms exactly once, no double-submit, no
stranding of `mid`'s non-existent invoke), and `#205`'s opt-in
`minimum_version`/`expected_machine_hash` trust-boundary remedy refuses a v0
downgrade, an absent-version snapshot, a hash-mismatched snapshot, and an
absent-hash snapshot when the caller opts in — while still accepting a
legitimate matching snapshot.

**No new `D10-determinism-n` defects are raised this pass.**

---

## 1. Prior-defect re-run table (round 5–8 inherited suite, on `19cb1f1`)

| ID / script | Prior status (f28719c) | Status on `19cb1f1` | Evidence |
|---|---|---|---|
| `d1_replay.py` | STABLE | **STABLE** | exit 0, no diff output (25/25 identical) |
| `d2_receipt_deferred.py` | 0 false positives | **0/400 false positives, both engines** | run A == run B on false-positive set |
| `d3_perturb.py` | STABLE | **STABLE** | 25/25 identical action trace/context/state; arrival order preserved 20/20 |
| `d4_ordering.py` | all windows STABLE | **all windows STABLE (C1–C10, both engines where dual)** | incl. `C9`/`C9s` FIFO defer replay identical order |
| `d5_hashseed.py` | config/actors/value_keys seed-stable; `current_state_ids_raw` varies by seed (expected, parallel-region ordering not contractually fixed) | **unchanged** | same shape, 6 distinct raw orderings across 6 seeds, snapshot-level keys stable |
| `d6_cross_engine.py` | 100% agreement | **100% agreement (context/state/trace), S1–S5** | |
| `d7_hook_parity.py` | byte-identical hook trace | **identical: True, 0 async/sync-only records** | |
| `d9_snapshot_replay.py` | known constraint: resume-from-snapshot vs straight-through diverge in log/deferred ordering under heavy concurrent traffic | **UNCHANGED (same constraint)** | `resumed trace length: 0`, `final snapshots identical: False` — same shape as prior round |
| `d10_concurrent.py` | INCONCLUSIVE (no output before 40s cap) | **RAN THIS TIME** — T1/T2 arrival==processed 10/10, 0 lost, 10/10 drained; T3 (4 tasks/4 threads, one interpreter) arrival==processed 0/10 (expected: unordered under `send_threadsafe`, matches `D-determinism-6` constraint), 0 lost, 10/10 drained | not a regression — matches the documented "send_threadsafe unordered" constraint |
| `d10b_threadsafe_order.py` | 0/8 FIFO, 8 distinct orders (constraint) | **UNCHANGED** — 0/8 FIFO, 8 distinct first-8 orderings | |
| `e1_internal_forgery.py` | 200/200 forged sends accepted (by design) | **UNCHANGED** — 200/200 accepted, 0 QueueOverflowError | design constraint, not re-litigated here |
| `f1_chain_vs_external.py` | tripped `RunawayChainError`, 268 external accepted concurrently | **tripped `RunawayChainError`, 379 external accepted concurrently** | still FIXED; count differs (workload-timing artifact, not a regression signal) |
| `f4_raise_dropped_hook_parity.py` | 236 refused == 236 hook fires | **4 accepted, 236 refused == 236 hook fires** | parity: True, unchanged |
| `f5_nested_parallel_snapshot_refusal.py` | all 3 windows REFUSED both engines, ctx 999/888 | **UNCHANGED** — all 3 windows REFUSED both engines, ctx 999/888 | |
| `g1_async_chain_charged.py` | both kinds trip at n=1002 | **UNCHANGED** — both kinds trip at n=1002, parity True | |
| `g6_hash_and_config_fuzz.py` | 300/300 mutated snapshots refused | **UNCHANGED** — 100/100 null-hash, 100/100 absent-hash, 100/100 config/state_ids-mismatch all refused | |
| `n5b_corrupt_escapes.py` | 0/9 untyped escapes | **UNCHANGED** — 0/9 untyped escapes, all typed `SnapshotCorruptError` | |
| `n6_observability.py` | S1 (redaction) OK, S2 (API surface) OK | **UNCHANGED** — leaked_keys=[], redacted_keys as expected, API surface OK; `version_string: 0.8.0`\* | \*package `__version__` not yet bumped for 0.8.1 — matches the task framing ("unreleased 0.8.1; `__version__` still 0.8.0") |

Scripts not carried forward from the f28719c suite this pass: `f2`/`f2b`
(`service_pool_size`/shutdown), `f3` (in-flight leak), `g2`–`g5`, `g7`
(livelock fuzzer) were not re-run given the time budget — they are not
round-9-targeted and the round-8 register already covers them; nothing in
this pass contradicts their prior FIXED status, but they are unverified
*this pass* (listed again in §4).

---

## 2. Round-9 pinned regression suite

```
C:/.../xstate-statemachine/.venv-main/Scripts/python -m pytest tests/test_round9_findings.py -q
19 passed in 19.40s
```

All 19 tests parametrised over `def`/`async def` (where parity is the
point) covering #203–#210 pass fresh at `19cb1f1`. This is the library's own
pinned regression coverage for this round, run as-is (not modified).

---

## 3. New attacks this pass (round-9-targeted, reduced scale)

### 3.1 `h1_statestoinvoke_snapshot.py` — persistence of #204's settle-then-arm

Attack: persist a snapshot of a machine after a macrostep that includes a
state (`mid`) entered and rolled forward by `always` to `settled` within the
**same** macrostep (the class of state #204 says must never submit an
invoke), then restore fresh and confirm `settled`'s own invoke arms
**exactly once** and `mid`'s invoke (which doesn't exist, standing in for
the "entered+exited" case) is never touched.

Result (both `def` and `async def` service kinds):

```
{"kind": "sync",  "pre_restore_calls": 1, "post_restore_calls": 0, "state": ["m.done"]}
{"kind": "async", "pre_restore_calls": 1, "post_restore_calls": 0, "state": ["m.done"]}
```

`svc` (arming from `settled`) fired exactly once before the snapshot was
taken, ran to completion, and the restored interpreter correctly shows 0
further calls (already `done`, no re-arming) on both service kinds. This is
**consistent** with #204 — no double-submit, no stranding.

**Caveat (stated honestly):** `interp.send("GO")` on both `Interpreter` and
`SyncInterpreter` runs the whole macrostep — including the `always`
roll-forward through `mid` into `settled`, and the invoke's `def`/`async`
submission — before `send()` returns, so the snapshot in this repro is
captured *after* settle has already completed and the service has already
been armed, not mid-settle as the brief's "invoke is pending arming (entered,
settle not yet run)" scenario asks for. Capturing a genuinely pre-settle
snapshot would require an internal hook (e.g. a plugin callback fired
between the eventless-transition loop and the settle-stabilization check) or
white-box instrumentation of the interpreter's private step loop — neither
is available as public API, and building one was out of scope for the time
budget. This probe is therefore **informative, not decisive**: it confirms
the post-hoc invariant (exactly-once arming survives a snapshot round trip
once the macrostep is complete) but does **not** independently establish the
harder mid-macrostep persistence claim in the brief. Flagged as not fully
covered in §4.

### 3.2 `h2_snapshot_trust_boundary.py` — #205's opt-in downgrade/drift remedy

Attack: exercise the exact vectors R9-05 named (v0/absent-`version`
downgrade past the drift check; hash mismatch; absent hash) against the new
`from_snapshot(minimum_version=, expected_machine_hash=)` parameters added
in #205, plus a control (legitimate snapshot must still be accepted).

Result, both refused as documented when the caller opts in:

```json
{
  "v0_downgrade_refused": true,
  "v_absent_refused": true,
  "bad_hash_refused": true,
  "absent_hash_refused_when_expected": true,
  "legitimate_snapshot_accepted": true
}
```

This confirms #205 does what the changelog claims: it is an **opt-in**
hardening (the caller must pass `minimum_version`/`expected_machine_hash`),
not a default-on gate — the register's framing ("DESIGN-CONSTRAINT, wrapper
obligation") stands: a caller who does not opt in is exactly as exposed as
before. No new defect: the remedy matches its documented contract.

---

## 4. Not covered this pass (explicit gaps against the brief)

- Persistence: forged after records under `strict` at 19cb1f1 (R9-02's
  remedy, i.e. does `after.*` now require an engine-minted `_EngineAfter`
  specifically, not just the public class) — not independently re-probed
  this pass (covered by the pinned suite's #203 test, not by a standalone
  battle-track repro here); genuinely pending-arming (pre-settle) snapshot
  capture (see §3.1 caveat); delayed-self-send debt across snapshot/restore
  (#206); property-based ≥300 random machines including parallel+children+
  after.
- Concurrency: 100 machines with `raise(delay=1ms)` self-ping-pong lap
  parity; stranded-invocation hook under 200 concurrent rollback+onDone
  storms; external delayed sends at 5k/s during self-generated chains.
- Fuzz: livelock fuzzer ≥500 configs (not re-run this pass; `g7` was not
  carried forward — see §1); illegal-configuration receipt fuzz at scale
  (the inherited `d2`/`n5b`/`g6` give partial coverage of receipt/corruption
  shape but not the specific 6-way stranded matrix).
- Determinism: 50× identical-trace comparison including stranded events and
  trip laps (the inherited `d1`/`d3`/`d4`/`d6`/`d7` give 20–25-run coverage
  of the non-stranded case only).
- Semantics: full SCXML §6.1 statesToInvoke matrix (enter-exit same
  macrostep via `always` / rollback / parallel-sibling-final / history) —
  only the `always`-roll-forward leg was probed (§3.1); after-provenance
  matrix beyond the pinned #203 test; receipt 6-way matrix incl. stranded.
- Observability: `on_invocation_stranded` × engines × kinds exactly-once +
  ordering vs `on_event_dropped` — only covered by the pinned suite's #207
  test, not independently re-probed here.
- Security: `_EngineAfter` construction via import path / `type(held)` /
  pickle / snapshot `"engine": true` post-#203 — the pinned suite covers
  the `after` provenance fix itself but this pass did not independently
  re-attempt R9-01's five forgery vectors (`_replace`, pickle, hand-written
  `engine:true`, importable private name, `type(held)(...)`) against
  `19cb1f1` to confirm whether R9-01 (the round-9 register's sole Blocker)
  was addressed by this release — **this is the most consequential gap in
  this pass** and should be the first follow-up.
- Soak: 12-minute run with 200 machines both kinds, always→invoke +
  rollback+onDone + delayed self-sends + external priority producer +
  chaos snapshot at quiescence.
- Re-run of `f2`/`f2b`/`f3`/`g2`–`g5` from the inherited suite (not
  round-9-targeted, skipped for time; no reason to expect regression, but
  unverified this pass).

---

## 5. Verdict

**Regression check: PASS.** Nothing in the inherited determinism suite
(`d1`–`d10b`, `e1`, `f1`, `f4`, `f5`, `g1`, `g6`, `n5b`, `n6`) regressed on
`19cb1f1`; the `d10`/`d10b` "unordered under `send_threadsafe`" shape is the
same documented design constraint as before, not a new finding.

**Round-9 pinned suite: PASS** (19/19,
`tests/test_round9_findings.py`).

**Round-9-specific new-attack verification: PARTIAL.** The two probes run
this pass (`h1` persistence-of-settle-then-arm, `h2` snapshot trust-boundary
remedy) both behave as documented and raise no new defect, but `h1` is
explicitly informative-not-decisive (see §3.1 caveat) and the brief's
higher-value security ask — whether R9-01's engine-completion-provenance
forgery (the round-9 register's sole **Blocker**) survived into `19cb1f1` —
was **not independently re-tested this pass**. Given the register's own
framing ("Adoption gate stays shut on it" as of the register's writing),
that re-test against `19cb1f1` is the single most important follow-up,
ahead of the concurrency/fuzz/soak items in §4, and should be done with a
dedicated pass budgeted at or beyond the 20-minute mark the brief actually
implies.

**No new `D10-determinism-n` defects raised.**

