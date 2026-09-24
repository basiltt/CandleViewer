# 10 — CandleViewer × `xstate-statemachine`: Component Fit Analysis & Architecture Proposal

**Library:** `basiltt/xstate-statemachine` 0.7.0 (local clone `_ref/xstate-statemachine`, PyPI `xstate-statemachine`)
**Date:** 2026-09-15
**Inputs:** studies `01`–`06` in this folder (source read, test/quality audit, docs audit, performance bench, semantic probes, ecosystem comparison); plan docs `20-architecture.md`, `24-internal-schemas.md`, ADR-0004/0006/0007/0008; backlog `E08, E09, E16, E26, E28, E29, E32, E33, E35, E39, E40, E44, E45`.
**Audience:** the owner, as the battle-test deliverable. Part D (Library Challenges Register) is the honest defect list; nothing in this document smooths over a limitation.

---

## 0. How to read this document

- **Part A** — the ground rules that fall out of studies 01–05 and constrain *every* component design below. Read this first; most per-component "Workaround" ratings are instances of these seven rules.
- **Part A2 — Constraints from adversarial review** — the binding MUST/MUST-NOT list produced by `11-adversarial-review.md`, which attacked this document with eight new probes. **Part A2 overrides Part B and Part C wherever they disagree.** Three of Part A's workarounds turned out to be more fragile than written; read A2 before implementing anything.
- **Part B** — one section per stateful component: current plan design → proposed statechart (XState-compatible JSON sketch) → library features required → fit rating → concrete plan-doc/ticket changes.
- **Part C** — the overall architecture proposal (hosting, bus, persistence, observability, testing, performance, failure handling).
- **Part D** — Library Challenges Register `LC-01 … LC-24` with severity, workaround and suggested upstream fix.
- **Part E** — consolidated change list against plan docs and backlog tickets.

### Rating legend

| Rating | Meaning |
|---|---|
| **Excellent** | The library's semantics match the domain requirement directly. Adopt with normal care. |
| **Good** | Fits, with one or two house-style rules from Part A applied. Low residual risk. |
| **Workaround** | Fits only with an explicit, documented mechanism we build on top (deferral buffer, external scheduler, direct actor delivery). The workaround is load-bearing; if a developer forgets it, the failure is silent. |
| **Not suitable** | Do not put this in a statechart, or do not put *this part* of it in a statechart. Reasons given. |

### Honest summary up front

Of the 20 components analysed: **3 Excellent, 7 Good, 7 Workaround, 3 Not suitable**. The library is genuinely strong where the plan docs are hardest — order lifecycle, algo supervision via actors, snapshot/restore fidelity, FIFO ordering, invoke cancellation. It is unsuitable exactly where the plan docs already say "hot path": per-tick rule evaluation, per-tick ingestion, per-fill paper matching. And it carries one defect class — *resolution and execution failures degrading to silent no-ops* — that is the wrong default for an order path and is the single biggest adoption risk (see `LC-01`, `LC-02`, `LC-03`).

> **Amended after adversarial review (`11-adversarial-review.md`).** Four claims in this document did not survive attack and are corrected in **Part A2**:
> 1. A failed action is not merely an in-memory hazard — it is **durably snapshotted** as truth (CR-1).
> 2. The A3 deferral buffer is **persisted but never drained** after a crash, and **destroys `(ts_exec, seq)` ordering** on drain (CR-2, CR-3). C2.3's "ordering is exactly what an OMS needs" is therefore wrong as written.
> 3. Pre-filtering does **not** make the rule budget comfortable: the realistic machine throughput floor is **8,813 ev/s, not 20,000**, and the required pre-filter rejection rate is **≥99 %**, not 90 % (CR-4).
> 4. The per-account **rate-limit governor**, absent from Part B, is a **Not suitable** component — a synchronous pre-flight decision that a statechart makes ~238,000× slower (CR-5).
>
> One claim was refuted in the proposal's *favour*: the feared per-entity interpreter explosion is a non-issue — **2,854 interpreters cost 16.7 MB and 88 ms to start** (RF-1), 4.5× better than C1.2's own estimate.

---

# Part A — Ground rules (binding house style)

These are derived from measured behaviour, not from documentation. Every statechart in Part B assumes them.

### A1. No action may raise. Ever.

Study 04 §7 (`bench_g2_error_channel.py`): when an action raises, remaining actions in that list are skipped **but the transition still commits**, the target's `entry` still runs, `status` stays `running`, `on_transition` fires as if nothing happened, and the *only* evidence is one `ERROR` log line. There is no exception, no error event, no plugin hook, no subscriber signal.

For CandleViewer this is a position-corruption path: `apply_fill` raising partway leaves the order in `filled` with a stale `filled_qty`.

**Rule:** every action body is wrapped by a `@cv_action` decorator that catches `BaseException`, writes `context["_fault"] = {...}`, and enqueues a `FAULT` event the machine handles by transitioning to a `quarantined` state. No bare action functions are registered. CI lint rejects any function passed to `MachineLogic(actions=…)` that is not decorated.

### A2. Timing lives outside the statechart.

Study 04 §3: under 500 busy interpreters a 10 ms `after` fires **2.25 s late**, and the absolute error is constant across 10 ms / 100 ms / 1 s requests — the signature of event-loop starvation, not timer inaccuracy. Study 04 §4: pending `after` timers do **not** survive `from_snapshot()`.

**Rule:** TWAP slice boundaries, chase reprice intervals, iceberg refill delays, unwind deadlines, native-SL deadlines and reconciliation sweeps are scheduled by a single external `MonotonicScheduler` that computes deadlines from `time.monotonic()` and injects a `TICK`/`DEADLINE` event. `after` is permitted **only** for coarse timeouts where multi-second lateness is acceptable, and only where the deadline is also mirrored in context so it can be re-armed on restore.

### A3. Every transient state has an explicit deferral handler.

Study 05 §2.6 (C17): events with no handler in the current state are **silently discarded**. Three `PARTIAL` fills sent while the machine sat in `pending` (mid-invoke) vanished; `filled` stayed `0`. Deterministic across 10 runs — it is the design, not a race.

**Rule:** every non-terminal state that can be occupied while exchange messages are in flight declares `"*": {"actions": ["defer"]}` (or explicit `EXEC_*` handlers), where `defer` appends to `context["_deferred"]`, and every state's `entry` ends with `drain_deferred`. A CI machine-linter fails any state reachable during an in-flight exchange call that lacks a wildcard handler.

### A4. Self-transitions must say `reenter: true`.

Study 05 §2.3 (A3/A17) and §2.1 (A10): the library classifies *any* self-target as an internal transition (`base_interpreter.py:1769`), so `entry` does not re-run. This produces the `always`-self-target deadlock (A10: expected `done` with `n==5`, observed `loop` with `n==1`, `is_running == True`, no error). `"internal": false` is **not** read; only `reenter` is.

**Rule:** every self-transition writes `"reenter": true`. Accumulate-until-threshold loops (iceberg slicing, rule counting) route through a distinct intermediate state — A19 proves that converges correctly. Machine-linter enforces both.

### A5. Absolute targets only; targets are validated at build time.

Study 05 §2.4 (A5/A18): leading-dot relative targets (`.A2`) resolve to `None` and are treated as "no transition" — a **silent no-op**, indistinguishable from a typo. Study 05 §2.5 (C15): an unknown target name passes `create_machine()` and does nothing at runtime. Study 01 §4.8: the interpreter's 4-stage fallback ends in an exhaustive tree walk matching on the *last id segment*, so `target: "filled"` can resolve to an unrelated `…child.filled`.

**Rule:** all targets are absolute `#machine.path.to.state`. A build-time validator walks every machine JSON, resolves every target against the state tree itself (not via the library), and fails CI on any unresolvable or ambiguous-last-segment target. This runs on rule-IR-compiled machines too, at deploy time.

### A6. Guards are pure, total, and deny-by-default on safety paths.

Study 05 §2.8 (A6): guards keep being evaluated after a branch is chosen (`[g1 false, g2 true, g3 true]` selects correctly but calls all three) — so guards with side effects, counters or cache writes misbehave. Study 05 §2.9 (A20) / Study 01 §14.5: a raising guard is swallowed as `False`, making a *crashing* risk check indistinguishable from a *failing* one, and in an `or` composition it can fall through to the permissive branch.

**Rule:** guards are pure predicates over `(context, event)` with no I/O. Safety-critical guards (`live_enabled`, `kill_switch_clear`, `within_risk_caps`, `native_sl_present`) are written in the **deny** polarity — the guard proves permission, and its failure or exception means *blocked*, never *allowed*. Each such guard carries its own try/except returning `False` explicitly, and logs at `ERROR`.

### A7. The statechart is never the book of record.

Postgres is authoritative (24 §8.2 S7/S8). The statechart is a *derived, restartable projection*; every transition writes an append-only `order_events` row **before** the in-memory state changes (write-ahead, S8). Snapshot restore does not re-run entry actions, does not restart invokes and does not re-arm timers (Study 05 §2.10, Study 04 §4) — so recovery is always "restore snapshot, then reconcile against the exchange, then re-arm deadlines from context".

### A8. Operational hygiene (non-negotiable, cheap)

- `logging.getLogger("xstate_statemachine").setLevel(logging.WARNING)` at composition-root time. The library logs INFO per guard, per event, per state entry/exit; Study 04 measured logging dominating the profile.
- `MachineNode` objects are **shared** across interpreters. Study 04 §2: build cost drops from ~325 µs to 17.3 µs (19×), and context is verifiably not aliased.
- All cross-thread sends go through a `SafeInterpreter.send_threadsafe()` wrapper using `asyncio.run_coroutine_threadsafe`. A bare `interp.send()` from a foreign thread **silently loses the event** (Study 04 g6) — no exception, the coroutine is simply never awaited. Lint bans direct `.send(` outside the wrapper.
- Never use `get_snapshot()` (hardcodes `indent=2`, inflating payload 1.77×); use `get_persisted_snapshot()` + compact `json.dumps` — also 30 % faster.
- Never use the "pure" API (`get_next_snapshot`) as an optimisation: it is 2.4× **slower** than the interpreter (77 µs vs 33 µs) and does not execute imperative actions at all.

---

# Part B — Per-component fit analysis

Component index and verdicts:

| # | Component | Plan source | Fit | Key blocker / enabler |
|---|---|---|---|---|
| B1 | Order | 24 §8.2, ADR-0006 | **Good** | LC-03 event drops in transient states; LC-01 silent action failure |
| B2 | TradeGroup | 24 §9.6, ADR-0008 | **Good** | LC-02 actor addressing by id |
| B3 | TradeGroupLeg | 24 §9.1, §9.5.1 | **Good** | child actor of B2; LC-04 on retry loops |
| B4 | EmulatedAlgo — OCO | 24 §10.2 | **Good** | double-fill race as an explicit state |
| B5 | EmulatedAlgo — Iceberg | 24 §10.3 | **Workaround** | LC-04 `always` self-target deadlock; LC-05 timers |
| B6 | EmulatedAlgo — TWAP | 24 §10.4 | **Workaround** | LC-05 timer starvation (2.25 s late under load) |
| B7 | EmulatedAlgo — Chase | 24 §10.5 | **Workaround** | 200 ms reprice interval below the library's usable timer floor |
| B8 | Bracket / NativeSL invariant | 24 §8.8, ADR-0008 P4 | **Workaround** | guard-swallow (LC-08) on a life-safety invariant |
| B9 | Rule runtime instance | 24 §11.5, ADR-0007 | **Workaround** (lifecycle) / **Not suitable** (per-tick eval) | measured 6.5× short on throughput |
| B10 | Alert lifecycle | E40 | **Excellent** | — |
| B11 | RecordingSession | 24 §13.1 | **Excellent** | — |
| B12 | ReplaySession | 24 §13.7 | **Good** | clock must be external |
| B13 | ExchangeConnection (WS reconnect/resync) | 20 §3.1, §10.4 | **Good** | backoff via external scheduler |
| B14 | IngestionPipeline per symbol | 20 §3.1–3.2 | **Not suitable** (data path) / **Good** (book health FSM) | 2k+ ev/s/symbol vs a ~20k ev/s *global* budget |
| B15 | PaperMatcher | 24 §12 | **Not suitable** | per-print matching is inner-loop arithmetic |
| B16 | AuthSession / step-up | 24 §15.1 | **Good** | one interpreter per active session |
| B17 | LiveEnablement gate | E44 | **Excellent** | — |
| B18 | KillSwitch | 24 §11.7, 20 §4.3 | **Good** | must bypass the event queue (LC-09) |
| B19 | Reconciliation job | 24 §8.5, E45 | **Good** | long-running invokes; cancellation is solid |
| B20 | RiskLockout | 24 §11.7, E39 | **Good** | day boundary via external scheduler |

---

## B1 — Order

### Current design (24 §8.2, ADR-0006)

Thirteen states — `Draft, Validated, Submitting, Submitted, Triggered, PartiallyFilled, Filled, CancelPending, AmendPending, Cancelled, Rejected, Expired, Unknown` — plus `untracked` (S9) for exchange-discovered orders. Binding rules S1–S9: no blind resubmission from `Unknown`; an amend rejection leaves the prior order live; a fill beats a pending cancel; `exec_id` dedupe; `(ts_exec, seq)` ordering with fills always applied; terminal states immutable; Postgres authoritative; write-ahead `order_events` rows.

### Proposed statechart

Two orthogonal regions. `lifecycle` carries the S-machine; `protection` independently tracks the native-SL invariant (§8.8), so an order can be `partially_filled` **and** `sl_missing` simultaneously — a state the current single-enum design cannot express and which is exactly what the §8.8 watchdog needs to observe.

```json
{
  "id": "order",
  "type": "parallel",
  "context": {
    "order_id": null, "order_link_id": null, "account_id": null, "symbol": null,
    "side": null, "qty": "0", "filled_qty": "0", "leaves_qty": "0",
    "avg_price": null, "seen_exec_ids": [], "last_exchange_update": 0,
    "recon_misses": 0, "_deferred": [], "_fault": null,
    "sl_deadline_us": null
  },
  "states": {
    "lifecycle": {
      "initial": "draft",
      "states": {
        "draft": {
          "entry": ["persist_event"],
          "on": {
            "VALIDATE": [
              {"target": "#order.lifecycle.validated", "guard": "passes_all_gates", "actions": ["stamp_validated"]},
              {"target": "#order.lifecycle.rejected", "actions": ["set_local_reject"]}
            ],
            "*": {"actions": ["defer"]}
          }
        },
        "validated": {
          "entry": ["persist_event", "drain_deferred", "reserve_rate_token"],
          "on": {
            "SEND": {"target": "#order.lifecycle.submitting"},
            "*": {"actions": ["defer"]}
          }
        },
        "submitting": {
          "entry": ["persist_event", "drain_deferred"],
          "invoke": {
            "id": "place",
            "src": "place_order",
            "onDone": [
              {"target": "#order.lifecycle.submitted", "guard": "ret_code_ok", "actions": ["adopt_ack"]},
              {"target": "#order.lifecycle.submitted", "guard": "is_duplicate_link_id", "actions": ["mark_needs_lookup"]},
              {"target": "#order.lifecycle.rejected", "actions": ["map_reject_code"]}
            ],
            "onError": {"target": "#order.lifecycle.unknown", "actions": ["record_transport_fault"]}
          },
          "on": {"*": {"actions": ["defer"]}}
        },
        "submitted": {
          "entry": ["persist_event", "drain_deferred"],
          "on": {
            "EXEC": [
              {"target": "#order.lifecycle.filled",           "guard": "exec_new_and_closes",  "actions": ["apply_fill"]},
              {"target": "#order.lifecycle.partially_filled", "guard": "exec_new_and_partial", "actions": ["apply_fill"]}
            ],
            "TRIGGERED":       {"target": "#order.lifecycle.triggered"},
            "CANCEL":          {"target": "#order.lifecycle.cancel_pending"},
            "AMEND":           {"target": "#order.lifecycle.amend_pending"},
            "EXPIRE":          {"target": "#order.lifecycle.expired"},
            "TRANSPORT_FAULT": {"target": "#order.lifecycle.unknown"},
            "FAULT":           {"target": "#order.lifecycle.quarantined"}
          }
        },
        "triggered": {
          "entry": ["persist_event", "drain_deferred"],
          "on": {
            "EXEC": [
              {"target": "#order.lifecycle.filled",           "guard": "exec_new_and_closes",  "actions": ["apply_fill"]},
              {"target": "#order.lifecycle.partially_filled", "guard": "exec_new_and_partial", "actions": ["apply_fill"]}
            ],
            "CANCEL": {"target": "#order.lifecycle.cancel_pending"}
          }
        },
        "partially_filled": {
          "entry": ["persist_event", "drain_deferred", "notify_protection_region"],
          "on": {
            "EXEC": [
              {"target": "#order.lifecycle.filled", "guard": "exec_new_and_closes", "actions": ["apply_fill"]},
              {"target": "#order.lifecycle.partially_filled", "guard": "exec_new_and_partial",
               "reenter": true, "actions": ["apply_fill"]}
            ],
            "CANCEL": {"target": "#order.lifecycle.cancel_pending"},
            "AMEND":  {"target": "#order.lifecycle.amend_pending"},
            "FAULT":  {"target": "#order.lifecycle.quarantined"}
          }
        },
        "cancel_pending": {
          "entry": ["persist_event", "drain_deferred"],
          "invoke": {
            "id": "cancel", "src": "cancel_order",
            "onDone":  {"target": "#order.lifecycle.cancelled", "actions": ["adopt_cancel_ack"]},
            "onError": {"target": "#order.lifecycle.unknown",   "actions": ["record_transport_fault"]}
          },
          "on": {
            "EXEC": [
              {"target": "#order.lifecycle.filled",           "guard": "exec_new_and_closes",  "actions": ["apply_fill"]},
              {"target": "#order.lifecycle.partially_filled", "guard": "exec_new_and_partial", "actions": ["apply_fill"]}
            ],
            "*": {"actions": ["defer"]}
          }
        },
        "amend_pending": {
          "entry": ["persist_event", "drain_deferred"],
          "invoke": {
            "id": "amend", "src": "amend_order",
            "onDone": [
              {"target": "#order.lifecycle.partially_filled", "guard": "has_fills", "actions": ["adopt_amend"]},
              {"target": "#order.lifecycle.submitted",        "actions": ["adopt_amend"]}
            ],
            "onError": {"target": "#order.lifecycle.unknown", "actions": ["record_transport_fault"]}
          },
          "on": {
            "AMEND_REJECTED": [
              {"target": "#order.lifecycle.partially_filled", "guard": "has_fills",
               "actions": ["keep_prior_order_live", "notify_amend_rejected"]},
              {"target": "#order.lifecycle.submitted",
               "actions": ["keep_prior_order_live", "notify_amend_rejected"]}
            ],
            "*": {"actions": ["defer"]}
          }
        },
        "unknown": {
          "entry": ["persist_event", "drain_deferred", "raise_unknown_alert", "arm_recon_deadline"],
          "on": {
            "RECON_FOUND_LIVE":      {"target": "#order.lifecycle.submitted",        "actions": ["adopt_recon"]},
            "RECON_FOUND_PARTIAL":   {"target": "#order.lifecycle.partially_filled", "actions": ["adopt_recon"]},
            "RECON_FOUND_FILLED":    {"target": "#order.lifecycle.filled",           "actions": ["adopt_recon"]},
            "RECON_FOUND_CANCELLED": {"target": "#order.lifecycle.cancelled",        "actions": ["adopt_recon"]},
            "RECON_MISS": [
              {"target": "#order.lifecycle.rejected", "guard": "second_consecutive_miss",
               "actions": ["set_reject_unresolvable"]},
              {"target": "#order.lifecycle.unknown", "reenter": true, "actions": ["bump_recon_misses"]}
            ]
          }
        },
        "quarantined": {
          "entry": ["persist_event", "raise_critical_alert", "request_reconciliation"],
          "tags": ["untrusted"],
          "on": {
            "RECON_FOUND_LIVE":    {"target": "#order.lifecycle.submitted",        "actions": ["adopt_recon"]},
            "RECON_FOUND_PARTIAL": {"target": "#order.lifecycle.partially_filled", "actions": ["adopt_recon"]},
            "RECON_FOUND_FILLED":  {"target": "#order.lifecycle.filled",           "actions": ["adopt_recon"]}
          }
        },
        "filled":    {"type": "final", "entry": ["persist_event", "emit_terminal"], "tags": ["terminal"]},
        "cancelled": {"type": "final", "entry": ["persist_event", "emit_terminal"], "tags": ["terminal"]},
        "rejected":  {"type": "final", "entry": ["persist_event", "emit_terminal"], "tags": ["terminal"]},
        "expired":   {"type": "final", "entry": ["persist_event", "emit_terminal"], "tags": ["terminal"]}
      }
    },
    "protection": {
      "initial": "not_required",
      "states": {
        "not_required": {"on": {"FIRST_FILL": {"target": "#order.protection.sl_pending"}}},
        "sl_pending": {
          "entry": ["arm_sl_deadline"],
          "invoke": {
            "id": "attach_sl", "src": "attach_native_sl",
            "onDone":  {"target": "#order.protection.sl_present"},
            "onError": {"target": "#order.protection.sl_missing"}
          },
          "on": {"SL_DEADLINE": {"target": "#order.protection.sl_missing"}}
        },
        "sl_present": {"tags": ["protected"], "on": {"SL_LOST": {"target": "#order.protection.sl_missing"}}},
        "sl_missing": {
          "tags": ["naked"],
          "entry": ["raise_naked_position_alert", "request_fallback_sl"],
          "on": {"SL_OBSERVED": {"target": "#order.protection.sl_present"}}
        }
      }
    }
  }
}
```

### Library features required

Parallel regions; compound states; `invoke` with `onDone`/`onError`; guard arrays with first-match; wildcard `*` handlers (for `defer`); `tags`; final states; `reenter: true`; `get_persisted_snapshot` / `from_snapshot`; plugin hooks for audit. All present and all measured working — Study 05 B1–B8 and C1–C5; Study 04 §4 round-tripped a 3-region parallel machine with a nested compound leaf **exactly**.

### Fit: **Good**

Why not Excellent:

1. **LC-03 (event drops in transient states).** `submitting`, `cancel_pending` and `amend_pending` are occupied while an exchange round trip is in flight. An `EXEC` arriving in a state with no matching handler is *silently discarded* — Study 05 C17 sent three `PARTIAL` fills during an ack round trip and all three vanished with `filled` still `0`, deterministically across 10 runs. The `"*": defer` + `drain_deferred` pattern above is the mitigation and it is load-bearing: omit it on one state and you have a fill-loss bug with no exception and no log line. `cancel_pending` deliberately handles `EXEC` explicitly rather than deferring, because S3 says the fill wins the race.
2. **LC-01 (silent action failure with a committed transition).** `apply_fill` raising leaves the machine in `filled` with a stale quantity, `status == "running"`, and `on_transition` reporting success. `quarantined` above is where a faulted order lands, driven by the mandatory `@cv_action` wrapper (A1).
3. **LC-11 (no snapshot schema version).** `from_snapshot` will load an old-shaped snapshot and partially mis-restore it without complaint. We wrap snapshots in our own versioned envelope.

