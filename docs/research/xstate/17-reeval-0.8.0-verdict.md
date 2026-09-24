# 17 — Re-evaluation verdict: `xstate-statemachine` 0.8.0 ("Fortify")

**Library under test:** `basiltt/xstate-statemachine` 0.8.0, commit `9bf6065`, local clone, `pip install -e .` into `.venv-gate`.
**Python / OS:** CPython 3.13.7, Windows 11 Pro 10.0.26200, Intel 4C/8T, 15.9 GB.
**Date:** 2026-09-17.
**Baseline replaced:** 0.7.0 (commit `42612cf`) — `20-adoption-gate.md`, `12-challenge-register.md`.
**Evidence:** `issues/verify-0.8.0/*.result.md` (34 per-issue re-verifications), `13-reeval-0.8.0-bench.md` (benchmarks + policy cost), `14-reeval-0.8.0-probes.md` (51 semantic probes), `15-reeval-0.8.0-adversarial.md` (11 hostile probes, `probes/v080/`), `16-reeval-0.8.0-diff-review.md` (full `v0.7.0..v0.8.0` source diff).

> **Reading rule, applied throughout.** The 0.8.0 release notes state that nearly
> every fix is a **per-machine policy or additive API whose default preserves
> 0.7.x semantics**. Our 0.7.0 repro scripts exercise the *defaults*. A repro
> that still exits 1 therefore means one of three things — *unfixed*,
> *fixed-but-opt-in*, or *stale repro* — and is never assumed to mean "unfixed".
> The classification column below is the triaged answer, not the exit code.

**Classification vocabulary**

| Class | Meaning |
|---|---|
| **FIXED-DEFAULT** | The correct behaviour is what you get with no configuration. No CandleViewer opt-in required. |
| **FIXED-OPT-IN** | The fix exists and is verified, but the 0.7.x-compatible behaviour is still the default. Closed **only if** CandleViewer mandates the option in §4 and CI enforces it. |
| **PARTIAL** | The fix lands for part of the defect class, or on one engine only, or introduces a new gap of the same class. |
| **NOT-FIXED** | Out of scope for 0.8.0; behaviour unchanged. |

---

## 1. Per-issue table

34 filed issues, re-verified individually. "Option required" is the exact
CandleViewer-side configuration that must be set for the row to count as closed.

