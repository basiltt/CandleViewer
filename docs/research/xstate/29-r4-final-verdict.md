# 29 — Round-4 FINAL verdict: `xstate-statemachine` main @ `5e07ba8` (unreleased 0.8.1)

Date: 2026-09-18. Method: 19 issue verifications (+ independent recheck), full regression gate, 3c527b0..5e07ba8 diff review, eight battle-test tracks (persistence, determinism, concurrency, semantics, fuzz, security, 25-min soak, observability), per-track triage with fresh re-execution, cross-track dedupe, and an independent adversarial refutation pass over every Blocker/High. Severities below are **post-refutation** (`30-r4-findings-register.md` "Final sev" column is normative).

---

## 0. Bottom line

**The 19 issues the team fixed are genuinely fixed — 17 confirm-closed, 2 partially (#91, #99).** No regressions at any level: suite **3 276 passed / 0 failed** (+34), coverage 90%, every prior verification set still green, probes unchanged.

**But the first deep battle-test of the library found 40 canonical defects, of which — after adversarial refutation — 2 Blocker, 6 High, 18 Medium, 12 Low survive (2 refuted).** The two Blockers and most Highs share one shape: **state-corrupting windows that report `status="running"`, `error=None`, `last_transition_ok=True`** — indistinguishable from health. For an order-management path that is the worst failure profile there is; a crash would be better because a crash is observable.

**Gate decision: DEFER for the order path** (decision-table row 1: any open Blocker → DEFER). Non-order paths may proceed only with the constraints in §6. This is the first round where the operative blocker is **upstream**, not our linter.

Plain answer to the question asked: **No — today, this library is not fit to run the order path of a financial application, even with the mandated configuration.** Not because the fixes were poor (they were good and complete), but because the persistence and settling machinery has not yet been tested by anyone at the depth an OMS requires, and round 4 was the first time it was. What is missing is specific, small, and listed in §8.

---

## 1. The 19 issues (per-issue disposition)

| # | Result | Note |
|---|---|---|
| #31, #77, #79, #84, #85, #86, #87, #88, #89, #90, #92, #93, #94, #95, #96, #97, #98 | **FIXED — confirm closed** | Every acceptance criterion met; verification scripts in `issues/verify-main-5e07ba8/`. |
| **#91** | PARTIAL — **reopen** (narrow) | Registry-side ambiguity guard works; criterion 3 (config-side duplicate-name warning) not implemented. |
| **#99** | PARTIAL — **reopen** (narrow) | Sync engine now delivers `onError` for a failed invoked child machine; the **async** path (`_deliver_invoked_completion`) still parks silently on an unhandled child error. Only the sync side was fixed. |

Harness errors on our side (not the library's): probe expectations A10/A18/C15 are stale (now correctly rejected at build time); the `g1_forge_system` probes were written against the pre-#85 `Event(system=)` kwarg and are inert; one observability claim (D-observability-6 `.use()` wrap) was wrong and is withdrawn. Full list in `30-r4-findings-register.md` §2.

---

## 2. Regressions

**None.** No item that passed at 3c527b0 fails at 5e07ba8 at gate, suite, benchmark or probe level. One *new* defect introduced by the round-3 fixes was found (R4-06, from #90's reroute) — listed below as a defect, not a regression of a previously-verified item.

---

## 3. Surviving defects (post-refutation)

### Blocker (2)

| ID | Defect | Why Blocker | Repro |
|---|---|---|---|
| **R4-01** | Mid-macrostep configuration is loop-visible and snapshottable. A snapshot taken in the exit→actions→enter window restores as a **permanently inert machine that reports healthy** (`status=running`, empty configuration, `PING` → `Receipt(changed=False, error=None)`). Property run: **45.5 % of mid-macrostep snapshots torn** (300 cases). Found independently by two tracks. | Silent order-state corruption on the exact path (snapshot-on-transition) our persistence design depends on. No in-library mitigation; must be fixed in the engine (snapshot must observe only committed configurations). | `probes/main-5e07ba8-final/v1_torn.py`, `battle-5e07ba8/persistence/` |
| **R4-04** | `SyncInterpreter.start()` **never terminates** for a cross-region `always` that re-enters an invoking state; `maxIterations=1000` → still running after 20 s with `last_transition_ok=True`, `last_error=None`. | Non-terminating start with no signal. Sync engine is banned for us (CV-C03), but the same settling logic is shared; and the library ships it as a supported engine. | `probes/main-5e07ba8-final/v4_sync_hang.py` |

### High (6)

| ID | Defect | Impact on order path |
|---|---|---|
| **R4-03** *(downgraded from Blocker)* | `OverflowPolicy.BLOCK` silently discards every fire-and-forget `send()` when the inbox is full. | We mandate RAISE on the order path, so contained — but BLOCK is the library's own recommended policy for suspending producers. |
| **R4-06** | #90's self-send reroute gates on the interpreter-wide `_processing` flag, so **external events sent during a macrostep are charged to the chain budget and can be discarded**. Reproduced at default `maxIterations`: `burst=1500 → LOST=1`. | A fill arriving while an action is running can be dropped as "runaway". New in round 3. |
| **R4-07** | `Receipt.deferred` is keyed on `id(event)` in a `Set[int]` that only shrinks on a receipt path → unbounded growth and **false positives on correctly handled events**. | The #84 fix reintroduces the `id()`-keying pattern that #75 removed. Wrong receipt on the order path. |
| **R4-11** | The priority (timer) lane is **never persisted**: an already-fired `after` event is lost by a snapshot taken before it is dequeued. | `after` is banned in our catalogue (CV-C12) — contained for us, but a persistence hole. |
| **R4-12** | An `always` targeting the machine root **empties the configuration** on both engines, `status="running"`. | Silent inert machine; build-time validation should reject it. |
| **R4-19** | An invoked child's `output` is discarded; the parent's `done.invoke` carries the child's `context` instead. | Any parent/child contract using `output` (B2 TradeGroup ← B3 Leg) gets the wrong data. |

### Medium (18) — headline items
R4-02 `from_snapshot()` performs no legality validation and leaks raw `KeyError`/`TypeError` past `XStateMachineError` · R4-08 provenance silently lost wherever an `Event` is reconstructed via `__init__` (third instance across two releases — needs one systematic audit, not point patches) · R4-13 settling-budget trip leaves an orphan leaf with inactive ancestors, and **the same machine snapshots to two different configurations depending on whether it went through a restore** · R4-14 non-`str` event `type` escapes the documented base exception · R4-16 run loop can die with `status="running"` and pending `wait=True` receipts never failed · R4-18 `SimulatedClock._attach` leaks per restore · R4-22 `from_snapshot()` has no `clock=` parameter (virtual clock cannot be restored via public API) · R4-24 `Receipt` grew a field — undeclared API break · R4-25 #94 implemented on sync engine only · R4-30 deferred replay folds into the triggering event's receipt · R4-31 `LoggingInspector` logs full context/payload at INFO, no redaction · plus R4-21, R4-23, R4-26–R4-29, R4-32.

### Low (12)
R4-33–R4-40 and others: unresolved `sendTo` target silently dropped; no `on_resolve_error` hook; `restart_services=True` inert until `start()` while `status` already "running"; self-referential config → `RecursionError`; provenance predicates (`is_system_event`, `system_event`) unexported and undocumented; provenance does not survive `deepcopy`/`pickle`.

Refuted (not library defects at the filed claim): R4-09, R4-17.

---

## 4. Battle-test scorecard

| Track | Coverage achieved | Defects after triage | Verdict |
|---|---|---|---|
| **Persistence / crash consistency** | hypothesis property runs over random interruption points; v1→v2 upcast; corrupt JSON; large context | **1 Blocker (R4-01)**, 3 High (R4-11, R4-19, +), 7 Medium | **FAIL** — snapshot is not transactional |
| **Concurrency & limits** | 2k interpreters × 16 producers × 3 policies; 32-thread `send_threadsafe`; stop/restore races; 1k cycles leak check | 1 Blocker→High (R4-03), R4-06, R4-16 | **FAIL** on silent drop paths; PASS on leaks (0 leaked tasks), loop blocking (<5 ms) |
| **Determinism / replay** | 50× runs both engines, 10k events; scheduling perturbation; PYTHONHASHSEED sweep | 0 Blocker, engine-parity Mediums (R4-21, R4-28, R4-29) | **PASS with constraints** — async engine deterministic run-to-run; sync≠async in 3 places |
| **Semantics conformance** | 60+ SCXML/XState cases | R4-12 (High), R4-19 (High), Mediums | **PARTIAL** — core algorithm sound; root-target `always` and `output` wrong |
| **Fuzz / property** | machine-def, event-sequence, snapshot-corruption fuzzers | R4-02, R4-14, R4-38 (typed-exception escapes) | **PARTIAL** — no crashes, but errors escape the documented base class |
| **Security / supply chain** | bandit/semgrep/pip-audit, import surfaces, codegen, snapshot reconstruction, logging | 2 Medium (R4-31 log redaction, R4-26), 3 Low | **PASS** — no injection/RCE surface; 0 deps; `kind` is an allow-list |
| **25-min soak** | 200 machines, 3k ev/s, chaos restore + plugin exceptions | 1 Low | **PASS** — flat memory, 0 leaked tasks, 0 lost accepted events, stable p99 |
| **Observability** | failure-mode × hook matrix | R4-15→Low, R4-32, R4-35, R4-36 | **PARTIAL** — most paths observable; several drop paths fire no hook |

---

## 5. Gate decision (`20-adoption-gate.md` §7)

| Row | Condition | Holds? |
|---|---|---|
| 1 | Any open **Blocker** | **YES — R4-01, R4-04 → DEFER** |

```
Gate run 2026-09-18 — xstate-statemachine main @ 5e07ba8 (unreleased 0.8.1)
DECISION: DEFER (order path)  ·  non-order paths: proceed under §6 constraints
  19 fixed issues : 17 confirm-closed, 2 reopen narrow (#91 crit 3, #99 async side)
  regressions     : none
  new defects     : 2 Blocker · 6 High · 18 Medium · 12 Low  (post-refutation; 2 refuted)
  suite/coverage  : 3276 passed / 0 failed · 90%
  operative block : UPSTREAM — R4-01 (torn snapshot), R4-04 (non-terminating start),
                    R4-06 (external events charged to chain budget), R4-07 (receipt id-keying)
```

Why this is not a harsh verdict: rounds 1–3 tested *the issues we had filed*. Round 4 was the first time the library's persistence, settling and concurrency machinery was driven the way an OMS drives it — random interruption points, property tests, hostile policies. It found what such testing usually finds in a young engine. The team's fix quality across three rounds (every item genuinely closed, +34 tests, no regressions) is the strongest evidence that R4-01/04/06/07 will be closed properly.

---

## 6. Constraints & mandatory configuration (recomputed)

**Retired:** none this round (nothing in the new findings relaxes a prior constraint).

**Standing (reinforced, incl. Amendment-3 CV-C23–C29):** CV-C01 policy block via single factory · **CV-C03 async `Interpreter` only** (R4-04, R4-21/25/28/29) · CV-C05 bounded inbox **RAISE only on the order path — BLOCK is forbidden everywhere** (R4-03) · CV-C12 **`after` banned** (R4-11 adds a persistence reason) · CV-C13 dedicated loop.

**New:**
- **CV-C23** — Snapshots may be taken **only at quiescence**: after a `send(wait=True)` receipt resolves and `queue_depth == 0`, never from a plugin hook or timer. Until R4-01 is fixed this is the only defence; encode as a factory-level `snapshot()` wrapper that refuses otherwise.
- **CV-C24** — Never rely on `Receipt.deferred` alone (R4-07); cross-check `deferred_count` before/after. Remove when R4-07 is fixed.
- **CV-C25** — No external `send()` from inside an action or while `_processing` (R4-06): all exchange/gateway events enter via the gateway queue between macrosteps. Lint: no `interp.send` in `MachineLogic` bodies.
- **CV-C26** — Parent/child data passes via explicit `sendTo`, never `output` (R4-19).
- **CV-C27** — `from_snapshot()` results validated by *our* legality check (non-empty configuration, known status, dict context) before `start()` (R4-02).
- **CV-C28** — `LoggingInspector` is never attached in production; our `CvMetricsPlugin` redacts context (R4-31).
- **CV-C29** — Every machine JSON passes our linter rule "no `always` may target the machine root" (R4-12).

Config block additions to §4.1 of `26-verify-3c527b0-verdict.md`: none (all new items are wrapper/lint constraints, not library options).

---

## 7. Release-readiness note for the library team (before tagging 0.8.1)

1. `__version__` still `0.8.0` — bump.
2. **Fix R4-01 before tagging**: `get_persisted_snapshot()` must observe only a committed configuration (take the snapshot under the same latch that guards `_processing`, or snapshot the pre-macrostep configuration). This is the single most important item in three rounds.
3. **Fix R4-06** — the #90 reroute must distinguish self-generated from external events by provenance/origin, not by the interpreter-wide `_processing` flag.
4. **Fix R4-07** — `Receipt.deferred` must not key on `id(event)`; reuse the envelope identity introduced for #75.
5. R4-04 — bound the settling loop by the same `RunawayChainError` path as the event chain (also closes R4-13).
6. R4-12 — reject root-targeting `always` at build time.
7. R4-19 — `done.invoke` must carry child `output`.
8. Do one **systematic provenance audit** of every `Event` reconstruction site (R4-08; third instance in two releases).
9. Async side of #99; config-side warning for #91.
10. Pin a `--cov-fail-under=88` floor now.

Items 1–4 are the tag-blocking set from our side.

---

## 8. What would change the verdict

- **R4-01 and R4-04 closed with a pinned test each → gate row 1 clears.** If R4-06 and R4-07 are also closed, open High count = 4 (R4-03, R4-11, R4-12, R4-19), all with mechanical mitigations in §6 → **ADOPT WITH CONSTRAINTS** for the order path, gated only on our E29-T10 linter + `tests/xstate_contract/`, exactly as at 0.8.0.
- Re-verification: re-run `gate/run_gate.py` + `probes/main-5e07ba8-final/*.py` + a reduced persistence property run (`battle-5e07ba8/persistence/`, 300 cases) on the fix commit. ~30 minutes.

---

## 9. Recommended next steps for CandleViewer

1. **Post round-4 results upstream** (drafts in `issues/post-5e07ba8/` once generated): confirm-close 17, reopen #91/#99 narrowly, file R4-01/04/06/07 as Blocker/High with the fresh repros, file Highs R4-03/11/12/19, group Mediums by area (persistence, provenance, engine parity, observability), meta #26 refresh with this scorecard and the release note.
2. **Non-order paths (B10–B14, B16–B20 except B18) may start on the library now** under §6 constraints; B18 KillSwitch and everything on the order path wait for R4-01/04/06/07.
3. **E50**: add tickets for CV-C23–C29 wrapper/lint work; keep the in-house shim as the order-path runtime until the gate clears; schedule the re-verification as the go/no-go input.
4. Contracts phase (our 20 machines end-to-end on the library) — run after R4-01 is fixed; running it now would mostly re-find R4-01.

---

## Evidence index
`30-r4-findings-register.md` (canonical findings, refutation column, merge map, harness errors) · `27-r4-gate.md` · `28-r4-diff-review.md` · `battle-5e07ba8/*.md` + `*.triage.md` · `issues/verify-main-5e07ba8/*.result.md` + `_summary.md` · `probes/main-5e07ba8-final/`.