Why it is nonetheless a good fit: the OMS is the library's strongest measured case. 500 resident order machines cost **0.53 MB total** (1.08 KB each) and fill latency is p50 0.057 ms / p95 0.127 ms when the loop is healthy (Study 04 Budget 3). Ordering is strictly FIFO with zero loss across 10 concurrent producers (g7) — the property an OMS depends on most, and it holds. A cancelled `place_order` invoke does **not** later deliver a stale `done.invoke` (Study 05 B5), which would otherwise be a genuine corruption path.

### Changes to plan docs / tickets

- **24 §8.2** — replace the flat `status` enum with the two-region model; add `quarantined` as a 14th lifecycle state, documented as "a transition whose action faulted; the order is not trusted until reconciliation confirms it". Add binding rule **S10**: *every state occupied during an in-flight exchange call declares a deferral handler; a fill is never dropped.* Add **S11**: *no action may raise; a raising action quarantines the order.*
- **ADR-0006** — add to Consequences/negative: the chosen statechart library commits transitions whose actions failed, so the write-ahead `order_events` row (S8) is the only reliable trace and independent reconciliation is not optional.
- **E29-T03** ("canonical order state machine with write-ahead events") — scope grows to machine JSON + `MachineLogic` + `@cv_action` wrapper + deferral buffer. Re-estimate upward.
- **New ticket E29-T10** — "Machine-definition linter: absolute targets, `reenter` on self-transitions, deferral coverage, action-decorator coverage, no side-effecting guards." Blocking gate for E29-T03.
- **E29-Q04** (chaos) — add scenarios "fill arrives during `submitting`" (assert `filled_qty` correctness) and "action raises mid-fill" (assert quarantine, assert no terminal state reached).

---

## B2 — TradeGroup

### Current design (24 §9.6, ADR-0008)

`draft → submitting → partially_open | open | failed`, then `closing → closed | failed`, plus `cancelled`. Leg failure policy `best_effort | all_or_none | abort_on_first`. The `all_or_none` path runs the §9.5.1 compensating unwind, which the plan doc already describes as "an explicit, restartable, idempotent state machine rather than 'cancel and close'" — a direct invitation to model it as one.

### Proposed statechart

The group is a **supervisor**: it spawns one leg actor per account (B3) and one unwind actor when policy demands it.

```json
{
  "id": "trade_group",
  "initial": "draft",
  "context": {
    "group_id": null, "policy": "best_effort", "leg_ids": [],
    "legs_open": 0, "legs_failed": 0, "legs_skipped": 0, "legs_total": 0,
    "quiesce_deadline_us": null, "unwind_id": null, "quiesced": false
  },
  "states": {
    "draft": {
      "on": {
        "CONFIRM": {"target": "#trade_group.submitting",
                    "actions": ["reserve_rate_budget", "spawn_all_legs"]},
        "CANCEL":  {"target": "#trade_group.cancelled"}
      }
    },
    "submitting": {
      "entry": ["arm_quiesce_deadline"],
      "on": {
        "LEG_OPEN":    {"actions": ["count_open", "raise_evaluate"]},
        "LEG_FAILED":  [
          {"target": "#trade_group.aborting", "guard": "policy_is_abort_on_first", "actions": ["count_failed"]},
          {"actions": ["count_failed", "raise_evaluate"]}
        ],
        "LEG_SKIPPED": {"actions": ["count_skipped", "raise_evaluate"]},
        "QUIESCE_DEADLINE": {"actions": ["mark_quiesced", "force_resolve_unknown_legs", "raise_evaluate"]},
        "EVALUATE": [
          {"target": "#trade_group.unwinding",      "guard": "policy_all_or_none_and_any_failed"},
          {"target": "#trade_group.open",           "guard": "all_non_skipped_open"},
          {"target": "#trade_group.failed",         "guard": "quiesced_and_zero_open"},
          {"target": "#trade_group.partially_open", "guard": "quiesced_and_some_open"}
        ]
      }
    },
    "partially_open": {
      "on": {
        "LEG_OPEN": [
          {"target": "#trade_group.open", "guard": "all_non_skipped_open", "actions": ["count_open"]},
          {"target": "#trade_group.partially_open", "reenter": true, "actions": ["count_open"]}
        ],
        "CLOSE_GROUP": {"target": "#trade_group.closing"}
      }
    },
    "open": {
      "on": {
        "CLOSE_GROUP":   {"target": "#trade_group.closing"},
        "ALL_LEGS_FLAT": {"target": "#trade_group.closed"}
      }
    },
    "aborting": {
      "entry": ["stop_submitting_remaining_legs"],
      "always": [
        {"target": "#trade_group.partially_open", "guard": "some_open"},
        {"target": "#trade_group.failed"}
      ]
    },
    "unwinding": {
      "entry": ["persist_unwind_plan"],
      "invoke": {
        "id": "unwind", "src": "unwind_machine",
        "onDone": [
          {"target": "#trade_group.failed", "guard": "unwind_complete", "actions": ["mark_unwound"]},
          {"target": "#trade_group.failed", "actions": ["mark_unwind_incomplete", "raise_critical_alert"]}
        ],
        "onError": {"target": "#trade_group.failed",
                    "actions": ["mark_unwind_incomplete", "raise_critical_alert"]}
      }
    },
    "closing": {
      "on": {
        "ALL_LEGS_FLAT":    {"target": "#trade_group.closed"},
        "CLOSE_INCOMPLETE": {"target": "#trade_group.failed", "actions": ["raise_critical_alert"]}
      }
    },
    "closed":    {"type": "final", "tags": ["terminal"]},
    "failed":    {"type": "final", "tags": ["terminal"]},
    "cancelled": {"type": "final", "tags": ["terminal"]}
  }
}
```

The `EVALUATE` self-raise exists because we must **not** put the aggregate decision in an `always` on `submitting` — LC-04 parks the machine on an `always` self-target. Raising a distinct `EVALUATE` event after each leg outcome re-runs the decision safely.

A consequence of **LC-06** must be designed around explicitly: `raise` is queued behind pending external events rather than settling within the macrostep (Study 05 C10 — expected `["entry","RAISED","EXTERNAL"]`, observed `["entry","EXTERNAL","RAISED"]`). So `EVALUATE` may be observed *after* a subsequently-arriving `LEG_OPEN`. This is harmless here because every guard reads counters from context. **Binding consequence: every aggregate decision in CandleViewer must be a pure function of context, never of event arrival order.**

### Fit: **Good**

Enablers: actor spawn is ~100–130 µs and teardown ~30 µs, both flat in child count, with **0.11 KB retained per actor over 3,000 spawn/stop cycles** (Study 04 §5) — the best-behaved subsystem measured. A 20-account fan-out costs ~2.6 ms to stand up.

Blockers:

1. **LC-02 — actor addressing.** The hard one for fan-out. Study 05 C16: `sendTo` resolves **only** by *service key* — the declared `invoke` `id` and `systemId` are both ignored. Actor ids are minted `parent:<serviceKey>:<uuid>`, so N legs invoked from the same `src` are mutually ambiguous, and the library's response to ambiguity is `logger.warning` plus a **dropped event**. ADR-0008 fan-out is precisely "invoke the same child machine under N distinct ids and address them individually". **Workaround:** the parent keeps its own `dict[leg_id -> Interpreter]` populated at spawn time and calls `actor.send(...)` directly. Study 05 verified direct delivery works. Cost: we give up declarative routing and must rehydrate the registry on restore.
2. **Routing cost.** `sendTo` forwarding costs 75.7 µs/msg vs 33 µs for a direct transition — 2.3× (Study 04 §5). Combined with (1): **fan out directly to leg actors; never route market or execution events through the group parent.**

### Changes to plan docs / tickets

- **24 §9.6** — add `aborting` as an explicit state (today `abort_on_first` appears only in the §9.5 prose table). Add a normative note that group status is a pure function of leg counters held in context.
- **ADR-0008** — add to Consequences: "leg actors are addressed through an application-owned registry, not the library's actor-addressing API, because that API cannot disambiguate N children sharing one `src` (research/xstate/10, LC-02)."
- **E34** (fan-out & rate-limit governor) — add "leg actor registry with restore-from-snapshot rehydration" to scope.
- **E28** — `profile_snapshot` becomes leg-actor input. Note **LC-12**: `invoke.input` is a static dict in this library and is **ignored entirely** when `src` is a child machine (`_spawn_and_manage_actor` never reads `invocation.input`). Input must be seeded by spawning explicitly and writing context ourselves.

---

## B3 — TradeGroupLeg

### Current design (24 §9.1, §9.5.1)

`pending → submitted → rejected | open → partially_filled → filled → cancelled | closed | error`, carrying `profile_snapshot`, sizing, SL/TP ladder, plus the unwind phases `cancel_children → close_position → verify_flat → verify_sl` with per-account strict ordering, max 2 close attempts, and the "read the authoritative exchange position, not the local accumulator" rule.

### Proposed statechart

```json
{
  "id": "leg",
  "initial": "pending",
  "context": {
    "leg_id": null, "account_id": null, "profile_snapshot": null,
    "sized_qty": "0", "filled_qty": "0", "entry_order_id": null,
    "tp_order_ids": [], "skip_reason": null, "error_code": null,
    "close_attempts": 0, "qty_drift": "0"
  },
  "states": {
    "pending": {
      "entry": ["size_from_profile"],
      "always": [
        {"target": "#leg.skipped",    "guard": "should_skip"},
        {"target": "#leg.submitting", "guard": "passes_preflight"},
        {"target": "#leg.error"}
      ]
    },
    "submitting": {
      "entry": ["spawn_entry_order", "arm_submit_timeout"],
      "on": {
        "ORDER_OPEN":     {"target": "#leg.open"},
        "ORDER_REJECTED": {"target": "#leg.rejected", "actions": ["map_error"]},
        "ORDER_UNKNOWN":  {"target": "#leg.resolving"},
        "SUBMIT_TIMEOUT": {"target": "#leg.resolving"}
      }
    },
    "resolving": {
      "invoke": {
        "id": "lookup", "src": "lookup_by_link_id",
        "onDone": [
          {"target": "#leg.open",     "guard": "lookup_says_live"},
          {"target": "#leg.filled",   "guard": "lookup_says_filled"},
          {"target": "#leg.rejected", "actions": ["map_error"]}
        ],
        "onError": {"target": "#leg.error", "actions": ["map_error"]}
      },
      "on": {"*": {"actions": ["defer"]}}
    },
    "open": {
      "entry": ["drain_deferred"],
      "on": {
        "EXEC":   {"target": "#leg.partially_filled",
                   "actions": ["accumulate_fill", "place_tp_ladder_once"]},
        "UNWIND": {"target": "#leg.unwinding"},
        "CLOSE":  {"target": "#leg.closing"}
      }
    },
    "partially_filled": {
      "on": {
        "EXEC": [
          {"target": "#leg.filled", "guard": "fully_filled", "actions": ["accumulate_fill"]},
          {"target": "#leg.partially_filled", "reenter": true, "actions": ["accumulate_fill"]}
        ],
        "UNWIND": {"target": "#leg.unwinding"},
        "CLOSE":  {"target": "#leg.closing"}
      }
    },
    "filled": {"on": {"UNWIND": {"target": "#leg.unwinding"}, "CLOSE": {"target": "#leg.closing"}}},
    "unwinding": {
      "initial": "cancel_children",
      "states": {
        "cancel_children": {
          "invoke": {"id": "cx", "src": "cancel_children_svc",
                     "onDone":  {"target": "#leg.unwinding.close_position"},
                     "onError": {"target": "#leg.unwinding.close_position",
                                 "actions": ["note_cancel_failure"]}}
        },
        "close_position": {
          "entry": ["read_authoritative_position_qty", "bump_close_attempts"],
          "invoke": {"id": "cl", "src": "reduce_only_close",
                     "onDone":  {"target": "#leg.unwinding.verify_flat"},
                     "onError": [
                       {"target": "#leg.unwinding.close_position", "reenter": true,
                        "guard": "close_attempts_left"},
                       {"target": "#leg.unwinding.verify_sl", "actions": ["mark_incomplete"]}
                     ]}
        },
        "verify_flat": {
          "invoke": {"id": "vf", "src": "poll_until_flat",
                     "onDone": [
                       {"target": "#leg.closed", "guard": "is_flat"},
                       {"target": "#leg.unwinding.close_position", "reenter": true,
                        "guard": "close_attempts_left"},
                       {"target": "#leg.unwinding.verify_sl", "actions": ["mark_incomplete"]}
                     ],
                     "onError": {"target": "#leg.unwinding.verify_sl", "actions": ["mark_incomplete"]}}
        },
        "verify_sl": {
          "invoke": {"id": "vs", "src": "assert_native_sl",
                     "onDone":  {"target": "#leg.error"},
                     "onError": {"target": "#leg.error", "actions": ["raise_naked_position_alert"]}}
        }
      }
    },
    "closing": {"on": {"FLAT": {"target": "#leg.closed"}, "CLOSE_FAILED": {"target": "#leg.error"}}},
    "skipped":  {"type": "final", "tags": ["terminal", "skip"]},
    "rejected": {"type": "final", "tags": ["terminal", "failure"]},
    "closed":   {"type": "final", "tags": ["terminal"]},
    "error":    {"type": "final", "tags": ["terminal", "failure"]}
  }
}
```

### Fit: **Good**

The unwind is the highest-risk path in the OMS and it maps to a nested compound state almost perfectly: strict per-account phase ordering is what a compound state gives you for free, and "no global barrier across accounts" (24 §9.5.1 rule 6) is satisfied automatically because each leg actor advances independently on its own interpreter.

Concerns:

1. **`always` chain in `pending`.** Safe here because every branch targets a *distinct* state — A19 proves such chains converge. It is nonetheless one refactor away from the A10 deadlock if someone adds a self-target fallback. Linter rule.
2. **`close_position` retry requires `reenter: true` on a capital-critical path.** Without it the `entry` — which re-reads the authoritative position quantity and increments the attempt counter — would not run, producing an unbounded retry that forever reads a stale quantity. This is LC-04 biting where it costs money. It is exactly the kind of thing that works in a demo and fails in production.
3. **`close_attempts_left` must be deny-polarity** (A6): a raising guard is swallowed as `False`, so the guard must be written so that `False` means "stop retrying", not "keep retrying".

### Changes

- **24 §9.5.1** — express the per-account procedure as the nested chart above, keeping the prose as commentary. Add the note: "the step retry counter is incremented in the state's `entry`, which requires an explicitly re-entering self-transition."
- **E34** — add a ticket "Unwind leg statechart + `UnwindResumer`" (today `UnwindResumer` is prose with no ticket anywhere in the backlog).
- **E45-T01/T02** — reconciliation must be able to drive a leg actor out of `resolving`, so the reconciler needs read access to the B2 leg registry.

---

## B4 — EmulatedAlgo: OCO

### Current design (24 §10.2)

Race two reduce-only legs; on a fill of qty `q` on leg A either cancel B (`cancel_other`) or **amend** B down by `q` (`reduce_other`, default — preserves queue position, no naked window). Amend rejection because B is already gone → reconcile and settle. Double-fill race detected as position overshoot → immediate reduce-only market for the excess + `warning` alert. Three failed cancel/amends → `failed` + `critical` alert, native SL remains.

### Proposed statechart

```json
{
  "id": "oco",
  "initial": "arming",
  "context": {
    "algo_id": null, "mode": "reduce_other", "leg_a_id": null, "leg_b_id": null,
    "filled_a": "0", "filled_b": "0", "settle_failures": 0, "excess_qty": "0"
  },
  "states": {
    "arming": {
      "invoke": {"id": "arm", "src": "submit_both_legs",
                 "onDone":  {"target": "#oco.racing", "actions": ["record_child_ids"]},
                 "onError": {"target": "#oco.failed", "actions": ["map_error"]}}
    },
    "racing": {
      "on": {
        "LEG_A_FILL": [
          {"target": "#oco.overshoot",  "guard": "position_overshoots", "actions": ["record_fill_a"]},
          {"target": "#oco.settling_b", "actions": ["record_fill_a"]}
        ],
        "LEG_B_FILL": [
          {"target": "#oco.overshoot",  "guard": "position_overshoots", "actions": ["record_fill_b"]},
          {"target": "#oco.settling_a", "actions": ["record_fill_b"]}
        ],
        "POSITION_FLAT": {"target": "#oco.cancelling_all", "guard": "cancel_on_position_flat"},
        "USER_CANCEL":   {"target": "#oco.cancelling_all"},
        "*": {"actions": ["defer"]}
      }
    },
    "settling_b": {
      "entry": ["drain_deferred"],
      "invoke": {
        "id": "settle_b", "src": "settle_other_leg",
        "onDone": [
          {"target": "#oco.completing", "guard": "other_leg_terminal"},
          {"target": "#oco.racing",     "guard": "partial_settle_remaining", "reenter": true}
        ],
        "onError": [
          {"target": "#oco.reconciling", "guard": "error_is_order_gone"},
          {"target": "#oco.settling_b",  "reenter": true, "guard": "settle_retries_left",
           "actions": ["bump_settle_failures"]},
          {"target": "#oco.failed", "actions": ["raise_critical_alert"]}
        ]
      },
      "on": {"*": {"actions": ["defer"]}}
    },
    "settling_a": {
      "entry": ["drain_deferred"],
      "invoke": {
        "id": "settle_a", "src": "settle_other_leg",
        "onDone": [
          {"target": "#oco.completing", "guard": "other_leg_terminal"},
          {"target": "#oco.racing",     "guard": "partial_settle_remaining", "reenter": true}
        ],
        "onError": [
          {"target": "#oco.reconciling", "guard": "error_is_order_gone"},
          {"target": "#oco.settling_a",  "reenter": true, "guard": "settle_retries_left",
           "actions": ["bump_settle_failures"]},
          {"target": "#oco.failed", "actions": ["raise_critical_alert"]}
        ]
      },
      "on": {"*": {"actions": ["defer"]}}
    },
    "overshoot": {
      "entry": ["raise_warning_alert", "journal_double_fill"],
      "invoke": {"id": "flatten_excess", "src": "reduce_only_market_excess",
                 "onDone":  {"target": "#oco.completing"},
                 "onError": {"target": "#oco.failed", "actions": ["raise_critical_alert"]}}
    },
    "reconciling": {
      "invoke": {"id": "rec", "src": "reconcile_children",
                 "onDone":  {"target": "#oco.completing"},
                 "onError": {"target": "#oco.failed", "actions": ["raise_critical_alert"]}}
    },
    "cancelling_all": {
      "invoke": {"id": "ca", "src": "cancel_all_children",
                 "onDone":  {"target": "#oco.cancelled"},
                 "onError": {"target": "#oco.failed", "actions": ["raise_critical_alert"]}}
    },
    "completing": {"on": {"CHILDREN_TERMINAL": {"target": "#oco.completed"}}},
    "completed": {"type": "final", "tags": ["terminal"]},
    "cancelled": {"type": "final", "tags": ["terminal"]},
    "failed":    {"type": "final", "tags": ["terminal", "failure"]}
  }
}
```

### Fit: **Good**

OCO is the algo with the least timing dependence — it is event-driven off fills, which is what this library does well. The double-fill race, which in the plan doc is a prose paragraph, becomes an explicit `overshoot` state with its own alert and compensating invoke; that is a genuine clarity win from statecharting.

Concerns:

- `settling_b` / `settling_a` are transient states occupied during an amend round trip, so they need deferral (LC-03): a fill on the *other* leg landing during the settle must not be dropped. This is exactly the double-fill race the plan doc says is "rare but not never".
- The `onError` guard chain distinguishes "order already gone" (expected, non-alarming per §10.2 step 3) from a genuine failure. Guards must be deny-polarity for the retry-exhaustion branch.
- **LC-13**: `error.platform.<id>` carries the exception *object* (verified, Study 05 B2), which is good, but there is no typed error channel — our guards must introspect the mapped `OmsErrorCode` we attach in the service, never the raw exception type.

### Changes

- **24 §10.2** — add the state diagram; promote "double-fill race" from step 4 prose to a named `overshoot` state with its own metric `oco_overshoot_total`.
- **E33-S01** — acceptance criteria should assert the deferral behaviour explicitly ("a fill on leg B during leg A settlement is applied, not dropped").

---

## B5 — EmulatedAlgo: Iceberg

### Current design (24 §10.3)

Submit one visible child of `display_qty` jittered ±`randomize_pct`; on full fill wait `refill_delay_ms + U(0, refill_jitter_ms)` then submit the next slice; on partial fill leave the child working and refill only after it terminates; final slice is the exact remainder, merged into the previous slice if below `min_order_qty`. Post-only rejections retried once; two consecutive rejections pause 1 s.

### Proposed statechart

```json
{
  "id": "iceberg",
  "initial": "pending",
  "context": {
    "algo_id": null, "total_qty": "0", "remaining_qty": "0", "slices_done": 0,
    "max_slices": 450, "active_child_id": null, "post_only_rejects": 0,
    "next_refill_at_us": null, "failure_count": 0
  },
  "states": {
    "pending": {
      "always": [
        {"target": "#iceberg.failed",          "guard": "preflight_invalid"},
        {"target": "#iceberg.submitting_slice"}
      ]
    },
    "submitting_slice": {
      "entry": ["compute_slice_qty", "bump_slices_done"],
      "invoke": {
        "id": "slice", "src": "submit_child",
        "onDone":  {"target": "#iceberg.working", "actions": ["record_child"]},
        "onError": [
          {"target": "#iceberg.repricing", "guard": "is_post_only_reject"},
          {"target": "#iceberg.failed",    "guard": "failures_exhausted"},
          {"target": "#iceberg.submitting_slice", "reenter": true, "actions": ["bump_failure"]}
        ]
      },
      "on": {"*": {"actions": ["defer"]}}
    },
    "working": {
      "entry": ["drain_deferred"],
      "on": {
        "CHILD_FILLED": [
          {"target": "#iceberg.completing", "guard": "remaining_is_zero", "actions": ["apply_fill"]},
          {"target": "#iceberg.waiting_refill", "actions": ["apply_fill"]}
        ],
        "CHILD_PARTIAL":   {"actions": ["apply_fill"]},
        "CHILD_CANCELLED": {"target": "#iceberg.waiting_refill"},
        "USER_PAUSE":      {"target": "#iceberg.paused"},
        "WS_DISCONNECT":   {"target": "#iceberg.paused", "guard": "on_disconnect_is_freeze"},
        "USER_CANCEL":     {"target": "#iceberg.cancelling"},
        "POSITION_FLAT":   {"target": "#iceberg.cancelling", "guard": "cancel_on_position_flat"},
        "MAX_DURATION":    {"target": "#iceberg.cancelling"}
      }
    },
    "waiting_refill": {
      "entry": ["schedule_refill_deadline"],
      "on": {
        "REFILL_DUE": [
          {"target": "#iceberg.completing",       "guard": "remaining_is_zero"},
          {"target": "#iceberg.completing",       "guard": "slices_exhausted"},
          {"target": "#iceberg.submitting_slice"}
        ],
        "USER_PAUSE":  {"target": "#iceberg.paused"},
        "USER_CANCEL": {"target": "#iceberg.cancelling"}
      }
    },
    "repricing": {
      "entry": ["bump_post_only_rejects"],
      "always": [
        {"target": "#iceberg.cooling_down",    "guard": "two_consecutive_post_only_rejects"},
        {"target": "#iceberg.submitting_slice"}
      ]
    },
    "cooling_down": {
      "entry": ["schedule_cooldown_deadline", "reset_post_only_rejects"],
      "on": {"COOLDOWN_DUE": {"target": "#iceberg.submitting_slice"}}
    },
    "paused": {
      "on": {
        "RESUME":      {"target": "#iceberg.reconciling"},
        "USER_CANCEL": {"target": "#iceberg.cancelling"}
      }
    },
    "reconciling": {
      "invoke": {"id": "rec", "src": "reconcile_children",
                 "onDone":  {"target": "#iceberg.working"},
                 "onError": {"target": "#iceberg.failed"}}
    },
    "cancelling": {
      "invoke": {"id": "cx", "src": "cancel_all_children",
                 "onDone":  {"target": "#iceberg.cancelled"},
                 "onError": {"target": "#iceberg.failed"}}
    },
    "completing": {"on": {"CHILDREN_TERMINAL": {"target": "#iceberg.completed"}}},
    "completed": {"type": "final", "tags": ["terminal"]},
    "cancelled": {"type": "final", "tags": ["terminal"]},
    "failed":    {"type": "final", "tags": ["terminal", "failure"]}
  }
}
```

