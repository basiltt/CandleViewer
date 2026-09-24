# 34 — Round-5 FINAL readiness verdict: `xstate-statemachine` main @ `3ed3099` (unreleased 0.8.1)

Date: 2026-09-19. Question asked by the owner: *"Verify all reported issues are genuinely closed; is the library completely ready, fully battle-tested, and are we good to proceed?"*

Method: 39 issue verifications (+ independent recheck); regression gate over every prior verification set and probe; library suite + coverage (run by hand after the gate agent timed out); key benchmarks (run by hand); diff review 5e07ba8..3ed3099; all 8 battle tracks re-run with new attacks on this round's fixes; the 20 CandleViewer contract machines driven end-to-end on the library; triage → dedupe → independent adversarial refutation of every Blocker/High. Register of record: `33-r5-findings-register.md`.

---

## 0. The answer

**Are the 39 reported issues genuinely closed? — Yes, 34 fully; 5 partially.** No regressions of any previously verified item (one probe flake, LC-12, is intermittent and *not counted*). Suite **3 322 passed / 0 failed**, coverage **90 %**. The team's fix quality has been consistently high across five rounds.

**Is the library fully battle-tested and ready for the order path? — No, not yet.** Round 5 found **21 new library defects — 4 Blocker, 8 High, 8 Medium, 1 Low** (post-refutation) — and, critically, **three of the four Blockers are the round-4 Blockers re-emerging one layer deeper**: each fix addressed the *reproducer* it was given rather than the *invariant* behind it.

| Round-4 fix | What it fixed | What it missed (round 5) |
|---|---|---|
| #102 `SnapshotMidStepError` | Snapshot with **no** active leaf is refused | Check is *any-leaf*, not *per-region*: a **parallel machine with one torn region still snapshots** and restores inert (R5-01) |
| #110 `SnapshotCorruptError` | Named malformed fields | **No configuration-legality check on restore**: a truncated/root-only configuration loads as `running` with zero leaves, permanently inert (R5-02); other fields still leak raw `TypeError`/`AttributeError` (R5-03) |
| #103 per-macrostep settle budget | The specific cross-region `always` case | **Nested invokes whose `onDone` targets their common ancestor livelock `start()`** — the budget self-resets, no `maxIterations` bounds it (R5-04) |
| — | — | **`actionErrorPolicy: "fail"` reverts to the *source* state**, bricks the interpreter, and the result is snapshottable (R5-12) — this policy is in our mandatory config for invariant machines |

