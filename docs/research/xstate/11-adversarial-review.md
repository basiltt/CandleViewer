# 11 — Adversarial Review of the `xstate-statemachine` Adoption Proposal

**Target of review:** `10-fit-analysis.md` (Parts A–E), supported by studies `01`, `02`, `04`, `05`, `06`.
**Library:** `basiltt/xstate-statemachine` 0.7.0 — 12,104 LOC across 9 modules, zero runtime deps, MIT, `requires-python >=3.9`.
**Date:** 2026-09-15
**Stance:** this document's job is to **refute** the proposal. Where refutation failed, that is stated as plainly as where it succeeded.
**New evidence:** eight adversarial probes written for this review, in `docs/research/xstate/adversarial/` (`adv01`–`adv08`), run against `.venv-xstate` (CPython 3.13.7, Windows 11, 4C/8T Kaby Lake-R mobile). Every number below labelled **[NEW]** was measured here, not inherited from studies 01–06.

---

## 0. Executive answer

The adoption proposal **survives**, but three of its load-bearing claims do not, and one component it rates `Good` should be downgraded.

| Claim in `10` | Verdict |
|---|---|
| "Pre-filtering rescues the rule-engine budget" (B9, C6) | ❌ **Refuted.** Pre-filter must reach ≥99 % rejection, not the 10–100× (90–99 %) the doc claims is sufficient. **[NEW]** |
| "Snapshot + reconcile makes crash recovery safe" (A7, C3.3) | ⚠️ **Partially refuted.** The snapshot durably persists a *corrupted* state produced by a failed action, and the deferral buffer is persisted-but-never-drained. **[NEW]** |
| "Machine JSON versioning is handled by `machine_hash` + upcasters" (C3.4) | ⚠️ **Partially refuted.** Renames fail loud (good), but *semantic* drift at a stable state id restores silently into a different machine. **[NEW]** |
| "Kill switch must bypass the queue" (B18) | ✅ **Confirmed and strengthened** — measured 33.5 ms p50 / 50.8 ms max at a realistic 2,854-interpreter fleet. **[NEW]** |
| "One interpreter per entity, ~1,800 worst case, ~76 MB" (C1.2) | ✅ **Confirmed; the memory estimate is 4.5× pessimistic.** Measured 5.9 KB/interpreter, 16.7 MB for 2,854. **[NEW]** |
| Fan-out rate-limit governor as a statechart | ❌ **New Not-suitable.** Never addressed in `10`; admission control is a synchronous pre-flight call and a statechart makes it ~238,000× slower. **[NEW]** |
| "Actor spawn is cheap and flat" (B2) | ⚠️ **Qualified.** Cheap in time and memory, but **2 asyncio tasks per invoked child**, one polling at 5 ms. **[NEW]** |
| "Hot paths must stay plain code" (R1, B14, B15) | ✅ **Confirmed, and should be tightened** — even *gating* by querying an interpreter is 12× a bool read. **[NEW]** |
| Single-maintainer risk is the dominant ecosystem risk (LC-24) | ⚠️ **Overstated.** 12k LOC, zero deps, MIT, owner-maintained. Vendorability is the real mitigation and `10` underweights it. |

**Final recommendation:** adopt for the lifecycle/supervision set; do not use for the five paths listed in §5. Full lists in §5.

---

## 1. Confirmed risks

These survived every attempt to argue them away. Ordered by what they cost if ignored.

---

### CR-1 🔴 A failed action does not just commit a wrong transition — it is **durably persisted** as truth **[NEW]**

`10` treats LC-01 as an in-memory hazard mitigated by `@cv_action` + reconciliation. Probe `adv01` t5 shows the failure reaches the *snapshot*:

```
trace=['persist', 'explode', 'entry_b']
states=['x.b']  status=running
SNAPSHOT PERSISTS THE BROKEN STATE: ['x.b'] ctx={'persisted': True, 'in_b': True}
```

The third action (`notify`) never ran, yet the machine is in `b`, `status == "running"`, and `get_snapshot()` serialises `b` with a half-applied context. If the snapshot writer fires on state change — which C3.2 mandates ("snapshot on state change, not on a timer") — **the corrupted state is written to Postgres before anything notices**. On restart, `from_snapshot` restores it without complaint. Reconciliation is then repairing a state the database asserts is correct.

**Why this is worse than LC-01 as written:** LC-01's four mitigation layers are all *runtime* layers. None of them prevents persistence. The snapshot path has no visibility into whether the transition that produced the state was clean.

**Required constraints:** MUST-01, MUST-02.

---

### CR-2 🔴 The mandated deferral buffer is persisted but never drained after a crash **[NEW]**