Note the deliberate `working → waiting_refill → submitting_slice` cycle. The obvious design — an `always` self-loop on a `slicing` state that decrements `remaining_qty` until zero — is **exactly the A10 deadlock**: the machine would submit one slice and park silently with `is_running == True`. Routing through distinct states is the A19-verified workaround and it is why the chart has three states where one would read more naturally.

### Fit: **Workaround**

Two load-bearing workarounds:

1. **LC-04 — `always` self-target deadlock.** "Accumulate until a threshold" is the canonical iceberg shape and it silently hangs if written the natural way. The plan-doc algorithm (§10.3) reads as a loop; the statechart must not be one. This is the single easiest way for a future contributor to introduce a silent stall in a live order algo.
2. **LC-05 — timers.** `refill_delay_ms` is 250 ms by default. Under 500 busy interpreters an `after` fires ~2.25 s late regardless of the requested delay (Study 04 §3), so a 250 ms refill would become a ~2.5 s refill during exactly the volatility burst where the algo matters. `schedule_refill_deadline` therefore writes an absolute `next_refill_at_us` into context and registers with the external `MonotonicScheduler` (A2), which injects `REFILL_DUE`. This also makes the deadline survive `from_snapshot` — the library's own timers do not (Study 04 §4, verified: a machine snapshotted with 700 ms left on an 800 ms timer never fired after restore, even 1.5 s later).

### Changes

- **24 §10.3** — add the statechart, and add a normative sentence: "slice cycling is expressed as a three-state cycle, never as a self-looping state; see research/xstate/10 LC-04."
- **24 §10.1** — add to the Universal rules: **(6) No algo uses the statechart library's `after` for any interval that matters. All algo deadlines are absolute timestamps in context, scheduled externally, and re-armed from context on resume/restore.**
- **E33-K01** ("Prove the emulated-algo scheduler, crash-resume seam and orphan adoption") — this spike now has a concrete, pre-identified answer to validate: external monotonic scheduler + context-held deadlines. Add an acceptance criterion measuring refill-interval fidelity under 500 concurrent machines.
- **E33-T01** (AlgoSupervisor framework) — add `MonotonicScheduler` as an explicit deliverable.

---

## B6 — EmulatedAlgo: TWAP

### Current design (24 §10.4)

Nominal slice `q = total/slices`, nominal interval `T = duration/slices`; slice `i` fires at `start + i*T ± U(0, randomize_time_pct*T)`; `max_participation_pct` shrinks a slice against traded volume since the last slice; `catch_up` ∈ `none | next_slice | proportional`; final slice carries the exact remainder and converts to market at `duration_ms` if `final_market_sweep`; price-limit breaches pause by default.

### Proposed statechart

```json
{
  "id": "twap",
  "initial": "pending",
  "context": {
    "algo_id": null, "slices_total": 0, "slices_done": 0,
    "total_qty": "0", "remaining_qty": "0", "shortfall_qty": "0",
    "slice_deadlines_us": [], "end_at_us": null,
    "catch_up": "next_slice", "price_limit": null, "failure_count": 0
  },
  "states": {
    "pending": {
      "entry": ["precompute_all_slice_deadlines", "register_deadlines_with_scheduler"],
      "always": [
        {"target": "#twap.failed",   "guard": "preflight_invalid"},
        {"target": "#twap.armed"}
      ]
    },
    "armed": {
      "on": {
        "SLICE_DUE": [
          {"target": "#twap.price_blocked", "guard": "price_limit_breached"},
          {"target": "#twap.submitting_slice"}
        ],
        "DURATION_END": [
          {"target": "#twap.final_sweep", "guard": "final_market_sweep_and_remaining"},
          {"target": "#twap.completing"}
        ],
        "USER_PAUSE":    {"target": "#twap.paused"},
        "WS_DISCONNECT": {"target": "#twap.paused", "guard": "on_disconnect_is_freeze"},
        "USER_CANCEL":   {"target": "#twap.cancelling"},
        "MAX_DURATION":  {"target": "#twap.cancelling"}
      }
    },
    "submitting_slice": {
      "entry": ["compute_slice_qty_with_participation_cap", "apply_catch_up", "bump_slices_done"],
      "always": [{"target": "#twap.armed", "guard": "slice_qty_below_min_roll_forward"}],
      "invoke": {
        "id": "slice", "src": "submit_child",
        "onDone":  {"target": "#twap.armed", "actions": ["record_child"]},
        "onError": [
          {"target": "#twap.failed", "guard": "failures_exhausted"},
          {"target": "#twap.armed",  "actions": ["bump_failure", "record_shortfall"]}
        ]
      },
      "on": {"*": {"actions": ["defer"]}}
    },
    "price_blocked": {
      "entry": ["raise_price_limit_notice"],
      "always": [{"target": "#twap.cancelling", "guard": "abort_on_price_limit"}],
      "on": {
        "PRICE_OK":    {"target": "#twap.armed"},
        "SLICE_DUE":   {"actions": ["record_shortfall"]},
        "DURATION_END":{"target": "#twap.completing"},
        "USER_CANCEL": {"target": "#twap.cancelling"}
      }
    },
    "final_sweep": {
      "invoke": {"id": "sweep", "src": "market_sweep_remainder",
                 "onDone":  {"target": "#twap.completing"},
                 "onError": {"target": "#twap.failed", "actions": ["raise_warning_alert"]}}
    },
    "paused": {
      "on": {"RESUME": {"target": "#twap.reconciling"}, "USER_CANCEL": {"target": "#twap.cancelling"}}
    },
    "reconciling": {
      "entry": ["rearm_deadlines_from_context"],
      "invoke": {"id": "rec", "src": "reconcile_children",
                 "onDone":  {"target": "#twap.armed"},
                 "onError": {"target": "#twap.failed"}}
    },
    "cancelling": {
      "invoke": {"id": "cx", "src": "cancel_all_children",
                 "onDone":  {"target": "#twap.cancelled"},
                 "onError": {"target": "#twap.failed"}}
    },
    "completing": {"on": {"CHILDREN_TERMINAL": {"target": "#twap.completed"}}},
    "completed": {"type": "final", "tags": ["terminal"]},
    "cancelled": {"type": "final", "tags": ["terminal"]},
    "failed":    {"type": "final", "tags": ["terminal", "failure"]}
  }
}
```

### Fit: **Workaround**

TWAP is *definitionally* a scheduler. The statechart contributes the lifecycle (armed / blocked / paused / sweeping / terminal) and contributes it well; it contributes **nothing** to the timing, and must be actively prevented from trying.

The measurement that decides this: with 500 busy interpreters, a requested 10 ms delay fires at +2.25 s, a requested 100 ms at +2.29 s and a requested 1 s at +2.16 s (Study 04 §3). The error is essentially **independent of the requested delay** — the loop is saturated and the callback simply cannot be serviced. A 12-slice TWAP over 60 s has a nominal 5 s interval; a 2.2 s systematic drift per slice destroys the "time-weighted" property that is the entire point of the algorithm. Worse, it degrades precisely during volatility, when the loop is busiest and when execution quality matters most.

Hence: `precompute_all_slice_deadlines` computes all `slices_total` absolute timestamps at arm time, stores them in context, and registers them with the external `MonotonicScheduler`. The scheduler injects `SLICE_DUE`. On restore, `rearm_deadlines_from_context` re-registers whatever remains — mandatory, because pending `after` timers do not survive `from_snapshot` (Study 04 §4).

Secondary concerns:

- `submitting_slice` has both an `always` (roll-forward for sub-minimum slices) and an `invoke`. Study 05 A8 confirms `always` chains with guards settle correctly, and the `always` is evaluated on entry before the invoke starts. This ordering should be pinned by our own regression test rather than assumed — the library's own test suite has had cross-engine divergences in exactly this area (Study 02: `test_engine_conformance.py` was written after six release-blocking semantic divergences, one of which was "early `onDone` leak").
- **LC-14**: the `SyncInterpreter` cannot run async services at all (`NotSupportedError`), and its `after` timers run on a background thread that mutates context without a lock (Study 04 §6). Algos must use the async `Interpreter` exclusively. This should be a lint rule, not a convention.

### Changes

- **24 §10.4** — add the statechart; add "all slice deadlines are precomputed as absolute timestamps at arm time and re-armed from context on resume, because in-machine timers neither survive restore nor hold accuracy under load".
- **E33-S03** (TWAP) — add an acceptance criterion: slice-interval error p95 ≤ 100 ms with 500 concurrent order machines resident. This is a real gate the naive implementation fails by ~20×.
- **06-performance-and-load-standard.md** — add a budget line for "algo scheduler fidelity under load" (currently absent).

---

## B7 — EmulatedAlgo: Chase

### Current design (24 §10.5)

Place a limit at the target; on each book update, if the target has drifted ≥ `reprice_threshold_ticks` **and** ≥ `reprice_interval_ms` (default **200 ms**) since the last reprice, **amend**. Hard bounds: `max_chase_ticks` from the arm price, `max_repricings` (200), `timeout_ms` (60 s) with `on_timeout` ∈ `market | cancel | leave`. In `maker` mode the target excludes our own size (the "chases itself into a spread walk" bug).

### Proposed statechart

```json
{
  "id": "chase",
  "initial": "arming",
  "context": {
    "algo_id": null, "arm_price": null, "target_price": null, "child_id": null,
    "repricings": 0, "max_repricings": 200, "max_chase_ticks": 0,
    "last_reprice_us": 0, "reprice_interval_us": 200000,
    "timeout_at_us": null, "failure_count": 0
  },
  "states": {
    "arming": {
      "invoke": {"id": "arm", "src": "submit_initial_limit",
                 "onDone":  {"target": "#chase.working", "actions": ["record_child", "stamp_arm_price"]},
                 "onError": {"target": "#chase.failed", "actions": ["map_error"]}}
    },
    "working": {
      "entry": ["drain_deferred"],
      "on": {
        "BOOK_TARGET_MOVED": [
          {"target": "#chase.bound_exceeded", "guard": "beyond_max_chase_ticks"},
          {"target": "#chase.bound_exceeded", "guard": "repricings_exhausted"},
          {"target": "#chase.repricing",
           "guard": "drift_over_threshold_and_interval_elapsed_and_budget_ok"}
        ],
        "CHILD_FILLED":   {"target": "#chase.completing", "actions": ["apply_fill"]},
        "CHILD_PARTIAL":  {"actions": ["apply_fill"]},
        "TIMEOUT":        {"target": "#chase.timing_out"},
        "RATE_BUDGET_EXHAUSTED": {"target": "#chase.paused"},
        "USER_PAUSE":     {"target": "#chase.paused"},
        "WS_DISCONNECT":  {"target": "#chase.paused", "guard": "on_disconnect_is_freeze"},
        "USER_CANCEL":    {"target": "#chase.cancelling"}
      }
    },
    "repricing": {
      "entry": ["compute_target_excluding_own_size", "bump_repricings", "stamp_last_reprice"],
      "invoke": {
        "id": "amend", "src": "amend_child_price",
        "onDone":  {"target": "#chase.working"},
        "onError": [
          {"target": "#chase.completing", "guard": "error_is_order_not_found_after_fill"},
          {"target": "#chase.failed",     "guard": "failures_exhausted"},
          {"target": "#chase.working",    "actions": ["bump_failure"]}
        ]
      },
      "on": {"*": {"actions": ["defer"]}}
    },
    "bound_exceeded": {
      "entry": ["raise_warning_alert"],
      "always": [
        {"target": "#chase.timing_out", "guard": "on_timeout_is_market"},
        {"target": "#chase.cancelling", "guard": "on_timeout_is_cancel"},
        {"target": "#chase.parked"}
      ]
    },
    "timing_out": {
      "always": [
        {"target": "#chase.market_converting", "guard": "on_timeout_is_market"},
        {"target": "#chase.cancelling",        "guard": "on_timeout_is_cancel"},
        {"target": "#chase.parked"}
      ]
    },
    "market_converting": {
      "invoke": {"id": "mkt", "src": "convert_to_market",
                 "onDone":  {"target": "#chase.completing"},
                 "onError": {"target": "#chase.failed"}}
    },
    "parked":  {"tags": ["left_working"], "on": {"CHILD_FILLED": {"target": "#chase.completing"},
                                                 "USER_CANCEL":  {"target": "#chase.cancelling"}}},
    "paused":  {"on": {"RESUME": {"target": "#chase.working"}, "USER_CANCEL": {"target": "#chase.cancelling"}}},
    "cancelling": {
      "invoke": {"id": "cx", "src": "cancel_child",
                 "onDone":  {"target": "#chase.cancelled"},
                 "onError": {"target": "#chase.failed"}}
    },
    "completing": {"on": {"CHILDREN_TERMINAL": {"target": "#chase.completed"}}},
    "completed": {"type": "final", "tags": ["terminal"]},
    "cancelled": {"type": "final", "tags": ["terminal"]},
    "failed":    {"type": "final", "tags": ["terminal", "failure"]}
  }
}
```

### Fit: **Workaround** — and the weakest of the four algos

Chase is the worst fit in the algo family for three independent reasons:

1. **The control interval is below the library's usable floor.** `reprice_interval_ms` defaults to **200 ms**. On idle the library's `after` is +6 to +16 ms and *always* late; under load it is +2,250 ms. Even the idle case is a 3–8 % distortion of a 200 ms control loop; the loaded case is 11× the interval. Study 04 states the conclusion plainly: "do not build a 10 ms control loop on `after`", and Windows' ~15.6 ms timer granularity is a platform floor beneath that. **The interval must be enforced as a guard over `time.monotonic()` (`interval_elapsed`), not as a timer**, which is why the chart's reprice condition is a compound guard on the incoming book event rather than a scheduled tick. That is a good design anyway — it means repricing is book-driven, exactly as §10.5 specifies — but it means the statechart contributes nothing to the timing.
2. **Book-update volume.** `BOOK_TARGET_MOVED` is derived from the book stream, throttled. Feeding raw book updates to a chase interpreter would put a market-data-rate stream into the 20k ev/s global budget (see B14). The chase actor must subscribe to a **pre-throttled, pre-filtered** derived event ("the same-side best excluding our own size changed by ≥ `reprice_threshold_ticks`"), computed in plain Python in the book engine. That filter is where the "chases itself" bug lives (§10.5), so the most bug-prone logic in chase sits *outside* the statechart.
3. **`repricing` is a transient state during an amend round trip**, so LC-03 applies: a fill landing during an in-flight amend is authoritative (§10.5 explicitly), and it must be deferred and drained, not dropped.

What the statechart *does* buy: the anti-runaway bounds (`max_chase_ticks`, `max_repricings`, `timeout_ms`, `on_timeout` fan-out) become explicit, inspectable states rather than scattered `if` statements. For the algorithm 24 §10.5 calls out as having "the single most common chase bug", making the bound structure visible is worth real money.

### Changes

