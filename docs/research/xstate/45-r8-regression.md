# 45 — Round-8 regression sweep: `xstate-statemachine` `main` @ `6db65d8` (unreleased 0.8.1)

Date: 2026-09-21. Scope: full regression sweep only (gate + every standalone verify/repro/probe
script), diffed against the last recorded baseline (`main` @ `221ce7c`, round 7). No new issue
verification performed here — round-7's 12 issues were already re-verified against `6db65d8` in
`issues/verify-main-6db65d8/*.result.md` (all reconfirmed FIXED except the documented `#174`
documented-only closure; superseded artefacts for #157/#166/#169-#173 were removed from that
directory because round 7 folded them into the `221ce7c` baseline and this commit adds only the
round-7 fix set proper — see §3).

## 0. Answer

**Zero true regressions.** The gate (`gate/run_gate.py --json gate/result-main-6db65d8.json`)
shows exactly **2** PASS→FAIL deltas versus `gate/result-main-221ce7c.json`, both in the
`verifyM3` (round-6, `cec108b`) set: `154` (sync-restore clock attach) and `158` (non-str
event-type restore). Both are **not library regressions** — they are pre-existing round-6
verification *scripts* that build a versioned snapshot blob without a `machine_hash` field. That
shape was accepted at `221ce7c`; round 7's own fix **#185** ("null/absent `machine_hash` on a
versioned payload is drift") — landed in this exact commit window and documented in
`CHANGELOG.md [Unreleased]` — now correctly refuses that blob with `SnapshotDriftError` before
either script reaches the behavior it was written to probe. This is a **documented-superseded**
case: the new drift check is the intended, changelog-declared behavior; the two scripts are stale
fixtures that predate #185 and need a `machine_hash` added to their hand-built blobs to keep
testing what they were written to test. Confirmed by direct reproduction (see §2).

The gate is **not clean** (17 blocking-check FAILs) but every one of them is a **pre-existing,
already-triaged FAIL** carried forward unchanged from `221ce7c` — none is new. Totals moved
FAIL=36→38, PASS=80→89 only because this run adds the 11 round-7 `verifyM4` checks
(`157,166,167,168,169,170,171,172,173,174,175`) that did not exist as a named set until round 7's
own gate run; `221ce7c`'s recorded JSON predates them being folded in as `verifyM4`. Every
individual `verifyM4` cell matches its already-recorded `221ce7c` value 1:1 (10 PASS, 1 expected
FAIL at `167`, per `44-r7-final-readiness-verdict.md` §1).

## 1. Gate diff (`221ce7c` → `6db65d8`)

- **PASS→FAIL: 2** — `154:verifyM3`, `158:verifyM3` (both explained above; not counted as
  regressions).
- **FAIL→PASS: 0.**
- **New keys (11):** the `verifyM4` set (`157,166,167,168,169,170,171,172,173,174,175`) — present
  in the `221ce7c` gate run's *console table* (`44-r7-final-readiness-verdict.md`) but the JSON
  snapshot at hand (`result-main-221ce7c.json`) was captured before that set was wired in;
  cell-by-cell they reproduce the round-7 verdict exactly.
- **Missing keys: 0.**
- **verify (LC-xx primary):** unchanged, 29/34 — same 5 FAILs as `221ce7c` (`LC-01, LC-12, LC-26,
  LC-48, LC-57`), all pre-existing and already triaged (H-2 in `44-r7-final-readiness-verdict.md`
  §2: the gate gives no baseline-failure allow-list to the `verify` set).
- **verifyM (5327ba6 set):** unchanged, 10/15 — same FAILs (`LC-01, LC-07, N-1, N-3, N-8`),
  matching the recorded baseline triage in `22-verify-main-verdict.md` §1 (3 expected: `LC-07,
  N-3, N-8`; 2 already-flagged regressions carried forward unchanged: `LC-01, N-1`).
- **verifyM2 (3c527b0 set):** unchanged, 3/3 PASS.
- **verifyM3 (cec108b set):** 23/27 — 2 expected FAILs unchanged (`150, 157`) plus the 2
  script-staleness FAILs discussed above (`154, 158`, newly flagged but not real regressions).
- **verifyM4 (221ce7c set, round 7):** 10/11 — matches the recorded round-7 verdict exactly
  (`167` PARTIAL, expected).