**Are we good to proceed?**
- **Non-order paths (B10–B17, B19, B20 — recording, replay, connection, ingestion supervision, auth, live-enablement, reconciliation, risk lockout): YES, proceed now** under the standing constraints. Every relevant Blocker is either on a path those machines do not use or is mechanically avoidable (no parallel regions + our restore legality check).
- **Order path (B1–B9, B18): NO — DEFER.** Four independent Blockers, each sufficient on its own. What stands in the way is **upstream**, and it is now clearly characterised: the library needs a **single configuration-legality invariant** (every parallel region has exactly one active leaf; every active state's ancestors are active) enforced on **both** the snapshot write side and the restore read side, plus a settle budget that is genuinely bounded. That is one design change, not four patches.

---

## 1. The 39 issues

| Result | Issues |
|---|---|
| **FIXED — confirm closed (34)** | #91 #99 #102 #103 #104 #105 #106 #107 #108 #109 #110 #111 #112 #113 #114 #115 #116 #117 #119 #120 #121 #123 #124 #126 #127 #128 #129 #130 #131 #132 #135 #136 #137 #138 |
| **PARTIAL — reopen narrowly (5)** | **#118** `AfterEvent` lateness telemetry round-trips only for the fields named · **#122** `tick()` still one-deadline-per-call in a documented sub-case · **#125** deferred replay is its own macrostep, but the *receipt* of the replay is not exposed · **#133** unresolved `sendTo` fires the hook but does not set `last_error` · **#134** `on_resolve_error` exists but is not fired from the `strict_targets=False` runtime path |

Note on the two round-4 Blockers: **#102 and #103 are closed as filed** (their reproducers pass) — the deeper defects are filed as *new* issues R5-01/R5-04, not as reopens, because the acceptance criteria as written were met. This distinction is stated plainly in the upstream comments.

---

## 2. Regressions

**None confirmed.** `31-r5-gate.md` flagged LC-12 (`spawn_blocking` async) as a possible regression on 1 of 3 runs; the triage did not count it (needs a ≥10-repeat run — listed in §8). Everything else that passed at 5e07ba8 passes at 3ed3099.

Suite **3 322 passed / 13 skipped / 0 failed** in 8 m 51 s (+46 tests); coverage **90 %** (unchanged).

---

## 3. Battle-test scorecard (3ed3099)

| Track | Round-4 defects | Now | New defects (post-refutation) | Verdict |
|---|---|---|---|---|
| Persistence | 1 B, 3 H, 7 M | all as-filed fixed | **R5-01 (B)**, R5-03 (H), R5-17, R5-21 | **FAIL** — legality invariant still absent |
| Concurrency | 1 H, 2 M | fixed | **R5-02 (B)**, R5-06 (H), R5-15, R5-16 | **FAIL** on restore path; PASS on leaks/loop blocking |
| Fuzz | 3 M | fixed | **R5-04 (B)**, R5-05 (H) | **FAIL** — livelock reachable from generated configs |
| Determinism | 3 M | fixed | R5-13 (H), R5-18 | PASS with constraints (async engine deterministic) |
| Semantics | 2 H, 1 M | fixed | R5-10 (H), R5-14 | PARTIAL |
| Observability | 1 H, 3 M | fixed | R5-11 (H) | PARTIAL — `Receipt(changed=False, error=None)` still ambiguous across 3 causes |
| Security | 2 M | fixed (redaction shipped) | R5-19, R5-20 | **PASS** — no injection surface; redaction has a DEBUG bypass |
| Soak (12 min reduced) | 1 L | — | none | **PASS** — flat memory, 0 leaked tasks, 0 lost events |

Diff review added R5-07 (H, **regression of intent**: #116 makes a plain-`def` service run inline on the async loop — a slow sync service now blocks the loop), R5-08 (H: the #105 self-send gate is a `contextvars` read, so `send_threadsafe` bypasses it), R5-09 (H: settle budget reset per drain, not per macrostep).

## 4. Contract machines (B1–B20) on the library

Every machine loads and runs its happy path after fixes to **our own JSON** (10 our-contract defects, `33-…` §6). The most important one is ours, not the library's:

- **OC-01 (Blocker, ours):** the `"*": {"actions": ["defer"]}` scaffolding we left in the catalogue from the 0.7.0 workaround is **live** — it pre-empts `onUnhandled: "defer"` and **silently disables `strict: true` machine-wide**. One-key-per-state removal. Already applied in `battle-3ed3099/contracts/*.machine.json`; must be applied to `28-statechart-catalogue.md`.
- OC-02…OC-06 (Major): genuine gaps in B2, B4, B11, B16, B19 invariants (e.g. B4 OCO `completing` never handles a late leg fill; B16 elevation survives logout). Good catches — these would have been production bugs regardless of runtime.
- OC-07: our mandatory `actionErrorPolicy: "fail"` row cannot achieve halt-not-continue on this library (R5-12).

Invariant results: B10–B17, B19, B20 **PASS** on the library after OC fixes. B1–B9, B18 **PASS functionally** but are exposed to R5-01/02/12 on the snapshot path and R5-12 on the fail policy.

---

## 5. Surviving library defects (final severity)

**Blocker (4):** R5-01 any-leaf mid-step check misses parallel tears · R5-02 no read-side legality check on restore · R5-04 nested-invoke `onDone` livelock in `start()` · R5-12 `"fail"` reverts to source state and bricks the interpreter.
**High (8):** R5-03 raw exceptions from `from_snapshot()` · R5-05 `strict_targets=False` reopens #108 · R5-06 external cancel before first turn → `running` + hang · R5-07 sync service inline blocks async loop · R5-08 `send_threadsafe` bypasses self-send gate · R5-09 settle budget per drain · R5-10 guard raising on engine-driven transition · R5-11 receipt ambiguity · R5-13 sync restore returns before clock attach.
**Medium (8), Low (1):** R5-14…R5-21 (see register).

---

## 6. Gate decision

```
Gate run 2026-09-19 — xstate-statemachine main @ 3ed3099 (unreleased 0.8.1)
DECISION: DEFER (order path)  ·  GO for non-order paths under constraints
  39 issues      : 34 confirm-closed, 5 partial (narrow reopens)
  regressions    : none confirmed
  new defects    : 4 Blocker · 8 High · 8 Medium · 1 Low  (post-refutation)
  suite/coverage : 3322 passed / 0 failed · 90%
  benchmarks     : order-path headroom 2.65× (bar 3.0×, FAIL, unchanged class);
                   rollback policy cost now ~0 (21.7k vs 21.4k ev/s — #27 fix confirmed);
                   500-order p95 0.10 ms PASS
  operative block: UPSTREAM — configuration-legality invariant (R5-01/02), bounded settle (R5-04), fail-policy semantics (R5-12)
```

**Why the verdict is DEFER and not "ADOPT with wrappers":** we *could* wrap R5-02 (our own restore legality check, already ticketed as E50-T12) and avoid R5-01 by banning parallel regions on the order path. But R5-04 and R5-12 are not wrappable — a livelocked `start()` and a policy that bricks the interpreter are engine behaviours — and stacking three wrappers over the persistence layer of a runtime we chose *for* its persistence is the wrong trade for money. The in-house shim stays on the order path.

---

## 7. Constraints

**Retired (fixes make them redundant):** CV-C24 (`Receipt.deferred` cross-check — #106 fixed by reference), CV-C25 (no send inside actions — #105 per-task gate; **but see R5-08**: keep the *lint*, drop the runtime guard), CV-C26 (`output` via sendTo — #109 fixed), CV-C29 (root-target `always` lint — #108 build-time rejection; keep as belt-and-braces only if `strict_targets` could ever be False, which CV-C01 forbids).
**Standing:** CV-C01…C22, **CV-C23 (quiescence-only snapshots) — stands and is now the primary defence against R5-01**, CV-C27 (restore legality check — now covers R5-02), CV-C28 (no `LoggingInspector` in prod — R5-19 DEBUG bypass).
**New:** **CV-C30** no parallel regions in order-path machines until R5-01 is fixed · **CV-C31** `actionErrorPolicy: "rollback"` everywhere; `"fail"` is **forbidden** until R5-12 is fixed (update the mandatory block: B8/B17/B18/B20 use `rollback` + an explicit `halted` state) · **CV-C32** every service is `async def` (R5-07) · **CV-C33** `send_threadsafe` only via our gateway which applies the self-send rule (R5-08) · **CV-C34** remove all `"*": defer` scaffolding from the catalogue (OC-01).

---

## 8. Release-readiness note for the team (before tagging 0.8.1)

1. `__version__` still `0.8.0` — bump.
2. **Implement one configuration-legality invariant** (each parallel region exactly one active leaf; ancestors of every active state active) and enforce it in `get_persisted_snapshot()` **and** `from_snapshot()` — closes R5-01, R5-02 and the class behind #102/#110 for good. Add a property test that snapshots at every quiescent point of a random parallel machine.
3. Bound the settle budget per macrostep for real (R5-04, R5-09); add the nested-invoke `onDone`-to-ancestor case as a pinned test.
4. Fix `"fail"` to halt in the *target-or-halted* state, never revert to source, and refuse to snapshot a halted interpreter (R5-12).
5. #116 follow-up: run plain-`def` services via `run_in_executor` or document that they must be trivial (R5-07).
6. Route `send_threadsafe` through the same self-send classification as `send` (R5-08).
7. Wrap every `from_snapshot` field access so only `SnapshotCorruptError` escapes (R5-03).
8. Repeat-run LC-12 ≥10× to settle the flake question.
9. Coverage floor `--cov-fail-under=88`.

---

## 9. What would change the verdict

Close **R5-01, R5-02, R5-04, R5-12** with pinned tests → Blocker row clears. With R5-07/R5-08 also closed, open-High count is 6 (R5-03/05/06/09/10/11/13 minus two) — over the bar of 5, so **one more** of those must close for **ADOPT WITH CONSTRAINTS** on the order path. Re-verification: `gate/run_gate.py` + `battle-3ed3099/persistence` property run (500 cases) + `battle-3ed3099/fuzz/d1_livelock.py` + contracts B1/B8/B18. ~40 minutes.

---

## 10. Next steps for CandleViewer

1. **Post round-5 upstream** (drafts to be generated in `issues/post-3ed3099/`): 34 confirm-closed, 5 narrow reopens, **21 new issues** (4 Blocker, 8 High, 8 Medium, 1 Low), meta #26 refresh with this scorecard and the release note.
2. **Fix our catalogue now** (OC-01…OC-10) — these are real bugs in our contracts regardless of runtime; apply the `battle-3ed3099/contracts/*.machine.json` diffs to `28-statechart-catalogue.md`.
3. **Start non-order machines on the library** (E50 enablement) under CV-C01…C34.
4. **Order path stays on the in-house shim**; E50-X01 go/no-go re-runs when the team pushes R5-01/02/04/12.
5. Retire E50-T11 (runtime send-guard) and E50-T13's root-target rule; keep E50-T10 (quiescence snapshot wrapper) and E50-T12 (restore legality check) — they are now the load-bearing mitigations.

## Evidence index
`33-r5-findings-register.md` · `31-r5-gate.md` · `32-r5-diff-review.md` · `battle-3ed3099/*.md` + `contracts/*.md` · `issues/verify-main-3ed3099/*.result.md` · suite/coverage/bench runs recorded in this document §2/§6 (2026-09-19, Python 3.13.7, Windows 11).
