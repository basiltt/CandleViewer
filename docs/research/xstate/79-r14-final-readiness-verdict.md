# 79 — Round-14 FINAL readiness verdict — `xstate-statemachine` **0.9.1**

**Date:** 2026-09-24 · **Tag under test:** `v0.9.1` = `45bb7f3` · **Tree:** `main` @ `801eacd` (merge of PR #249; `git diff v0.9.1..HEAD --stat` **empty**)
**Inputs:** `75-r14-regression.md`, `76-r14-suite-bench.md`, `77-r14-diff-review.md`, `78-r14-findings-register.md` (+ the `R14-01` refutation), `battle-v0.9.1/**`, `issues/verify-v0.9.1/**`, `suite-v0.9.1.log`, `20-adoption-gate.md` §7, `74-r13-final-readiness-verdict.md`.
**Re-run in this session:** the tail of `suite-v0.9.1.log`, and `battle-v0.9.1/r14_01_remint_retarget.py` from cwd `<home>` with K=async and K=def. Both kinds printed `['m.a.d', 'm.pay.settled']`, so the defect reproduces.
**Time box:** 20 min. `bench_h_candleviewer_budgets` (BENCH-1/2) was **not re-run**; see §0.

---

## 0. Plain answers

**Are the 10 round-13 issues (#239–#248) genuinely closed?**
**Yes, all 10, on both engines and both service spellings (`def` / `async def`).** Each has a standalone re-verification in `issues/verify-v0.9.1/`, and every one exited 0 across five sweeps. `tests/test_round13_findings.py` passes 24/24. The only caveat is on #248. `re_mint()` correctly refuses plain or demoted events, which is exactly what #248 asked for. But the *new* public API has its own hole: it accepts `type=` / `src=` overrides, so it can re-target a completion at a different live invoke (**R14-01**, below). That is a new defect in the fix, not a failure to fix #248.

**Is 0.9.1 fully battle-tested?**
**Yes, as far as this programme can test from outside.** This is the 14th round. It covered six tracks plus the 20-chart contract corpus in both spellings, and the historical sweep had **0 true regressions and 0 timeouts**. One apparent regression (105) was a sleep-instead-of-poll flake; a convergence repro went 12/12 at 3000/3000. The library's own suite: **3601 passed, 13 skipped, 0 failed, 586.76 s, coverage 92.93%** (bar 90%). One library defect survives: **R14-01, Medium after refutation.** It needs in-process code that already holds a genuine engine event and misuses a public API. External input cannot reach it.

**Good to proceed?**
**Yes. ADOPT WITH CONSTRAINTS, decision-table row 8.** This is up two from round 13's row 6. #239 closed R13-01, the High row is now **empty**, and all Mediums are triaged. It is **not row 9**, because BENCH-1/2/6 are not all met (details below).

**Is v0.9.1 the pin? Yes.**
- `v0.9.1` = `45bb7f3`. `main` differs from it only by an empty merge commit.
- The PyPI wheel `xstate_statemachine-0.9.1-py3-none-any.whl` has sha256 `d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162`, which matches the briefing.
- **Wheel equals tag, 42/42.** Every `.py` module is byte-identical to `git show v0.9.1:src/...` after newline normalisation.
- **The attestation is verifiable.** `python -m pypi_attestations verify pypi --repository https://github.com/basiltt/xstate-statemachine pypi:xstate_statemachine-0.9.1-py3-none-any.whl` returned `OK` (`issues/verify-v0.9.1/247-248.md`). This is the first release in the programme with Sigstore-backed PEP 740 provenance.

**Is this row 9? No, but the reason is ours, not the library's.**

| Condition | Status |
|---|---|
| Blocker row empty (library) | ✅ 0 |
| High row empty (library) | ✅ 0 (R14-01 downgraded to Medium, with evidence) |
| All Medium triaged | ✅ R14-01 → new constraint `CV-C68` (§7) |
| **BENCH-6** loaded timer drift, 500 busy, p99 ≤ 100 ms | ✅ **met, p99 = 92.2 ms** (p50 70.3), n = 10. Headroom fell from 44 ms (r13: 55.8) to 7.8 ms. The wrapper read p99 69.0 in the same session. **Watch item** (host variance, see §3). |
| **BENCH-1** order-path headroom ≥ 3.0× | ⚠ **last measured 3.17×, met**, at 0.8.0. Not re-measured on 0.9.1 (bench_h was descoped by the time box). *Unmeasured is not met.* |
| **BENCH-2** rule-lifecycle rate ≥ 2,000 ev/s | ❌ **last measured 380.9 ev/s**, bar 2,000. **Short by about 5×.** |

BENCH-2 is short, and that is **architectural (ours)**. The bar assumes a statechart evaluates every rule on every tick. Our design (the `20-adoption-gate.md` §7 BENCH-2 constraint) already gives charts rule *lifecycle* only, behind a ≥99% plain-function pre-filter. No engine that runs a Python macrostep per event gets to 200k evaluations/s. Neither the library nor anything upstream can close this; it is a standing architectural constraint. BENCH-1 just needs to be re-run. BENCH-6 is met, narrowly, on a dev host.

---

## 1. Disposition of the 10 issues

| # | Disposition | Evidence |
|---|---|---|
| 239 | **FIXED** | `drain_pending()` drains the priority lane first, then the inbox. `wait=True` receipts resolve with `error=InterpreterStoppedError`. Standalone repro and B17/B18/B20 both kinds. |
| 240 | **FIXED** | `on_interpreter_start` fires exactly once on fresh start, sync-restore, and async-restore+`restart_services`. `restored_from_snapshot` correctly tells resume from boot. |
| 241 | **FIXED** | NaN-string, list, dict, negative int, and bool `chain_trips`/`last_chain_error` all raise `SnapshotCorruptError`. Valid numeric strings are still accepted (T-3, Info). |
| 242 | **FIXED (docs)** | The `snapshots.md` trust-boundary paragraph (#205/#242) is present verbatim. |
| 243 | **CLOSED** | MRO `RestoredChainError → RestoredError → RunawayChainError`, verified live. |
| 244 | **CLOSED** | `dropped_receipts` and `on_receipt_dropped` are deterministic under any warning filter. Caveat to document: the hook runs in a finaliser, so it may run off-loop and after `stop()` (T-5). |
| 245 | **CLOSED** | `SyncInterpreter(max_queue_size=<non-None>)` raises `ValueError`. `overflow_policy` on its own is accepted by design. |
| 246 | **CLOSED** | `--json`/`--json-file` emit the host block and rows. The script is a repo dev tool and not in the wheel, as expected. |
| 247 | **FIXED** | PEP 740 attestation verifies `OK` against live PyPI. |
| 248 | **FIXED, with a new defect in the new API** | Plain or demoted events raise `TypeError`, as documented. The `type`/`src` override route is R14-01 (§5). |

**10/10 closed. 0 partial. 0 not-fixed.** This is the fifth consecutive round where every claimed fix landed on every axis it claimed.

## 2. Regressions

**0 true library regressions** (`75-r14-regression.md`).
- Adoption gate: 0 ERROR. The FAIL set is the tracked baseline set. Row 167 failed once under sweep CPU load, then passed ×3 on its own and 10/10 as a script. **Standing rule: run the gate on an idle host.**
- Historical sweep: 0 TIMEOUT, including 190 livelock/hang scripts under the 120 s watchdog.
- Four sweep FAILs were triaged as harness issues, not regressions:
  - 105: sleep-not-poll flake; a convergence repro went 12/12.
  - 233_235: pinned to 0.9.0.
  - p3: needs argv.
  - 228: needs `XSM_REPO`.

## 3. Scorecard

| Axis | r13 (0.9.0) | **r14 (0.9.1)** | Δ |
|---|---|---|---|
| Issues closed | 11/11 | **10/10** | = |
| Suite | 3577 P / 92.86 % | **3601 P / 13 S / 0 F / 92.93 %** | ▲ |
| Library Blocker / High / Medium | 0 / 1 / 3 | **0 / 0 / 1** | ▲▲ |
| Wheel == tag | 42/42 | **42/42** | = |
| Provenance | hash only | **hash + PEP 740 attestation, verified** | ▲ |
| BENCH-6 p99 @ 500 busy | 55.8 ms | **92.2 ms** (bar 100) | ▼ still met |
| BENCH-1 | 3.17× (0.8.0) | **not re-measured** | — |
| BENCH-2 | 380.9 ev/s (0.8.0) | **not re-measured**; architectural | — |
| bench_a / bench_e / bench_j | OK | **OK** (33.4k ev/s; 0.085 KB/actor RSS; policy overheads nominal) | = |

The BENCH-6 drift from 55.8 to 92.2 ms is not a functional regression: no tests fail, and the wrapper read 69.0 ms p99 in the same session. The most likely cause is host load while the suite ran concurrently. `P3-G6` (target-hardware BENCH-6) is still the binding gate before any `after:` deadline relies on it.

## 4. Contracts, drain→restore round-trip, our catalogue Blockers

- **B1–B20, both `def` and `async def`:** green on 0.9.1. Example: B16–B20 plus B11 `w1_contracts.py` passed **48/48 on each kind**, run under `-W error::RuntimeWarning`, bounded queue, `strict`, `minimum_version=3`.
- **drain → persist → stop → restore → start → replay:** green on every chart, both kinds:
  - `drain_pending()` returns `[prio, *inbox]` in that order.
  - The restored configuration equals the pre-shutdown one.
  - `on_interpreter_start` fires once, with `restored_from_snapshot=True`.
  - Each drained event is replayed exactly once, with one receipt.
  - `dropped_receipts == 0` and `chain_trips == 0`.
- **Our 3 catalogue Blockers (R14-03, OURS):** R13-13 (B16/C-04 root-hoist to `elevation.dead`), R13-14 (B18/C-07b defer plus an unguarded audit arm), and R13-15/16 (B11 event-aware guard). The fixes are **proven green on 0.9.1 in both lanes** (g4 11/11, g2, w1) but are **not yet merged into `docs/plan/28`**. This pass records them in 28 as *fix specified, merge pending implementation*. They remain **Blocker (ours)** until the corrected JSON lands in the catalogue source of truth. Also ours: **B610-OC-CD03**, High (the B8 naked↔verifying loop trips the chain budget; needs a bounded attempt counter).

## 5. Surviving defects by final severity

**Library:**

| ID | Class | Final severity | Summary |
|---|---|---|---|
| **R14-01** | LIBRARY-DEFECT, CONFIRMED | **Medium** (High → Medium on refutation) | `events.re_mint(ev, type=..., src=...)` re-targets a genuine completion at a different live invoke. The still-running `m.pay.w` invoke's `onDone` fired while its service slept. This was reproduced this session in both kinds. Root cause: `events.py:687-702` forwards every `**fields` override to the `_Engine*` constructors, which contradicts the docstring's "carried forward, never created". **Why Medium:** it needs in-process code that already holds an engine event and passes identity overrides; external input cannot reach it. |
| R14-02 | DESIGN-CONSTRAINT | Low | A drained receipt carries `InterpreterStoppedError` even when the machine keeps running. |
| R14-04 | NEEDS-WRAPPER | Info | rollback plus a raising `onDone` re-arms, and is cut by `maxIterations`. Alert on `chain_trips > 0`. |
| T-3 / T-5 | Info | Info | `check_shape` is lenient toward int-coercible strings. `on_receipt_dropped` runs in a finaliser. |
| R11-01, R12-03, D13-security-3 | Carried | accepted | Documented trust boundaries or mitigated. |

**Board: 0 Blocker · 0 High · 1 Medium · 1 Low · 3 Info (library).**
**Ours: 3 Blocker (R14-03 chart merges) · 1 High (B610-OC-CD03).** These are not library defects.

## 6. GATE DECISION (§7 decision table, first match wins)

| Row | Condition | Status |
|---|---|---|
| 1 | Any ERROR row | No (0 ERROR) |
| 2 | Suite fails or coverage < 86% | No (3601 P, 92.93%) |
| 3 | Snapshot format changed while LC-21 open | No (LC-21 closed) |
| 4 | Filed Blocker repro exits 1 | No |
| 5–7 | High open | No (0 High) |
| **8** | **All Blocker and High closed; all Medium triaged; BENCH-1/2/6 not all met** | **✅ MATCH**. BENCH-2 is short (architectural) and BENCH-1 is unmeasured this round. |
| 9 | …all benchmarks met | Refused: BENCH-2 is 380.9 against 2,000, and BENCH-1 was not re-measured |

### **DECISION: ADOPT WITH CONSTRAINTS — decision-table ROW 8**, on all four lifecycle families.

The §7 architectural constraints apply: BENCH-1 → a dedicated order loop, BENCH-2 → lifecycle-only charts with a ≥99% pre-filter. **Precondition for live order traffic (ours, not the library's):** the R14-03 chart fixes are merged into catalogue 28 and `tests/xstate_contract/` is green on them.

```
Gate run 2026-09-24 — xstate-statemachine 0.9.1 (tag v0.9.1 = 45bb7f3) — DECISION: ADOPT with constraints (row 8)
  repros   : all library Blockers closed; 10/10 round-13 issues closed
  gate     : 0 ERROR (FAIL set = tracked baseline; 167 load-flake, idle re-run PASS)
  benches  : BENCH-6 MET p99 92.2 ms (bar 100, n=10); BENCH-1 unmeasured (last 3.17x);
             BENCH-2 380.9 ev/s (bar 2000, architectural)
  suite    : 3601 passed, 13 skipped, 92.93%
  blockers open: (library) none   high open: none   medium: R14-01 -> CV-C68
```

## 7. Constraints: retire / stand / new

| ID | Change | Ground |
|---|---|---|
| `CV-C65` | **RELAXES to `CV-C65′`.** `drain_pending()` is now complete (both lanes, priority first; #239). The shutdown path may use it to journal the drained list *before* `stop()`. Persist through `get_persisted_snapshot()`, check `Receipt.error` on drained receipts, and de-duplicate re-submits (R14-02). | #239 FIXED |
| `CV-C66` | **RELAXES to `CV-C66′`.** `on_interpreter_start` now fires on every path. It is permitted for telemetry, branching on `interpreter.restored_from_snapshot`. Bring-up stays in our wrapper, which is simpler to audit. | #240 FIXED |
| `CV-C63` | **Stands, narrowed.** Read `chain_trips > 0`. `isinstance(..., RunawayChainError)` is now safe on restored latches too (#243), but the count remains the single rule. | #243 |
| `CV-C12′`, `CV-C25`, `CV-C45″`, `CV-C49′`, `CV-C55`, `CV-C58`, `CV-C64′`, `CV-C67` | **Stand**, unchanged. | r13 §7 |
| `CV-C12′` | **Stands, with an added watch.** BENCH-6 headroom is now 7.8 ms on the dev host. P3-G6 (target hardware) is binding. | §3 |
| **`CV-C68`** *(new)* | `events.re_mint()` may be called **only** with payload overrides (`data`, `error`, and timer `fired_at`/`scheduled_for`). Passing `type=` or `src=` is **banned**. Enforce it with a lint over the plugin and listener modules, plus a wrapper `cv_re_mint()` that raises on any other key. Retires when upstream closes R14-01. | R14-01 |
| **`CV-C69`** *(new)* | Supervisors must use `dropped_receipts`/`on_receipt_dropped` in place of the RuntimeWarning. The hook body must be thread-safe and must not touch the loop, because it may run in a finaliser after `stop()`. | #244, T-5 |

### FINAL mandatory machine configuration (binding; both engines, both spellings)

```python
machine = create_machine(chart, logic=logic, strict_config=True)
interpreter = Interpreter(
    machine, strict=True, event_schemas=CV_EVENT_SCHEMAS,
    max_queue_size=CV_INBOX_BOUND,     # async only; SyncInterpreter(max_queue_size=...) -> ValueError (#245)
    overflow_policy="refuse",
).use(CvErrorHooks())
# chart root: "onUnhandled": "defer" (+ ordered unguarded audit arm), "maxIterations": 500 (CV-C62)

# restore
interpreter = Interpreter.from_snapshot(machine, blob, minimum_version=3,
                                        plugins=[CvErrorHooks()])   # kwarg, not .use() (R13-W1)
assert interpreter.last_transition_ok is not None                    # before start() (CV-C60)
_cv_bring_up(interpreter)                                            # CV-C66'
await interpreter.start()   # on_interpreter_start fires; branch on restored_from_snapshot

# supervision
if interpreter.chain_trips > 0: page_operator(interpreter.last_chain_error)
if interpreter.dropped_receipts > 0: alert("receipt dropped")        # CV-C69

# shutdown (CV-C65')
drained = await interpreter.drain_pending()     # [priority..., inbox...]
journal(drained)                                # replay exactly once after restore
blob = interpreter.get_persisted_snapshot()
await interpreter.stop()

# provenance (CV-C68)
ev2 = cv_re_mint(ev, data=patched)              # never type=/src=
# timing: after:/raise(delay=) coarse only, >=250 ms tolerance, >=10 ms (CV-C12', CV-C55)
# actions: coroutine functions directly (CV-C67); no external send() in actions (CV-C25)
```

## 8. Release position

**v0.9.1 is tagged, published, attested, and is the pin.**

```toml
[project.dependencies]
xstate-statemachine = "==0.9.1"
# lock: sha256:d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162
# provenance: PEP 740 attestation, repo basiltt/xstate-statemachine, verify in CI:
#   python -m pypi_attestations verify pypi --repository https://github.com/basiltt/xstate-statemachine \
#       pypi:xstate_statemachine-0.9.1-py3-none-any.whl
# anchor: git tag v0.9.1 = 45bb7f3
```

### What is still missing for "perfect"

1. **Upstream (library):** fix R14-01 by rejecting `type`/`src` (or anything other than payload fields) in `re_mint`, with a regression test on both engines for Done and AfterEvent. That is the only library item.
2. Optional upstream: a dedicated `EventDrainedError` (R14-02), and a doc note that `on_receipt_dropped` runs in a finaliser (T-5).
3. **Ours:** re-run `bench_h` for BENCH-1 alone on an idle host; BENCH-6 on target hardware (P3-G6); merge the R14-03 chart fixes; fix B610-OC-CD03.

BENCH-2 is not on this list, because it is architectural and permanent.

## 9. What would change the verdict

| Event | Effect |
|---|---|
| R14-01 fixed upstream and verified on both kinds | `CV-C68` retires. The row stays 8, because BENCH-2 is architectural. |
| R14-01 shown reachable from external input (a deserialised or wire event) | It rises back to High and the verdict drops to **row 6**, with `CV-C68` as the enforced mitigation. |
| BENCH-1 re-measured < 3.0× on 0.9.1 | Still row 8. The dedicated order-loop constraint becomes load-bearing rather than precautionary. |
| BENCH-6 > 100 ms p99 on an idle host or target hardware | Still row 8. `CV-C12′` reverts to the `after:` ban (`CV-C12`) on that hardware. |
| Any new library Blocker, or a suite/coverage regression | Rows 1–4: **DEFER**. |
| Row 9 | This would need BENCH-2 ≥ 2,000 ev/s, which is not expected with any Python engine. **Row 8 is the realistic ceiling for this architecture.** |

## 10. Next steps

**Phase-3 gates** (carried from r13, updated):
- **P3-G1.** Merge the R14-03 fixes (B16, B18, B11) and the B8 attempt counter into `28-statechart-catalogue.md`. `tests/xstate_contract/` must be green on both kinds. **This blocks live order traffic.**
- **P3-G2.** Dependency bump to `xstate-statemachine==0.9.1` with a hash lock, plus a CI attestation-verify step.
- **P3-G3.** Implement and lint `CV-C68` and `CV-C69`; relax `CV-C65′`/`CV-C66′` in the wrapper.
- **P3-G4.** Run `bench_h` alone on an idle host (BENCH-1).
- **P3-G6.** BENCH-6 on target hardware, ≤ 100 ms p99, as a CI gate.

**E50:** new tickets E50-T56 (CV-C68 re_mint wrapper + lint), E50-T57 (bump to 0.9.1 + attestation verify), and E50-T58 (CV-C65′ drain journal + CV-C69 receipt-drop supervision).

**What remains OURS:** the chart fixes (R14-03, B610-OC-CD03), BENCH-1 re-measurement, target-hardware BENCH-6, the BENCH-2 architecture (the pre-filter), and every wrapper constraint above. **What remains theirs:** R14-01 (Medium) only.

**Postables (NOT posted):** `issues/post-v0.9.1/` has comments for #239–#248, `new/R14-01-re-mint-type-src-override-retargets-completion.md`, `meta-26.md`, and `manifest.json`.