- **24 §10.5** — add the statechart; state normatively that `reprice_interval_ms` is enforced as a monotonic-clock guard on incoming book events, never as a timer, and that the chase actor consumes a pre-filtered derived event rather than raw book deltas.
- **E33-S04** — add an acceptance criterion that the chase actor's input event rate is bounded (≤ 10 Hz per §11.6 `on_book_update` throttling) and assert it in the perf test E33-Q03.
- **20-architecture.md §3.2** — Book Engine gains a `ChaseTargetTracker` component emitting the filtered target-moved event (it does not exist today; §10.5's "exclude our own size" rule currently has no owning component).

---

## B8 — Bracket / NativeSL invariant

### Current design (24 §8.8, ADR-0008 rule 2, §10.7)

Binding, non-configurable: every position opened by CandleViewer carries a native exchange-side SL. Entry orders carry attached `stopLoss` where possible; otherwise a position-level SL within a 2 s deadline (ADR-0008 says `CV_NATIVE_SL_DEADLINE_MS` default 3000 ms — *note the plan docs disagree: 24 §8.8 says 2 s, ADR-0008 says 3 s; this must be reconciled*). A watchdog scans every open position every 5 s; >10 s without a native SL raises `critical` and auto-attaches a fallback. Smarter stops may only ever **tighten**.

### Proposed statechart

The invariant is best expressed as a **per-position** parallel region (not per-order), because the invariant is about positions. This is the `protection` region of B1 promoted to its own machine at position scope:

```json
{
  "id": "position_protection",
  "type": "parallel",
  "context": {
    "account_id": null, "symbol": null, "position_qty": "0",
    "native_sl_px": null, "desired_sl_px": null,
    "sl_deadline_us": null, "naked_since_us": null, "attach_attempts": 0
  },
  "states": {
    "sl": {
      "initial": "flat",
      "states": {
        "flat": {"on": {"POSITION_OPENED": {"target": "#position_protection.sl.attaching"}}},
        "attaching": {
          "entry": ["arm_sl_deadline", "bump_attach_attempts"],
          "invoke": {"id": "att", "src": "attach_native_sl",
                     "onDone":  {"target": "#position_protection.sl.verifying"},
                     "onError": [
                       {"target": "#position_protection.sl.attaching", "reenter": true,
                        "guard": "attach_attempts_left"},
                       {"target": "#position_protection.sl.naked"}
                     ]},
          "on": {"SL_DEADLINE": {"target": "#position_protection.sl.naked"}}
        },
        "verifying": {
          "invoke": {"id": "ver", "src": "read_position_sl",
                     "onDone": [
                       {"target": "#position_protection.sl.protected", "guard": "exchange_reports_sl"},
                       {"target": "#position_protection.sl.naked"}
                     ],
                     "onError": {"target": "#position_protection.sl.naked"}}
        },
        "protected": {
          "tags": ["protected"],
          "on": {
            "TIGHTEN_SL":     {"target": "#position_protection.sl.amending",
                               "guard": "tightens_only"},
            "LOOSEN_SL":      {"target": "#position_protection.sl.amending",
                               "guard": "explicit_audited_override"},
            "WATCHDOG_MISS":  {"target": "#position_protection.sl.naked"},
            "POSITION_FLAT":  {"target": "#position_protection.sl.flat"}
          }
        },
        "amending": {
          "invoke": {"id": "am", "src": "set_trading_stop",
                     "onDone":  {"target": "#position_protection.sl.verifying"},
                     "onError": {"target": "#position_protection.sl.verifying"}},
          "on": {"*": {"actions": ["defer"]}}
        },
        "naked": {
          "tags": ["naked", "critical"],
          "entry": ["stamp_naked_since", "raise_critical_alert", "emit_naked_metric"],
          "invoke": {"id": "fb", "src": "attach_fallback_sl",
                     "onDone":  {"target": "#position_protection.sl.verifying"},
                     "onError": {"target": "#position_protection.sl.naked_unrecoverable"}},
          "on": {"POSITION_FLAT": {"target": "#position_protection.sl.flat"}}
        },
        "naked_unrecoverable": {
          "tags": ["naked", "critical"],
          "entry": ["page_owner", "consider_reduce_only_close"],
          "on": {
            "SL_OBSERVED":   {"target": "#position_protection.sl.protected"},
            "POSITION_FLAT": {"target": "#position_protection.sl.flat"}
          }
        }
      }
    },
    "watchdog": {
      "initial": "idle",
      "states": {
        "idle":     {"on": {"POSITION_OPENED": {"target": "#position_protection.watchdog.scanning"}}},
        "scanning": {
          "on": {
            "SCAN_DUE": [
              {"target": "#position_protection.watchdog.scanning", "reenter": true,
               "guard": "sl_observed", "actions": ["reset_miss_counter"]},
              {"target": "#position_protection.watchdog.scanning", "reenter": true,
               "actions": ["bump_miss_counter", "maybe_raise_watchdog_miss"]}
            ],
            "POSITION_FLAT": {"target": "#position_protection.watchdog.idle"}
          }
        }
      }
    }
  }
}
```

### Fit: **Workaround**

The structure is a genuinely good fit — a parallel region that says "this position is protected / naked" independently of order lifecycle is clearer than anything in the current plan docs, and `tags: ["naked"]` gives the UI and the metrics exporter a first-class query.

But this is the **P4 invariant**, the one ADR-0008 calls "the guarantee", and three library behaviours are hostile to it:

1. **LC-08 — a raising guard is silently `False`.** `tightens_only` is the ratchet guard. If it raises (a `None` price from a malformed message, a Decimal error), the library swallows it as `False` and the transition is simply not taken — here that fails *safe* (no amend). But `explicit_audited_override` failing to `False` also fails safe, while a guard written in the opposite polarity (`not_loosening`) would fail *open*. The polarity of every safety guard is therefore load-bearing and invisible. Rule A6 exists because of this; it must be a reviewed checklist item on this machine specifically.
2. **LC-01 — a raising action commits the transition anyway.** If `attach_native_sl`'s bookkeeping action raises after the exchange call succeeded, we would land in `verifying` with corrupt context. Mitigated by `verifying` re-reading the exchange (which it does regardless) — this machine is deliberately designed so that *every* protected claim is confirmed by an exchange read, never by local state. That design is forced by the library's error semantics, and it is the right design anyway.
3. **LC-05 — the 5 s watchdog scan and the 2/3 s attach deadline are timers.** Both go to the external scheduler. A watchdog that is itself starved by the event loop is worse than no watchdog, because it reports "protected" by silence.

Also note the plan-doc discrepancy flagged above (2 s vs 3 s deadline) — surfaced by trying to write `arm_sl_deadline` and finding two authorities.

### Changes

- **24 §8.8 / ADR-0008 rule 2** — reconcile the SL deadline to a single number and a single named config key (`CV_NATIVE_SL_DEADLINE_MS`). Currently 24 §8.8 says 2 s and ADR-0008 says 3000 ms.
- **24 §8.8** — add the position-protection statechart; add rule 6: *"protected" is only ever asserted from an exchange read, never from a local action's success.*
- **E32** (Brackets, scaled orders & native SL invariant) — add a ticket "Position-protection statechart + naked-position tags exported to metrics and WS". Add a test that the watchdog itself is liveness-monitored (a watchdog that stops scanning must alert).
- **E39-Q03 / E45-T08** — add a chaos scenario "event loop saturated for 30 s" asserting the naked-position watchdog still fires within its deadline. On the measured numbers, an in-machine timer implementation fails this.

---

---

## B9 — Rule runtime instance

### Current design (24 §11.5, §11.7, ADR-0007)

Trigger-driven, never polled (E1). One `MetricSnapshot` per evaluation (E2). `None` is false (E3). Short-circuit with full logging (E4). Deterministic child order (E5). **Per-scope instances** — a symbol-scoped rule over 3 symbols is 3 independent instances with independent `once`/cooldown state (E6). Stale-data guard (E7), evaluation timeout (E8), transactional-per-fire actions (E9), no replay of missed triggers after reconnect (E10). Safety: `once`, `cooldown_ms`, `max_fires_per_hour/day`, `kill_switch_on_error_count` → auto-disable requiring human re-arm; `simulate` → `armed` promotion gate (`min_simulation_fires` 5 / `min_simulation_hours` 24); rules paused while the private WS is down.

### The split verdict

This component must be cut in two, and the measurement is unambiguous.

**Per-tick evaluation: Not suitable.** Study 04's Budget 2 modelled the plan's own load — 2,000 market events/s × 100 rule instances = 200,000 evaluations/s required. The library delivers ~30,000/s on the bench CPU; even granting 3× for server silicon, ~90,000/s is **~2.2× short**, and the honest framing in Study 04 is 6.5× short of the full budget. Sync vs async differ by under 10 %, so switching engines does not rescue it. More fundamentally, Study 04 §2 establishes the architectural fact: throughput is a **fixed global budget shared by every interpreter in the process** (1 machine → 21,231 ev/s; 1,000 machines → 18,152 ev/s aggregate, i.e. 18.2 ev/s each). Adding rule machines does not add capacity; it divides it — and it divides it with the OMS.

**Rule lifecycle: Workaround.** Armed / triggered / cooling-down / paused / kill-switched / simulating is a genuinely stateful, safety-critical lifecycle with human re-arm gates, and it changes at human timescales, not tick timescales. That is exactly what statecharts are for.

### Proposed statechart (lifecycle only)

```json
{
  "id": "rule_instance",
  "initial": "draft",
  "context": {
    "rule_id": null, "version": 0, "scope_key": null,
    "consecutive_errors": 0, "kill_switch_at": 5,
    "fires_this_hour": 0, "fires_today": 0,
    "simulation_fires": 0, "simulation_started_us": null,
    "cooldown_until_us": null, "once_satisfied": false,
    "last_skip_reason": null
  },
  "states": {
    "draft":     {"on": {"SAVE": {"target": "#rule_instance.simulating"}}},
    "simulating": {
      "entry": ["stamp_simulation_start"],
      "on": {
        "TRIGGER":  {"actions": ["evaluate_and_record_simulated"]},
        "SIM_FIRE": {"actions": ["bump_simulation_fires"]},
        "ARM_REQUESTED": [
          {"target": "#rule_instance.armed", "guard": "promotion_gate_satisfied_and_permitted"},
          {"actions": ["reject_promotion_with_reason"]}
        ],
        "EDIT": {"target": "#rule_instance.simulating", "reenter": true,
                 "actions": ["reset_simulation_counters"]}
      }
    },
    "armed": {
      "entry": ["subscribe_triggers", "emit_armed_audit"],
      "exit":  ["unsubscribe_triggers"],
      "on": {
        "TRIGGER": [
          {"actions": ["record_skip_debounced"],  "guard": "debounce_blocked"},
          {"actions": ["record_skip_stale_data"], "guard": "data_stale"},
          {"actions": ["record_skip_limit"],      "guard": "limits_blocked"},
          {"target": "#rule_instance.evaluating"}
        ],
        "FEED_DEGRADED":   {"target": "#rule_instance.paused_degraded"},
        "KILL_SWITCH":     {"target": "#rule_instance.kill_switched"},
        "DISARM":          {"target": "#rule_instance.disarmed"},
        "EDIT":            {"target": "#rule_instance.simulating",
                            "actions": ["reset_simulation_counters"]}
      }
    },
    "evaluating": {
      "invoke": {
        "id": "eval", "src": "evaluate_condition_dag",
        "onDone": [
          {"target": "#rule_instance.pending_confirmation", "guard": "condition_true_and_requires_confirmation"},
          {"target": "#rule_instance.acting",               "guard": "condition_true"},
          {"target": "#rule_instance.armed",                "actions": ["log_no_op_with_values"]}
        ],
        "onError": [
          {"target": "#rule_instance.kill_switched", "guard": "error_budget_exhausted"},
          {"target": "#rule_instance.armed",         "actions": ["bump_consecutive_errors"]}
        ]
      },
      "on": {"*": {"actions": ["defer"]}}
    },
    "pending_confirmation": {
      "entry": ["queue_for_human_confirmation", "arm_confirmation_ttl"],
      "on": {
        "CONFIRMED":        {"target": "#rule_instance.acting"},
        "CONFIRM_TIMEOUT":  {"target": "#rule_instance.armed", "actions": ["record_skip_unconfirmed"]},
        "REJECTED":         {"target": "#rule_instance.armed", "actions": ["record_skip_rejected"]}
      }
    },
    "acting": {
      "entry": ["assert_safety_limits"],
      "invoke": {
        "id": "act", "src": "dispatch_actions_in_order",
        "onDone":  {"target": "#rule_instance.cooling_down",
                    "actions": ["record_fire", "reset_consecutive_errors"]},
        "onError": [
          {"target": "#rule_instance.kill_switched", "guard": "error_budget_exhausted",
           "actions": ["raise_critical_alert"]},
          {"target": "#rule_instance.cooling_down",
           "actions": ["record_partial_fire", "bump_consecutive_errors", "raise_partial_alert"]}
        ]
      },
      "on": {"*": {"actions": ["defer"]}}
    },
    "cooling_down": {
      "entry": ["stamp_cooldown_deadline"],
      "always": [{"target": "#rule_instance.spent", "guard": "once_satisfied"}],
      "on": {
        "COOLDOWN_DUE":  {"target": "#rule_instance.armed", "actions": ["drain_deferred"]},
        "KILL_SWITCH":   {"target": "#rule_instance.kill_switched"},
        "DISARM":        {"target": "#rule_instance.disarmed"}
      }
    },
    "paused_degraded": {
      "entry": ["emit_rules_paused_notice"],
      "on": {
        "FEED_HEALTHY": {"target": "#rule_instance.armed"},
        "KILL_SWITCH":  {"target": "#rule_instance.kill_switched"},
        "DISARM":       {"target": "#rule_instance.disarmed"}
      }
    },
    "kill_switched": {
      "tags": ["needs_human_rearm"],
      "entry": ["raise_critical_alert", "emit_kill_switch_audit"],
      "on": {"HUMAN_REARM": {"target": "#rule_instance.armed",
                             "guard": "rearm_permitted_and_elevated",
                             "actions": ["reset_consecutive_errors"]}}
    },
    "spent":    {"tags": ["once_satisfied"], "on": {"RESET_ONCE": {"target": "#rule_instance.armed"}}},
    "disarmed": {"on": {"ARM_REQUESTED": {"target": "#rule_instance.armed",
                                          "guard": "promotion_gate_satisfied_and_permitted"}}}
  }
}
```

The **evaluation itself** (`evaluate_condition_dag`) is a plain Python function over the IR and a `MetricSnapshot` — not a statechart. E2 (one snapshot per evaluation), E4 (short-circuit with full logging) and E5 (deterministic child order) are all properties of that function, and none of them benefit from statechart machinery.

### Fit: **Workaround** (lifecycle) / **Not suitable** (per-tick evaluation)

Additional concerns even for the lifecycle half:

- **LC-15 — instance count.** E6 mandates per-scope instances. 50 rules × 20 symbols = 1,000 interpreters. At ~42 KB RSS idle each (Study 04 §2) that is ~42 MB — affordable. But each one consumes from the shared 20k ev/s budget the moment it receives events, so the **trigger pre-filter must happen before the interpreter**: the rule engine indexes instances by trigger key and sends `TRIGGER` only to instances whose trigger actually fired. Study 04's recommended mitigation (pre-filter by threshold band, cutting evaluations 10–100×) is not optional; it is the architecture.
- **LC-16 — rule IR compiled to a machine is the highest-risk consumer of A5.** If we ever compile rule IR into machine JSON (tempting for conflict arbitration), an unknown target "deploys clean and fails open at runtime" (Study 05 C15) — the library validates unknown *actions* at `create_machine()` time but never validates targets, at any point. Our build-time target validator must run on every compiled rule before it is armed, and rule arming must fail closed on a validation error.
- **LC-17 — `evaluation_timeout_ms` (E8) has no library support.** There is no per-transition or per-invoke timeout. It must be implemented inside the service with `asyncio.wait_for`, and the timeout must surface as `onError`, not as a raised action.
- **Determinism is genuinely good news.** Study 05 C8/C9/C17: identical event sequences produce byte-identical state, context and action traces across 5, 10 and 15 repeated runs, including a burst-send variant racing an async invoke. E5's "same snapshot ⇒ same outcome, always (required for simulation parity)" is achievable.

### Changes

- **24 §11.5** — add a normative sentence: *"rule lifecycle is a statechart; rule evaluation is a pure function. The condition DAG is never compiled into statechart transitions."* Add E13: *trigger dispatch is pre-filtered by an index; an instance receives an event only when its own trigger fired.*
- **ADR-0007** — add to Consequences: the IR is compiled to a Python evaluator, not to a state machine, for measured throughput reasons (cite Study 04 Budget 2).
- **New ADR-0017** — "Statechart hosting and scope" recording the per-tick/lifecycle split and the global-throughput-budget fact. This is the decision most likely to be re-litigated later by someone who has not read the benchmark.
- **E35-S02** ("deterministic evaluator with snapshotting, guards and timeouts") — clarify that "guards" here are IR guards in Python, not statechart guards.
- **E35-S07** (conflict detection/arbitration) — must not be modelled as cross-machine `always` racing; arbitration is a deterministic sort in Python.
- **E35-Q04** (perf benchmarks) — add the explicit assertion that rule evaluation throughput is measured **with 500 order machines resident**, since the budget is shared.

---

## B10 — Alert lifecycle

### Current design (E40)

Alert definition → evaluation with gating and storm suppression → fired → delivery (toast / webhook with HMAC / notification centre) → acknowledged / resolved / expired. `T03` server-side evaluator with gating and storm suppression; `T04` delivery dispatcher with a deliveries API and outbox topics; `S03` HMAC-signed webhooks with allow-listed egress.

### Proposed statechart

```json
{
  "id": "alert",
  "initial": "armed",
  "context": {
    "alert_id": null, "severity": "info", "storm_count": 0,
    "suppressed_until_us": null, "delivery_attempts": 0,
    "max_delivery_attempts": 5, "channels": [], "delivered_channels": []
  },
  "states": {
    "armed": {
      "on": {
        "CONDITION_MET": [
          {"target": "#alert.suppressed", "guard": "in_storm_window"},
          {"target": "#alert.firing"}
        ],
        "DISABLE": {"target": "#alert.disabled"}
      }
    },
    "suppressed": {
      "entry": ["bump_storm_count", "emit_suppression_metric"],
      "on": {"SUPPRESSION_EXPIRED": {"target": "#alert.armed"},
             "DISABLE": {"target": "#alert.disabled"}}
    },
    "firing": {
      "entry": ["persist_fired_row", "stamp_storm_window"],
      "invoke": {
        "id": "deliver", "src": "dispatch_to_channels",
        "onDone": [
          {"target": "#alert.delivered",         "guard": "all_channels_ok"},
          {"target": "#alert.partially_delivered"}
        ],
        "onError": [
          {"target": "#alert.retrying", "guard": "delivery_attempts_left"},
          {"target": "#alert.delivery_failed"}
        ]
      }
    },
    "retrying": {
      "entry": ["bump_delivery_attempts", "schedule_backoff_deadline"],
      "on": {"RETRY_DUE": {"target": "#alert.firing"},
             "ACK":       {"target": "#alert.acknowledged"}}
    },
    "delivered":           {"on": {"ACK": {"target": "#alert.acknowledged"},
                                   "RESOLVE": {"target": "#alert.resolved"}}},
    "partially_delivered": {"tags": ["degraded"],
                            "on": {"ACK": {"target": "#alert.acknowledged"},
                                   "RESOLVE": {"target": "#alert.resolved"}}},
    "delivery_failed":     {"tags": ["degraded"], "entry": ["emit_delivery_failure_metric"],
                            "on": {"ACK": {"target": "#alert.acknowledged"}}},
    "acknowledged":        {"on": {"RESOLVE": {"target": "#alert.resolved"}}},
    "resolved":            {"type": "final", "tags": ["terminal"]},
    "disabled":            {"on": {"ENABLE": {"target": "#alert.armed"}}}
  }
}
```

### Fit: **Excellent**

Everything this component needs is in the library's strong set, and nothing it needs is in the weak set:

- Low event rate (alerts fire at human frequencies), so the throughput ceiling is irrelevant.
- Delivery retry is a service invoke with `onError` — the invoke lifecycle is 14/14 in Study 05, including error payloads carrying the exception object and cancellation not producing stale `done` events.
- Storm suppression windows and retry backoff are the one place where in-machine `after` would *almost* be acceptable (seconds of lateness on an alert-suppression window is tolerable) — but for consistency and restore-survivability they still go to the external scheduler.
- No financial correctness depends on an action not raising; a faulted alert action degrades to `delivery_failed`, which is a visible state.

### Changes

- **E40-T03/T04** — adopt this chart; it adds `partially_delivered` and `delivery_failed` as distinct states, which the current ticket descriptions do not distinguish (they matter for the deliveries API).
- **24** — the plan docs have no Alert schema section at all; alerts live only in E40. Add a §13.8 or a new section defining `Alert`/`AlertDelivery` models with this lifecycle, since every other stateful entity is specified in 24.

---

## B11 — RecordingSession

### Current design (24 §13.1)

`RecordingState.state ∈ idle | starting | recording | degraded | stopping | stopped | error`, with `streams_healthy` per stream, gap counting, and the auto-record lifecycle: chart-open adds a reason and starts within 2 s; last chart closed removes the reason and, if `reasons` becomes empty, recording lingers `linger_minutes` (default 15) before stopping; an open position **cannot** stop recording.

### Proposed statechart

```json
{
  "id": "recording",
  "initial": "idle",
  "context": {
    "symbol": null, "reasons": [], "streams": [], "streams_healthy": {},
    "gap_count_24h": 0, "linger_until_us": null, "error": null
  },
  "states": {
    "idle": {
      "on": {"REASON_ADDED": {"target": "#recording.starting", "actions": ["add_reason"]}}
    },
    "starting": {
      "invoke": {"id": "sub", "src": "subscribe_streams",
                 "onDone":  {"target": "#recording.recording"},
                 "onError": {"target": "#recording.error", "actions": ["record_error"]}},
      "on": {"REASON_ADDED": {"actions": ["add_reason"]},
             "REASON_REMOVED": {"actions": ["remove_reason"]}}
    },
    "recording": {
      "entry": ["cancel_linger", "emit_recording_metric"],
      "on": {
        "STREAM_UNHEALTHY": {"target": "#recording.degraded", "actions": ["mark_stream_unhealthy"]},
        "REASON_ADDED":     {"actions": ["add_reason"]},
        "REASON_REMOVED": [
          {"actions": ["remove_reason"], "guard": "reasons_remain"},
          {"target": "#recording.lingering", "actions": ["remove_reason"]}
        ],
        "GAP_DETECTED": {"actions": ["bump_gap_count", "emit_gap_metric"]}
      }
    },
    "degraded": {
      "tags": ["degraded"],
      "entry": ["raise_degraded_alert"],
      "on": {
        "STREAM_HEALTHY": [
          {"target": "#recording.recording", "guard": "all_streams_healthy",
           "actions": ["mark_stream_healthy"]},
          {"actions": ["mark_stream_healthy"]}
        ],
        "REASON_REMOVED": [
          {"actions": ["remove_reason"], "guard": "reasons_remain"},
          {"target": "#recording.lingering", "actions": ["remove_reason"]}
        ]
      }
    },
    "lingering": {
      "entry": ["schedule_linger_deadline"],
      "on": {
        "REASON_ADDED": {"target": "#recording.recording", "actions": ["add_reason"]},
        "LINGER_DUE": [
          {"target": "#recording.recording", "guard": "position_open_for_symbol"},
          {"target": "#recording.stopping"}
        ]
      }
    },
    "stopping": {
      "invoke": {"id": "unsub", "src": "unsubscribe_and_flush",
                 "onDone":  {"target": "#recording.stopped"},
                 "onError": {"target": "#recording.error", "actions": ["record_error"]}}
    },
    "stopped": {"on": {"REASON_ADDED": {"target": "#recording.starting", "actions": ["add_reason"]}}},
    "error":   {"tags": ["error"], "on": {"RETRY": {"target": "#recording.starting"}}}
  }
}
```

### Fit: **Excellent**

The plan doc already specifies a 7-state enum; the statechart adds only `lingering` (today a prose rule with no state) and makes the "position open blocks stop" invariant a guard rather than a scattered check. Event rate is per-symbol lifecycle events (chart opened/closed, stream health), i.e. single-digit per minute. One interpreter per recorded symbol — dozens at most.

The only note: `linger_minutes` is 15 minutes, far too long for an in-machine `after` to be trusted across a restart. External scheduler, deadline in context, re-armed on restore (A2/A7).

### Changes

- **24 §13.1** — add `lingering` to the `RecordingState.state` literal (it is currently missing, so the 15-minute grace period is unrepresentable in the model that the admin UI and API serialise).
- **E16** — adopt; add the `lingering` state to the recorder status API and the admin panel.

---

## B12 — ReplaySession

### Current design (24 §13.7)

`ReplaySession.state ∈ created | buffering | playing | paused | finished | error`, with cursor, speed (0 = step mode, 0.1–100, −1 = as fast as possible), loop, bookmarks, optional paper account. Seek is a 5-step algorithm bounded at ≤2 s. Playback preserves inter-event deltas scaled by speed; backpressure slows the clock rather than dropping events. `source="replay"` on every event so the OMS can structurally refuse to route replay events to a live account.

### Proposed statechart

```json
{
  "id": "replay",
  "initial": "created",
  "context": {
    "session_id": null, "symbols": [], "range_start": 0, "range_end": 0,
    "cursor": 0, "speed": 1.0, "loop": false,
    "paper_account_id": null, "error": null, "coverage_gaps": []
  },
  "states": {
    "created": {
      "on": {"PREPARE": {"target": "#replay.buffering"}, "DESTROY": {"target": "#replay.destroyed"}}
    },
    "buffering": {
      "invoke": {"id": "seek", "src": "seek_and_prime",
                 "onDone":  {"target": "#replay.paused", "actions": ["set_cursor", "record_coverage"]},
                 "onError": {"target": "#replay.error",  "actions": ["record_error"]}},
      "on": {"CANCEL": {"target": "#replay.paused"}, "*": {"actions": ["defer"]}}
    },
    "paused": {
      "entry": ["drain_deferred"],
      "on": {
        "PLAY":    {"target": "#replay.playing"},
        "STEP":    {"target": "#replay.stepping"},
        "SEEK":    {"target": "#replay.buffering"},
        "DESTROY": {"target": "#replay.destroyed"}
      }
    },
    "playing": {
      "entry": ["start_clock"],
      "exit":  ["stop_clock"],
      "on": {
        "PAUSE":       {"target": "#replay.paused"},
        "SEEK":        {"target": "#replay.buffering"},
        "SET_SPEED":   {"actions": ["set_speed"]},
        "CONSUMER_SLOW": {"actions": ["slow_clock"]},
        "RANGE_END": [
          {"target": "#replay.buffering", "guard": "loop_enabled", "actions": ["reset_cursor_to_start"]},
          {"target": "#replay.finished"}
        ],
        "SOURCE_ERROR": {"target": "#replay.error", "actions": ["record_error"]}
      }
    },
    "stepping": {
      "invoke": {"id": "step", "src": "emit_one_step",
                 "onDone":  {"target": "#replay.paused", "actions": ["set_cursor"]},
                 "onError": {"target": "#replay.error",  "actions": ["record_error"]}}
    },
    "finished":  {"on": {"SEEK": {"target": "#replay.buffering"}, "DESTROY": {"target": "#replay.destroyed"}}},
    "error":     {"tags": ["error"], "on": {"SEEK": {"target": "#replay.buffering"},
                                            "DESTROY": {"target": "#replay.destroyed"}}},
    "destroyed": {"type": "final", "tags": ["terminal"]}
  }
}
```

### Fit: **Good**

The session **control** lifecycle is a clean fit: few states, human-driven transitions, a long-running `seek_and_prime` invoke whose cancellation semantics the library handles correctly (Study 05 B4/B5, Study 04 g5 — `stop()` returned in 0.15 ms without blocking on a 10 s sleep, `CancelledError` delivered, `finally` honoured).

Two boundaries must be respected:

1. **The replay clock is not the statechart.** `speed` ranges to 100× and step mode needs single-event precision. The `ReplayClock` (20 §3.9) stays a plain monotonic pacer; the statechart only tells it to start, stop and rescale. Putting event emission inside the machine would put the entire replayed market-data stream into the shared 20k ev/s budget (see B14).
2. **Determinism for replay is real, and the risk is elsewhere.** Study 05 §3 is explicit and worth quoting in the plan docs: *"the risk to replay is not the interpreter — it is §2.6, where the live machine and the replayed machine could see different event sets if timing differs."* In other words, LC-03 (silent event drops in transient states) is simultaneously an OMS bug **and** a replay-fidelity bug: a fill dropped live but not in replay (or vice versa) breaks the golden-file guarantee in 24 §13.7. Fixing the deferral problem fixes replay fidelity too.

### Changes

- **24 §13.7** — add a determinism clause (5): *"machine-hosted components must not silently drop events; any event with no handler in the current state is buffered and drained, because a live/replay divergence in delivered events breaks guarantee (2)."*
- **E26-T06** ("replay determinism and live-parity harness as a required CI check") — the harness must diff *delivered event sets* per machine, not only derived outputs. Otherwise a dropped fill that happens to be dropped in both runs passes CI while being wrong in both.
- **E26-T03** (ReplayClock and Injector) — confirm the clock is independent of any interpreter.

---

## B13 — ExchangeConnection (WS reconnect / resync)

### Current design (20 §3.1, §10.4; 24 §14.2–14.3)

`ConnectionManager` owns one task per socket; auth for private sockets; heartbeat 20 s ping / 10 s pong deadline from a **dedicated task**; `ReconnectPolicy` exponential backoff 0.5 s→30 s with full jitter under a ≤500 conns/5 min/IP budget; `SubscriptionPlanner` packs ≤10 topics per request; on a book sequence gap, drop-and-resubscribe (no checksum available). Book state machine: `INIT → SNAPSHOT_PENDING → LIVE → DESYNCED → SNAPSHOT_PENDING`.

### Proposed statechart

```json
{
  "id": "ws_conn",
  "initial": "disconnected",
  "context": {
    "env": null, "kind": "public", "account_id": null,
    "attempt": 0, "backoff_ms": 500, "max_backoff_ms": 30000,
    "conn_budget_remaining": 500, "last_pong_us": 0,
    "pending_topics": [], "subscribed_topics": []
  },
  "states": {
    "disconnected": {
      "on": {"CONNECT": [
        {"target": "#ws_conn.budget_blocked", "guard": "connection_budget_exhausted"},
        {"target": "#ws_conn.connecting"}
      ]}
    },
    "budget_blocked": {
      "tags": ["degraded"],
      "entry": ["raise_conn_budget_alert", "schedule_budget_recheck"],
      "on": {"BUDGET_RECHECK": {"target": "#ws_conn.disconnected"}}
    },
    "connecting": {
      "entry": ["bump_attempt"],
      "invoke": {
        "id": "dial", "src": "open_socket",
        "onDone": [
          {"target": "#ws_conn.authenticating", "guard": "is_private"},
          {"target": "#ws_conn.subscribing"}
        ],
        "onError": {"target": "#ws_conn.backing_off", "actions": ["record_conn_error"]}
      }
    },
    "authenticating": {
      "invoke": {"id": "auth", "src": "ws_auth",
                 "onDone":  {"target": "#ws_conn.subscribing"},
                 "onError": {"target": "#ws_conn.backing_off", "actions": ["record_auth_error"]}}
    },
    "subscribing": {
      "invoke": {"id": "sub", "src": "subscribe_in_batches",
                 "onDone":  {"target": "#ws_conn.live", "actions": ["record_subscribed"]},
                 "onError": {"target": "#ws_conn.backing_off", "actions": ["record_sub_error"]}},
      "on": {"*": {"actions": ["defer"]}}
    },
    "live": {
      "entry": ["reset_backoff", "drain_deferred", "emit_feed_healthy", "arm_pong_deadline"],
      "on": {
        "PONG":            {"actions": ["stamp_pong", "rearm_pong_deadline"]},
        "PONG_DEADLINE":   {"target": "#ws_conn.backing_off", "actions": ["record_pong_timeout"]},
        "SOCKET_CLOSED":   {"target": "#ws_conn.backing_off"},
        "TOPIC_STALE":     {"target": "#ws_conn.backing_off", "actions": ["record_staleness"]},
        "TOPICS_CHANGED":  {"target": "#ws_conn.subscribing", "actions": ["set_pending_topics"]},
        "SHUTDOWN":        {"target": "#ws_conn.closing"}
      }
    },
    "backing_off": {
      "entry": ["compute_jittered_backoff", "emit_feed_degraded", "schedule_backoff_deadline",
                "notify_dependents_degraded"],
      "on": {
        "BACKOFF_DUE": {"target": "#ws_conn.connecting"},
        "SHUTDOWN":    {"target": "#ws_conn.closing"}
      }
    },
    "closing": {
      "invoke": {"id": "cl", "src": "close_socket",
                 "onDone":  {"target": "#ws_conn.closed"},
                 "onError": {"target": "#ws_conn.closed"}}
    },
    "closed": {"type": "final", "tags": ["terminal"]}
  }
}
```

The separate **book resync** FSM (`INIT → SNAPSHOT_PENDING → LIVE → DESYNCED`) is a second, per-symbol machine driven by `SequenceTracker` gaps — see B14.

### Fit: **Good**

Connection lifecycle is a textbook statechart and the event rate is trivial (connects, pongs, gaps). The library's invoke cancellation quality matters here and it is proven: a `SHUTDOWN` during `connecting` cancels the dial cleanly with `finally` honoured.

Concerns:

1. **LC-05 again — the pong deadline is 10 s and the backoff is 0.5–30 s.** These are exactly the scale where in-machine `after` *seems* fine on idle (+6–16 ms) but is not: under load the timer fires ~2.2 s late, which turns a 10 s pong deadline into ~12 s, and more importantly the pong deadline is a **liveness detector** — it must not be starved by the very backlog that indicates trouble. External scheduler, no exceptions.
2. **LC-18 — cross-thread sends.** If any part of ingestion ever runs off the main loop (20 §4.1 forbids implicit threads, but `run_in_executor` is explicitly allowed for blocking work), a bare `interp.send()` from that thread is **silently lost** — no exception, the coroutine is never awaited (Study 04 g6). And cross-thread delivery via `run_coroutine_threadsafe` costs 336 µs/event vs 33 µs in-loop, a 10× penalty. The `SafeInterpreter` wrapper (A8) plus a lint ban on bare `.send(` is the mitigation.
3. **Connection-budget guard must be deny-polarity** (A6): `connection_budget_exhausted` raising must mean "blocked", because exceeding Bybit's 500 conns/5 min/IP gets the IP banned.

### Changes

- **20 §3.1** — add the connection statechart; add `budget_blocked` as an explicit state (today the budget guard is prose in `ReconnectPolicy`).
- **20 §10.4** — the reconnect/resync sequence diagram should reference the two machines (connection, book) and the `notify_dependents_degraded` fan-out that pauses armed rules (24 §11.7 "Disconnect guard").
- **E08** (Bybit adapter & ingestion skeleton) — adopt; add the `SafeInterpreter` wrapper as a shared utility ticket since every module needs it.

---

## B14 — IngestionPipeline per symbol

### Current design (20 §3.1, §3.2, §4.2)

Per-socket reader task → bounded `asyncio.Queue` (4096) → `Normalizer` (≤15 µs/trade, ≤60 µs/200-level book delta) → `SequenceTracker` → bus. Book engine applies deltas into sorted arrays. Backpressure: trades and executions are **never** dropped (await, apply real backpressure); book deltas are never skipped — instead the book is invalidated and re-snapshotted.

### The split verdict

**Data path: Not suitable.** This is the clearest "no" in the document. The plan's own load model is 2,000+ market events/s per busy symbol across a few dozen symbols. The library's *entire process* budget is ~20–30k ev/s shared across all interpreters (Study 04 §2), and each transition costs ~33 µs against a normalizer measured at 15 µs. Routing market data through interpreters would consume the whole budget on ingestion and leave nothing for the OMS — while making every tick 2–3× more expensive than the plain function that does the actual work. The ADR-0004 principle "zero serialisation cost on the market-data hot path" and the §4.2 rule "trades are never dropped" both argue the same way; LC-03 makes the second one impossible to guarantee inside a machine anyway.

**Book health FSM: Good.** `INIT → SNAPSHOT_PENDING → LIVE → DESYNCED → SNAPSHOT_PENDING` is per-symbol, transitions only on gaps and snapshots (rare), and gates whether derived engines may consume. That is a real invariant worth making explicit.

```json
{
  "id": "book",
  "initial": "init",
  "context": {
    "symbol": null, "last_seq": 0, "snapshot_seq": 0,
    "buffered_deltas": [], "resync_count": 0, "desynced_since_us": null
  },
  "states": {
    "init": {"on": {"SUBSCRIBE": {"target": "#book.snapshot_pending"}}},
    "snapshot_pending": {
      "entry": ["clear_buffer", "request_snapshot"],
      "on": {
        "SNAPSHOT": {"target": "#book.live",
                     "actions": ["install_snapshot", "replay_buffered_deltas_after_seq"]},
        "DELTA":    {"actions": ["buffer_delta"]},
        "SNAPSHOT_TIMEOUT": {"target": "#book.snapshot_pending", "reenter": true,
                             "actions": ["bump_resync_count"]}
      }
    },
    "live": {
      "tags": ["consumable"],
      "entry": ["emit_book_live"],
      "on": {
        "DELTA":        {"actions": ["apply_delta"]},
        "SEQUENCE_GAP": {"target": "#book.desynced", "actions": ["stamp_desync"]},
        "UNSUBSCRIBE":  {"target": "#book.init"}
      }
    },
    "desynced": {
      "tags": ["not_consumable"],
      "entry": ["emit_book_desynced", "bump_resync_count", "emit_resync_metric"],
      "always": {"target": "#book.snapshot_pending"}
    }
  }
}
```

Note: `DELTA` in `live` is an **internal** transition (actions only, no target) — deliberately, because the ~2k/s delta rate must not incur entry/exit work. But this exposes a real tension: even an internal transition costs ~33 µs of interpreter overhead versus ~60 µs for the actual delta application, i.e. a ~55 % tax on the hot path, and 2k/s × 24 symbols = 48k ev/s, already over the whole process budget.

**Therefore the recommendation is stricter than the chart implies: deltas must NOT be sent to the interpreter at all.** The book engine applies deltas directly in Python and sends the machine only `SNAPSHOT`, `SEQUENCE_GAP`, `SUBSCRIBE`, `UNSUBSCRIBE` — four event types at single-digit frequency. The chart above is shown with `DELTA` handlers to illustrate the tempting design and to mark it as rejected; the shipped machine omits them and `buffer_delta`/`apply_delta` live in the book engine, which queries `machine.matches("live")` (or the `consumable` tag) before publishing.

### Fit: **Not suitable** (data path) / **Good** (health FSM with the data path excluded)

### Changes

- **20 §3.2** — document the book health FSM and state explicitly that **deltas never enter the state machine**; the machine is consulted, not driven, by the data path. This is a general principle worth stating once: *statecharts gate the hot path; they are not in it.*
- **20 §4.1** — add to the rules: **(6) No market-data event is delivered to a statechart interpreter. Statecharts receive control and lifecycle events only.** Lint-checkable by topic prefix.
- **E08 / E17** — no scope change; add the principle to the module README.

---

## B15 — PaperMatcher

### Current design (24 §12)

Book-walk market fills (one `Execution` per level consumed), crossing-limit handling, resting-limit queue-position modelling (`queue_ahead` decremented by same-side prints, pro-rata reduction on cancels, re-capped on price return), latency modelling (`latency_submit_ms` 60, `latency_cancel_ms` 60, `latency_market_data_ms` 30), fee computation, funding at `next_funding_time`, tiered margin and liquidation.

### Fit: **Not suitable**

Not because it is unimportant, but because none of it is *statechart-shaped*:

- The core is **arithmetic over the book**, executed per trade print. In replay at `speed=-1` ("as fast as consumers accept", used for rule backtests) this is the single hottest loop in the system. A 33 µs/transition tax on a computation measured in single-digit microseconds is a 5–10× slowdown of backtesting.
- The queue-position model is a numeric estimator (`queue_ahead *= new_size/old_size`), which the plan doc rightly calls "the single most important honesty knob in the whole simulator". It has no states — it has a number.
- The *order* being matched is already a B1 statechart. Adding a second machine for the matcher would mean two machines racing over one order's fill accounting, which is strictly worse than one.
- The latency model needs deterministic virtual time. The library has **no clock injection and no virtual time** (Study 01 §13.5): there is no `SimulatedClock`, and `helpers.wait_for` polls real time. Making `latency_submit_ms` deterministic inside a machine is therefore impossible without building our own clock — at which point the machine is contributing nothing.

**What *is* worth a statechart here:** the paper *account* lifecycle (`active → margin_call → liquidating → liquidated`) — a small, rare-transition, safety-shaped FSM. That is the liquidation path in §12.4, and making it explicit is worthwhile.

```json
{
  "id": "paper_account",
  "initial": "active",
  "context": {"account_id": null, "equity": "0", "maintenance_margin": "0", "liq_price": null},
  "states": {
    "active": {
      "on": {"MARK_UPDATE": [
        {"target": "#paper_account.liquidating", "guard": "mark_crossed_liq_price"},
        {"target": "#paper_account.margin_call", "guard": "below_maintenance_margin"}
      ]}
    },
    "margin_call": {
      "tags": ["warning"],
      "entry": ["emit_margin_warning"],
      "on": {"MARK_UPDATE": [
        {"target": "#paper_account.liquidating", "guard": "mark_crossed_liq_price"},
        {"target": "#paper_account.active",      "guard": "above_maintenance_margin"}
      ]}
    },
    "liquidating": {
      "entry": ["apply_liquidation_haircut", "write_liquidation_journal"],
      "always": {"target": "#paper_account.liquidated"}
    },
    "liquidated": {"type": "final", "tags": ["terminal"]}
  }
}
```

Even here, `MARK_UPDATE` is a per-tick event, so the same rule as B14 applies: the matcher evaluates the two guards in plain Python and sends the machine an event **only when the answer changes**. Edge-triggered, not level-triggered.

### Changes

- **24 §12** — add a normative note that the fill model, queue estimator and fee/funding accounting are plain deterministic functions and are deliberately not statecharts; add the paper-account lifecycle FSM to §12.4.
- **E38** (Paper trading & demo/live parity) — add "paper account liquidation FSM" as a small ticket; note the edge-triggered requirement.

---

## B16 — AuthSession / step-up

### Current design (24 §15.1, §15.3)

`Session` with `expires_at` (12 h absolute), `idle_expires_at` (30 min idle), `refresh_expires_at` (7 d), `mfa_satisfied`, `elevated_until` (step-up window, 15 min), `revoked_at`. MFA mandatory for owner/manager. Revocation is immediate, checked per request. Step-up (re-enter MFA via `POST /auth/step-up`) is required for: enabling live trading, adding/rotating an API key, editing a risk cap or profile, arming a live rule, assigning roles, purging recorded data, exporting audit, restoring a backup, clearing a risk lockout, panic-flatten-all. Login lockout after 5 failures / 15 min.

### Proposed statechart

```json
{
  "id": "session",
  "type": "parallel",
  "context": {
    "session_id": null, "user_id": null,
    "expires_at_us": 0, "idle_expires_at_us": 0, "refresh_expires_at_us": 0,
    "elevated_until_us": null, "mfa_satisfied": false, "revoke_reason": null
  },
  "states": {
    "auth": {
      "initial": "pending_mfa",
      "states": {
        "pending_mfa": {
          "on": {
            "MFA_OK":     {"target": "#session.auth.active", "actions": ["mark_mfa_satisfied"]},
            "MFA_FAILED": [
              {"target": "#session.auth.revoked", "guard": "mfa_attempts_exhausted",
               "actions": ["set_revoke_locked"]},
              {"actions": ["bump_mfa_attempts", "audit_mfa_failed"]}
            ],
            "MFA_TIMEOUT": {"target": "#session.auth.revoked", "actions": ["set_revoke_timeout"]}
          }
        },
        "active": {
          "entry": ["stamp_idle_deadline", "audit_login"],
          "on": {
            "REQUEST":        {"target": "#session.auth.active", "reenter": true,
                               "actions": ["stamp_idle_deadline"]},
            "IDLE_DEADLINE":  {"target": "#session.auth.revoked", "actions": ["set_revoke_idle"]},
            "ABSOLUTE_DEADLINE": {"target": "#session.auth.revoked", "actions": ["set_revoke_expired"]},
            "REVOKE":         {"target": "#session.auth.revoked", "actions": ["set_revoke_admin"]},
            "LOGOUT":         {"target": "#session.auth.revoked", "actions": ["set_revoke_logout"]}
          }
        },
        "revoked": {"type": "final", "tags": ["terminal"], "entry": ["audit_session_revoked",
                                                                     "broadcast_revocation"]}
      }
    },
    "elevation": {
      "initial": "normal",
      "states": {
        "normal": {
          "tags": ["not_elevated"],
          "on": {"STEP_UP_OK": {"target": "#session.elevation.elevated",
                                "actions": ["stamp_elevated_until", "audit_step_up"]},
                 "STEP_UP_FAILED": {"actions": ["audit_step_up_failed"]}}
        },
        "elevated": {
          "tags": ["elevated"],
          "entry": ["schedule_elevation_deadline"],
          "on": {
            "ELEVATION_DEADLINE": {"target": "#session.elevation.normal", "actions": ["clear_elevated"]},
            "STEP_UP_OK":         {"target": "#session.elevation.elevated", "reenter": true,
                                   "actions": ["stamp_elevated_until"]},
            "REVOKE":             {"target": "#session.elevation.normal", "actions": ["clear_elevated"]}
          }
        }
      }
    }
  }
}
```

### Fit: **Good**

The two-region split is a real modelling win: elevation is genuinely orthogonal to authentication, and the current model expresses it as a nullable timestamp that every call site must remember to check. `tags: ["elevated"]` makes the 4-tuple authorization check (24 §15.2) able to ask the machine rather than compare clocks.

Concerns:

1. **`REQUEST` is a per-HTTP-request event.** With single-digit concurrent users this is fine (tens of events/s), but the `active` self-transition with `reenter: true` runs `entry` each time, which is the point (idle-deadline refresh) — and is exactly the transition that would silently do nothing without `reenter` (LC-04/A4). If this were a high-traffic service it would belong outside the machine; at CandleViewer's scale it is fine. **Documented threshold: if concurrent sessions ever exceed ~100, move idle tracking out of the machine.**
2. **Revocation must be immediate and is checked per request** (24 §15.1). The machine is in-process; a revocation issued on another process/worker would not reach it. With ADR-0004's single-process monolith this is currently safe, but it becomes a correctness bug the day the designated first split (ingestion vs OMS+gateway) happens. Record it now: **session machines must live in exactly one process, or revocation must be checked against Postgres rather than the machine.**
3. **LC-05** — idle (30 min), absolute (12 h) and elevation (15 min) deadlines all go to the external scheduler, and all are re-armed from context on restore. A 12-hour `after` would not survive a restart and would silently extend a session forever.

### Changes

- **24 §15.1** — add the two-region session statechart; state that `elevated_until` is derived from the elevation region rather than being an independent field two subsystems can disagree about.
- **E09** (Auth, sessions, 2FA & RBAC) — adopt; add the explicit note about single-process ownership of session machines and the ~100-session threshold.

---

## B17 — LiveEnablement gate

### Current design (E44; 24 §11.5 E12, §15.3)

Live trading is an evidence-bound flag write: pen-test complete (R4), key-permission audit passed, environment separation verified, step-up authentication, per-manager eligibility grant, confirmation dialog, high-severity audit entry. `scope.environments` defaults to `["demo"]`; adding `"live"` requires `rules.arm_live`. Environment is a typed first-class setting with a fail-fast startup self-check (E44-T01).

### Proposed statechart

```json
{
  "id": "live_gate",
  "initial": "locked",
  "context": {
    "evidence": {
      "pentest_passed": false, "key_audit_passed": false,
      "env_separation_verified": false, "runbooks_signed": false
    },
    "enabled_by": null, "enabled_at_us": null, "disable_reason": null,
    "eligible_user_ids": []
  },
  "states": {
    "locked": {
      "tags": ["live_blocked"],
      "on": {
        "EVIDENCE_RECORDED": [
          {"target": "#live_gate.eligible", "guard": "all_evidence_present",
           "actions": ["record_evidence"]},
          {"actions": ["record_evidence"]}
        ]
      }
    },
    "eligible": {
      "tags": ["live_blocked"],
      "on": {
        "EVIDENCE_INVALIDATED": {"target": "#live_gate.locked", "actions": ["clear_evidence_item"]},
        "ENABLE_REQUESTED": [
          {"target": "#live_gate.enabled",
           "guard": "owner_and_elevated_and_evidence_still_valid",
           "actions": ["record_enable", "audit_live_enabled"]},
          {"actions": ["audit_enable_denied"]}
        ]
      }
    },
    "enabled": {
      "tags": ["live_allowed"],
      "entry": ["broadcast_live_enabled", "enable_live_visual_language"],
      "on": {
        "DISABLE_REQUESTED": {"target": "#live_gate.eligible",
                              "guard": "owner_and_elevated",
                              "actions": ["record_disable", "audit_live_disabled"]},
        "EVIDENCE_INVALIDATED": {"target": "#live_gate.locked",
                                 "actions": ["clear_evidence_item", "raise_critical_alert"]},
        "EMERGENCY_DISABLE":  {"target": "#live_gate.locked",
                               "actions": ["record_disable", "raise_critical_alert"]}
      }
    }
  }
}
```

### Fit: **Excellent**

This is the ideal statechart shape: three states, transitions only on deliberate human/administrative events, guards that encode policy, and a `tags`-based query (`live_allowed`) that every order-path check can consult. Transition frequency is measured in events per *year*. None of the library's weaknesses apply: no timers, no hot path, no actors, no invokes.

One item with teeth, and it is worth stating starkly: **the guards on this machine are the last line before real money.** Per A6/LC-08, a raising guard evaluates to `False`. Here that direction is safe: a broken `owner_and_elevated_and_evidence_still_valid` guard blocks enabling. But `EVIDENCE_INVALIDATED` is *not* guarded, deliberately — invalidation must never be blockable by a guard failure. That asymmetry (permissive actions guarded, restrictive actions unguarded) should be the house pattern for every safety gate in the system, and it is a pattern the library's error semantics force on us rather than one we chose.

### Changes

- **E44-T04** ("live_trading gate: evidence-bound flag write and gate evaluation API") — adopt this chart directly; it clarifies that `eligible` (evidence complete, not yet enabled) is a distinct state from `locked`, which the ticket currently conflates.
- **24 §16.2** — the `live_trading` feature flag becomes a projection of this machine's state, not an independently writable boolean.

---

## B18 — KillSwitch

### Current design (24 §11.7, 20 §4.3, ADR-0008 rule 8, E39-S03)

Global and scoped (per manager) freeze over REST with WS propagation. Blocks new orders, optionally cancels working orders and flattens. Enforced server-side in the `Validator`, before any adapter call. **Bypasses admission control entirely** and drains from the `critical` bucket across all accounts in parallel; `entry` and `poll` drains are cancelled first. Step-up required (`killswitch:write`).

### Proposed statechart

```json
{
  "id": "kill_switch",
  "initial": "clear",
  "context": {
    "scope": "global", "engaged_by": null, "engaged_at_us": null,
    "reason": null, "cancel_working": false, "flatten": false,
    "accounts_flat": 0, "accounts_total": 0
  },
  "states": {
    "clear": {
      "tags": ["trading_allowed"],
      "on": {"ENGAGE": {"target": "#kill_switch.engaging",
                        "actions": ["record_engagement", "audit_kill_switch"]}}
    },
    "engaging": {
      "tags": ["trading_blocked"],
      "entry": ["block_new_orders_immediately", "cancel_entry_and_poll_drains",
                "broadcast_kill_switch"],
      "always": [
        {"target": "#kill_switch.cancelling", "guard": "cancel_working_requested"},
        {"target": "#kill_switch.engaged"}
      ]
    },
    "cancelling": {
      "tags": ["trading_blocked"],
      "invoke": {"id": "cx", "src": "cancel_all_working_orders",
                 "onDone": [
                   {"target": "#kill_switch.flattening", "guard": "flatten_requested"},
                   {"target": "#kill_switch.engaged"}
                 ],
                 "onError": {"target": "#kill_switch.engaged",
                             "actions": ["raise_critical_alert"]}}
    },
    "flattening": {
      "tags": ["trading_blocked"],
      "invoke": {"id": "fl", "src": "flatten_all_positions",
                 "onDone": [
                   {"target": "#kill_switch.engaged", "guard": "all_accounts_flat"},
                   {"target": "#kill_switch.engaged_incomplete"}
                 ],
                 "onError": {"target": "#kill_switch.engaged_incomplete",
                             "actions": ["raise_critical_alert"]}}
    },
    "engaged": {
      "tags": ["trading_blocked"],
      "on": {"RELEASE": {"target": "#kill_switch.clear",
                         "guard": "owner_and_elevated",
                         "actions": ["audit_kill_switch_released"]}}
    },
    "engaged_incomplete": {
      "tags": ["trading_blocked", "critical"],
      "entry": ["page_owner", "emit_incomplete_metric"],
      "on": {
        "RETRY_FLATTEN": {"target": "#kill_switch.flattening"},
        "RELEASE":       {"target": "#kill_switch.clear",
                          "guard": "owner_and_elevated_and_acknowledged_residual"}
      }
    }
  }
}
```

### Fit: **Good**

Structurally ideal — and one design decision is non-negotiable and is forced by the library.

**LC-09 — the kill switch must not depend on the event queue.** `send()` is `await queue.put(...)`: the caller cannot await the resulting transition, and the event is processed whenever the single consumer gets to it. Study 04 Budget 1 measured **65 ms p50 / 95 ms p95 queueing delay per event** with 500 busy order machines — so "engage the kill switch" could sit behind a backlog for ~100 ms+, and under genuine saturation (the scenario where you press the kill switch) far longer: §3 measured ~2.2 s of queueing latency at 500 busy interpreters.

Therefore `block_new_orders_immediately` must be a **synchronous flag write outside the machine**, checked by the `Validator` directly, executed by the REST handler *before* it sends `ENGAGE` to the machine. The machine then drives the orderly cancel/flatten sequence and provides the auditable state. The statechart is the *record and the workflow*; it is not the *enforcement point*. This inverts the naive design and must be written down, because the naive design looks correct and passes every test that is not run under load.

Related: the `Validator`'s kill-switch check is on every order path (20 §3.5), i.e. it is hot. Reading a plain `bool` is nanoseconds; asking an interpreter is a cross-task query. Another instance of B14's principle: statecharts gate the hot path, they are not in it.

### Changes

- **24 §11.7 / 20 §4.3** — add normatively: *"kill-switch enforcement is a synchronous in-process flag consulted by the Validator. The kill-switch statechart records and orchestrates; it does not gate. The flag is set before the machine event is dispatched."*
- **E39-S03** ("Kill-switch engine: global and scoped freeze over REST with WS propagation") — add an acceptance criterion: engaging the kill switch blocks the next order submission **even when the event loop is saturated**, verified in E39-Q03's chaos scenario.
- **ADR-0008** rule 8 — add the same clarification.

---

## B19 — Reconciliation job

### Current design (24 §8.5, §14.3, 20 §10.4, E45)

Triggered by reconnect, by a periodic full sweep (`full_sweep_interval_s` 300 live/demo, 60 testnet), by an unknown order, and on startup. Diffs `GET /v5/order/realtime` + `/v5/order/history` + `/v5/position/list` + `/v5/execution/list` against local state by `orderLinkId`; resolves `Unknown` orders; remediation step 5 (auto-attach fallback SL, auto-cancel orphaned children, adopt untracked). Environment-dependent via `ReconCapabilities` (retention, WS stability, grace period, `auto_remediate`).

### Proposed statechart

```json
{
  "id": "reconciliation",
  "initial": "idle",
  "context": {
    "account_id": null, "trigger": null, "started_us": null,
    "orders_checked": 0, "divergences": [], "remediations": [],
    "consecutive_failures": 0, "auto_remediate": true
  },
  "states": {
    "idle": {
      "on": {
        "SWEEP_DUE":  {"target": "#reconciliation.fetching", "actions": ["set_trigger_periodic"]},
        "RECONNECTED":{"target": "#reconciliation.fetching", "actions": ["set_trigger_reconnect"]},
        "UNKNOWN_ORDER": {"target": "#reconciliation.fetching", "actions": ["set_trigger_unknown"]},
        "STARTUP":    {"target": "#reconciliation.fetching", "actions": ["set_trigger_startup"]}
      }
    },
    "fetching": {
      "entry": ["stamp_start", "emit_recon_started"],
      "invoke": {
        "id": "fetch", "src": "fetch_exchange_state",
        "onDone":  {"target": "#reconciliation.diffing", "actions": ["store_exchange_state"]},
        "onError": [
          {"target": "#reconciliation.stale_lockout", "guard": "failures_exhausted"},
          {"target": "#reconciliation.backing_off",   "actions": ["bump_failures"]}
        ]
      },
      "on": {"CANCEL": {"target": "#reconciliation.idle"}, "*": {"actions": ["defer"]}}
    },
    "backing_off": {
      "entry": ["schedule_retry_deadline"],
      "on": {"RETRY_DUE": {"target": "#reconciliation.fetching"},
             "CANCEL":    {"target": "#reconciliation.idle"}}
    },
    "diffing": {
      "invoke": {
        "id": "diff", "src": "diff_against_local",
        "onDone": [
          {"target": "#reconciliation.remediating",
           "guard": "divergences_found_and_auto_remediate", "actions": ["store_divergences"]},
          {"target": "#reconciliation.reporting", "actions": ["store_divergences"]}
        ],
        "onError": {"target": "#reconciliation.reporting", "actions": ["record_diff_error"]}
      }
    },
    "remediating": {
      "invoke": {
        "id": "rem", "src": "apply_remediations",
        "onDone":  {"target": "#reconciliation.reporting", "actions": ["store_remediations"]},
        "onError": {"target": "#reconciliation.reporting",
                    "actions": ["store_remediations", "raise_critical_alert"]}
      },
      "on": {"*": {"actions": ["defer"]}}
    },
    "reporting": {
      "entry": ["persist_report", "emit_recon_metrics", "drain_deferred",
                "reset_failures", "broadcast_recon_complete"],
      "always": [
        {"target": "#reconciliation.divergent", "guard": "unresolved_divergences"},
        {"target": "#reconciliation.idle"}
      ]
    },
    "divergent": {
      "tags": ["needs_attention"],
      "entry": ["raise_divergence_alert"],
      "on": {
        "OPERATOR_RESOLVED": {"target": "#reconciliation.idle"},
        "SWEEP_DUE":         {"target": "#reconciliation.fetching"}
      }
    },
    "stale_lockout": {
      "tags": ["account_locked", "critical"],
      "entry": ["lock_account_for_new_orders", "page_owner"],
      "on": {"RECONNECTED": {"target": "#reconciliation.fetching",
                             "actions": ["reset_failures"]}}
    }
  }
}
```

### Fit: **Good**

This is the best-supported shape in the library's measured strengths: a linear pipeline of long-running invokes, with correct cancellation. Study 04 g5 and Study 05 B4/B5 both confirm what matters most here — cancelling a mid-flight sweep delivers `CancelledError` into the service, honours `finally`, returns `stop()` promptly, and **does not** later deliver a stale `done.invoke`. A stale reconciliation result applied after a newer sweep would be a genuine corruption path; the library gets it right.

Concerns:

1. **Reconciliation is the recovery mechanism for every other component's failures**, including LC-01 quarantines and LC-03 drops. It therefore must not itself be hosted in a way that shares a failure mode with what it repairs. Practical rule: the reconciliation machine is started by the supervisor **before** the OMS accepts orders (already implied by 24 §9.5.1's `UnwindResumer` ordering), and its own faults escalate to `stale_lockout` rather than being retried forever.
2. **LC-10 — snapshot restore does not re-issue invokes.** A crash during `fetching` restores a machine parked in `fetching` with no service running and no timer — a silent hang. Every state with an `invoke` must be re-driven on restore. Our restore procedure therefore re-sends the triggering event rather than trusting the restored configuration (see Part C §3.3). This is the single most consequential operational consequence of the library's documented "restore is static" behaviour.
3. Environment differences (`auto_remediate=False` on testnet, 60 s sweeps, 120 s grace) are context values, not separate machines — matching 24 §14.3's "capabilities drive behaviour, not conditionals" rule.