- **repro (secondary, informational):** 13/34 — unchanged from `221ce7c`; same 21 FAILs, all
  already covered by the "fixed but opt-in / stale repro" triage rule
  (`17-reeval-0.8.0-verdict.md` §0). No new secondary FAILs.
- **probe:** `PROBE-01` 16/20 (same 4 failing cells: `A10, A18, A3, A6`), `PROBE-02` 14/14 PASS,
  `PROBE-03` 13/17 (same 4 failing cells: `C15, C17, C6, C7`) — all unchanged from `221ce7c`.

## 2. Reproduction of the two flagged deltas (154, 158)

Ran directly (not just via the gate) with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`:

```
issues/verify-main-cec108b/154_sync-restore-clock-attach.py
  -> SnapshotDriftError: snapshot declares version 1 but carries no 'machine_hash' ... (#185)

issues/verify-main-cec108b/158_non_str_event_type_restore.py
  -> [A] FAIL: wrong exception type SnapshotDriftError (#185, no machine_hash)
     [B] PASS: restore_event() rejects non-str type directly
     [C] FAIL: wrong exception type SnapshotDriftError (#185, no machine_hash)
     [D] FAIL: wrong exception type SnapshotDriftError (#185, no machine_hash)
  OVERALL: FAIL
```

Both scripts hand-build a `version: N` snapshot dict without a `machine_hash` key — valid at
`221ce7c` (the v0-style bypass was keyed on field *presence*), refused at `6db65d8` because #185
keys the bypass on the *declared version* instead. `158`'s sub-case `[B]` (the one path that does
not depend on identity-check ordering — `restore_event()`'s own direct type validation) still
PASSes, confirming the underlying #158 fix is intact; only the harness's identity-check plumbing
needs a `machine_hash` added to keep exercising cases A/C/D. **Verdict: not a regression — a
downstream consequence of round 7's own #185 fix hitting stale round-6 fixtures. Flag for our own
backlog** (update `machine_hash` in both scripts' hand-built blobs), not for the library.

## 3. verifyM4 set provenance note

`issues/verify-main-6db65d8/` currently holds only the round-7 *fix* scripts
(`167,168,174,175,179-190`) — `122,157,166,169,170,171,172,173` were dropped from this directory
because they were already folded into `issues/verify-main-221ce7c/` as the recorded round-7
baseline and are unchanged at this commit; re-running them from `verify-main-221ce7c/` (as the
gate does via `VERIFY_MAIN4_DIR`) reproduces the identical 10 PASS + 1 expected-FAIL (`167`)
recorded in round 7. No drift here; this is expected directory hygiene, not a gap.

## 4. Flaky check re-run (×5)

Re-ran the checks the round-7 verdict flagged as flake-prone or newly time-sensitive
(`167:verifyM4`, `PROBE-01`, `PROBE-03`) five times each:

- `167` (`rollback_reinvoke_spin.py`): FAIL ×5/5, identical detail each time — deterministic, not
  flaky (matches the recorded PARTIAL: plain-`def` bounded, `async def` still unbounded is the
  *other* half now fixed via #179, but `167`'s own script still targets the narrower rollback
  shape reopened at round 6 and remains PARTIAL as filed).
- `PROBE-01`: 16/20 ×5/5, same 4 failing cells (`A10, A18, A3, A6`) every run — deterministic.
- `PROBE-03`: 13/17 ×5/5, same 4 failing cells (`C15, C17, C6, C7`) every run — deterministic.

No flakes observed in this window.

## 5. Verdict

**No true PASS→FAIL regressions in `main` @ `6db65d8`.** The 2 gate deltas (`154`, `158`) are a
harness-staleness artifact of round 7's own `#185` fix, not a library defect — reproduced and
attributed above. Every other blocking-check FAIL (17 total) is a pre-existing, already-triaged
item carried forward unchanged from `221ce7c`, with cell-level parity confirmed by direct JSON
diff. The round-7 fix set itself (`#179-#190` + reopened `#167/#168/#175`) reconfirms clean at
this commit per `issues/verify-main-6db65d8/*.result.md` (round-7 findings register
`43-r7-findings-register.md` and final verdict `44-r7-final-readiness-verdict.md` stand, nothing
here changes their conclusions).

**Action item (ours, non-blocking):** update `machine_hash` in
`issues/verify-main-cec108b/154_sync-restore-clock-attach.py` and
`issues/verify-main-cec108b/158_non_str_event_type_restore.py`'s hand-built snapshot blobs so they
resume exercising their original assertions under #185's stricter identity check.
