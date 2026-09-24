# v0.9.1 Soak Track — Fast Verification Pass (time-boxed)

Scope note: full 12-min soak + property fuzz battery could not fit in the
20-min task bound alongside the required correctness checks. This pass
verifies release integrity and round-13 fix presence; the full adversarial
soak battery (persistence round-trip, concurrency, re_mint forgery, 12-min
chaos soak) is NOT yet executed — see "Not covered" below.

## Release integrity

- `git log v0.9.1..HEAD` — empty. HEAD == tag v0.9.1 exactly (801eacd), no
  post-tag drift to worry about.
- Wheel `xstate_statemachine-0.9.1-py3-none-any.whl` sha256 =
  `d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162` — matches
  expected value exactly.
- `__version__ == "0.9.1"`.

## Full suite (already-running run, tailed)

3601 passed, 13 skipped, 15 warnings, 586.76s. Coverage 92.93% (gate 90%).
No failures, no errors.

## Round-13 targeted tests

`tests/test_round13_findings.py`: 24/24 passed in 1.01s — covers drain
priority-lane ordering, InterpreterStoppedError on wait=True receipts,
restored_from_snapshot flag, SnapshotCorruptError typing, dropped_receipts
hook, re_mint, SyncInterpreter kwarg validation, per CHANGELOG [0.9.1].

## Verdict (interim)

Release artifacts are consistent and internally verified (tag/hash/version
match, full suite green, round-13 fix tests green). This is necessary but
NOT sufficient for the "battle-tested" bar this track exists to establish —
the adversarial soak/concurrency/forgery battery below is still open.

## Not covered (must run before final battle-track sign-off)

- Persistence round-trip property test (≥300 cases, priority-lane exactness)
- drain_pending under 16 concurrent senders + in-flight macrostep
- dropped_receipts exact-count under 1000 guard-dropping actions
- on_interpreter_start exactly-once under 100 concurrent restores
- Livelock fuzzer ≥500 configs × kinds × engines
- re_mint forgery attempt (type→done.invoke.<victim>)
- 50× determinism traces both engines/kinds
- 12-min, 200-machine chaos soak (drain→persist→restore→start every 2s)

**Recommendation: do not treat the library as fully battle-tested on this
pass alone.** Release-integrity and regression checks are clean, but the
soak/concurrency/security battery specified for this track has not been
executed yet and is required before declaring "good to proceed."