### Changes

- **24 §8.5** — add the reconciliation statechart; add `stale_lockout` explicitly (E45-T02 mentions "stale-account lockout" but 24 §8.5 does not model it).
- **E45-T01/T03** — adopt; T03's "persist, expose and instrument the reconciliation report" maps to the `reporting` state's entry actions.
- **E45-T06/T07** — add a chaos case: "crash during `fetching`, restart, assert the sweep is re-driven and completes" — this directly exercises LC-10.

---

## B20 — RiskLockout

### Current design (24 §11.7, E39)

Per-account risk caps enforced by the OMS **after** the rule engine. `sys.daily_loss_lockout`: `realised_pnl_today <= -max_daily_loss` → `halt_new_orders` until next UTC day. Lockout clearing requires step-up (24 §15.3). `halt_new_orders` scope/`until` ∈ `next_utc_day | duration_ms | manual`. E39-K01 is an open spike on the authoritative daily-PnL source and day-boundary semantics.

### Proposed statechart

```json
{
  "id": "risk_lockout",
  "initial": "clear",
  "context": {
    "account_id": null, "scope": "account",
    "realised_pnl_today": "0", "max_daily_loss": "0",
    "breach_reason": null, "until_mode": "next_utc_day",
    "until_us": null, "cleared_by": null
  },
  "states": {
    "clear": {
      "tags": ["trading_allowed"],
      "on": {
        "PNL_UPDATE": [
          {"target": "#risk_lockout.locked", "guard": "breaches_daily_loss_cap",
           "actions": ["set_breach_daily_loss"]},
          {"target": "#risk_lockout.warning", "guard": "within_warning_band"},
          {"actions": ["update_pnl"]}
        ],
        "CAP_BREACH":  {"target": "#risk_lockout.locked", "actions": ["set_breach_from_event"]},
        "MANUAL_LOCK": {"target": "#risk_lockout.locked", "actions": ["set_breach_manual"]}
      }
    },
    "warning": {
      "tags": ["trading_allowed", "warning"],
      "entry": ["emit_risk_warning"],
      "on": {
        "PNL_UPDATE": [
          {"target": "#risk_lockout.locked", "guard": "breaches_daily_loss_cap",
           "actions": ["set_breach_daily_loss"]},
          {"target": "#risk_lockout.clear", "guard": "outside_warning_band"},
          {"actions": ["update_pnl"]}
        ]
      }
    },
    "locked": {
      "tags": ["trading_blocked"],
      "entry": ["halt_new_orders", "compute_until", "schedule_expiry_deadline",
                "raise_lockout_alert", "audit_lockout", "broadcast_lockout"],
      "on": {
        "EXPIRY_DUE": [
          {"target": "#risk_lockout.clear", "guard": "until_mode_is_time_based",
           "actions": ["resume_new_orders", "reset_daily_counters_if_new_day"]},
          {"actions": ["log_expiry_ignored_manual_mode"]}
        ],
        "OVERRIDE_REQUESTED": [
          {"target": "#risk_lockout.clear",
           "guard": "owner_and_elevated_and_override_permitted",
           "actions": ["resume_new_orders", "audit_override"]},
          {"actions": ["audit_override_denied"]}
        ]
      }
    }
  }
}
```