`10` A3 mandates `_deferred` + `drain_deferred` as the universal answer to LC-03. Probe `adv06` tests it under crash:

```
[defer_crash] snapshot state=['o.submitting'] _deferred=[e0, e1, e2]
   after restore+start: state=['o.submitting'] filled=0 _deferred_still=3
```

Three fills were correctly deferred, correctly persisted, and then **silently stranded forever**. The drain lives in `submitted`'s `entry`; `submitted` is only reachable via `done.invoke.place`; the invoke is not restarted on restore (LC-10); so `entry` never runs. The machine sits in `submitting` looking healthy with three unapplied fills in its own context.

C3.3 step 4 ("re-drive invoke states") is the only thing standing between this design and lost fills, and `10` correctly labels it "mandatory and has no library support" — but it does not connect it to the deferral buffer. The two workarounds are **coupled**: A3 is only safe if C3.3-step-4 is implemented perfectly, for every family, forever. Two independent silent-failure mechanisms composed into one.

The happy path does work (`adv06` t_ok: `filled=3`), which is precisely why this will pass every test that does not kill the process mid-invoke.

---

### CR-3 🔴 The deferral workaround destroys exchange event ordering **[NEW]**

Probe `adv06` t_reorder. `drain_deferred` must re-`send` buffered events, which means they re-enter the queue *behind* anything that arrived in the meantime, and `create_task(send)` gives no ordering guarantee relative to live traffic:

```
[defer_reorder] delivery order = ['old0','old1','old2','LIVE']
```

In this run order happened to hold. It is not guaranteed by anything — it is an artifact of `create_task` scheduling and queue timing. 24 §8.2 S5 requires `(ts_exec, seq)` ordering with fills always applied. The library's strict-FIFO guarantee (Study 04 g7), which `10` C2.3 leans on as "exactly what an OMS needs", **does not extend across a defer/drain boundary** — and every transient state on the order path has one by mandate.

**Consequence:** FIFO is not a property the OMS may rely on. `apply_fill` must be order-independent and sort by `(ts_exec, seq)` itself. `10` C2.3's "Within one machine, ordering is exactly what an OMS needs" is **wrong as stated** once A3 is applied.

---

### CR-4 🟠 The rule-engine pre-filter mitigation does not close the gap **[NEW]**

This is the most important refutation in the document, because `10` B9 and Study 04 Budget 2 both present pre-filtering as the rescue ("cut evaluations by 10–100× and makes the budget comfortable").

Probe `adv05`, 1,000 rule machines at realistic fleet shape:

```
[fleet_throughput] 1000 rule machines, 30000 events: 8,813 ev/s aggregate
   pre-filter hit-rate 100.0%: required   200,000 machine-ev/s -> FAIL
   pre-filter hit-rate  10.0%: required    20,000 machine-ev/s -> FAIL
   pre-filter hit-rate   5.0%: required    10,000 machine-ev/s -> FAIL
   pre-filter hit-rate   1.0%: required     2,000 machine-ev/s -> OK
   plain-python 200,000 predicate evals: 30 ms -> 6,559,678 eval/s
```

Two findings, both worse than `10` assumes:

1. **8,813 ev/s, not 20,000.** The ~20k figure in Study 04 §2 is a bare transition loop. A *realistic* rule machine — guard evaluation, a guarded branch list, a `reenter` self-transition — halves it. `10`'s R3 alarm threshold of 8,000 ev/s is therefore not "40 % of the floor"; it is **essentially the entire realistic budget for this machine shape**.
2. **The required pre-filter hit-rate is ≥99 %, not 90–99 %.** A 10× filter (the low end of Study 04's recommendation) still demands 20,000 machine-ev/s — 2.3× the measured realistic ceiling, before the OMS gets a single event. Only a 100× filter fits, and it fits by consuming ~23 % of the whole process budget.

For calibration: plain Python does the *entire unfiltered* 200,000 eval/s workload in **30 ms — 6.5 M eval/s, ~744× the statechart fleet.**

**This does not change B9's verdict** (`10` already says Not suitable for per-tick evaluation). It changes the *margin*: the doc presents the split as comfortable once pre-filtered. It is not comfortable — it is conditional on a filter quality nobody has built yet, and a filter that underperforms its target degrades the **OMS**, not the rule engine, because the budget is shared.

---

### CR-5 🟠 The fan-out rate-limit governor must not be a statechart — and `10` never says so **[NEW]**

A gap, not an error. `10` Part B has no component for the per-account token-bucket governor (20 §4.3), yet B1's `validated` state calls `reserve_rate_token` as an action and B2's chart calls `reserve_rate_budget`. The governor is exactly the kind of thing a reader will reach for a statechart for — it has states (`open` / `starved` / `downshifted`), it has transitions, it looks textbook.

Probe `adv04`:

```
[governor] statechart RESERVE decision under 500-machine churn:
   p50=35.20ms p95=44.03ms max=53.18ms
   plain-python token bucket decision: 0.148 us -> ~238,264x slower
```

20 §4.3 is unambiguous that admission control is **pre-flight and synchronous** — `budget.reserve(entry, cost=1+sl_cost)` returns yes/no *before* any child is submitted, with `CV_FANOUT_ADMIT_WAIT_MS` = 750 ms for the whole all-or-nothing decision across N accounts. A statechart governor costs 35 ms p50 *per account* under load, so a 5-account `atomic` fan-out burns ~175 ms p50 / ~220 ms p95 of a 750 ms budget purely on asking permission — and it does so exactly when the loop is busiest, which is exactly when admission control matters. It also cannot answer synchronously at all: `send()` is fire-and-forget (LC-09), so "did I get a token?" requires a subscribe-and-wait round trip.

This is structurally identical to B18's kill-switch finding, and it generalises: **anything on the order path that must return an answer rather than record a fact cannot be a statechart in this library.**

---

### CR-6 🟠 Every invoked child actor costs two asyncio tasks, one polling at 5 ms **[NEW]**

Study 01 §12 notes the 5 ms poll (`_ACTOR_POLL_INTERVAL`); `10` B2 rates actors "the best-behaved subsystem measured" on spawn/teardown/leak and does not carry the poll cost forward. Probe `adv04`:

```
[tasks_per_actor] children -> asyncio.Task count
   children=   0 tasks=   2
   children=  10 tasks=  22   (delta 20 = 2 per child)
   children=  50 tasks= 102
   children= 200 tasks= 402
```

**Two tasks per invoked child, exactly linear.** One is the child's own event loop; one is the parent's `while child.status == "running": await sleep(0.005)` poll. At `10` C1.2's own worst case — 500 legs + 600 algo slices as child actors — that is **~2,200 tasks, ~1,100 of them waking 200×/s purely to ask "are you done yet?"**, i.e. ~220,000 wakeups/s of scheduler overhead on the same loop the OMS lives on.

Mitigating evidence, and it is real: `adv02` measured no detectable event-loop degradation at 200 children (`sleep(0)` median 3.8 → 5.3 µs; 5 ms timer drift flat at ~10.9 ms). The poll is cheap *per wakeup*. But the drift baseline is worth noting on its own — **~11 ms drift on a 5 ms sleep with an otherwise idle loop** is the Windows timer floor (~15.6 ms) showing through, independently confirming B7's conclusion that a 200 ms chase interval has no timing headroom.

**The constraint is therefore not "avoid actors" but "bound them".** 200 children is fine; 1,100 has not been measured and the linear task growth says it should be before it is built.

---

### CR-7 🟠 Semantic drift in machine JSON restores silently **[NEW]**

`10` C3.4's versioning scheme keys on `machine_hash` mismatch → upcaster → else fail closed. Probe `adv01` tests three drift classes:

| Drift | Result |
|---|---|
| State **renamed** (`submitted` → `working`) | ✅ `StateNotFoundError: Could not find state with ID 'ord.submitted'` — **fails loud** |
| Context **schema changed** (keys added) | ⚠️ restores; new default keys `cum_qty`/`venue` **MISSING** — v2 actions hit `KeyError` or silently use `.get()` defaults |
| Same state id, **different semantics** (guard added to `FILL`) | ❌ restores silently; order enters `submitted`, `FILL` is now guarded false, **order stuck forever** |

Row 1 is genuinely good and better than `10` credits — a renamed state cannot be mis-restored. Row 3 is the dangerous one and it is the *common* case: OMS evolution is far more often "add a guard / add a branch / tighten a condition" than "rename a state". `machine_hash` does catch it — but only because we compute it; the library contributes nothing. And a hash mismatch on *every* deploy means the upcaster registry is exercised on every release, which makes "fail closed on no upcaster" an operational trap: every routine deploy parks the fleet in `quarantined` unless someone writes a no-op upcaster, and writing no-op upcasters by reflex defeats the mechanism.

Row 2 is a second, quieter hazard: `from_snapshot` sets `interpreter.context = snapshot["context"]` wholesale (source: `base_interpreter.py:872`) — it does **not** merge new machine-default keys. Every context field added to a machine is a `KeyError` waiting for every pre-existing entity.

---

### CR-8 🟠 Events in the interpreter queue are lost on crash and invisible in the snapshot **[NEW]**

Probe `adv01` t4:

```
50 events sent; snapshot taken immediately shows n=0;
context after stop n=0; 50 events LOST on stop
```

The snapshot schema (confirmed by `adv07`: keys are `actors, configuration, context, error, history, output, state_ids, status, system`) has **no pending-queue field**. Everything between `send()` and the transition is volatile. Since `send()` is 2.26 µs and a transition is 33 µs, the queue is where events *live* under any burst — Study 04 Budget 1's 165 ms p95 is 165 ms of events sitting in exactly this volatile place.

`10` A7/C2.2 handles this correctly in principle — the bus and `order_events` are the durable record, the machine is a projection. But it must be stated as a hard constraint rather than left implicit, because the natural implementation (gateway reads from bus → `send()` → ack the bus) loses every in-flight event on crash.

---

### CR-9 🟡 Debugging a live fleet is materially worse than the proposal implies **[NEW]**

`10` C4 covers metrics and WS projection well. What it does not cover is what an operator has at 3 a.m. Probe `adv07`:

- `current_state_ids` is a **flat set** (`['o.life.b', 'o.prot.p']`) — LC-22, already known.
- The snapshot has **no timestamp, no event history, no machine hash, no schema version, no pending queue**. A snapshot cannot answer "how did this order get here?" — only "where is it".
- **A typo'd event name is indistinguishable from a legitimately unhandled one.** Sending `EE` instead of `E` left the machine unchanged, `status == running`, with 2 log lines that look exactly like a normal unhandled-event log. Combined with A3's mandate that *every* transient state declares `"*": {"actions":["defer"]}`, a typo'd event is not merely ignored — it is **silently appended to the deferral buffer and replayed later against a state that also does not handle it**.

The learning curve compounds this. A developer must hold simultaneously: XState semantics, the seven Part-A house rules, the four ways this library deviates from XState (`reenter`, absolute targets, no macrostep, flat state value), and the knowledge that violating any of them fails *silently*. `10` A1–A8 is enforced by a linter that does not exist yet (E29-T10) and a contract suite that does not exist yet (C5.4). Until both ship, the rules are a style guide, and every one of them fails silently when forgotten.

---

### CR-10 🟡 Terminal machines are not reaped **[NEW]**

Probe `adv04`: on reaching a final state, `status='done'`, `is_running=False` — but the interpreter object, its context, its queue and its registry entry all persist until *we* call `stop()` and evict it. For a system churning hundreds of orders a day through `filled`/`cancelled`/`rejected`, eviction is our job and there is no library support for it. `10` C1.2 notes ~3 MB/1,000-interpreter churn cycle of allocator retention; `adv03` independently measured **8.8 MB retained after full teardown + gc of a 2,854-interpreter fleet** (~3.1 KB/interpreter) — same order as Study 04's finding, confirming allocator arena retention rather than a reference leak.

---

## 2. Refuted concerns

Attempts to kill the proposal that **failed**. Stated as forcefully as the confirmed risks, because a review that only accumulates objections is not a review.

---

### RF-1 "Per-entity interpreter count explodes at 500 orders × legs × algos"

**Refuted, decisively.** This was the strongest prior objection and it does not survive measurement. Probes `adv02`/`adv03` built the full `10` C1.2 worst case — 500 orders + 500 legs + 600 algo slices + 1,000 rules + 100 protections + 154 miscellaneous = **2,854 interpreters**:

```
start cost = 88 ms (30.8 us each)
RSS delta  = 16.7 MB (5.9 KB each)
after queueing 20,000 events: +3.2 MB
after teardown+gc: 8.8 MB retained
```

`10` C1.2 budgets ~76 MB at 42 KB each. The real figure is **5.9 KB each, 16.7 MB total — 4.5× better than the doc's own pessimistic estimate.** (The 42 KB in Study 04 §2 was measured mid-burst with queued events; idle steady state is far cheaper.) Whole-fleet cold start is 88 ms.

**Memory and instance count are not a constraint at CandleViewer's scale and should be removed from the risk register.** The constraint is, as `10` correctly identifies, the shared event-loop budget — and CR-4/CR-6 are the sharpened forms of that.

### RF-2 "Process crash mid-transition leaves a torn state"

**Refuted as stated; the real risk is different.** A transition is not interruptible in a way that produces a partial *state*: the async engine processes one event at a time on one task, and `_execute_transition` either runs to completion or the process dies before the snapshot is written. `adv01` t5 confirms the active-state set is always coherent (`['x.b']`, never half-in/half-out), and Study 05 C4/C6 confirm exact round-trip of a 3-region parallel machine with a nested compound leaf.

What is *not* refuted is CR-1 (the coherent state is semantically wrong because an action failed) and CR-8 (queued events vanish). **The danger is not a torn state — it is a clean-looking state that is a lie.** That is a meaningfully different, and harder, problem.

### RF-3 "Machine JSON versioning is unsolvable"

**Refuted for the case that matters most.** A renamed or removed state raises `StateNotFoundError` on restore (`adv01` t1). This is the strongest failure signal the library gives anywhere, and it is exactly where a silent failure would be most expensive. `10` C3.4 does not credit it — worth correcting, because it means the fail-closed path is partly enforced by the library rather than entirely by us. The residual risk is CR-7 (semantic drift at a stable id) and the context-merge gap, both narrower than "versioning is unsolvable".

### RF-4 "Sharing one `MachineNode` across 500 interpreters will cause cross-talk"

**Refuted.** Study 01 §14.8 flags `transition.target_str` being mutated in place on shared definition objects as a race. `adv07` ran 200 interpreters over one `MachineNode`, sent `E` to exactly 100, and got 100/100 moved and 100/100 untouched — no cross-talk, no context aliasing. The mutation is an idempotent memoisation (target id → same target id), and the async engine serialises all interpreters onto one loop anyway, so the race window does not exist. **A8's 19×-cheaper shared-node mandate is safe.**

Caveat preserved: this reasoning depends on the single-loop model. It would *not* hold for `SyncInterpreter` with threaded timers — another reason that engine is disqualified (MUSTNOT-06).

### RF-5 "Statecharts will creep into the hot path"

**Refuted as a design risk, confirmed as a discipline risk.** `adv08` measured the *gating* pattern (`10` R1's "statecharts gate the hot path; they are never in it"):

```
interp.matches('live') = 0.746 us -> 3.58% of one core at 48k deltas/s
plain bool flag        = 0.060 us -> 12x cheaper
```

3.6 % of a core for the full 24-symbol book-delta rate is affordable — R1 is viable as written. But 12× a bool is a pointless tax for a value that changes a few times an hour. The fix is trivial and should be mandated: **the machine writes a plain `bool` on state entry; the hot path reads the bool and never touches the interpreter.** This also removes any coupling between hot-path code and the library's API, which is the real prize.

### RF-6 "Single-maintainer risk is disqualifying"

**Overstated in `10` LC-24, and the mitigation is stronger than the doc claims.** The facts are as Study 06 reports (14 stars, 1 fork, 1 issue ever, no third-party production adoption, 11 releases in under a year). But:

- The library is **12,104 LOC across 9 modules with zero runtime dependencies, MIT-licensed** (verified from `pyproject.toml` and `wc -l`). That is small enough to vendor, read end-to-end, and patch. The three largest files — `base_interpreter.py` (3,046), `sync_interpreter.py` (1,568), `pythonic.py` (1,542) — account for half of it, and CandleViewer uses neither of the latter two. **The code we actually depend on is roughly 5,000 LOC.**
- **The owner is the maintainer.** LC-24 notes this in passing; it deserves more weight. Upstream fixes are a scheduling decision, not a hope. The D2 issue list is a backlog, not a wishlist.
- Zero dependencies means no transitive supply-chain surface — a genuine advantage for a self-hosted trading system, and one that partly offsets the adoption-evidence deficit.

**Reframe:** the risk is not abandonment — it is that CandleViewer is the first-line battle-tester and will find defects in production that no one else has found. That is a *testing* obligation (C5.4's contract suite), not an *availability* risk. The vendor-fallback plan should be written down and costed once, then filed (MUST-08).

### RF-7 "Timer starvation makes the algos unusable"

**Refuted in the direction `10` already took.** A2 moves all timing to an external `MonotonicScheduler`, which sidesteps the library entirely. `adv02` incidentally confirms the floor is a *platform* property, not a library one: 5 ms sleeps drift ~10.9 ms p50 even with an idle loop and zero children. **No in-process Python scheduler on Windows will do better**, so the external scheduler must also compute deadlines from `time.monotonic()` and accept ~15 ms granularity — which B7's 200 ms chase interval tolerates, and which no `after`-based design would.

---

## 3. Required design constraints

Normative. Each is traceable to a confirmed risk and each is mechanically checkable. These are the constraints to import into `10`.

### MUST NOT

| # | Constraint | Source |
|---|---|---|
| **MUSTNOT-01** | **MUST NOT** put book-engine delta application, bar builders, footprint aggregation, paper-matcher fill/queue arithmetic, or per-tick rule condition evaluation in a statechart — in any form, including internal (actions-only) transitions. | B14, B15, B9, CR-4 |
| **MUSTNOT-02** | **MUST NOT** implement the per-account rate-limit governor / fan-out admission control as a statechart. It is a synchronous pre-flight decision; a statechart is ~238,000× slower and cannot answer synchronously. | CR-5 |
| **MUSTNOT-03** | **MUST NOT** query an interpreter from any path running faster than ~100 Hz. The machine publishes a plain `bool`/enum on state entry; hot paths read that. | RF-5 |
| **MUSTNOT-04** | **MUST NOT** rely on event ordering across a defer/drain boundary, or on interpreter FIFO as an OMS ordering guarantee. `apply_fill` and all aggregation actions **must** be order-independent and sort by `(ts_exec, seq)`. | CR-3 |
| **MUSTNOT-05** | **MUST NOT** use any statechart as an enforcement point for a safety decision (kill switch, live gate, risk cap, rate budget). Statecharts **record and orchestrate**; a synchronous flag or function **enforces**. | B18, CR-5 |
| **MUSTNOT-06** | **MUST NOT** use `SyncInterpreter` anywhere. Thread-per-timer, lock-free cross-thread `send`, no async services, and it breaks the shared-`MachineNode` safety argument in RF-4. | Study 01 §11, RF-4 |
| **MUSTNOT-07** | **MUST NOT** ack a bus message before the resulting transition is observed. The interpreter queue is volatile and absent from the snapshot. | CR-8 |
| **MUSTNOT-08** | **MUST NOT** exceed 200 concurrently invoked child actors per process without re-measuring. Task growth is 2 per child, one polling at 200 Hz; only up to 200 has been measured. | CR-6 |
| **MUSTNOT-09** | **MUST NOT** write a no-op upcaster to clear a `machine_hash` mismatch. Every mismatch is reviewed; a genuine no-op is recorded as an explicit, signed-off registry entry with a test. | CR-7 |

### MUST

| # | Constraint | Source |
|---|---|---|
| **MUST-01** | **MUST** gate snapshot persistence on transition cleanliness. The `@cv_action` wrapper sets `context["_fault"]`; the snapshot writer **refuses to persist** a snapshot whose context carries `_fault`, writes a `quarantined` marker row instead, and alerts P1. A corrupted state must never become the durable record. | CR-1 |
| **MUST-02** | **MUST** treat `machine_events` (write-ahead) as the sole book of record for the order family, with `actions_run` populated from the actual execution list, so a failed action is visible as a **short** `actions_run` versus the machine definition. This is the only forensic signal the library leaves. | CR-1, LC-01 |
| **MUST-03** | **MUST** drain `_deferred` at boot, unconditionally, **before** re-driving invokes — not only from a state's `entry`. Boot procedure C3.3 gains a step 3b: "for every restored machine with non-empty `context['_deferred']`, re-deliver its contents through the gateway with dedupe, then clear". | CR-2 |
| **MUST-04** | **MUST** alert on any machine whose `_deferred` is non-empty for longer than 5 s (`cv_machine_deferred_depth`). A stranded deferral buffer is otherwise completely invisible. | CR-2 |
| **MUST-05** | **MUST** achieve ≥99 % rejection in the rule trigger pre-filter, asserted as a test (`cv_rule_prefilter_rejection_ratio`), not an aspiration. A filter below 99 % degrades the **OMS**, because the budget is shared. Below 99 %, rule dispatch is disabled and alerts. | CR-4 |
| **MUST-06** | **MUST** merge machine-default context keys over the restored context on `from_snapshot` (`{**machine_defaults, **snapshot_context}`), in our restore wrapper. The library assigns the snapshot context wholesale. | CR-7 |
| **MUST-07** | **MUST** pin `xstate-statemachine == 0.7.0` exactly (`==`, not `~=` or `>=`), with the version, the source sha256 and the `tests/xstate_contract/` pass as a single gated artifact. No transitive dependency exists, so the pin is total. | LC-24, RF-6 |
| **MUST-08** | **MUST** vendor a copy of the library source at the pinned version into `third_party/xstate_statemachine/` (12,104 LOC, MIT, zero deps) with a documented one-line import switch, and a quarterly test that the vendored copy still passes the contract suite. This is the abandonment mitigation and it costs one afternoon. | RF-6 |
| **MUST-09** | **MUST** land the machine-definition linter (E29-T10) **before** the first statechart ships, not alongside. Every Part-A rule fails silently; an unenforced rule is not a rule. Minimum checks: absolute targets resolvable against the state tree; `reenter: true` on every self-target; wildcard deferral on every state reachable during an in-flight invoke; `@cv_action` on every registered action; no I/O in guards; deny-polarity on the safety-guard allowlist; no `.send(` outside the gateway. | CR-9, A1–A8 |
| **MUST-10** | **MUST** add a `cv_machine_unhandled_events_total{kind,event}` counter and **fail CI** if any event name sent by a gateway is absent from the corresponding machine's descriptor set. A typo'd event is otherwise silently deferred and replayed. | CR-9 |
| **MUST-11** | **MUST** explicitly `stop()` and evict every machine on reaching a terminal state, via a supervisor reaper. Export `cv_machine_live_count{kind}` and alert on monotonic growth. | CR-10 |
| **MUST-12** | **MUST** compute `machine_hash` in CI and **fail the build** when a shipped machine's hash changes without either a version bump or a registered upcaster with a golden-snapshot test. | CR-7 |

### MUST add library test X — `tests/xstate_contract/`

Beyond the suite `10` C5.4 already specifies, these are the tests that exist because of *this* review. Each is a direct regression for a confirmed risk, and each must run on every version bump as the gate.

| Test | Asserts | Guards |
|---|---|---|
| `test_failed_action_is_not_persisted` | An action raising mid-list ⇒ `_fault` set ⇒ snapshot writer refuses ⇒ P1 alert fired. Includes the raw-library assertion that the transition **does** commit, so a future upstream fix is detected. | CR-1 |
| `test_deferred_survives_crash_and_drains_at_boot` | Defer 3 fills mid-invoke → kill → restore → boot procedure drains and applies all 3 exactly once. | CR-2 |
| `test_fill_application_is_order_independent` | Apply a random permutation of N fills; assert identical final `filled_qty`/`avg_price`. Hypothesis-driven. | CR-3 |
| `test_queue_events_are_never_acked_early` | Events in the interpreter queue at crash are re-delivered from the bus, not lost. | CR-8 |
| `test_state_rename_fails_loud` | Restoring a v1 snapshot into a v2 machine with a renamed state raises `StateNotFoundError`. **Locks in the one loud failure the library gives us** — a future "more forgiving" release would break the fail-closed path. | RF-3, CR-7 |
| `test_context_defaults_merged_on_restore` | A context key added in v2 is present after restoring a v1 snapshot. | CR-7 |
| `test_shared_machine_node_no_crosstalk` | 200 interpreters, one `MachineNode`, disjoint event delivery, no state or context bleed. | RF-4 |
| `test_actor_task_growth_is_bounded` | Task count ≤ 2N + C for N invoked children; fails if the poll implementation changes shape. | CR-6 |
| `test_realistic_machine_throughput_floor` | A representative guarded rule/order machine sustains ≥ 8,000 ev/s at N=1,000. **Locks in the realistic floor, not the synthetic one.** | CR-4 |
| `test_reenter_semantics` | Self-target without `reenter` is internal; with `reenter: true` re-runs exit/entry. | LC-04, A4 |
| `test_camel_to_snake_logic_mapping` | camelCase JSON names bind to snake_case Python callables. The one bug ever filed upstream was here. | Study 06 §3 |
| `test_terminal_machine_is_reaped` | A machine reaching `final` is stopped and evicted by the supervisor; live count returns to baseline. | CR-10 |

---

## 4. Where the proposal should change its own ratings

| Component | `10` rating | This review | Why |
|---|---|---|---|
| B9 Rule runtime (lifecycle) | Workaround | **Workaround, conditional on MUST-05** | Pre-filter target is ≥99 %, not 90 %. Below that, disable dispatch. |
| B2/B3 TradeGroup + legs | Good | **Good, bounded by MUSTNOT-08** | 2 tasks/child; only ≤200 measured. |
| — Rate-limit governor | *absent* | **Not suitable** (new) | CR-5. Add as a named non-component so no one reaches for it later. |
| B14 Book health FSM | Good | **Good, with MUSTNOT-03** | Publish a bool; don't query the interpreter. |
| C2.3 "ordering is exactly what an OMS needs" | — | **Incorrect as written** | CR-3: A3's defer/drain breaks it. |
| C1.2 memory budget (~76 MB) | — | **4.5× pessimistic** | 16.7 MB measured at 2,854 interpreters. |
| LC-24 single-maintainer | ⚪ Ecosystem | **⚪, downgraded severity** | 12k LOC / 0 deps / MIT / owner-maintained ⇒ vendorable. Reframe as a testing obligation. |

---

## 5. Final recommendation

**Adopt, scoped, with §3 treated as binding.** The proposal in `10` is directionally right and its Part-A rules are the correct rules. This review's contribution is that **three of the workarounds are more fragile than `10` presents them** (CR-1 persistence, CR-2 stranded deferrals, CR-3 lost ordering) and **one budget is tighter than `10` presents it** (CR-4), while **the objection most likely to sink adoption — interpreter-count explosion — is simply false** (RF-1).

### Adopt for

1. **Order lifecycle (B1)** — two-region chart, with MUST-01 through MUST-04.
2. **TradeGroup + legs (B2, B3)** — with the application-owned actor registry and MUSTNOT-08's 200-child bound.
3. **OCO (B4)** — the best algo fit; event-driven, timing-light.
4. **Iceberg / TWAP / Chase (B5, B6, B7)** — as *structure and bounds only*; all timing external, per A2.
5. **Position protection / native-SL invariant (B8)** — the parallel-region formulation is a genuine clarity win; guards deny-polarity, protection asserted only from an exchange read.
6. **Rule *lifecycle*** (B9) — armed/triggered/cooldown/paused/kill-switched, conditional on MUST-05.
7. **Alert lifecycle (B10)**, **RecordingSession (B11)**, **ReplaySession (B12)** — low rate, clean fit.
8. **ExchangeConnection (B13)** and **book *health* FSM (B14)** — rare transitions; health publishes a bool.
9. **AuthSession (B16)**, **LiveEnablement (B17)**, **RiskLockout (B20)** — low rate, audit-shaped.
10. **KillSwitch (B18)** and **Reconciliation (B19)** — as record-and-orchestrate only; enforcement stays synchronous.

### Do not use for

1. **Book-engine delta application, bar builders, footprint aggregation** — MUSTNOT-01. 48k ev/s vs a ~9–20k process budget, and a 33 µs tax on ~15–60 µs of real work.
2. **Per-tick rule condition evaluation** — 744× slower than plain Python (measured); no filter closes it.
3. **Paper matcher fill model, queue-position estimator, fee/funding arithmetic** — no states, and it needs virtual time the library does not have.
4. **Per-account rate-limit governor / fan-out admission control** — CR-5; ~238,000× slower and structurally unable to answer synchronously.
5. **Any synchronous safety enforcement point** — kill switch, live gate, risk caps, rate budgets. MUSTNOT-05.

### The one-line version

> The library is correct where correctness is hardest and wrong where wrongness is quietest. Adopt it for the ten lifecycle components, keep it entirely out of the five hot/synchronous paths, and accept that the cost of adoption is not the library — it is the **linter, the contract suite, the boot procedure and the reaper** that make its silent failures loud. Ship those four before the first statechart, or do not ship statecharts.

### Reconsider adoption if

- The machine-definition linter (E29-T10) slips past the first statechart. Every Part-A rule fails silently without it.
- The rule pre-filter cannot demonstrate ≥99 % rejection on real trigger distributions.
- `tests/xstate_contract/` cannot be kept under 60 s, because then it will not gate bumps and the pin becomes theatre.
- Upstream D2 items 1–3 are still open in 12 months **and** CandleViewer has hit any of LC-01/LC-03/LC-04 in production. At that point the vendor fork (MUST-08) becomes the primary, not the fallback.

---

## Appendix — adversarial probes written for this review

`docs/research/xstate/adversarial/`, run with `./.venv-xstate/Scripts/python.exe docs/research/xstate/adversarial/<file>`:

| File | Probes | Feeds |
|---|---|---|
| `adv01_versioning_crash.py` | state rename / context drift / semantic drift on restore; queue loss on stop; action-failure durability | CR-1, CR-7, CR-8, RF-2, RF-3 |
| `adv02_scale_poll.py` | actor-poll event-loop tax (0/50/200 children); 2,854-interpreter fleet start + critical-event latency under churn | CR-6, RF-1, RF-7 |
| `adv03_mem.py` | RSS for a 2,854-interpreter fleet; queued-backlog memory; retention after teardown | RF-1, CR-10 |
| `adv04_tasks_governor.py` | asyncio.Task growth per invoked child; statechart-governor vs plain token bucket; terminal-machine reaping | CR-5, CR-6, CR-10 |
| `adv05_prefilter.py` | realistic rule-machine fleet throughput; required pre-filter hit-rate; plain-Python baseline | CR-4 |
| `adv06_defer.py` | defer/drain happy path; defer across crash+restore; defer vs live-event ordering | CR-2, CR-3 |
| `adv07_shared_node.py` | shared `MachineNode` cross-talk; snapshot field inventory; typo'd-event observability | RF-4, CR-9 |
| `adv08_gate_cost.py` | `matches()` / `has_tag()` vs bool on a 48k/s hot path | RF-5, MUSTNOT-03 |

**Caveat on all measurements:** taken on a 4C/8T Kaby Lake-R mobile CPU under Windows 11. Server silicon will be faster (Study 04 assumes ~3×), but the *ratios* — statechart vs plain Python, task growth per child, budget shares — are architectural and do not improve with hardware.
