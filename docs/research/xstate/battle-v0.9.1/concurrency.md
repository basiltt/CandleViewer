# Battle track: CONCURRENCY — v0.9.1 (origin/main 801eacd, tag v0.9.1 45bb7f3)

**Reduced run.** Only part of the brief was covered in the time limit. Everything not covered is listed in §4.

## 0. Baseline
- The full suite (`suite-v0.9.1.log`) shows **3601 passed, 13 skipped**, with 92.93% coverage.
- `main` is one merge commit (#249) ahead of the previous release line.

## 1. Prior-defect table (battle-v0.9.0/concurrency/, re-run on v0.9.1)
| Script | v0.9.1 result | Status |
|---|---|---|
| w1_task_identity_matrix | CLEAN | FIXED / holds |
| w2_persistence_latch_strict_plugins | 16 "failures": `restored latch is RestoredChainError, expected RestoredError` | **SUPERSEDED**. #243 makes `RestoredChainError` a subclass of both `RestoredError` and `RunawayChainError` (checked: `issubclass` is True for both). The script checked for the exact type, which no longer applies. The rewrite should use `isinstance`. |
| w3_restore_lifecycle_hook | CLEAN | FIXED |
| w4_warning_config_and_load | CLEAN | FIXED |
| w5_chaos_soak | not re-run (12-min budget) | NOT COVERED |

## 2. New attacks
| # | Attack | Result |
|---|---|---|
| N1 | `re_mint` forging a different completion (`type` changed to `done.invoke.<victim>`) | **DEFECT D14-concurrency-1** |
| N2 | `RestoredChainError` isinstance matrix | PASS |

## 3. Defects

### D14-concurrency-1: `re_mint()` can forge a completion for a different invoke (HIGH, security/provenance)
- **Where:** `src/xstate_statemachine/events.py:661-700` (`re_mint`).
- **What:** the function only checks that its *input* is engine-minted. It then applies any field override, including `type` and `src`, and re-mints the result as a trusted engine event.
- **Effect:** any holder of one genuine completion (an action or plugin that sees `done.invoke.ok`) can produce a trusted `done.invoke.victim` carrying arbitrary `data`. The `victim` invoke's `onDone` then fires even though `victim` never finished. This works with `strict: True`.
- **Why this contradicts the release notes:** the changelog says re_mint "can carry provenance forward but never create it" and describes the use case as redacting `data`. In practice, provenance for a *different* event identity is created.
- **Repro:** `battle-v0.9.1/concurrency/n1_re_mint_forge_completion.py` (standalone, stdlib + library only, run from cwd `<home>`).
  - SyncInterpreter / def: the machine reaches `m.s.p2.victim_done`, so the forgery is **ACCEPTED**.
  - Interpreter / async def: the machine reaches `m.s.p2.victim_done`, so the forgery is **ACCEPTED**.
  - Interpreter / def: no result. The harness never captured an event within 1 s (the blocking thread service interfered). This is a harness gap, not a pass.
- **Suggested fix:** in `re_mint`, reject overrides of identity fields (`type`, `src`, and the `after` type/state). Alternatively, allow only `data` / `fired_at`, or require the new `type` to equal `original.type`.
- **Test gap:** `tests/test_round13_findings.py::TestReMint` only patches `data`, `src`, and `fired_at`. It never tests changing `type`. The `src`-override case is itself a forgery vector, and the test treats it as intended behaviour.

## 4. Not covered (time bound)
These parts of the brief were not run:
- The w5 soak and the 12-min / 200-machine chaos soak.
- Drain→persist→restore property test (≥300 cases).
- `drain_pending` with 16 concurrent senders.
- `dropped_receipts` with 1000 dropping guards.
- `on_interpreter_start` under 100 concurrent restores.
- Livelock fuzzer.
- `re_mint` fuzz (beyond N1).
- 50× determinism traces.
- Ordering of `drain_pending` vs `pending_events`.
- `SyncInterpreter` kwargs.
- PyPI attestation verification.
- Chain-field fuzz for `SnapshotCorruptError`.

## 5. Verdict
**NOT READY on this track.**
- One confirmed HIGH security defect was introduced in this release (#248 `re_mint`). It lets any holder of a genuine completion forge a trusted completion for another invoke.
- The prior round-12/13 concurrency defects re-tested here are FIXED or SUPERSEDED.
- Most of the new-attack matrix and the soak were not run, so "battle tested" cannot be claimed from this track.