### Fit: **Good**

Same architecture as B18 and the same non-negotiable consequence: **`halt_new_orders` is a synchronous flag consulted by the `Validator`, not a query against the interpreter.** Blocking must take effect before the event that records it is processed.

Concerns:

1. **`PNL_UPDATE` is potentially per-fill and, with unrealised PnL in the warning band, potentially per-tick.** Same treatment as B15: the risk evaluator computes the band in plain Python and sends the machine an event only on a **band change** (edge-triggered). Level-triggering this machine on mark updates would put market-rate traffic into the shared budget.
2. **The day boundary is the open question in E39-K01, and the library makes one answer wrong.** A `next_utc_day` expiry is up to 24 hours away; an in-machine `after` would neither survive a restart nor be trusted under load. The deadline is an absolute timestamp in context, scheduled externally, re-armed on restore — and on restore the machine must also re-evaluate whether the boundary already passed while the process was down, because nothing will re-fire a deadline that expired during downtime. That "expired while down" case is a class of bug the library's static restore creates across B5, B6, B16, B19 and B20 alike; it is handled once in the restore procedure (Part C §3.3), not per machine.
3. `breaches_daily_loss_cap` is the deny-polarity guard (A6): written so that a failure blocks trading, never permits it.

### Changes

- **24 §11.7** — add the lockout statechart; document `warning` as a distinct state (today it is implicit in the dashboard design, with no server-side representation).
- **E39-K01** — the spike's output should record the day-boundary semantics **and** the "boundary passed while the process was down" rule.
- **E39-S02** ("Automatic lockout on cap breach with day-boundary reset and step-up override") — adopt; add an acceptance test for restart across a day boundary while locked.
- **E39-T01** (risk evaluator core) — specify edge-triggered event emission into the lockout machine.

---

# Part C — Overall architecture proposal

## C1. Statechart hosting

### C1.1 The governing fact

From Study 04 §2, and it should be on the wall of whoever builds this:

| N interpreters | aggregate ev/s | per-interpreter ev/s |
|---:|---:|---:|
| 1 | 21,231 | 21,231 |
| 10 | 20,305 | 2,031 |
| 100 | 20,063 | 201 |
| 500 | 19,323 | 38.6 |
| 1,000 | 18,152 | **18.2** |

Every interpreter shares one asyncio event loop and one thread. **Concurrency is interleaving, not parallelism.** Adding machines does not add capacity; it divides a fixed ~20k ev/s budget — and it divides it with everything else in the process, including the OMS. Capacity planning is **per process**, never per machine.

This produces three binding hosting rules:

- **R1 — Statecharts gate the hot path; they are never in it.** Market data, book deltas, trade prints, per-tick metric evaluation and per-print paper matching never become machine events. Machines receive control and lifecycle events only. (Lint: no bus topic matching `md.*` may be wired to an interpreter.)
- **R2 — Event sources into machines are edge-triggered.** A machine hears about a condition when it *changes*, not on every sample. Applies to `PNL_UPDATE` (B20), `MARK_UPDATE` (B15), `BOOK_TARGET_MOVED` (B7), `TRIGGER` (B9).
- **R3 — The event budget is a tracked, alarmed resource.** Export `cv_machine_events_total` and `cv_machine_transition_seconds`; alert when total machine event throughput exceeds 8,000/s (40 % of the measured floor). This is a capacity signal no one will think to add later.

### C1.2 Granularity: one interpreter per entity, for a bounded set of entity types

| Entity | Instances (steady state) | Interpreter? | Rationale |
|---|---:|---|---|
| Order | ≤500 open | **yes, per entity** | 1.08 KB each resident, µs fill latency (Study 04 Budget 3) |
| TradeGroup | ≤50 active | yes, per entity | supervisor |
| TradeGroupLeg | ≤ groups × 5–20 | yes, per entity (child actor) | |
| EmulatedAlgo | ≤50 active | yes, per entity (child actor) | |
| PositionProtection | ≤100 | yes, per position | the P4 invariant |
| RuleInstance | rules × scopes, ~1,000 | yes, per instance, **lazily started** | E6 mandates per-scope state |
| Alert | per *fired* alert, short-lived | yes, transient | |
| RecordingSession | ~dozens | yes, per symbol | |
| ReplaySession | ≤5 | yes, per session | |
| ExchangeConnection | ~5–10 | yes, per socket | |
| BookHealth | per symbol, ~24 | yes, per symbol | deltas excluded (B14) |
| AuthSession | ≤20 | yes, per active session | |
| LiveGate / KillSwitch | 1 each | yes, singleton | |
| RiskLockout | per account, ≤25 | yes, per account | |
| Reconciliation | per account | yes, per account | |
| PaperAccount | per paper account | yes, edge-triggered | |

Worst case ≈ 1,800 interpreters. At ~42 KB RSS idle each that is ~76 MB — acceptable, and well under the 10,000-interpreter point (~450 MB) where memory starts to matter. The constraint is not memory, it is the shared event budget, which is why rule instances are **lazily started** (only instances whose trigger has ever fired get an interpreter; the rest are a row in Postgres).

Note a measured caveat: **~3 MB per 1,000-interpreter churn cycle is retained after teardown** and does not fully flatten across 5 cycles (Study 04 §2, `bench_i_retention.py` — confirmed *not* a reference leak; 0 live `Interpreter` objects, empty `gc.garbage`; consistent with allocator arena retention). For a process churning thousands of order machines per day, either budget headroom or plan a periodic recycle. Add `cv_process_rss_bytes` to the alerting set.

### C1.3 Actor tree per account

```
AppSupervisor                         (plain Python, not a machine)
├── LiveGate                          (singleton machine)
├── KillSwitch                        (singleton machine)
├── ConnectionSupervisor              (plain Python)
│   ├── ws_conn:public:linear         (machine)
│   └── ws_conn:private:<account>     (machine, one per account)
├── BookSupervisor                    (plain Python)
│   └── book:<symbol>                 (machine, gate only)
├── AccountSupervisor:<account_id>    (plain Python)
│   ├── risk_lockout:<account>        (machine)
│   ├── reconciliation:<account>      (machine)
│   ├── position_protection:<sym>     (machine)
│   └── order:<order_id>              (machine, ≤500 across all accounts)
├── TradeGroupSupervisor              (plain Python)
│   └── trade_group:<gid>             (machine)
│       ├── leg:<leg_id>              (child actor, addressed via our registry — LC-02)
│       └── algo:<algo_id>            (child actor)
├── RuleSupervisor                    (plain Python, owns the trigger index)
│   └── rule_instance:<rule,scope>    (machine, lazily started)
├── RecorderSupervisor / ReplaySupervisor / AlertSupervisor / SessionSupervisor
└── MonotonicScheduler                (plain Python — owns ALL deadlines)
```

**Supervisors are plain Python, not machines.** Three reasons: (a) a supervisor's job is lifecycle management, which ADR-0004 already assigns to per-module `asyncio.TaskGroup`s; (b) making supervisors machines would route every child event through a parent at 75.7 µs/msg vs 33 µs direct (Study 04 §5); (c) LC-02 means parent→child addressing does not work by id anyway, so a machine parent buys nothing.

**Actor parentage is used only where the parent genuinely owns the child's lifetime** — trade group → leg, algo → nothing (algos are leaves). Everything else is a flat registry owned by a supervisor. This deliberately limits our exposure to the library's actor subsystem, which is simultaneously its best-measured area (spawn/teardown/leak) and its worst-specified one (addressing).

---

## C2. Event bus integration

### C2.1 Domain events ↔ machine events

ADR-0004 mandates the bus carries immutable pydantic models on topics `{env}.{domain}.{symbol?}.{detail?}`. The library's `Event` is a frozen dataclass with an untyped `payload` dict and **no validation whatsoever** — `send("E", qty="not-a-number")` is accepted silently (Study 05 C12, LC-19).

The seam is a single `MachineGateway` per machine family:

```
bus topic (pydantic model)
   → gateway.on_domain_event(evt)
       → validate + map to (event_type: str, payload: dict)   # one place, typed
       → dedupe by idempotency key
       → SafeInterpreter.send(...)
   ← interpreter subscribe() callback
       → map machine state → pydantic projection model
       → bus.publish("{env}.oms.{symbol}.order_state", model)
```

Rules:

- **Machine event types are a closed `StrEnum` per family.** The gateway is the only place a string event name appears. This substitutes for the typed-events support the library does not have (`TContext` is bound to `Dict[str, Any]`; there is no `setup({types})` equivalent — Study 01 §13.1).
- **Payloads are validated pydantic models serialised to dicts at the boundary and re-validated inside actions.** The library will not do it (LC-19).
- **Nothing outside the gateway calls `interp.send()`.** Lint-enforced; this is also the cross-thread safety mechanism (A8/LC-18).

### C2.2 Idempotency

Three layers, because the library provides none:

1. **Business key.** `order_link_id` (24 §8.3) and `exec_id` are the domain idempotency primitives. `apply_fill` checks `exec_id ∈ context["seen_exec_ids"]` before mutating (S4). This is the only layer that is authoritative.
2. **Gateway dedupe.** A bounded LRU of `(machine_id, idempotency_key)` drops exact replays before they reach the queue — cheap insurance for reconnect storms re-delivering the same private-WS frames.
3. **Write-ahead ordering.** S8 requires the `order_events` row before the in-memory change. Because an action can raise *after* committing a transition (LC-01), the persisted row is the trustworthy record and the machine is the fast projection. On any disagreement, Postgres wins (S7).

### C2.3 Ordering

Good news, measured: the async interpreter is **strict FIFO single-consumer**, 500/500 delivered with per-producer order preserved across 10 concurrent producers (Study 04 g7). Within one machine, ordering is exactly what an OMS needs.

Two caveats that must be designed around:

- **Cross-machine ordering is not guaranteed.** Two machines processing events from the same source may interleave arbitrarily. Any invariant spanning machines (e.g. "the group is open only when all legs are open") must be a pure function of persisted/aggregated state, never of observed ordering. This is the same rule B2 arrived at from LC-06.
- **`raise` is queued behind pending external events** (LC-06, Study 05 C10), so the microstep/macrostep distinction XState guarantees does not hold. Internal follow-ups may be observed after externally-arriving events. Never rely on a raised event settling before the next external one.

### C2.4 Backpressure

The interpreter's queue is an unbounded `asyncio.Queue`. That is a latent memory risk under a burst and it silently converts backpressure into latency: Study 04 Budget 1 measured **65 ms p50 / 95 ms p95** queueing delay per event with 500 busy machines, and §3 measured ~2.2 s under saturation. `send()` itself costs only 2.26 µs — producers are never the bottleneck, the single consumer is (LC-20).

Mitigations:

- The gateway enforces a **bounded** inbound queue per machine family with the §4.2 policy matrix applied *before* the interpreter: control/OMS events never dropped (await), state-like events conflated.
- Export `cv_machine_queue_depth` per family and alert at depth > 100; it is otherwise invisible.
- Never place a machine on a path whose latency budget is under ~200 ms without measuring under the *loaded* population. Budget 1's 165 ms p95 for submit→open is the engine alone, before any network I/O, against a 300 ms budget — **1.81× headroom, and the measured max already touched 292 ms.** That is the tightest budget in the system and it is tight because of queueing, not transition cost (a transition is 33 µs, 5,000× smaller).

---

## C3. Persistence

### C3.1 Model — snapshots + event log (event sourcing, with Postgres authoritative)

```sql
CREATE TABLE machine_snapshots (
  machine_kind      text        NOT NULL,
  entity_id         uuid        NOT NULL,
  env               text        NOT NULL,
  cv_schema_version int         NOT NULL,   -- OUR version; library has none (LC-11)
  machine_hash      text        NOT NULL,   -- sha256 of the machine JSON
  snapshot          jsonb       NOT NULL,   -- get_persisted_snapshot(), compact
  state_ids         text[]      NOT NULL,   -- denormalised for querying/indexing
  updated_at        timestamptz NOT NULL,
  PRIMARY KEY (machine_kind, entity_id, env)
);

CREATE TABLE machine_events (             -- append-only; the OMS's order_events (S8) specialises this
  seq           bigserial PRIMARY KEY,
  machine_kind  text NOT NULL,
  entity_id     uuid NOT NULL,
  env           text NOT NULL,
  event_type    text NOT NULL,
  payload       jsonb NOT NULL,
  from_states   text[] NOT NULL,
  to_states     text[] NOT NULL,
  actions_run   text[] NOT NULL,
  fault         jsonb,                     -- non-null when an action raised (LC-01 evidence)
  occurred_at   timestamptz NOT NULL
);
```

