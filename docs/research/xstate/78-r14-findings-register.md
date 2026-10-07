# 78 — Round-14 findings register (v0.9.1)

**Target:** origin/main 801eacd. This is the merge of PR #249. `git diff v0.9.1..HEAD --stat` is empty, so the code is identical to tag v0.9.1 (45bb7f3). The wheel sha256 matches (d832d4d9…). Full suite: **3601 passed, 13 skipped, 92.93% coverage**. test_round13_findings.py: 24/24.

**Verdict: NOT ready to sign off.** There is 1 open LIBRARY-DEFECT (R14-01). Every other round-13 fix (#239–#247) is confirmed closed in both the async def and def lanes. There are also 3 of our own chart blockers (R14-03), which are not library defects.

## R14-01 — LIBRARY-DEFECT — High (OMS) — `events.re_mint()` forges a different completion via `type`/`src` overrides
- **Merges:** D14-persistence-1, D14-concurrency-1, D14-fuzz-1, D14-determinism-1, D14-semantics-1, D14-security-1, T-1 (77). All have the same root cause.
- **Root cause:** `events.py` `re_mint()` only checks that the *input* is engine-minted. After that check it takes any `_replace(**fields)` result, including a new `type` and `src`, and re-mints it as `_EngineDone`/`_EngineError`/`_EngineAfter`. Routing (`_completion_is_for_live_invocation`) trusts `is_system_event` plus a `src` match. The result is that a caller can create provenance for a different invocation. That breaks the #248 docstring promise that provenance can be "carried forward …, never created".
- **Fresh standalone repro (this round):** `battle-v0.9.1/r14_01_remint_retarget.py`, cwd <home>, K=async and K=def. The original event was `_EngineDone(type='done.invoke.m.a.r', src='m.a.r')`. It was re-minted with `type='done.invoke.m.pay.w'` and `src='m.pay.w'`. Both kinds ended in `['m.a.d','m.pay.settled']` while the victim service was still inside `asyncio.sleep(30)`. The fuzz track also saw the sync engine fire a 99999 ms `after` timer at once when an AfterEvent was retyped.
- **Not a trust boundary:** unlike R12-03 (importing the private `_EngineDone`), `re_mint` is a *public, documented* API that is presented as safe.
- **Fix to ask for:** refuse `type`/`src` in `fields` (raise TypeError), or allow only payload fields (`data`, `error`, and for timers `scheduled_for`/`fired_at`). Add a regression test for the retarget case on both engines.
- D14-determinism-1 rated this as "docs only". That is overruled: the docstring's safety claim is false, so this is a defect.

## R14-02 — DESIGN-CONSTRAINT — Low — drained receipt error type (T-2, W-239-receipt, W-02, B15-V091-W1)
`drain_pending()` fails wait=True receipts with `InterpreterStoppedError` even if the machine keeps running afterwards. The receipt *resolves*, with `.error` set; it does not raise. Snapshots taken after a drain carry `pending_events==[]`. This matches the documented #239 semantics. **NEEDS-WRAPPER:** journal the drained list before stop(), check `Receipt.error`, and de-duplicate re-submits. We can suggest a clearer error name upstream (optional, not blocking).

## R14-03 — OUR-CONTRACT-DEFECT — Blocker (ours) — catalogue chart fixes not merged
- R13-13 (B16 / C-04 revocation: root-hoist to elevation.dead), R13-14 (B18 / C-07b: defer plus an unguarded audit arm), R13-15/R13-16 (B11: event-aware guard). Also merges B610-OC-C04-C07b-B11 and the duplicate R13-13/14/15 rows. The fixes are proven green on 0.9.1 in both lanes (g4 11/11, g2, w1). The action is to merge them into docs/plan/28.
- B610-OC-CD03 (B8 naked↔verifying loop trips the chain budget): High (ours). Add a bounded attempt counter.

## R14-04 — NEEDS-WRAPPER — Info — W-01
rollback plus a raising onDone re-arms the invoke. maxIterations cuts the loop (chain_trips=1). The wrapper must alert on chain_trips>0.

## Carried / accepted
| id | class | note |
|---|---|---|
| R11-01 | DESIGN-CONSTRAINT (mitigated) | Upcasting a v2 snapshot mints provenance. `minimum_version=3` refuses it, and we must pin that. Unchanged. |
| R12-03 | DESIGN-CONSTRAINT | Importing the private `_EngineDone` is an accepted trust boundary. |
| D13-security-3 | DESIGN-CONSTRAINT / docs, Info | The receipt RuntimeWarning does not escalate under `-W error`. Use the new `on_receipt_dropped`/`dropped_receipts` instead. |
| T-3 | Info | `check_shape` accepts int-coercible strings. No impact. |
| T-4..T-7, T-10 | closed | Review OK. |
| T-8, T-9 | not verified | The JSON schema has no version field. Attestations were not run (read-only). |

## Harness / superseded (not counted)
- q2-harness: HARNESS-ERROR. The documented #102 SnapshotMidStepError needs a retry. No loss.
- prior-w2, B1-superseded: SUPERSEDED-RULE. The exact type-name checks predate #243 (RestoredChainError ⊂ RestoredError ∧ RunawayChainError).
- 75 regressions: 105 is a sleep-not-poll flake (the convergence repro gave 12/12). 233_235 is pinned to 0.9.0. p3 needs argv. 228 needs XSM_REPO. **0 true regressions.**
- F1/release-integrity/full-suite/round13-tests/B15-V091-OK/B610-LIB-0/LIB: verification passes. #239, #240, #244, #245 and #248 (other than the retarget case) are closed on B1–B20 contract machines, 0 FAIL under -W error::RuntimeWarning.

## Canonical LIBRARY-DEFECTs
1. **R14-01** (High): `re_mint` type/src retarget forgery.