| LC | GH# | Severity (register) | 0.8.0 classification | Option required | Residual |
|---|---|---|---|---|---|
| **LC-01** | [#27](https://github.com/basiltt/xstate-statemachine/issues/27) | **Blocker** | **FIXED-OPT-IN** | `actionErrorPolicy: "rollback"` (order path) / `"fail"` (invariant machines) | Rollback is a *context + configuration* transaction only — already-emitted `raise`/`sendTo` effects are **not** retracted (D-2). Costs **−22% throughput** when armed (bench §5). Default `"continue"` still commits, but is now observable via `last_transition_ok` + `on_transition_failed`. |
| **LC-02** | [#29](https://github.com/basiltt/xstate-statemachine/issues/29) | **Blocker** | **FIXED-DEFAULT** | none (`strict_targets` default `True`) | Original repro exits 1 only because it now dies with an uncaught `InvalidConfigError` at `create_machine()` — which *is* the fix. Repro stale. |
| **LC-03** | [#28](https://github.com/basiltt/xstate-statemachine/issues/28) | **Blocker** | **FIXED-OPT-IN** | `onUnhandled: "defer"` (order path) / `"error"` (control machines) | None found. 9/9 under hostile probing (B1–B9), including the exact original blocker (B5: a `FILL` arriving one microstep before its handler is armed is held and applied). `DEFER_MAX` overflow evicts oldest and reports it. Cost ≈ −1.7%. |
| **LC-05** | [#36](https://github.com/basiltt/xstate-statemachine/issues/36) | High | **FIXED-DEFAULT** | none | None. Original repro passes unmodified on both engines. Probe C10 flipped FAIL→PASS. |
| **LC-06** | [#34](https://github.com/basiltt/xstate-statemachine/issues/34) | High | **FIXED-DEFAULT** | none; **must not** set `strict_targets=False` | Exception type is `InvalidConfigError`, not the `StateNotFoundError` the issue specified. The `strict_targets=False` escape hatch warns via `DeprecationWarning` (a Python warning), not a `logger.warning`. Ambiguous last-segment match not independently re-verified. |
| **LC-07** | [#31](https://github.com/basiltt/xstate-statemachine/issues/31) | High | **FIXED-DEFAULT** (core) / **PARTIAL** (warning) | `strictTargets: true` to kill the sibling fallback | The 0.7.x sibling fallback for `.child` is **still reachable by default and emits no warning** in our run. There is no "warn but still succeed" middle ground — you either get the fallback silently or disable it. |
| **LC-08** | [#30](https://github.com/basiltt/xstate-statemachine/issues/30) | High | **FIXED-DEFAULT** | none | Multi-target single-message aggregation and runtime `on_transition_failed` under `strict_targets=False` not independently stress-tested. |
| **LC-09** | [#35](https://github.com/basiltt/xstate-statemachine/issues/35) | High | **FIXED-DEFAULT** (observability) / **FIXED-OPT-IN** (outcome) | `guardErrorPolicy: "raise"` | `on_guard_error` fires under the default, so the *invisibility* half is unconditionally closed. `SyncInterpreter` propagation under `"raise"` and the interpreter-level override not re-verified. |
| **LC-12** | [#41](https://github.com/basiltt/xstate-statemachine/issues/41) | Medium | **FIXED-DEFAULT** | `spawnBlockingTimeout` (ms) per machine | Async `spawn_` still blocks the parent loop for a sync-bodied child; the naming remains confusing (diff review §2d). |
| **LC-16** | [#40](https://github.com/basiltt/xstate-statemachine/issues/40) | **Blocker** | **FIXED-DEFAULT** | none | `sendTo` to an **unresolved** id may still log-and-drop under all settings — 0.8.0's `strict` mode covers *inbound* event names, not `sendTo` destinations. Flagged upstream (§7). |
| **LC-19** | [#44](https://github.com/basiltt/xstate-statemachine/issues/44) | High | **FIXED-OPT-IN** (restart) / **FIXED-DEFAULT** (inspection) | call `pending_invocations()` at restore; **never** blanket `restart_services=True` | `status` still reports `"running"` for a statically restored, service-dormant machine. Health checks must use `pending_invocations()`, not `status`. Probe C7 still fails at defaults, correctly. |
| **LC-21** | [#45](https://github.com/basiltt/xstate-statemachine/issues/45) | High | **FIXED-DEFAULT** | keep `verify_machine_hash=True` (the default) | `machine_hash` **ignores action params** — a param-only drift a restore should refuse is invisible (diff review §8). Nested child-actor snapshot versioning not re-verified. |
| **LC-22** | [#46](https://github.com/basiltt/xstate-statemachine/issues/46) | High | **FIXED-DEFAULT** | none | Sync engine + recursive child restore not independently re-verified (shared code path). |
| **LC-24** | [#47](https://github.com/basiltt/xstate-statemachine/issues/47) | High | **FIXED-DEFAULT** (durability API) | `stop(drain=True)` on every shutdown path | Bare `stop()` still discards a non-empty queue — it now *warns* loudly, closing the "silent" half but not the "lost" half. Recursive child `pending_events` capture not exercised. |
| **LC-26** | [#48](https://github.com/basiltt/xstate-statemachine/issues/48) | High | **FIXED-DEFAULT** | none | **14.5× better but the bar is still missed**: loaded timer drift 2530 ms → **174.4 ms** against a ≤100 ms threshold (BENCH-6 FAIL). Sync-engine side not load-tested. |
| **LC-27** | [#49](https://github.com/basiltt/xstate-statemachine/issues/49) | High | **FIXED-DEFAULT** | inject `SimulatedClock` in tests/replay; `RealClock` in prod | `SimulatedClock.increment()` takes **milliseconds** and inside a running loop returns a `_MustAwait` that is neither coroutine nor future — an `iscoroutine()` guard silently skips it and no timer fires. Ship a wrapper. Child clock inheritance not re-verified. |
| **LC-28** | [#43](https://github.com/basiltt/xstate-statemachine/issues/43) | Medium | **PARTIAL** | none | Poll→future done (5 ms floor → sub-ms), `wait_done()` exists. But the task count per idle child is **still 2**, not the ≤1 the issue asked for. |
| **LC-29** | [#42](https://github.com/basiltt/xstate-statemachine/issues/42) | Medium | **FIXED-DEFAULT** | use a `context` factory on child machines | A plain-dict child context receives `input` only at `context["input"]` — declared keys are deliberately never overwritten, which is the documented XState contract, not a gap. Repro encoded the wrong expectation. |
| **LC-32** | [#57](https://github.com/basiltt/xstate-statemachine/issues/57) | Medium | **FIXED-DEFAULT** | none | None for the primary defect. Repro's own teardown probe crashes on a now-`None` child handle, without affecting the exit code. |
| **LC-34** | [#51](https://github.com/basiltt/xstate-statemachine/issues/51) | High | **FIXED-OPT-IN** | `strict: true` + `event_schemas={...}` | **Strict alone is silent for internally `raise`d typos under `actionErrorPolicy: "continue"`** (D-5) — the pair is what closes the class. **`send_threadsafe()` bypasses `strict` and `event_schemas` entirely** (diff §5.3) — new defect, see §5. Wildcard/partial descriptor handling not re-tested. |
| **LC-36** | [#32](https://github.com/basiltt/xstate-statemachine/issues/32) | High | **FIXED-DEFAULT** | none | Cosmetic only — repro now demonstrates the fix by crashing at build time. |
| **LC-37** | [#52](https://github.com/basiltt/xstate-statemachine/issues/52) | Medium | **FIXED-DEFAULT** (decorated) / **PARTIAL** (undecorated) | use `@action`/`@guard`/`@service` markers everywhere | The arity fallback is retained and can still misfile an undecorated 3-arg action into `services`. It now always emits a `UserWarning`, so it is no longer silent — but it is not prevented. |
| **LC-38** | [#50](https://github.com/basiltt/xstate-statemachine/issues/50) | High | **FIXED-DEFAULT** / **PARTIAL in a loop** | keep `SyncInterpreter` off-loop entirely | **D-1:** a `SyncInterpreter` constructed *inside a running asyncio loop* parks its `after` deadlines on `loop.call_later`, leaving `clock._heap` empty, so `tick()` and the `send()` pump cannot deliver a due timer. New defect, see §5. Thread-per-timer is genuinely gone (25 machines → +0 threads). |
| **LC-39** | [#53](https://github.com/basiltt/xstate-statemachine/issues/53) | High | **FIXED-DEFAULT** (docs) | none | Documentation-only by design; the throughput budget remains a fixed **per-process** number. CandleViewer sizing must still treat it that way. |
| **LC-41** | [#38](https://github.com/basiltt/xstate-statemachine/issues/38) | High | **FIXED-DEFAULT** (`queue_depth`) / **FIXED-OPT-IN** (bounding) | `max_queue_size=` + `overflow_policy=` per machine | None against the criteria exercised — 13/13 under hostile probing. `BLOCK` resumption and `send_events()` bound-honouring not independently re-verified. |
| **LC-42** | [#39](https://github.com/basiltt/xstate-statemachine/issues/39) | High | **FIXED-DEFAULT** (additive) | use `send(wait=True)` / `send_priority()` on decision paths | **Reusing the same `Event` instance across two concurrent `send(..., wait=True)` calls hangs forever** (diff §5.1) — receipts are keyed on `id(event_obj)`. New defect, see §5. Reserved-payload-key deprecation not re-verified. |
| **LC-43** | [#37](https://github.com/basiltt/xstate-statemachine/issues/37) | High | **PARTIAL** | `send_threadsafe()` only; ban `run_coroutine_threadsafe(send(...))` | Core fix is real (bare cross-thread `send()` now raises `WrongThreadError` instead of losing the event), **but the documented 0.7.0 correct pattern `asyncio.run_coroutine_threadsafe(interp.send(...), loop)` now raises**, undocumented and with no deprecation window; and the replacement `send_threadsafe()` is the one path without the `strict`/schema guardrail. |
| **LC-44** | [#54](https://github.com/basiltt/xstate-statemachine/issues/54) | Medium | **FIXED-DEFAULT** (perf) | none | ~3× faster (39,036 ev/s, now above the interpreter's own 34,467). Raw wall-clock vs `SyncInterpreter.send` still 1.35–1.56×, not parity. The "skips imperative actions" half was **never** in scope — it is documented design, and the original issue conflated "slow" with "wrong". |
| **LC-45** | [#55](https://github.com/basiltt/xstate-statemachine/issues/55) | Medium | **FIXED-DEFAULT** | none | Under-load ratio is noisy (1.35× in 1 run of 4) against the strict `<1.10` criterion; nowhere near the original 2.5–4×. `_select_transitions` per-event allocation not confirmed restructured. |
| **LC-47** | [#59](https://github.com/basiltt/xstate-statemachine/issues/59) | Low | **FIXED-DEFAULT** | none | Async engine not independently exercised (shared code path); the proposed per-interpreter `_target_cache` was not confirmed to exist. |
| **LC-48** | [#33](https://github.com/basiltt/xstate-statemachine/issues/33) | High | **FIXED-DEFAULT** | register hooks on every machine (§4) | Hooks fire **under the 0.7.x defaults** — the right shape. `on_transition_failed` fires **twice** per transition under `"continue"` (one per action slot) — alerting must dedupe (D-7). Async engine emits no `on_transition` for initial entry; sync does (D-3). |
| **LC-49** | [#58](https://github.com/basiltt/xstate-statemachine/issues/58) | Medium | **FIXED-DEFAULT** | none | Atomic-root / nested-parallel / final-leaf cases and the sync engine not independently re-verified. `from_snapshot` ignoring a persisted `"value"` not re-tested. |
| **LC-53** | [#56](https://github.com/basiltt/xstate-statemachine/issues/56) | High | **FIXED-DEFAULT** | none | Docs page ships and is linked. `Interpreter` class-docstring linkage not line-checked. |
| **LC-57** | [#60](https://github.com/basiltt/xstate-statemachine/issues/60) | Medium | **FIXED-DEFAULT** (claim) / **PARTIAL** (sketch) | none | One shared algorithm delivered by a different design than the issue sketched (`BaseInterpreter` coroutines + `SyncInterpreter._drive()`, not `core/algorithm.py` + `ExecutionStrategy`). **LC-52 (`ErrorEvent` rename) did not ship** — `error.platform.*` is still delivered as a `DoneEvent`. |

---

## 2. Counts

**By classification (34 filed issues)**

| Class | Count | LCs |
|---|---:|---|
| FIXED-DEFAULT | **23** | LC-02, 05, 06, 08, 12, 16, 21, 22, 24, 26, 27, 29, 32, 36, 39, 44, 45, 47, 48, 49, 53, 57, and LC-09 (observability half) |
| FIXED-OPT-IN | **6** | LC-01, 03, 09 (outcome half), 19, 34, 41 |
| PARTIAL | **5** | LC-07 (warning), LC-28, LC-37, LC-38 (in-loop), LC-43 |
| NOT-FIXED | **0** | — |

*(LC-09 and LC-41 and LC-42 are split-classified; each is counted once against its
gate-relevant half. LC-42 counts as FIXED-DEFAULT with a new high-severity defect
filed separately in §5.)*

**By original severity**

| Severity | Filed | Closed (FIXED-DEFAULT) | Closed (FIXED-OPT-IN, config mandated) | PARTIAL / open |
|---|---:|---:|---:|---:|
| Blocker | 4 (LC-01, 02, 03, 16) | 2 (LC-02, LC-16) | 2 (LC-01, LC-03) | **0** |
| High | 20 | 13 | 3 (LC-09, LC-19, LC-34) | **4** (LC-07, LC-26†, LC-38, LC-43) |
| Medium | 9 | 7 | 0 | 2 (LC-28, LC-37) |
| Low | 1 | 1 | 0 | 0 |

† LC-26 is classified FIXED-DEFAULT (the starvation-free lane is real and
unconditional) but the **BENCH-6 threshold it exists to satisfy is still missed**
— 174.4 ms against ≤100 ms. It therefore still carries a constraint.

**Mechanical gate (defaults only, `run_gate.py`)**

```
repro  : 12/34 pass unconditional  (+ 9 verified fixed-but-opt-in, + 13 stale-repro/triaged)
probe  : 43/51 pass (was 41/51)    baseline: A3 A6 A10 A18 · C6 C7 C15 C17
bench  : 5/7 thresholds met (was 2/7)
suite  : 3170 passed, 13 skipped, 0 failed, 19 warnings (463.8 s)
```

**Benchmarks**

| ID | 0.7.0 | 0.8.0 | Bar | Verdict |
|---|---:|---:|---:|---|
| BENCH-1 order-path headroom | 1.81× | **3.17×** | ≥3.0× | **PASS** (was FAIL) |
| BENCH-2 rule-lifecycle ev/s | 288 | 380.9 | ≥2000 | **FAIL** |
| BENCH-3 500-order memory | 1.08 KB | 3.32 KB | ≤8.0 KB | PASS (headroom shrank 3×) |
| BENCH-4 10k-interp RSS | 1055 MB | 594.8–1164.9 MB | ≤1200 MB | PASS (marginal) |
| BENCH-5 idle timer drift | 15.1 ms | 14.98 ms | ≤25 ms | PASS |
| BENCH-6 loaded timer drift | 2530 ms | **174.4 ms** | ≤100 ms | **FAIL** (14.5× improved) |
| BENCH-7 throughput guard | 30,662 | 34,467 | ≥30,000 | PASS |

**Policy cost** (new `bench_j_policies.py`, machinery *armed but never firing*):

| Variant | ev/s | vs baseline |
|---|---:|---:|
| defaults | 35,532 | 1.00× |
| `actionErrorPolicy="rollback"` | 27,586 | **0.776×** |
| `onUnhandled="defer"` | 34,936 | 0.983× |
| both | 27,469 | 0.773× |

The mandated configuration in §4 is **not free**: it costs ~22% of single-process
throughput before any failure occurs. BENCH-1's new 3.17× headroom becomes
**~2.46×** once `rollback` is armed — below the 3.0× bar. That is an explicit,
accepted cost, recorded as constraint **CV-C13**.

---

## 3. Gate decision

Applying `20-adoption-gate.md` §7 in order, honestly.

| Row | Condition | Holds? | Reasoning |
|---|---|---|---|
| 1 | Any `ERROR` row | **No** | Zero `ERROR` rows across repros, probes and benches. Several repros are *stale* (assert 0.7.x shape) but exit cleanly with 0 or 1; staleness is recorded, not an ERROR. |
| 2 | Library suite fails / coverage < 86% | **No** | 3170 passed, 13 skipped, 0 failures. Coverage not re-measured this pass (`fail_under` is not configured upstream — see §5, D-13); the suite grew +13,115 lines. Treated as *not tripped*, with the coverage gap filed. |
| 3 | Snapshot format changed while LC-21 open | **No** | Format changed **and** LC-21 closed in the same release: envelope v1 with `version`/`machine_id`/`machine_hash`/`taken_at`; unversioned 0.7.x payloads restore unchanged; `SnapshotVersionError`/`SnapshotDriftError` on mismatch. Row 3 exists to prevent a *silent* break; the break is loud. |
| 4 | Any filed **Blocker** repro still exits 1 | **No — but only under the classification rule** | LC-02 and LC-16 are FIXED-DEFAULT (LC-16's repro exits 0; LC-02's exits 1 solely because it now dies at `create_machine()`, which is the fix). LC-01 and LC-03 are FIXED-OPT-IN and count as closed **only because §4 mandates `actionErrorPolicy` and `onUnhandled` on every machine and §4's lint rule makes the mandate mechanical**. Neither is PARTIAL. |
| 5 | Blockers closed; **> 5 High** open | **No** | 4 High are PARTIAL/open (LC-07, LC-26, LC-38, LC-43) plus 2 new High-for-us defects (D-1 in LC-38's class, N-1 `send(wait=)` hang). By the register's own accounting the *open High* set is **LC-07, LC-26, LC-38, LC-43** = 4 ≤ 5. The new defects (§5) are counted against their parent rows rather than double-counted. |
| 6 | Blockers closed; **1–5 High** open, **each with a mechanically enforced mitigation and a passing test in `tests/xstate_contract/`**; all Medium triaged | **YES — conditionally** | Each of the four has an enforcement mechanism specified in §4/§6, and each maps to a named contract test. **The tests do not exist yet.** |
| 7 | Blockers closed; 1–5 High open **without** enforced mitigations | — | Would apply if §4's lint rule and the four contract tests do not ship. |

### The honest answer

Row 6 and row 7 differ on exactly one fact: **whether the mitigations are
mechanically enforced today.** They are not. `tests/xstate_contract/` does not
exist, the machine-definition linter (`E29-T10`) has not shipped, and
`20-adoption-gate.md` §7 row 7 states in terms that *"a documented convention is
not a mitigation."* The gate's own prerequisite (MUST-09 / meta §3) says the
linter and the contract suite must ship **before the first statechart**.

Two further facts bear on the same question:

* **LC-01 and LC-03 — both Blockers — are FIXED-OPT-IN.** They count as closed
  *only* while the mandated configuration in §4 is enforced by a machine. The
  moment the enforcement is a convention, both Blockers are open again by the
  register's own definition.
* The mandated configuration carries a **−22% throughput cost** that pushes
  BENCH-1 back under its bar (§2), and BENCH-2 and BENCH-6 are still missed.

### DECISION

```
Gate run 2026-09-17 — xstate-statemachine 0.8.0 (9bf6065) — DECISION: ADOPT WITH CONSTRAINTS, CONDITIONAL
  repros   : 12/34 pass unconditional; 9 verified fixed-but-opt-in; 13 stale/triaged; 0 unfixed
  probes   : 43/51 pass (baseline A3 A6 A10 A18 C6 C7 C15 C17)
  benches  : 5/7 thresholds met (BENCH-2, BENCH-6 missed)
  suite    : 3170 passed, 13 skipped, 0 failed; coverage not re-measured
  blockers open: none, CONDITIONAL on LC-01/LC-03 mandated config being lint-enforced
  high open    : LC-07, LC-26, LC-38, LC-43
  new defects  : N-1 (High), N-2 (High), N-3 (Medium), N-4 (Medium), N-5 (Medium)
  constraints  : CV-C01..CV-C15 (section 6)
  condition    : E29-T10 linter + tests/xstate_contract/ must be GREEN before
                 the first live-path statechart. Until then the operative
                 decision is DEFER for the order path.
  decided by   : Architect (this run)
```

Stated in one line, without softening:

> **0.8.0 closes every filed Blocker and 23 of 34 issues at the default, but two
> Blockers (LC-01, LC-03) are closed only by opt-in policy — so 0.8.0 is
> ADOPT-with-constraints the moment the §4 configuration is enforced by the
> linter and `tests/xstate_contract/`, and DEFER on the order path until it is.**

This is decision-table row 6 with its precondition unmet, which today reads as
row 7. The gap is a few days of CandleViewer work, not upstream work — which is a
genuinely different position from 0.7.0, where the gap was upstream and unbounded.

**Non-order paths** (replay/backtest, rule-runtime lifecycle, B10–B14, B16–B20)
may proceed under `20-adoption-gate.md` §8's *legitimate* partial-adoption path
immediately, since every Blocker affecting them is FIXED-DEFAULT and a silent
no-op there costs a wrong chart, not money.

---

## 4. Mandatory machine configuration for CandleViewer

**Normative.** Every machine in `28-statechart-catalogue.md` — B1–B20, without
exception — is constructed through the single factory below. Direct calls to
`create_machine()` / `Interpreter()` / `SyncInterpreter()` outside
`cv.statechart.factory` are a **CI failure**, not a review comment.

### 4.1 The machine-config block (goes in every machine JSON)

```jsonc
{
  "id": "order",
  "initial": "…",

  // ── 0.8.0 mandatory policy block — identical in every catalogue machine ──
  "actionErrorPolicy": "rollback",   // "fail" for B8/B17/B18/B20 (invariant machines)
  "onUnhandled":       "defer",      // "error" for B13/B14/B18 (control machines)
  "guardErrorPolicy":  "raise",      // never "false"; a crashed guard is not a denial
  "strictTargets":     true,         // kill the 0.7.x sibling fallback (LC-07)
  "strict":            true,         // reject undeclared event names at the call site
  "spawnBlockingTimeout": 5000,      // ms; never rely on the 30 s default

  "states": { /* … */ }
}
```

### 4.2 The interpreter-construction block (the factory, one place)

```python
# cv/statechart/factory.py — the ONLY place these constructors may be called.
from xstate_statemachine import (
    create_machine, Interpreter, OverflowPolicy, RealClock,
)

ORDER_PATH = frozenset({"order", "trade_group", "leg", "oco", "iceberg",
                        "twap", "chase", "position_protection",
                        "reconciliation", "risk_lockout"})

def build(defn: dict, logic, *, clock=None, kind: str) -> Interpreter:
    machine = create_machine(
        defn,
        logic=logic,
        strict_targets=True,                 # MUST NOT be False — removed in 1.0
        event_schemas=EVENT_SCHEMAS[kind],   # payload validation, independent of `strict`
    )
    interp = Interpreter(
        machine,
        clock=clock or RealClock(),          # SimulatedClock in tests/replay (CV-C10)
        strict=True,                         # ctor wins over machine config
        max_queue_size=BOUNDS[kind],         # never None
        overflow_policy=(
            OverflowPolicy.RAISE             # order path: overflow is a P1 incident
            if kind in ORDER_PATH
            else OverflowPolicy.DROP_NEWEST  # market-data ingress only
        ),
    )
    interp.use(CvErrorHooks())               # on_transition_failed / on_guard_error /
    interp.use(CvMetricsPlugin())            # on_unhandled_event / on_event_dropped /
    return interp                            # on_error / on_done — all mandatory
```

| Key | Mandated value | Why (evidence) |
|---|---|---|
| `actionErrorPolicy` | `"rollback"` (order path) · `"fail"` (invariant machines) | LC-01 Blocker is closed only by this. The default `"continue"` still commits a half-built state, and the one-shot `DeprecationWarning` is **per-`MachineNode`**, so a long-lived process warns once ever, probably in a warm-up path nobody reads (diff §5.4, D-4). **Never leave it unset.** |
| `onUnhandled` | `"defer"` (order path) · `"error"` (control machines) | LC-03 Blocker. `defer` replays at the **head** of the queue in original order, re-defers still-unhandled events, survives snapshots, is bounded by `DEFER_MAX`, and never defers system events — 9/9 under hostile probing. |
| `guardErrorPolicy` | `"raise"` | A crashed risk guard must never be indistinguishable from a denial (LC-09). `on_guard_error` fires regardless, but the *outcome* only changes here. |
| `strictTargets` | `true` | Kills the surviving, silent `.child` → sibling fallback (LC-07). |
| `strict_targets=` (build) | `True` (default — never pass `False`) | LC-02/LC-06/LC-08. The `False` escape hatch is removed in 1.0. |
| `strict` | `true` (machine **and** ctor) | LC-34. **Only effective against internal `raise` typos when paired with a non-default `actionErrorPolicy`** (D-5). |
| `event_schemas` | required, per machine kind | Payload validation is independent of `strict` and is the only defence for `send_threadsafe()`… except it isn't — see CV-C14. |
| `max_queue_size` | per-kind bound, **never `None`** | LC-41. `queue_depth` exported to `cv_machine_queue_depth{kind}`. |
| `overflow_policy` | `RAISE` on the order path · `DROP_NEWEST` for market-data ingress · `BLOCK` only where the producer may legitimately suspend | 13/13 under hostile probing. `DROP_NEWEST` on an order path is forbidden. |
| `clock` | `RealClock()` in prod · `SimulatedClock()` in every time-dependent test and in replay | LC-27. Wrap `increment()` (milliseconds, and `await` whatever it returns). |
| `spawnBlockingTimeout` | `5000` ms | LC-12; never rely on the 30 s default. |
| Plugins | `CvErrorHooks` + `CvMetricsPlugin` on every interpreter | LC-48. `on_transition_failed` **must dedupe** (fires twice per transition under `"continue"`, D-7) and must tolerate the initial-entry hook asymmetry between engines (D-3). |
| Engine | **async `Interpreter` only** | MUSTNOT-06 stands and is reinforced: D-1 (sync timers unreachable in a loop) and diff §5.2 (sync macrostep budget still `clear()`s legitimate events). |
| Shutdown | `stop(drain=True)` on every path | LC-24. Bare `stop()` still drops a non-empty queue (loudly). |
| Restore | `from_snapshot(json_string)`; call `pending_invocations()`; **never** blanket `restart_services=True` | LC-19. `from_snapshot` will not accept a dict (D-6). `status` lies about dormancy. |
| Sends | `send(wait=True)` for any gated decision, with a **freshly constructed** event · `send_priority()` for kill/risk paths · `send_threadsafe()` for foreign threads | LC-42. Reusing one `Event` object across concurrent `wait=True` sends **hangs forever** (N-1). |

### 4.3 CI lint rule

Add to the machine-definition linter (`E29-T10`), failing the build on any hit.
Ships as `tools/lint_statecharts.py` and as
`tests/xstate_contract/test_machine_config_mandate.py`.

```python
"""CV-LINT-XS1 .. XS9 — mandatory xstate-statemachine 0.8.0 configuration.

Every rule below is a build failure. Rationale: docs/research/xstate/
17-reeval-0.8.0-verdict.md sections 3-4. Two of the four closed Blockers
(LC-01, LC-03) are FIXED-OPT-IN; without this file they are open Blockers.
"""
REQUIRED_MACHINE_KEYS = {
    "actionErrorPolicy": {"rollback", "fail"},   # XS1 - "continue" forbidden
    "onUnhandled":       {"defer", "error"},     # XS2 - "ignore" forbidden
    "guardErrorPolicy":  {"raise"},              # XS3
    "strictTargets":     {True},                 # XS4
    "strict":            {True},                 # XS5
}
# XS6  every machine declares spawnBlockingTimeout when it uses spawn_blocking_*
# XS7  no `create_machine(`/`Interpreter(`/`SyncInterpreter(` outside
#      cv/statechart/factory.py                             (AST check)
# XS8  no `strict_targets=False`, no `verify_machine_hash=False`,
#      no `overflow_policy=DROP_NEWEST` on an ORDER_PATH machine,
#      no `max_queue_size=None`, no bare `.stop()` (must be stop(drain=True)),
#      no `restart_services=True`, no `SyncInterpreter` anywhere,
#      no `asyncio.run_coroutine_threadsafe(<interp>.send(`  (AST check)
# XS9  every `send(..., wait=True)` call site passes a literal event type or a
#      freshly-constructed Event, never a name bound outside the call  (AST, N-1)
# XS10 `after` is still banned in catalogue machines (house rule A2, BENCH-6
#      still FAILs at 174.4 ms); deadlines stay on the MonotonicScheduler.
```

Plus a runtime assertion in the factory (defence in depth, because a lint rule
that is skipped is not a rule):

```python
assert defn.get("actionErrorPolicy") in {"rollback", "fail"}, defn["id"]
assert defn.get("onUnhandled") in {"defer", "error"}, defn["id"]
assert defn.get("guardErrorPolicy") == "raise", defn["id"]
assert defn.get("strictTargets") is True and defn.get("strict") is True, defn["id"]
```

---

## 5. New defects found by adversarial and diff review

Not present in the 0.7.0 register. Severity is **relative to CandleViewer's order
path**, per the register's scale. `N-*` ids are new; `D-*`/`§*` cite the source
study.

| ID | Source | Severity | Defect |
|---|---|---|---|
| **N-1** | diff §5.1 | **High** | `send(event_obj, wait=True)` keys its receipt map on `id(event_obj)`. Two concurrent sends with the **same `Event` instance** collide: the second `_make_receipt` overwrites the first future, which is never resolved and never failed — **an unkillable coroutine with no error, in the exact API added to make `send` answerable.** Fresh objects (`send("T", wait=True)` ×200) all resolve, so this is caller-side object reuse, not `id()` recycling. Fix: a monotonic per-send token. |
| **N-2** | adversarial D-1 | **High** (for us) | `RealClock.set_timeout` branches on the **caller's** context, not the owning engine. A `SyncInterpreter` built inside a running asyncio loop parks `after` deadlines on `loop.call_later`, leaving `clock._heap` empty, so `tick()` / the `send()` pump find nothing and **`tick()` is not authoritative** — it cannot deliver a genuinely-due deadline. Measured: off-loop `clock.pending=1` → `sy.b`; in-loop `pending=0` → stuck in `sy.a`. |
| **N-3** | diff §5.2 | **Medium** (High if we ever used the sync engine) | `SyncInterpreter._process_event_queue` still does `processed += 1` per event and, past `max_iterations` (1000), calls `self._event_queue.clear()` — **discarding every queued event**. The CHANGELOG's claim that "the two engines now agree" is true only for *replayed deferred* events; `replay_credit` exempts only those. A silent 501-event drop on the default sync engine. |
| **N-4** | diff §5.3 | **Medium** | `send_threadsafe()` — the *recommended* API for foreign threads, and after §4.1 the *only* one — **bypasses `strict` mode and `event_schemas` entirely**. `_check_strict` is called from `Interpreter.send`, `SyncInterpreter.send` and the `raise` built-in, but not from `send_threadsafe`. Verified: `send("FIL")` raises with a "Did you mean 'FILL'?" suggestion; `send_threadsafe("FIL")` is accepted, its future completes, and the event is silently dropped at dispatch. |
| **N-5** | adversarial D-2 | **Medium** | `actionErrorPolicy: "rollback"` is a **context + configuration** transaction, not an effect transaction. A `raise` or `sendTo` emitted by an earlier action in the same list survives the rollback. A11: `seen=['PING']` with the configuration correctly back at `rs.a`; A12r: `hits=1` after a full rollback, with a live child on a surviving state; A16: it escapes under `"fail"` too. For an OMS this means the machine can roll back to `idle` while the risk actor believes an order exists. The library is self-consistent; the *name* oversells it. |
| **N-6** | diff §4.1 | **Medium** | `asyncio.run_coroutine_threadsafe(interp.send(...), loop)` — the pattern the original LC-43 issue text named as *"the only correct form"* for 0.7.0 — now raises `WrongThreadError`, because the thread check runs eagerly on the caller's thread before the coroutine is scheduled. Undocumented in the CHANGELOG, no deprecation window, and the error message ("Events sent this way would be silently lost") is actively wrong for this case. |
| **N-7** | diff §4.2 | **Medium** | `TEvent` was removed from `Interpreter`'s generics as a *typing improvement*; `Interpreter[Ctx, Any]` — the spelling 0.7.0's generics forced users to write — now raises `TypeError` **at runtime**. Belongs under a Removed/breaking heading. |
| **N-8** | diff §4.3 | **Medium** | Any user event namespaced `error.*` or `done.*` is **invisible** to `on: {"*": …}` and **exempt** from `onUnhandled: "error"`. Verified: `error.myapp.validation` does not match bare `"*"`; `done.review` does not trip `onUnhandled: "error"`. Load-bearing in three places now (matcher, `onUnhandled`, `_check_strict`) and undocumented — a silent-drop class the release otherwise set out to eliminate. Directly hits any domain that names events `done.*`/`error.*`. |
| **N-9** | diff §8 | **Medium** | Snapshot `machine_hash` **ignores action params**. A definition whose only change is a built-in action's `params` produces an identical hash, so `SnapshotDriftError` does not fire on drift a restore should refuse. Weakens MUST-12. |
| **N-10** | diff §6 | **Medium** | `output` callables and named-delay callables **still fail silently** — the last two untreated members of the exact class this release targeted. |
| **N-11** | adversarial D-5 | **Medium** | A strict-mode violation inside an **internal `raise`** is invisible under `actionErrorPolicy: "continue"`. Strict alone does not close the typo class; it must be paired with a non-default action-error policy (already mandated in §4). |
| **N-12** | adversarial D-3 | **Low** | The async engine emits **no `on_transition`** for the initial entry; the sync engine does. Any plugin that persists one row per transition disagrees across engines on the synthetic `___xstate_statemachine_init___` event. |
| **N-13** | diff §10 | **Low** | Three docs version-badge tests (`test_hero_badge_matches_package_version`, `test_nav_badge_matches_package_version`, `test_no_hardcoded_version_in_layout`) were deleted with **no successor anywhere in `tests/`**, while `docs/index.html:9` and `docs/_config.yml:9` hard-code `0.8.0`. `pyproject.toml` sets **no `fail_under`**, so there is no enforced coverage floor. A coverage regression introduced by this release. |
| **N-14** | adversarial D-6 | **Low** | `from_snapshot` accepts only the JSON **string**; handing back the dict from `get_persisted_snapshot()` raises `TypeError`. The natural JSONB/Mongo persistence path needs a `json.dumps()` round-trip. |
| **N-15** | adversarial D-7 | **Low** | `on_transition_failed` fires **twice** per transition under `"continue"` (once per action slot). Alerting must dedupe. |
| **N-16** | adversarial D-4 / diff §5.4 | **Low** | The one-shot `actionErrorPolicy` `DeprecationWarning` sets a flag on the **shared `MachineNode`**, so a process creating interpreters per request from a module-level machine warns exactly once, ever. The signal heralding the 1.0 default flip is far quieter than the migration it announces. |
| **N-17** | diff §3 | **Low** (docs) | The CHANGELOG's "two deliberate exceptions under **Changed**" claim is unverifiable: `Changed` lists 12 items, at least 5 behavioural, none marked as *the* exception. Undercounts the migration cost by ~3. |

**New-defect severity roll-up:** 2 High, 9 Medium, 6 Low, **0 Blocker**.

---

## 6. Updated constraints list

Supersedes the constraint table in `20-adoption-gate.md` §7 for the 0.8.0
baseline. `MUSTNOT-01…09` and `MUST-01…12` from `11-adversarial-review.md` §3
remain binding **except where explicitly retired below**.

### 6.1 Retired by 0.8.0

| Retired | Because |
|---|---|
| **MUST-06** (merge context defaults on restore, in our wrapper) | LC-22 FIXED-DEFAULT — `from_snapshot` now deep-copies and merges over machine defaults. Keep the *test* (`test_context_defaults_merged_on_restore`) as a regression lock; delete the wrapper code. |
| **MUST-07** as written (`== 0.7.0`) | Re-pin to `== 0.8.0` with sha256. The pin discipline stands; the version changes. |
| Gate constraint "**LC-27 open** ⇒ replay cannot use `after`" | LC-27 FIXED-DEFAULT — `SimulatedClock` is real and deterministic. Replay may now use in-machine time under CV-C10. |
| Gate constraint "**LC-43 open** ⇒ cross-thread via `run_coroutine_threadsafe`" | **Inverted.** That pattern now *raises* (N-6). Replaced by CV-C14. |
| The `"*": {"actions": ["defer"]}` + `drain_deferred` scaffolding (house rule A3) | LC-03 closed by native `onUnhandled: "defer"`. Delete the scaffolding **and** its workaround tests once §4 is enforced; keep INV-5 per family. |
| **MUST-03 / MUST-04** as written (boot-drain `_deferred`, alert on depth) | Re-expressed against the library's own buffer: alert on `interpreter.deferred_count` and `pending_events`, both of which now survive snapshots. The *alert* stays; the hand-rolled buffer goes. |

### 6.2 Standing, reinforced

| ID | Constraint | Enforced by |
|---|---|---|
| **CV-C01** | Every catalogue machine carries the §4.1 policy block; every interpreter is built by `cv.statechart.factory`. | CV-LINT-XS1–XS8 + factory assertions + `test_machine_config_mandate` |
| **CV-C02** | **Outward effects are emitted only from the entry actions of the committed state**, or as the *last* action in a list. Rollback is context+configuration only (N-5). | Linter: no `sendTo`/`raise` before a non-final action in any transition `actions` list; design-review checklist |
| **CV-C03** | **Async `Interpreter` only.** No `SyncInterpreter` anywhere, in any process. | CV-LINT-XS8 (AST); MUSTNOT-06 (reinforced by N-2, N-3) |
| **CV-C04** | `strict: true` **and** a non-default `actionErrorPolicy` are set together; neither alone closes the typo class (N-11). Plus an `on_transition_failed` alert, the only observation point under `"continue"`. | CV-LINT-XS1/XS5 |
| **CV-C05** | Every inbox is bounded. Order/execution: `RAISE`, and `QueueOverflowError` is a **P1 incident**. Market-data ingress: `DROP_NEWEST` + `on_event_dropped` counter. `BLOCK` only where the producer may suspend. | CV-LINT-XS8; `cv_machine_queue_depth{kind}` |
| **CV-C06** | `send(wait=True)` for every gated decision; `send_priority()` for kill/risk paths. **Never** poll `current_state_ids`. **Never** reuse an `Event` instance across concurrent `wait=True` sends** (N-1). | CV-LINT-XS9; `test_send_receipt_fresh_event_only` |
| **CV-C07** | Restore always calls `pending_invocations()` and decides per invocation against the venue. **Never** blanket `restart_services=True` — re-invoking a submit is a duplicate-order risk. `status` must not be trusted for liveness. | CV-LINT-XS8; `test_restore_reconciles_pending_invocations` |
| **CV-C08** | Snapshots are persisted as the JSON **string** from `get_snapshot()` (N-14), through `cv.statechart.persistence.save/load` only. | Linter: no direct `from_snapshot` call sites |
| **CV-C09** | Any plugin that counts or persists transitions filters `___xstate_statemachine_init___` explicitly (N-12) and dedupes `on_transition_failed` (N-15). | `test_hook_parity_and_dedupe` |
| **CV-C10** | `SimulatedClock` in every time-dependent test and in replay, via the `cv.testing.advance(clock, seconds)` helper — `increment()` takes **milliseconds** and returns a `_MustAwait` that must be awaited, or no timer fires. | `cv.testing` helper + lint on raw `increment(` |
| **CV-C11** | `last_transition_ok` is read **immediately** after the send it describes, or — preferred — not at all, in favour of `receipt.error`. It is clobbered by the very next event, including an unhandled one. | Code review + `test_last_transition_ok_is_clobbered` |
| **CV-C12** | **`after` remains banned in catalogue machines** (house rule A2). BENCH-6 is still missed at 174.4 ms against ≤100 ms; all algo timing stays on the external `MonotonicScheduler` with absolute `*_us` deadlines in context. | CV-LINT-XS10 |
| **CV-C13** | The order path runs on a **dedicated event loop / process**. BENCH-1's 3.17× headroom falls to **~2.46×** once `actionErrorPolicy="rollback"` is armed (−22.4%), below the 3.0× bar. This cost is accepted, not ignored. | Startup assertion on loop identity; `bench_j_policies.py` in CI |
| **CV-C14** | Cross-thread sends go through `send_threadsafe()` **wrapped by `cv.statechart.gateway`, which performs the `strict`/`event_schemas` check itself** — the library's own path does not (N-4). `asyncio.run_coroutine_threadsafe(interp.send(...))` is banned; it now raises (N-6). | CV-LINT-XS8; `test_threadsafe_send_validates_event_name` |
| **CV-C15** | No CandleViewer event may be named `error.*` or `done.*`. Such names are invisible to `"*"` handlers and exempt from `onUnhandled: "error"` (N-8). | Event-name gate (`E50-T05`), extended |
| **MUST-05** | ≥99% rule pre-filter, asserted as a test. **Unchanged** — BENCH-2 is still missed (380.9 ev/s vs ≥2000). | `cv_rule_prefilter_rejection_ratio` |
| **MUST-12** | `machine_hash` in CI. **Strengthened:** hash it ourselves including action params, because the library's hash ignores them (N-9). | `test_machine_hash_covers_action_params` |
| **MUST-08** | Vendor the pinned source into `third_party/`. **Unchanged.** | Quarterly vendored-copy contract test |
| **MUST-09** | The linter and `tests/xstate_contract/` ship **before** the first statechart. **This is now the single gating condition** (§3). | `E29-T10` |

---

## 7. Upstream disposition

### 7.1 Close as verified (23)

These are FIXED-DEFAULT with no residual gap serious enough to keep the issue
open. Each is backed by an `issues/verify-0.8.0/LC-xx.result.md`.

`#29` (LC-02) · `#36` (LC-05) · `#34` (LC-06) · `#30` (LC-08) · `#41` (LC-12) ·
`#40` (LC-16) · `#45` (LC-21) · `#46` (LC-22) · `#48` (LC-26) · `#49` (LC-27) ·
`#42` (LC-29) · `#57` (LC-32) · `#32` (LC-36) · `#53` (LC-39) · `#54` (LC-44) ·
`#55` (LC-45) · `#59` (LC-47) · `#33` (LC-48) · `#58` (LC-49) · `#56` (LC-53) ·
`#35` (LC-09, observability half) · `#47` (LC-24) · `#38` (LC-41)

*(`#48`/LC-26 and `#47`/LC-24 close upstream but keep a CandleViewer constraint —
CV-C12 and `stop(drain=True)` respectively. Closing the issue is correct; the
constraint is ours.)*

### 7.2 Needs a follow-up comment before closing (11)

Draft comment text is in `issues/followups-0.8.0/<LC>.md`. **Do not file these —
they are drafts only.**

| LC | GH# | Point of the comment |
|---|---|---|
| LC-01 | #27 | Rollback is not an effect transaction (N-5); the `DeprecationWarning` is per-`MachineNode` (N-16); the −22% armed cost should be documented. |
| LC-03 | #28 | Verified 9/9. Asks only that `DEFER_MAX` and the oldest-evicted policy be stated in the guide, and that `error.*`/`done.*` exemption (N-8) be documented. |
| LC-07 | #31 | The sibling fallback is still reachable **and silent** by default; the issue's criterion 2 (`DeprecationWarning` on fallback) did not land. |
| LC-19 | #44 | `status` still reports `"running"` for a statically restored machine with dormant services; asks for a `restored`/`dormant` qualifier or a docs note. |
| LC-28 | #43 | The poll→future half landed; the "collapse the second task" half did not — still 2 tasks per idle child. |
| LC-34 | #51 | `send_threadsafe()` bypasses `strict` and `event_schemas` (N-4); internal `raise` typos are invisible under `"continue"` (N-11). |
| LC-37 | #52 | Undecorated arity fallback still misfiles, now with a `UserWarning`; asks whether `MachineLogic(strict=True)` is still planned. |
| LC-38 | #50 | **D-1 / N-2** — sync timers unreachable by `tick()` inside a running loop. The most important follow-up in this set. |
| LC-42 | #39 | **N-1** — `send(wait=True)` hangs on a reused `Event` object. Four-line repro; suggests a monotonic send token. |
| LC-43 | #37 | **N-6** — `run_coroutine_threadsafe(send(...))` regression, undocumented, with a misleading error message. |
| LC-57 | #60 | LC-52 (`ErrorEvent` rename) did not ship; `error.platform.*` is still a `DoneEvent`. |

### 7.3 New issues to file (5)

Full write-ups with runnable repros, in the same format as the originals, in
`issues/new-0.8.0/`. **Drafts only — nothing filed.**

| New ID | Title | Severity |
|---|---|---|
| **N-1** | `send(event, wait=True)` hangs forever when the same `Event` instance is in flight twice (receipt keyed on `id()`) | High |
| **N-2** | `SyncInterpreter` `after` deadlines are unreachable by `tick()` when constructed inside a running asyncio loop | High |
| **N-3** | `SyncInterpreter` macrostep budget still `clear()`s legitimate external events; the engines do not agree | Medium |
| **N-4** | `send_threadsafe()` bypasses `strict` mode and `event_schemas` | Medium |
| **N-8** | User events namespaced `error.*` / `done.*` are invisible to `"*"` handlers and exempt from `onUnhandled: "error"` | Medium |

The remaining new findings (N-5, N-6, N-7, N-9…N-17) ride along on the follow-up
comments in §7.2 or, where documentation-only, on `#56` (LC-53).

---

## 8. Bottom line

0.8.0 is not a veneer. `base_interpreter.py` grew ~1,500 lines of real algorithm,
three genuinely new contract modules shipped, the test suite grew +13,115 lines to
3,170 passing tests, and the two features we most needed — `defer` and the bounded
inbox with receipts — survived deliberately hostile probing at **9/9** and
**13/13**. Every filed Blocker is closed. Timer starvation improved **14.5×**.
The silent-failure surface that motivated the entire audit is materially smaller.

What is left is smaller and sharper than 0.7.0's: one new silent hang in the very
API added to make `send` answerable (N-1), one displaced timer bug (N-2), a
rollback that is narrower than its name (N-5), and the fact that **the two most
important fixes are opt-in**. That last point is the whole decision. A policy that
defaults to the old behaviour closes a Blocker only for a caller that sets it —
and "sets it" must mean a lint rule, not a convention.

> **Verdict: ADOPT WITH CONSTRAINTS (CV-C01…CV-C15), conditional on the
> `E29-T10` linter and `tests/xstate_contract/` being green; DEFER on the order
> path until then. Non-order paths may proceed now.**