The event log is written **write-ahead** (before the in-memory transition) for the order family per S8, and write-behind (from the plugin's `on_transition`) for non-financial families where a lost row is acceptable.

### C3.2 Snapshot policy

Measured costs (Study 04 §4): `get_snapshot()` 289.7 µs, `get_persisted_snapshot()` 203.3 µs, `from_snapshot()` 321.2 µs, restore+start 17.5 µs; a 2.1 KB context yields a 2,249 B compact snapshot (3,976 B with the library's hardcoded `indent=2` — 1.77× waste, LC-21).

- **Snapshot on state change, not on a timer.** Sweeping 500 machines on a timer costs ~145 ms of loop time ≈ 2,900 events of stalled throughput. On-change is both cheaper and more correct.
- **Use `get_persisted_snapshot()` + compact `json.dumps`.** 30 % faster and 44 % smaller.
- Snapshot writes go through an async batched writer; a snapshot write must never block a transition.

### C3.3 Restore on boot — the procedure that makes the library's static restore safe

This is the most important operational section in the document. The library's restore is **deliberately static**: it restores state ids, context, history and actor records correctly (verified exactly, including a 3-region parallel machine with a nested compound leaf), but it does **not** re-run entry actions, does **not** restart invoked services and does **not** re-arm `after` timers (Study 04 §4 C6/C7, Study 05 §2.10 — documented, not a bug). A naive restore therefore yields a fleet of machines that look healthy and do nothing: an order parked in `submitting` with no request in flight, a reconciliation parked in `fetching` with no sweep running, a TWAP parked in `armed` with no deadlines (LC-10).

**Boot procedure (normative):**

1. Load all non-terminal snapshots for the environment; verify `cv_schema_version` and `machine_hash`. On a `machine_hash` mismatch, run the registered upcaster; if none exists, **fail closed** — park the entity in `quarantined`/`needs_attention` and alert. Never best-effort a mis-restore (LC-11).
2. `from_snapshot()` each machine with the **shared** `MachineNode` (19× cheaper build).
3. **Re-arm deadlines:** for every context field ending `_at_us`/`_deadline_us`, register with `MonotonicScheduler`. If the deadline **already passed while down**, fire it immediately rather than dropping it — this case does not exist while running and is easy to miss (affects B5, B6, B16, B19, B20).
4. **Re-drive invoke states:** for every machine whose active configuration includes a state with an `invoke`, re-send the event that would have entered it, or send an explicit `RESUME` the machine handles by re-entering that state with `reenter: true`. Machines are authored so every invoke state is re-enterable. **This step is mandatory and has no library support.**
5. **Reconcile before accepting traffic:** per account, run the B19 reconciliation to completion before the OMS opens (already implied by 24 §8.5 startup trigger and §9.5.1's `UnwindResumer` precedence). Restored state is a *hypothesis*; the exchange is the fact.
6. Rehydrate the actor registries (LC-02) from `machine_snapshots` rows and the parent's `actors` map.

Cost: 500 machines restore in ~169 ms (Study 04 §4) — comfortably inside the ≤90 s RTO in ADR-0004.

### C3.4 Schema versioning

The library has **no snapshot schema version** and `from_snapshot` will load an old-shaped snapshot and partially mis-restore it (LC-11). We supply the missing machinery:

- `cv_schema_version` (ours) + `machine_hash` (sha256 of the canonicalised machine JSON) on every row.
- Machine JSON files live in `services/api/candleviewer/machines/<family>/v<N>.json`, are immutable once shipped, and are content-hashed at import.
- An upcaster registry `(kind, from_version) -> callable(snapshot) -> snapshot`, unit-tested with golden snapshots from every shipped version. This mirrors the rule-IR upcasters E35-T05 already plans, and should share the same infrastructure.
- CI check: every `machine_hash` present in any production snapshot has either a matching shipped machine or an upcaster.

---

## C4. Observability

### C4.1 Plugin → logs / metrics / audit

`PluginBase` hooks (`on_interpreter_start/stop`, `on_event_received`, `on_transition`, `on_action_execute`, `on_action_error`, `on_guard_evaluated`, `on_service_start/done/error`) are the integration point, and every plugin is wrapped in `_SafePlugin`, which swallows hook exceptions — so a broken exporter cannot take down a machine. Good.

One `CandleViewerPlugin` per family emits:

| Signal | Source hook | Notes |
|---|---|---|
| `cv_machine_transitions_total{kind,from,to}` | `on_transition` | |
| `cv_machine_transition_seconds{kind}` | around `on_transition` | histogram |
| `cv_machine_events_total{kind,event}` | `on_event_received` | feeds the R3 budget alarm |
| `cv_machine_action_errors_total{kind,action}` | `on_action_error` | **P1 alert, see below** |
| `cv_machine_service_errors_total{kind,service}` | `on_service_error` | |
| `cv_machine_guard_denials_total{kind,guard}` | `on_guard_evaluated` | safety-guard denials are a security signal |
| audit rows | `on_transition` | maps to the 24 §15.5 vocabulary |
| `machine_events` rows | `on_transition` | §C3.1 |

**Critical caveat, measured:** `on_transition` fires **normally on a transition whose action raised** — the plugin is told the transition succeeded (Study 04 §7: "Plugin hook signalled an error: ❌ no — `on_transition` fired normally, as if successful"). So `on_transition` alone cannot be trusted as a success signal. Two compensations, both required:

1. The `@cv_action` wrapper (A1) records the fault in context and raises `FAULT`, so the fault is visible in the *next* transition and in the `fault` column.
2. A `logging.Handler` attached to the `xstate_statemachine` logger at `ERROR` converts any library-level error log into a **P1 alert and a reconciliation trigger**. Study 04 is explicit that a log line is the only evidence; we turn that log line into a page.

Also mandatory: `logging.getLogger("xstate_statemachine").setLevel(WARNING)` — the library logs INFO per guard, per event, per state entry/exit, and Study 04 found logging dominated the profile when left on.

### C4.2 State exposure over WS to the UI

The current WS protocol (ADR-0005, 24 §19.3) already carries OMS and rule state. Machine state maps to it directly, with one wrinkle: **the library has no hierarchical `state.value`** — active states are a flat `Set[str]` of ids (Study 01 §13.7, LC-22), which is *not* what XState consumers and visualisers expect (`{parent: 'child'}`).

We therefore publish both forms from one projector:

```json
{
  "entity_id": "…",
  "kind": "order",
  "machine_hash": "sha256:…",
  "state_ids": ["order.lifecycle.partially_filled", "order.protection.sl_present"],
  "value": {"lifecycle": "partially_filled", "protection": "sl_present"},
  "tags": ["protected"],
  "context_projection": {"filled_qty": "0.4", "leaves_qty": "0.6"}
}
```

`value` is reconstructed by our projector from the flat id set plus the machine tree. Never publish raw context — publish an explicit whitelist projection per family (context is `Dict[str, Any]` and will accumulate internals like `_deferred` and `_fault`).

### C4.3 Stately visualiser interop for the React app

The pitch (Study 03 §5): a JSON machine exported from the Stately editor loads unmodified into `create_machine()` (library's own claim: 103/104 real-world machines parse unchanged), and the *same* JSON can be loaded into `@xstate/react` purely for visualisation — one source of truth for the state graph, a live picture of "which state is this order in right now", no hand-maintained diagram drifting from the code.

This is genuinely valuable for CandleViewer: the OMS graph is exactly the thing a reviewer or the owner wants to *see*, and 24 §8.2's mermaid diagram is already a hand-maintained duplicate of the real state machine.

Three honest caveats:

1. **We have not verified it.** Study 03 §5 item 4 says so plainly: the claim rests on the library's own corpus, and the specific shapes CandleViewer needs (spawned-actor persistence, parallel regions with our `tags`/wildcard usage) have not been round-tripped by us. **Action: a spike (see E-new below) that authors one real OMS sub-machine in the Stately editor, diffs the JSON against ours, and loads it through both `create_machine()` and `@xstate/react`.**
2. **Interop is structural only.** Actions/guards/services transfer as *names*; Python implementations never transfer, and should not.
3. **LC-22 bites here:** since the library exposes flat state ids and XState's visualiser expects hierarchical values, the live-state overlay needs our reconstructed `value` (§C4.2). Static diagram rendering is unaffected.

For docs and runbooks, `to_mermaid()` / `to_plantuml()` generate diagrams from the same machine JSON with no JS toolchain — this should replace the hand-maintained mermaid in 24 §8.2, §9.6 and §10.1, making diagram drift structurally impossible.

---

## C5. Testing

### C5.1 Unit — a real weakness, stated plainly

The library's advertised "pure API" (`transition` / `initialTransition` / `get_next_snapshot`) is the natural unit-test entry point, and it has two measured problems (LC-23):

- It is **2.4× slower** than the full interpreter (77 µs vs 33 µs) — a pessimisation, not an optimisation.
- It **does not execute imperative actions**: after `SUBMIT`, the state advanced while `context["qty"]` stayed `0.0`. Verified directly.

Since CandleViewer's actions are imperative Python (exchange calls, Decimal arithmetic, DB writes), the pure API tests **transitions only, not effects**. That is still useful — a fast table-driven test of "from state X, event E with context C goes to state Y" is exactly the S1–S9 matrix ADR-0006 demands — but it must never be mistaken for testing behaviour.

Test layering:

| Layer | Mechanism | Covers |
|---|---|---|
| Transition table | pure API, table-driven | the S1–S11 matrix, guard branches |
| Action unit | call action functions directly with a fake interpreter | `apply_fill` dedupe, Decimal quantisation, ratchet logic |
| Machine integration | real `Interpreter` + fake services | invoke lifecycle, deferral/drain, quarantine on fault |
| Fleet | 500 machines + a fake exchange | queueing latency, budget assertions |
| Chaos | fault injection (E45-T06) | crash/restore, action faults, saturation |

### C5.2 Model-based testing

The machine JSON is itself a model, so generate paths from it: enumerate simple paths from initial to each terminal, execute each against real logic with a fake exchange, assert invariants at every step:

- **INV-1** — `filled_qty ≤ qty` always.
- **INV-2** — a terminal state is never left (S6).
- **INV-3** — no position is in `sl_missing` for longer than the deadline without an alert (P4).
- **INV-4** — the sum of leg `filled_qty` equals the group aggregate.
- **INV-5** — no `EXEC` event is ever dropped: every delivered `exec_id` appears in `seen_exec_ids` or `_deferred`. **This is the direct regression test for LC-03 and it must exist for every family.**

Property tests with Hypothesis over event sequences: any permutation of `{ACK, EXEC×n, CANCEL, RECON_*}` must leave the machine in a state consistent with the delivered set.

### C5.3 Replay determinism

Strong measured foundation: identical event sequences produce byte-identical state, context and action traces across 5, 10 and 15 repeated runs, including a burst-send variant racing an async invoke (Study 05 C8/C9/C17). Re-run three times to check flakiness; stable each time.

The determinism test that matters is therefore **not** "does the machine respond deterministically" (it does) but **"did the live run and the replay run deliver the same event set to the machine"** — because LC-03 makes that the actual risk (Study 05 §3 states this explicitly). E26-T06's parity harness must diff delivered event sets per machine, not only derived outputs.

### C5.4 Regression suite against the library itself

Study 02 and Study 06 converge on this, and it is a governance requirement, not a nicety: 2,805 tests pass at 87 % coverage, but coverage is thinnest exactly where we lean hardest (`base_interpreter.py` at 86 %, with misses concentrated in rollback and cancellation branches); two consecutive minor releases (0.6.0, 0.7.0) each disclosed CRITICAL silent-wrongness defects that had survived thousands of passing tests; the project has 14 stars, 1 fork, one filed issue ever, a single maintainer, ~11 releases in under a year, and **no independent third-party production adoption**. CandleViewer would be the first-line battle-tester, not a beneficiary of someone else's.

Therefore:

- **Pin the exact version.** Vet the changelog before every bump.
- Maintain `tests/xstate_contract/` — our own reproduction of every behaviour we depend on: guard arity, action ordering, deferral, actor spawn/teardown, snapshot round-trip of a parallel machine, invoke cancellation, FIFO ordering, `reenter` semantics, camelCase↔snake_case logic mapping (which has already broken once, per Study 06). This suite runs on every library bump and is the gate for accepting one.
- Budget the cost honestly: the library's own suite takes ~9.5 minutes; ours should stay under 60 s by testing only our dependencies.

---

## C6. Performance plan (numbers from Study 04)

| Path | Budget | Engine cost measured | Headroom | Verdict |
|---|---|---|---|---|
| Order submit → ack | p95 < 300 ms | **165.6 ms p95** (500 machines busy), max 292.5 ms | 1.81×, before network | ⚠️ **PASS, tight** |
| 500 open order machines | resident | **0.53 MB**, fill p95 **0.127 ms** | vast | ✅ PASS |
| Rule eval, 2k ev/s × 100 rules | 200k eval/s | ~30k/s (≈90k/s on server silicon) | **−2.2× to −6.5×** | ❌ **FAIL — architectural** |
| Failover restore, 500 orders | ≤90 s RTO | **169 ms** | vast | ✅ PASS |
| Actor spawn (12-slice TWAP) | — | **~1.5 ms** | vast | ✅ PASS |
| Timer fidelity under load | algo intervals | **+2,250 ms at 500 machines** | — | ❌ FAIL — design timing out |

Planning rules that follow:

1. **Per-process capacity: ~20,000 machine events/s**, shared by every family. Alert at 8,000/s. If the ceiling is approached, the escape is the designated ADR-0004 process split (ingestion+engines | OMS+gateway), which gives ~N× because throughput is per-event-loop. Note `send_events()` batching buys nothing (19,966 vs 18,152 ev/s) — the bottleneck is transition processing, not enqueue.
2. **Budget 1 is the one to watch.** 165 ms p95 of *pure queueing* against a 300 ms budget that also has to contain a 50–150 ms Bybit round trip. The order path must be measured with the realistic loaded population, not in isolation. If it degrades, the first lever is reducing non-OMS machine traffic (R1/R2), not micro-optimising transitions.
3. **Never use the pure API for speed** (2.4× slower, LC-23). Never use `SyncInterpreter` for speed either (only 1.25× faster, and it cannot run async services at all).
4. **Sharing `MachineNode`** across interpreters is the default (19× cheaper construction, verified context-safe).
5. **Cross-thread sends cost 336 µs vs 33 µs** — 10×. Keep the hot path in-loop.
6. Add `cv_machine_*` metrics to the 20 §12.1 Prometheus set and a "Statechart fleet" Grafana dashboard: event rate by family, queue depth, transition latency, action errors, RSS.

---

## C7. Failure handling

### C7.1 Action exceptions — the defining risk

Restating because it governs the design: an action that raises **skips the rest of that action list but still commits the transition**, still runs the target's `entry`, leaves `status == "running"`, reports a clean `on_transition` to plugins, propagates nothing to the caller, and leaves one log line as the only evidence. There is **no programmatic error channel** — verified: no exception, no error event, no status change, no plugin hook, no subscriber notification.

Defence in depth:

1. `@cv_action` wrapper — no action raises; faults are recorded and a `FAULT` event is raised. (Prevention.)
2. Every family has a `quarantined` / `needs_attention` state that `FAULT` targets. (Containment.)
3. `ERROR`-level logging handler on the library logger → P1 alert + reconciliation trigger. (Detection, for anything that escapes 1.)
4. Independent reconciliation against the exchange. The statechart is never the book of record. (Recovery.)
5. Write-ahead `machine_events` / `order_events` rows. (Forensics.)

Note the related gap: an entry action raising during `start()` does **not** fail the start (Study 04 g3) — the interpreter reports `running` in a state whose entry logic never completed. Our `start()` wrapper asserts a post-condition (expected initial configuration reached, no `_fault` in context) and fails loudly if not.

### C7.2 Service (invoke) errors

Well-behaved, and this is the library at its best: `onError` receives `error.platform.<id>` carrying the exception **object**; an unhandled service error surfaces loudly (`status == "error"`, `is_running == False`, `interpreter.error` populated) rather than pretending health; cancellation delivers `CancelledError` mid-`await`, honours `finally`, returns `stop()` in 0.15 ms, and correctly does *not* fire `onError` (cancellation is not failure); a cancelled invoke never delivers a stale `done.invoke`.

House rules: every `invoke` declares `onError` (an undeclared one kills the machine); services map exchange errors to `OmsErrorCode` before raising, so guards branch on our taxonomy, not on exception types; `evaluation_timeout_ms`-style deadlines use `asyncio.wait_for` *inside* the service, surfacing as `onError` (LC-17).

### C7.3 Poison events

An event that always faults would loop forever if naively retried. Rules:

- The `FAULT` path is terminal-ish by design: a quarantined entity does not re-process the poison event; it waits for reconciliation or an operator.
- The gateway keeps a per-(machine, event-key) fault counter; 3 faults ⇒ the event is dead-lettered to `machine_dead_letters` with full payload, and the entity is quarantined.
- Unknown events are safely ignored by the library (verified, A14) — but our gateway counts them (`cv_machine_unknown_events_total`) because a rising count means a producer/consumer version skew.
- Self-feeding is bounded by `max_iterations` (`_raise_depth`), which we set explicitly per family rather than relying on the default.

### C7.4 Degraded-mode interaction

20 §6.3 already has a degraded-mode matrix. Add: **statechart fleet degraded** = action-error rate > 0 in the last 5 minutes, or machine queue depth > 100, or any entity in `quarantined`. In that mode the UI shows the OMS as "reconciling", armed rules pause (consistent with 24 §11.7's disconnect guard), and new orders require explicit confirmation. Reusing the existing degraded path rather than inventing a new one keeps this cheap.

---

# Part D — Library challenges register

The owner's battle-test deliverable. Every entry is a limitation *we measured or read in the source*, not a doc claim. Severity is **relative to CandleViewer's use**, not to the library in general.

| Severity | Meaning |
|---|---|
| 🔴 Blocker | Can cause financial loss or silent data corruption on the order path. Must be mitigated before any live use. |
| 🟠 Major | Causes silent wrongness or a hard architectural constraint. Requires a documented workaround. |
| 🟡 Minor | Surprising, costly or awkward; worked around cheaply. |
| ⚪ Ecosystem | Not a code defect — a project-maturity or adoption risk. |

---

### LC-01 🔴 An action that raises still commits the transition, with no programmatic error channel

**Evidence:** Study 04 §7, `bench_g2_error_channel.py`; source `base_interpreter.py` action handler catches `Exception`, logs `"🔥 Action '%s' raised…; skipping remaining actions"`, continues. Reproduced on both engines.
**Observed:** with `actions: ["first","explode","third"] → b`, `explode` raising: `third` skipped ✅, but target `entry_b` still ran, machine ended in `b`, `status == "running"`, no exception to the caller, `on_transition` fired as if successful, no plugin error hook, no subscriber notification. One `ERROR` log line is the entire evidence.
**Impact:** `apply_fill` raising leaves an order `filled` with a stale `filled_qty` — silent position corruption, and the audit trail says everything is fine.
**Workaround:** A1 (`@cv_action` wrapper → record fault → `FAULT` event → `quarantined` state) + an `ERROR`-level log handler that pages + independent reconciliation. Four layers, because none alone is sufficient.
**Suggested upstream fix:** add `on_action_error` escalation semantics with a configurable policy per machine: `continue` (today's behaviour), `rollback` (the transition-failure path already exists in the codebase for transition errors — reuse it), or `fail` (status → `error`). Minimum viable PR: make `on_transition` receive a `failed_actions: list[str]` argument so plugins can at least *observe* the failure, and fire a dedicated `on_transition_failed` hook. This is the single highest-value change the library could make for production users.

---

### LC-02 🟠 `sendTo` cannot address an actor by its `invoke` `id` or `systemId`

**Evidence:** Study 05 §2.2 (C16); source `interpreter.py:958-964` mints ids as `parent:<serviceKey>:<uuid>`; `_resolve_actor_target` (`base_interpreter.py:1329-1391`) matches on `actor_id.split(":")[1:]`.
**Observed:** `by_service_key("child") → "PONG"` ✅; `by_invoke_id("kid") → None` ❌; `by_system_id("kid") → None` ❌ — with `invoke: {"id":"kid","src":"child","systemId":"kid"}`. Failure mode is a `logger.warning` plus a **dropped event**. With N children sharing one `src`, the service key is ambiguous by construction and the code logs "ambiguous, event dropped".
**Impact:** trade-group fan-out (ADR-0008) is exactly "invoke the same child machine under N distinct ids and address them individually". Not expressible in config.
**Workaround:** application-owned `dict[leg_id -> Interpreter]`, direct `actor.send(...)`. Verified working. Costs us declarative routing and adds restore-time rehydration.
**Suggested upstream fix:** include the declared `id` in the minted actor id (`parent:<id>` when `id` is given), and make `systemId` an exact-match first-class key in `_resolve_actor_target`. Also: an ambiguous target should raise, not drop.

---

### LC-03 🔴 Events with no handler in the current state are silently discarded

**Evidence:** Study 05 §2.6 (C17), deterministic across 10 runs.
**Observed:** `send("NEW")` → `pending` (invoke ack ~5 ms); three subsequent `PARTIAL`/`FILL` events arriving during `pending` all vanished. Expected `oms.filled, filled == 30`; observed `oms.live, filled == 0`. No queue, no deferral, no error — the same "no transition found" path as an unknown event.
**Impact:** the most dangerous item in the entire study for CandleViewer, because it is invisible. Fills arriving during an ack round trip disappear and our `filled_qty` silently disagrees with the exchange. It is *also* a replay-fidelity bug: live and replay runs can see different delivered event sets (Study 05 §3).
**Workaround:** explicit deferral — `"*": {"actions":["defer"]}` on every transient state, `drain_deferred` in every `entry`, enforced by a machine linter, plus INV-5 ("no delivered `exec_id` is ever unaccounted for") as a standing test for every family.
**Suggested upstream fix:** implement XState's `defer`/`deferred` semantics, or at minimum a machine-level `on_unhandled: "ignore" | "defer" | "error"` option. Today "ignore" is the only behaviour and it is the silent one.

---

### LC-04 🔴 `always` with a self-target deadlocks silently

**Evidence:** Study 05 §2.1 (A10); root cause `base_interpreter.py:1769` — `if target_state == transition.source and not transition.reenter` classifies *any* self-target as internal, so `entry` never re-runs and the guard is never re-evaluated.
**Observed:** a `loop` state with `entry: ["inc"]` and `always: [{target:"done", guard:"n>=5"}, {target:"loop"}]` was expected to reach `done` with `n == 5`; it ran once and parked at `loop` with `n == 1`, `is_running == True`, no error. A19 confirms the identical loop via a distinct intermediate state converges correctly.
**Impact:** "accumulate until a threshold" is the canonical iceberg-slicing and rule-counting shape. Whether it works or silently hangs depends on whether the author happened to route through a second state.
**Workaround:** never self-target; route loops through a distinct state; write `reenter: true` on every intentional self-transition; lint both.
**Suggested upstream fix:** treat an **explicit** self-target as external by default (XState v5 semantics), with `internal: true` / omitting the target as the opt-out — and read `internal` as well as `reenter`. Failing that, at least warn loudly when an `always` self-target is configured, since it can never make progress.

---

### LC-05 🟠 Timers degrade catastrophically under load and do not survive restore

**Evidence:** Study 04 §3 (`bench_c_timers.py`) and §4 (`bench_d_snapshot.py`).
**Observed:** idle error +6 to +16 ms, always late (Windows' ~15.6 ms granularity is a floor). With 100 busy interpreters: ~+500 ms. With 500: **+2,250 ms for a 10 ms timer**, and roughly the same absolute error for 100 ms and 1 s requests — the signature of event-loop starvation. Separately, a machine snapshotted with 700 ms left on an 800 ms timer never fired after restore, even 1.5 s later (documented behaviour).
**Impact:** TWAP intervals, chase repricing (200 ms), iceberg refills (250 ms), pong deadlines (10 s), SL attach deadlines (2–3 s) and watchdog scans (5 s) are all unsafe on `after`. A TWAP drifts by seconds precisely during a volatility burst; a starved liveness watchdog reports health by silence.
**Workaround:** A2 — one external `MonotonicScheduler` owns every deadline; deadlines are absolute timestamps in context; the scheduler injects events; restore re-arms from context and fires already-expired deadlines immediately.
**Suggested upstream fix:** (a) run timers on a dedicated task/thread that is not starved by the event queue, or at least document the starvation characteristic prominently — it is not mentioned in the docs; (b) offer an optional `resume_timers=True` on `from_snapshot` using persisted remaining durations.

---

### LC-06 🟠 `raise` is queued behind pending external events (no macrostep semantics)

**Evidence:** Study 05 §2.7 (C10). `raise` goes through `_deliver` onto the same FIFO queue as external sends.
**Observed:** expected `["entry","RAISED","EXTERNAL"]`, got `["entry","EXTERNAL","RAISED"]`.
**Impact:** the microstep/macrostep distinction XState guarantees does not hold. A state's raised follow-up can be observed *after* an external event that arrived during the transition. Behaviour is deterministic, so it is consistency, not chaos — but any logic that assumes "my raised event settles first" is wrong.
**Workaround:** every aggregate decision must be a pure function of context, never of arrival order (see B2). Documented as a binding rule.
**Suggested upstream fix:** a separate internal queue drained to exhaustion before the next external event is dequeued — this is the SCXML macrostep algorithm and the library otherwise implements SCXML faithfully.

---

### LC-07 🟠 Over-forgiving target resolution can silently bind the wrong state

**Evidence:** Study 01 §4.8 / §14.4. Both engines wrap resolution in a multi-stage fallback (`base_interpreter.py:1164-1261`) ending in an **exhaustive tree walk matching on the last id segment** (`:1238-1250`).
**Impact:** `target: "filled"` can resolve to an unrelated `…somewhere.else.filled` in a different branch — silently, with no warning. In a machine with repeated leaf names (`filled`, `cancelled`, `failed` appear in Order, Leg, and every algo) this is a live hazard.
**Workaround:** A5 — absolute `#machine.path` targets only; a build-time validator that resolves every target against the tree itself and fails on ambiguous last segments.
**Suggested upstream fix:** make the last-segment tree walk opt-in (`strict_targets=True` should be the default), and warn on every fallback stage beyond exact resolution.

---

### LC-08 🟠 A raising guard is swallowed as `False`

**Evidence:** Study 05 §2.9 (A20); `base_interpreter.py:2911-2925`. Documented behaviour.
**Impact:** a *crashing* risk check and a *failing* risk check are indistinguishable. In an `or` composition, or with a permissive fallback branch, a crashing guard can fall through to the permissive path. For live-enablement gating, kill-switch checks and the SL ratchet, that is the wrong default.
**Workaround:** A6 — safety guards are written in deny polarity, carry their own try/except returning an explicit `False`, and log at ERROR. Restrictive transitions (invalidate evidence, engage lockout) are left **unguarded** so a guard failure cannot block them.
**Suggested upstream fix:** a `guard_error_policy` option (`false` | `true` | `raise`), defaulting to today's behaviour but allowing `raise` for safety-critical machines. At minimum, fire `on_guard_error` on plugins — today the failure is invisible to observers.

---

### LC-09 🟠 `send()` is fire-and-forget with unbounded queueing latency

**Evidence:** Study 01 §11 (`send()` is `await queue.put(...)`; the caller cannot await the resulting transition); Study 04 Budget 1 (65 ms p50 / 95 ms p95 queueing with 500 busy machines) and §3 (~2.2 s under saturation).
**Impact:** any control action whose *effect* must be immediate — kill switch, risk lockout, halt-new-orders — cannot be enforced by sending an event. Under the exact conditions where you press the kill switch (loop saturated), the delay is worst.
**Workaround:** enforcement is a synchronous flag consulted by the `Validator`, set *before* the machine event is dispatched. The statechart records and orchestrates; it does not gate (B18, B20).
**Suggested upstream fix:** an awaitable `send()` returning a future resolved after the event is processed (XState's `actor.send` is sync-and-immediate; this library's is neither), and/or a priority-send that jumps the queue.

---

### LC-10 🟠 Restore does not restart invokes or re-run entry actions — parked machines look healthy

**Evidence:** Study 05 §2.10 (C6, C7) and Study 04 §4. Explicitly documented, so this is a limitation rather than a bug — listed because the consequence is severe and easy to miss.
**Observed:** a snapshot taken mid-`invoke` restored with `calls == 0` — the service never re-ran. A snapshot taken mid-`after` never fired.
**Impact:** after a crash, an order restored in `submitting` has no request in flight, a reconciliation restored in `fetching` has no sweep running, a TWAP restored in `armed` has no deadlines. All report `running`. Silent, fleet-wide stall.
**Workaround:** §C3.3 boot procedure — re-arm every deadline (firing already-expired ones), re-drive every invoke state by re-sending the entering event, and reconcile against the exchange before accepting traffic. Every invoke state is authored to be re-enterable.
**Suggested upstream fix:** an opt-in `restart_services=True` / `resume_timers=True` on `from_snapshot`, or at minimum an API that reports "these restored states have invokes that are not running" so the application can drive them without walking the tree itself.

---

### LC-11 🟡 No snapshot schema version

**Evidence:** Study 01 §9, §13.12. `from_snapshot` will happily load an old-shaped snapshot and partially mis-restore it.
**Impact:** a machine-shape change between releases silently mis-restores live orders.
**Workaround:** our own `cv_schema_version` + `machine_hash` envelope, an upcaster registry, and fail-closed on an unknown hash.
**Suggested upstream fix:** write a `version` field into `get_persisted_snapshot()` and validate it on restore; optionally a machine-structure hash.

---

### LC-12 🟡 `invoke.input` is static and is ignored entirely for child-machine actors

**Evidence:** Study 01 §13.3; `InvokeDefinition.input` is a static dict (`models.py:469`); `_spawn_and_manage_actor` never reads `invocation.input` (`interpreter.py:1173-1252`).
**Impact:** the natural way to pass a leg's frozen `profile_snapshot` into a child machine does not work. XState's callable `input: ({context, event}) => …` has no equivalent.
**Workaround:** spawn explicitly and seed the child's context ourselves.
**Suggested upstream fix:** support callable `input` and actually apply it to spawned child machines' context.

---

### LC-13 🟡 No typed context or events; no payload validation; no strict mode

**Evidence:** Study 01 §5, §13.1; Study 05 §2.11 (C12). `TContext` is bound to `Dict[str, Any]`; `send("E", qty="not-a-number")` is accepted silently; there is no `strict` option anywhere in the source.
**Impact:** the whole surface is stringly-typed in a codebase where 24 §1.1 mandates pydantic models on every boundary. A typo'd event name is a silent no-op (it is just an unknown event).
**Workaround:** `MachineGateway` with a closed `StrEnum` of event types per family, pydantic payload validation at the boundary and re-validation inside actions; lint that nothing else calls `send()`.
**Suggested upstream fix:** a `setup({types})` analogue accepting TypedDict/pydantic models, and a `strict=True` that raises on unknown event types and unknown targets.

---

### LC-14 🟡 `SyncInterpreter` is not actually single-threaded and rejects async services

**Evidence:** Study 04 §6; Study 01 §11.
**Observed:** `after` timers fire under `SyncInterpreter` with no event pump (a machine advanced purely from a `time.sleep()` on the main thread), implying a background timer thread that mutates context concurrently with caller code — with **no locks anywhere in the codebase**. Separately, an `async def` service raises `NotSupportedError` (a clean, correct, early failure — good design).
**Impact:** reading `interp.context` while a timer thread mutates it is unsynchronised. Not called out in the docs.
**Workaround:** async `Interpreter` only, enforced by lint. (Also: sync is only 1.25× faster, so there is no performance reason to reach for it.)
**Suggested upstream fix:** document the threading model of `SyncInterpreter` explicitly, and either add a lock around context/queue access or refuse `after` in sync machines.

---

### LC-15 🟡 Throughput is a fixed global budget, not per machine

**Evidence:** Study 04 §2 (`bench_b2_scaling.py`): 1 machine 21,231 ev/s; 1,000 machines 18,152 ev/s **aggregate** (18.2 each).
**Impact:** the single most important architectural fact in the study. Capacity planning is per process. The measured consequence is Budget 2's failure (rule evaluation short by 2.2–6.5×) and Budget 1's tightness (165 ms p95 of pure queueing against a 300 ms budget).
**Workaround:** R1/R2/R3 hosting rules; lazy rule instances; process split as the designated escape (ADR-0004 already pre-designs it).
**Suggested upstream fix:** none realistic — this is asyncio, not the library. But the docs should state it plainly; a reader could reasonably assume N interpreters scale.

---

### LC-16 🟡 Unknown targets and relative `.child` targets are silent no-ops

**Evidence:** Study 05 §2.4 (A5, A18) and §2.5 (C15).
**Observed:** `target: ".A2"` → `[]`, state unchanged, nothing raised. `target: "nowhere_at_all"` passes `create_machine()` and does nothing on send. Contrast C14: an unknown **action** name correctly raises `ImplementationMissingError` at build time.
**Impact:** for config-driven rule IR, a bad rule deploys clean and fails open at runtime. Leading-dot relative syntax is standard XState and all over the Stately docs, so this will be written by anyone following upstream documentation.
**Workaround:** A5 — absolute targets, build-time validation, deploy-time validation for compiled rules.
**Suggested upstream fix:** validate targets in `create_machine()` exactly as actions are validated; implement or explicitly reject `.child` syntax rather than silently resolving it to `None`.

---

### LC-17 🟡 No per-transition / per-invoke timeout

**Evidence:** absent from the API surface (Study 01 §2).
**Impact:** 24 §11.5 E8 mandates `evaluation_timeout_ms`; there is no library mechanism.
**Workaround:** `asyncio.wait_for` inside the service so the timeout surfaces as `onError`.
**Suggested upstream fix:** `invoke: {..., "timeout_ms": N, "onTimeout": {...}}`.

---

### LC-18 🟡 Cross-thread `send()` silently loses events

**Evidence:** Study 04 §7 (g6). A bare `interp.send(...)` from a foreign thread returns a coroutine that is never awaited — no exception, event lost. `run_coroutine_threadsafe` works (500/500 delivered) at 336 µs/event, 10× the in-loop cost.
**Impact:** any `run_in_executor` work (20 §4.1 permits it for DuckDB, Parquet, Argon2, crypto) that tries to notify a machine loses the event.
**Workaround:** `SafeInterpreter.send_threadsafe()`; lint bans bare `.send(`.
**Suggested upstream fix:** detect the foreign-thread case and either raise or dispatch via `call_soon_threadsafe`. Returning an un-awaited coroutine with no warning is the worst of the three options.

---

### LC-19 🟡 Guards continue to be evaluated after a branch is selected

**Evidence:** Study 05 §2.8 (A6). Guard array `[g1 false, g2 true, g3 true]` selects correctly but calls all three.
**Impact:** harmless for pure predicates; wrong for guards that count, log, cache or meter. It also wastes measurable time in a system where transition cost is the bottleneck.
**Workaround:** A6 — guards are pure. (Which we want anyway.)
**Suggested upstream fix:** short-circuit guard evaluation at the first match.

---

### LC-20 🟡 Unbounded interpreter queue; no backpressure signal

**Evidence:** Study 01 §11 (single unbounded `asyncio.Queue`); Study 04 Budget 1 latency.
**Impact:** bursts become latency and memory rather than a visible signal; queue depth is not observable through any public API.
**Workaround:** a bounded queue in front of the gateway, with the 20 §4.2 policy applied there; export `cv_machine_queue_depth` from our own counter.
**Suggested upstream fix:** expose `qsize()` / a `queue_depth` property, and support an optional bounded queue with an overflow policy.

---

### LC-21 🟡 `get_snapshot()` hardcodes `indent=2`

**Evidence:** Study 04 §4 — snapshot JSON 3,976 B as produced vs 2,249 B compact (1.77×); `get_persisted_snapshot()` is also 30 % faster.
**Impact:** pure waste in disk and bandwidth for a recorder writing per-entity snapshots.
**Workaround:** always use `get_persisted_snapshot()` + our own compact `json.dumps`.
**Suggested upstream fix:** accept `**json_kwargs`, or default to compact.

---

### LC-22 🟡 No hierarchical `state.value`; active states are a flat set of ids

**Evidence:** Study 01 §13.7.
**Impact:** XState consumers and the Stately visualiser expect `{parent: 'child'}`. Our WS projection and any `@xstate/react` live overlay must reconstruct it.
**Workaround:** a projector that rebuilds `value` from the flat id set plus the machine tree (§C4.2).
**Suggested upstream fix:** add a `value` property producing the hierarchical form — it is a pure function of data the library already has, and it is what makes visualiser interop actually work.

---

### LC-23 🟡 The "pure" API is slower than the interpreter and does not run imperative actions

**Evidence:** Study 04 §1 — 77.2 µs vs 33 µs (2.4× slower); after `SUBMIT` the state advanced while `context["qty"]` stayed `0.0`, verified directly.
**Impact:** it is advertised as the no-overhead path and is a pessimisation. More importantly, unit tests written against it silently test transitions **without effects** — a test suite that looks thorough and verifies nothing about behaviour.
**Workaround:** use it only for transition-table tests, and document that limitation in the test module docstring so no one mistakes green for correct.
**Suggested upstream fix:** document that it only executes declarative `assign`; investigate the 2.4× overhead (it should be the fast path).

---

### LC-24 ⚪ Project maturity: single maintainer, no independent production adoption, rapid API churn

**Evidence:** Study 06 and Study 02.
**Facts:** 14 stars, 1 fork, exactly one filed GitHub issue ever, one maintainer, ~11 releases in under a year (0.2.x→0.7.x). No blog posts, case studies or Stack Overflow discussion of production use outside the author's own materials. 2,805 tests pass at 87 % coverage, but `base_interpreter.py` sits at 86 % with misses concentrated in rollback and cancellation branches — the paths CandleViewer leans on hardest. Both 0.6.0 and 0.7.0 disclose CRITICAL "silent wrongness" defects that had survived thousands of passing tests. `test_engine_conformance.py` exists because the sync and async engines had silently diverged in six release-blocking ways. The one previously known bug is in the camelCase↔snake_case logic-mapping seam — exactly the mechanism CandleViewer would use to wire XState JSON to Python callbacks.
**Impact:** CandleViewer would be the first-line battle-tester, not a beneficiary of anyone else's. Competing options (`sismic`, `python-statemachine`, `transitions`) have years of issue-tracker evidence; `temporalio` solves the durability problem natively that we must otherwise build ourselves (§C3.3).
**Workaround:** pin the exact version; vet each changelog; maintain `tests/xstate_contract/` as the bump gate (§C5.4); file an issue upstream for every entry in this register.
**Note:** the owner *is* the maintainer, which changes the risk calculus — fixes are available rather than hoped for. That is a genuine advantage, and it is also why this register is written as a work list rather than a rejection.

---

## D2. Upstream issues to file (priority order)

| # | Title | LC | Value to us |
|---|---|---|---|
| 1 | Action errors commit the transition with no programmatic error channel | LC-01 | Removes four layers of defensive scaffolding from the order path |
| 2 | Events with no handler in the current state are silently dropped — add `defer` | LC-03 | Removes the deferral pattern from every transient state; fixes replay fidelity |
| 3 | `always` self-target never re-enters — silent deadlock | LC-04 | Removes a whole class of silent stall |
| 4 | `sendTo` cannot address actors by `id`/`systemId` | LC-02 | Lets fan-out use the library's own actor routing |
| 5 | Timers starve under event-loop load; document and/or isolate | LC-05 | Would let coarse timeouts stay in-machine |
| 6 | Unknown/relative targets are silent no-ops; validate at build time | LC-16, LC-07 | Removes our build-time validator |
| 7 | `raise` should settle within the macrostep | LC-06 | Restores XState semantic parity |
| 8 | Add snapshot schema version + optional `restart_services` / `resume_timers` | LC-11, LC-10 | Simplifies the boot procedure substantially |
| 9 | Guard error policy + `on_guard_error` hook; short-circuit guard evaluation | LC-08, LC-19 | Makes safety guards honest |
| 10 | Hierarchical `state.value`; compact `get_snapshot`; queue depth; thread-safe `send` | LC-22, LC-21, LC-20, LC-18 | Ergonomics and observability |

---

# Part E — Consolidated changes to plan docs and tickets

## E1. Plan-document changes

| Doc | Section | Change |
|---|---|---|
| `24-internal-schemas.md` | §8.2 | Two-region Order statechart; add `quarantined`; add binding rules **S10** (deferral/no dropped fills) and **S11** (no action may raise) |
| | §8.5 | Reconciliation statechart; add `stale_lockout` state |
| | §8.8 | Position-protection statechart; **reconcile the SL deadline (2 s in §8.8 vs 3000 ms in ADR-0008)**; add rule 6 (protection asserted only from an exchange read) |
| | §9.5.1 | Express the per-account unwind as the nested chart; note the retry-counter/`reenter` requirement |
| | §9.6 | Add `aborting`; group status is a pure function of leg counters |
| | §10.1 | Universal rule **(6)**: no algo uses in-machine timers; deadlines are absolute timestamps in context |
| | §10.2–10.5 | Add each algo statechart; OCO `overshoot` as a named state; chase reprice interval as a monotonic guard, not a timer |
| | §11.5 | **E13**: trigger dispatch is pre-filtered by index; rule lifecycle is a statechart, rule evaluation is a pure function |
| | §11.7 | Lockout statechart with `warning`; kill-switch enforcement is a synchronous flag, not an event |
| | §12 / §12.4 | Fill model/queue estimator explicitly not statecharts; add the paper-account liquidation FSM |
| | §13.1 | Add `lingering` to `RecordingState.state` |
| | §13.7 | Determinism clause **(5)**: no silent event drops; parity is over *delivered event sets* |
| | §15.1 | Two-region session statechart; `elevated_until` derived from the elevation region |
| | **new §13.8** | `Alert` / `AlertDelivery` models and lifecycle (today alerts exist only in E40, not in 24) |
| `20-architecture.md` | §3.1 | Connection statechart; `budget_blocked` state |
| | §3.2 | Book health FSM; **deltas never enter a state machine**; new `ChaseTargetTracker` component |
| | §4.1 | Rule **(6)**: no market-data event reaches an interpreter; statecharts receive control/lifecycle events only |
| | §4.3 | Kill-switch enforcement precedence clarification |
| | §6.3 | Add "statechart fleet degraded" to the degraded-mode matrix |
| | §12.1 | Add `cv_machine_*` metrics; "Statechart fleet" dashboard |
| `ADR-0006` | Consequences | Library commits transitions whose actions failed; write-ahead events + reconciliation are mandatory, not optional |
| `ADR-0007` | Consequences | IR compiles to a Python evaluator, not to a statechart — cite Study 04 Budget 2 |
| `ADR-0008` | rules 2, 8; Consequences | SL deadline reconciliation; kill-switch enforcement precedence; leg actors addressed via our own registry (LC-02) |
| **new ADR-0017** | — | "Statechart hosting, scope and the shared event-loop budget" — records R1/R2/R3, the per-tick/lifecycle split, and the library challenges accepted |
| `06-performance-and-load-standard.md` | — | Budgets for machine event throughput (alert at 8k/s) and algo scheduler fidelity under load |

## E2. Backlog changes

| Ticket | Change |
|---|---|
| **New: E29-T10** | Machine-definition linter (absolute targets, `reenter`, deferral coverage, action-decorator coverage, no side-effecting guards). Gates E29-T03. |
| **New: E29-T11** | `SafeInterpreter` + `MachineGateway` shared utility (validation, dedupe, bounded queue, thread-safe send, metrics). Needed by every module. |
| **New: E29-T12** | Machine persistence: `machine_snapshots` / `machine_events` migrations, versioned envelope, upcaster registry, boot-restore procedure (§C3.3). |
| **New: E34-T\*** | Unwind leg statechart + `UnwindResumer` (currently prose in 24 §9.5.1 with **no ticket anywhere in the backlog**). |
| **New spike: E29-K02** | Stately/`@xstate/react` interop: author one real OMS sub-machine both ways, diff the JSON, round-trip through `create_machine()` and a React loader, verify the reconstructed hierarchical `value` (LC-22). Study 03 §5 flags this as untested by us. |
| **New: E04-T\*** | Statechart observability: `CandleViewerPlugin`, `cv_machine_*` metrics, the `ERROR`-log→P1-alert handler, the fleet dashboard. |
| E29-T03 | Scope grows (machine JSON, `MachineLogic`, `@cv_action`, deferral). Re-estimate. |
| E29-Q04 | Add chaos: fill during `submitting`; action raises mid-fill → quarantine. |
| E33-K01 | Validate the external `MonotonicScheduler` + context-held deadlines; measure refill/slice fidelity under 500 concurrent machines. |
| E33-T01 | `MonotonicScheduler` as an explicit deliverable of AlgoSupervisor. |
| E33-S01 | Acceptance: a fill on the other leg during settlement is applied, not dropped. |
| E33-S03 | Acceptance: TWAP slice-interval error p95 ≤ 100 ms with 500 resident order machines. |
| E33-S04 / E33-Q03 | Chase input event rate bounded to ≤10 Hz; assert it. |
| E35-S02 / E35-S07 | "Guards" are IR guards in Python; conflict arbitration is a deterministic sort, not racing machines. |
| E35-Q04 | Rule throughput measured **with 500 order machines resident**. |
| E39-K01 | Spike output must cover "day boundary passed while the process was down". |
| E39-S02 | Test: restart across a day boundary while locked. |
| E39-S03 / E39-Q03 | Kill switch blocks the next order **with the loop saturated**. |
| E39-T01 | Edge-triggered emission into the lockout machine. |
| E40-T03/T04 | Adopt the alert chart; `partially_delivered` and `delivery_failed` as distinct states. |
| E44-T04 | Adopt the live-gate chart; `eligible` distinct from `locked`; the feature flag becomes a projection. |
| E45-T01/T02/T03 | Adopt the reconciliation chart; add `stale_lockout`. |
| E45-T06/T07 | Chaos: crash during `fetching` → restart → assert the sweep is re-driven (exercises LC-10). |
| E26-T06 | Parity harness diffs **delivered event sets** per machine, not only derived outputs. |
| E16 | `lingering` state in the recorder status API and admin panel. |
| E09 | Session machines single-process-owned; document the ~100-session threshold. |
| E38 | Paper-account liquidation FSM, edge-triggered. |
| E08 | Adopt the connection chart; `budget_blocked`; consume the shared `SafeInterpreter`. |
| E12 (testing pyramid, ADR-0012) | Add `tests/xstate_contract/` as the library-bump gate. |

---

## E3. Recommendation

**Adopt, scoped, with the mitigations in Part A treated as non-negotiable.**

The library earns its place on the OMS, trade-group, algo-supervision, connection, session, gating and reconciliation components — 10 of 20 rate Good or Excellent, and the measured evidence on the hardest properties (parallel/nested snapshot fidelity, FIFO ordering, invoke cancellation, actor teardown, determinism) is genuinely strong, in several cases stronger than expected. Replacing the hand-rolled state machines those components would otherwise need is a real win in reviewability and in the ability to *show* the owner the order lifecycle as a diagram generated from the code that runs.

It must be kept out of the hot path — rule evaluation, ingestion, paper matching — where the measured shortfall is 2.2–6.5× and no tuning closes it.

And the honest headline, restated from Study 04: **the error-handling philosophy is the problem, not the performance.** The library consistently prefers staying alive over failing loudly. That is a defensible default for UI workflows and the wrong default for an order path, where a silently committed wrong transition costs money. LC-01, LC-03, LC-04 and LC-16 are all instances of it. Every one is mitigable, all four mitigations are cheap, and all four fail *silently* if a developer forgets them — which is why Part A's rules are enforced by a linter and a contract-test suite rather than by a style guide.

If upstream fixes 1–3 from §D2 land, three of the four highest-severity mitigations disappear and this becomes a straightforward Good-to-Excellent fit across the board.
