---
lc: LC-00-META
title: "Meta: CandleViewer adoption readiness — tracking issue for 34 filed defects (0.7.0 → 0.8.0)"
labels: [meta, tracking, candleviewer]
severity: Meta
blocks_adoption: true
library_version: 0.8.0 (commit 9bf6065)
previous_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
verified_date: 2026-09-17
previous_verified_date: 2026-09-15
gate_runner: gate/run_gate.py
register: 12-challenge-register.md
---

# Meta: CandleViewer adoption readiness

**Status on 0.8.0 (re-verified 2026-09-17): 23 FIXED-DEFAULT · 6 FIXED-OPT-IN ·
5 PARTIAL · 0 NOT-FIXED. All four filed Blockers closed — two of them only by
opt-in policy.**

Gate: `repro 12/34 pass at defaults (+9 verified fixed-but-opt-in), probe 43/51,
bench 5/7, suite 3170 passed / 0 failed`.
Verdict: **ADOPT WITH CONSTRAINTS, conditional** on the mandated machine
configuration being lint-enforced — see `../17-reeval-0.8.0-verdict.md`.

> *Status on 0.7.0 (2026-09-15), preserved: 34/34 repro scripts reproduced their
> defect, 0 closed.*

**Per-item status legend.** `FIXED-DEFAULT` = correct with no configuration ·
`FIXED-OPT-IN` = fix verified but the 0.7.x behaviour is still the default,
closed only while the mandated option is enforced · `PARTIAL` · `NOT-FIXED`.
Each item links to its re-verification in `verify-0.8.0/<LC>.result.md`.

This is the umbrella tracking issue for a set of individually-filed defects found
while evaluating `xstate-statemachine` as the statechart runtime for a production
trading system. It exists so that the maintainer has one place to see the whole
shape of the evaluation, the order in which fixes unlock the most value, and what
we will contribute back.

---

## 1. Purpose — why this evaluation exists

**CandleViewer** is a Bybit trading terminal. We want to build four distinct
lifecycle families on top of this library, and we intend to battle-test it hard
in the process:

| Family | What the statechart owns |
|---|---|
| **OMS / order lifecycle** | `pending → submitted → open → partially_filled → filled / cancelled / rejected`, per order and per leg, durably persisted and restored across process restarts. |
| **Emulated algos** | TWAP slicing, chase repricing, iceberg clip release — each a long-lived machine with timers, child actors per leg, and cancellation. |
| **Rule runtime** | User-authored alert/automation rules compiled to a machine IR: `armed → triggered → cooling_down → disarmed`. |
| **Replay / backtest** | The same machines driven from historical data, requiring deterministic, virtual-time execution. |

This is a demanding fit because three properties matter more to us than to a
typical consumer:

1. **Silent wrongness is the worst possible failure mode.** A dropped event or an
   uncommitted-but-reported transition on the order path is money.
2. **State is durable.** Snapshots are written to disk and restored days later,
   across code versions.
3. **Timing is semantic.** A TWAP slice that fires 2.5 s late during a volatility
   burst is a materially different order than the one intended.

We chose this library on its merits — zero runtime dependencies, MIT, 2,805
passing tests, faithful SCXML-style hierarchy/parallel/history semantics — and we
want to adopt it. This issue set is the price of that adoption being safe, not a
complaint. **We are not filing these to argue against the library; we are filing
them because we intend to use it and want to fix what we found.**

### The one-sentence finding

> The library is **correct where correctness is hardest** — invoke cancellation,
> parallel/nested snapshot fidelity, FIFO ordering, history semantics,
> determinism across repeated runs, actor teardown (0.11 KB/actor over 3,000
> cycles) — and **wrong where wrongness is quietest**.

`LC-01`, `LC-02`, `LC-03`, `LC-07`, `LC-08` and `LC-36` are all the same design
decision wearing different clothes: **resolution and execution failures degrade
to silent no-ops instead of errors.** If that single philosophy were inverted —
fail loudly by default, opt into forgiveness — most of this list evaporates.

---

## 2. The checklist

Every row below has a standalone issue file in `issues/` with a full write-up and
a runnable repro in `issues/repro/` that **exits 1 while the defect is present
and exits 0 once it is fixed**. Check a box when its repro exits 0.

### Blockers (4 filed) — CandleViewer cannot go live while any of these is open

- [x] **LC-01** — **FIXED-OPT-IN** (#27) — needs `actionErrorPolicy:"rollback"/"fail"`; default `"continue"` still commits, now observable. Was: An action that raises still commits the transition, with no programmatic error channel. `on_transition` reports success; the failed state is then durably persisted as truth.
- [x] **LC-02** — **FIXED-DEFAULT** (#29). Was: An `always` transition with a self-target deadlocks silently: the guard is never re-evaluated, `is_running` stays `True`, nothing is raised.
- [x] **LC-03** — **FIXED-OPT-IN** (#28) — needs `onUnhandled:"defer"/"error"`; 9/9 adversarial. Was: Events with no handler in the current state are silently discarded; there is no `defer`/`error` option, and "ignore" is both the only behaviour and the silent one.
- [x] **LC-16** — **FIXED-DEFAULT** (#40) — unresolved `sendTo` target may still log-and-drop. Was: `sendTo` cannot address an actor by its `invoke` `id` or `systemId`; the event is silently dropped, and a duplicate `systemId` silently replaces the previous actor.

> The register carries three further Blockers (`LC-15` durable persistence of a
> failed action's state, `LC-17` un-drained deferral buffer after a crash,
> `LC-40`/pre-filter) that are **consequences of LC-01 and LC-03 in our
> architecture** rather than separable library defects. They are not filed
> upstream; they close automatically when LC-01 and LC-03 close.

### High (20 filed) — each needs a fix or a documented, tested mitigation

**Semantics & resolution**
- [x] **LC-05** — **FIXED-DEFAULT** (#36). Was: `raise` is queued behind pending external events; no macrostep/microstep distinction.
- [x] **LC-06** — **FIXED-DEFAULT** (#34) — raises `InvalidConfigError`, not `StateNotFoundError`. Was: Over-forgiving 4-stage target resolution can silently bind an unrelated state in another region by matching the last id segment.
- [ ] **LC-07** — **PARTIAL** (#31) — sibling fallback still reachable **and silent** unless `strictTargets:true`. Was: Relative `.child` targets resolve to nothing and are silently dropped.
- [x] **LC-08** — **FIXED-DEFAULT** (#30). Was: An unknown target is never validated at `create_machine()` and is a silent runtime no-op (contrast: an unknown *action* name correctly raises).
- [x] **LC-09** — **FIXED-DEFAULT** (observability) / **FIXED-OPT-IN** (outcome: `guardErrorPolicy:"raise"`) (#35). Was: A guard that raises is swallowed as `False` and is invisible to every observer; a crashing risk check and a failing one are indistinguishable.
- [x] **LC-34** — **FIXED-OPT-IN** (#51) — needs `strict:true` + `event_schemas`; `send_threadsafe()` bypasses both (N-4). Was: No strict mode: event names and payloads are unvalidated, so a typo'd event is a silent no-op.
- [x] **LC-36** — **FIXED-DEFAULT** (#32). Was: Built-in action params must nest under `params`; the obvious spelling parses fine and silently does nothing.

**Persistence & recovery**
- [x] **LC-19** — **FIXED-OPT-IN** (#44) — `pending_invocations()` unconditional; never blanket `restart_services=True`. Was: Restore does not restart invokes or re-run entry actions; parked machines report `running`.
- [x] **LC-21** — **FIXED-DEFAULT** (#45) — `machine_hash` ignores action params (N-9). Was: Persisted snapshots carry no schema version and no machine identity.
- [x] **LC-22** — **FIXED-DEFAULT** (#46) — retires MUST-06. Was: `from_snapshot` assigns the restored context wholesale: machine defaults are not merged, and the caller's dict is aliased.
- [x] **LC-24** — **FIXED-DEFAULT** (#47) — use `stop(drain=True)`; bare `stop()` still drops, loudly. Was: Pending events in the interpreter queue are lost on stop and invisible in the snapshot.

**Timing**
- [x] **LC-26** — **FIXED-DEFAULT** (#48) — 14.5x better (2530→174.4 ms) but **BENCH-6 still missed** vs ≤100 ms. Was: `after` timers degrade catastrophically under event-loop load: a 100 ms timer fires ~2.53 s late (p95) with 500 busy interpreters, and the absolute error is roughly constant regardless of the requested delay — the signature of loop starvation.
- [x] **LC-27** — **FIXED-DEFAULT** (#49) — `increment()` is ms and returns a `_MustAwait`. Was: No clock injection / virtual time, so `after` transitions cannot be made deterministic in tests or replay.

**Concurrency & flow control**
- [ ] **LC-38** — **PARTIAL** (#50) — zero threads per timer, but **N-2**: sync timers unreachable by `tick()` in a running loop. Was: `SyncInterpreter` is not single-threaded: `after` timers run on background threads and mutate context with no locks.
- [x] **LC-39** — **FIXED-DEFAULT** (docs, #53) — budget is still per-process by design. Was: Throughput is a fixed *global* budget shared by all interpreters, not per-machine capacity; undocumented.
- [x] **LC-41** — **FIXED-DEFAULT** (`queue_depth`) / **FIXED-OPT-IN** (bounding) (#38) — 13/13 adversarial. Was: The interpreter event queue is unbounded, unobservable, and has no backpressure signal.
- [x] **LC-42** — **FIXED-DEFAULT** (#39) — **N-1**: hangs forever on a reused `Event` instance. Was: `send()` is fire-and-forget with unbounded queueing latency; a statechart cannot answer a question synchronously.
- [ ] **LC-43** — **PARTIAL** (#37) — `run_coroutine_threadsafe(send(...))` regressed (N-6); `send_threadsafe()` lacks the guardrail (N-4). Was: Cross-thread `send()` silently loses every event, returning an un-awaited coroutine with no error.

**Observability & docs**
- [x] **LC-48** — **FIXED-DEFAULT** (#33) — hooks fire under the 0.7.x defaults; dedupe `on_transition_failed` (N-15). Was: No error-observability hooks: no `on_transition_failed`, no `on_guard_error`, no unhandled-event signal.
- [x] **LC-53** — **FIXED-DEFAULT** (#56). Was: Three production-critical characteristics are undocumented: timer starvation under load, the `SyncInterpreter` threading model, and the global throughput budget.

### Medium (9 filed) — triaged; must have an owner and a decision, not necessarily a fix

- [x] **LC-12** — **FIXED-DEFAULT** (#41) — `spawnBlockingTimeout`; async `spawn_` still blocks for a sync-bodied child. Was: `spawn_blocking_<key>` is silently ignored by the async `Interpreter` (sync-only), so the same action name means different things on the two engines.
- [ ] **LC-28** — **PARTIAL** (#43) — poll→future done, but still **2** tasks per idle child. Was: Every invoked child actor costs two asyncio tasks, one busy-polling its status at 5 ms.
- [x] **LC-29** — **FIXED-DEFAULT** (#42). Was: `invoke.input` is static and is ignored entirely for child-machine actors.
- [x] **LC-32** — **FIXED-DEFAULT** (#57). Was: Terminal machines are not reaped: a `done` interpreter keeps its children, tasks, context and registry entry.
- [ ] **LC-37** — **FIXED-DEFAULT** (decorated) / **PARTIAL** (undecorated arity fallback, now `UserWarning`) (#52). Was: `MachineLogic` subclass auto-registration classifies callables **by arity** and silently misclassifies them.
- [x] **LC-44** — **FIXED-DEFAULT** (#54) — ~3x faster; "skips imperative actions" was never in scope. Was: The pure API (`transition`/`get_next_snapshot`) is 3–4× slower per event than a real `SyncInterpreter` **and does not run imperative actions** — undocumented.
- [x] **LC-45** — **FIXED-DEFAULT** (#55). Was: Hot path rebuilds transition-candidate lists per event and logs at INFO on every event, guard and state entry/exit (~6× slowdown with logging left on).
- [x] **LC-49** — **FIXED-DEFAULT** (#58). Was: No hierarchical `state.value`; active states are only a flat `Set[str]` of ids.
- [x] **LC-57** — **FIXED-DEFAULT** for the checkable criterion (#60) — LC-52 did not ship. Was: The two engines duplicate rather than share the core algorithm (umbrella for the code-quality group: LC-58, LC-59, LC-61).

### Low (1 filed)

- [x] **LC-47** — **FIXED-DEFAULT** (#59). Was: Target resolution writes `transition.target_str` on definition objects shared across every interpreter of a machine.

> The full 62-row register (including 12 Low rows not filed individually and the
> rows we mitigate application-side rather than upstream) is
> `12-challenge-register.md`. Register totals: **6 Blocker, 25 High, 18 Medium,
> 13 Low**; 54 rows marked for upstream filing, of which the 34 above have
> standalone issues and repros.

---

## 3. The adoption gate rule

CandleViewer adopts this library on a live-trading path only when:

> **All Blocker and High items are closed, and every Medium item is triaged.**

Precisely:

| Severity | Definition of "closed" |
|---|---|
| **Blocker** | Fixed upstream, **or** mitigated by a mechanically enforced CandleViewer mechanism with a regression test in `tests/xstate_contract/`. A documented convention is *not* a mitigation — an unenforced rule is not a rule. |
| **High** | Fixed upstream, **or** has a documented mitigation with a named owner and a passing contract test pinned to the defect. |
| **Medium** | **Triaged**, not necessarily fixed: an explicit accept / mitigate / defer decision recorded in the register, with an owner. |
| **Low** | No gate. Tracked for hygiene. |

**Gate mechanics.** "Closed" is proven by the repro script, never by assertion:
a defect is closed when `issues/repro/LC-xx_*.py` **exits 0**. The gate is run by
`gate/run_gate.py`; the exact procedure, benchmark thresholds and the
ADOPT / ADOPT-with-constraints / DEFER decision table live in `20-adoption-gate.md`.

**Prerequisite that gates everything else.** The machine-definition linter and
`tests/xstate_contract/` must ship *before the first CandleViewer statechart*.
Every Blocker mitigation on our side fails silently if a developer forgets it,
so the enforcement mechanism has to exist before the code it enforces.

**Current verdict (0.8.0, 2026-09-17): ADOPT WITH CONSTRAINTS, CONDITIONAL.**
All four filed Blockers are closed; 4 High remain PARTIAL (LC-07, LC-26, LC-38,
LC-43). The condition is ours, not upstream's: **LC-01 and LC-03 are closed only
by opt-in policy**, so they count as closed only while the mandated machine
configuration is enforced by the linter (`E29-T10`) and `tests/xstate_contract/`.
Neither has shipped, so the operative decision on the order path is still DEFER;
non-order paths may proceed now. See `../17-reeval-0.8.0-verdict.md` for the
decision-table walk and `00-README.md` for the executive summary.

> *Previous verdict (0.7.0, 2026-09-15): DEFER — 4 filed Blockers open, 20 High
> open.*

**A note on how "closed" is now decided.** The rule below ("a defect is closed
when its repro script exits 0") was written before the library began shipping
fixes as per-machine policies whose defaults preserve the old semantics. It is
retained, with one amendment recorded in `../20-adoption-gate.md` §9.2: the
authoritative check set is now `verify-0.8.0/*.py`, which exercise the **mandated
configuration**. The original `repro/*.py` exercise the **defaults** and are
informational — a FAIL there must be triaged into `unfixed` / `fixed-but-opt-in` /
`stale repro` in writing, never assumed to mean unfixed.

---

## 4. What the CandleViewer team will contribute back

We are not filing and walking away. Concretely, and in this order:

1. **The repro corpus — already written, available now.**
   34 standalone scripts in `issues/repro/`, zero dependencies beyond the library
   itself, each printing `OBSERVED` / `EXPECTED` / `RESULT` and exiting 1 on
   defect / 0 on fix. These are drop-in `xfail` candidates for the upstream
   suite. We will open a PR adding them under `tests/regression/candleviewer/`
   on request, marked `xfail(strict=True)` so each one flips to a green test the
   moment its fix lands.

2. **A cross-engine conformance suite.**
   The probe harness (`probes/`, 51 probes across core transitions, invoke/timer/
   history, and context/snapshot/determinism) generalised into a parametrised
   suite that runs every probe against **both** `Interpreter` and
   `SyncInterpreter` and asserts identical observable outcomes. LC-12 and LC-38
   are both "the two engines disagree" bugs that this class of test is designed
   to catch, and `test_engine_conformance.py` does not currently cover them.

3. **The benchmark suite.**
   `bench/` — 11 scripts covering single-interpreter throughput, scaling to 10k
   interpreters, timer precision under load, snapshot/restore cost, actor
   spawn/teardown, sync-vs-async, and the error channel. All emit machine-readable
   JSON via a shared `common.report()`. We will contribute these as a
   `benchmarks/` directory plus a CI job that records numbers per release, so
   regressions like LC-45's INFO-logging overhead are caught by measurement
   rather than by a downstream user.

4. **Pull requests, in the priority order of §5.**
   We will start with the three that unlock the most (`LC-01`, `LC-03`, `LC-02`)
   and the cheap validation wins (`LC-08`, `LC-07`, `LC-36`). We will follow the
   project's existing style (`black`, `flake8`, the emoji-sectioned docstring
   convention) and add tests alongside each fix.

5. **Documentation PRs** for `LC-53`, `LC-39`, `LC-44` and `LC-54` — the
   production-characteristics gaps. These need no code change and are pure
   measured fact: we have the numbers.

6. **Production feedback.** If the gate opens, we will report real operating
   characteristics back — event rates, restore volumes, failure modes observed in
   live use. The register notes this project currently has **exactly one issue
   ever filed** and no known independent production adoption; we would like to
   change the second of those.

**What we will not do:** vendor a fork and disappear. Our mitigation plan pins
`== 0.7.0` with a hash and vendors into `third_party/` as a *risk control*, not
as a divergence — every local change is intended to become an upstream PR.

---

## 5. Suggested upstream priority order

Ordered by *defects retired per unit of work*, not by severity alone.

| # | Item | Why first |
|---|---|---|
| 1 | **LC-01** `action_error_policy: continue \| rollback \| fail` | The rollback machinery already exists for *transition* failures (0.6.0 "Transition atomicity") — this reuses it. Also closes LC-11, and LC-15/LC-17 on our side. |
| 2 | **LC-03** `on_unhandled: ignore \| defer \| error` | Retires the single most invasive workaround in our design (a `"*": defer` handler on every transient state plus a drain in every `entry`), and with it LC-17 and LC-18. |
| 3 | **LC-02 + LC-04** external self-target semantics | One-line root cause at `base_interpreter.py:1769`; read `internal` as well as `reenter`. Closes a silent deadlock *and* an XState divergence together. |
| 4 | **LC-08 + LC-07** target validation at `create_machine()` | Actions are already validated this way — targets should be too. Cheap, self-contained, and turns two silent no-ops into build-time errors. |
| 5 | **LC-48** error-observability hooks | `on_transition_failed`, `on_guard_error`, unhandled-event signal. Makes LC-01/LC-03/LC-09 *observable* even before they are fixed, so it has value on its own. |
| 6 | **LC-43 + LC-41 + LC-42** the flow-control group | Cross-thread `send()` losing events silently is a correctness bug, not just ergonomics; queue depth and a request/response path are the natural companions. |
| 7 | **LC-26 + LC-27** timers: starvation + clock injection | The hardest and the most valuable for algos and replay. Clock injection alone would let us test deterministically even if starvation remains. |
| 8 | **LC-53 + LC-39 + LC-44** documentation of measured behaviour | Zero code risk, immediate value to every user. |
| 9 | **LC-06** `strict_targets=True` by default | Behaviour change; worth a major-version note. |
| 10 | **LC-34 / LC-35** strict mode + typed context/events | Largest design surface; naturally last. |

---

## 6. Re-verification protocol

The evidence in this issue set decays. Every claim is pinned to
**0.7.0 (commit 42612cf), Python 3.13.7, Windows**, and must be re-established,
not assumed, on any change.

**Triggers.** Re-verify on: (a) any new library release; (b) any commit to
`base_interpreter.py`, `interpreter.py` or `sync_interpreter.py` that we intend
to consume; (c) a CandleViewer Python-version bump; (d) quarterly, if none of the
above has fired.

**Procedure.**

1. Install the exact version under test into the pinned venv, and record
   `xstate_statemachine.__version__`, the commit sha and `sys.version`.
2. Run `python gate/run_gate.py --json gate/<version>.json`.
   - Every repro that **exits 0** is a closed defect. Move it to the checklist's
     checked state, annotate the issue file with `fixed_in:`, and — this is the
     part that is easy to skip — **delete the corresponding CandleViewer
     mitigation and its workaround test**, so we do not carry dead complexity.
   - Every repro that still exits 1 stays open.
   - Any repro that exits with something other than 0 or 1 is a **harness
     failure**, not a result: the API it exercises changed. Repair the repro
     before drawing any conclusion from it.
3. Run the benchmarks: `python gate/run_gate.py --bench-only`. Benchmark
   thresholds are hardware-sensitive; re-baseline on the target host before
   trusting a marginal verdict.
4. Run the library's own suite (expect ~9.5 min, `2805 passed, 2 skipped` on
   0.7.0) and diff the count and coverage against the recorded baseline.
5. Diff `docs/FEATURE_GAP_ANALYSIS.md` and `CHANGELOG.md` against the previous
   release, and check each new entry against this register for rows that a fix
   has made obsolete.
6. Update this file's header (`Status on X`), the register, and the decision in
   `20-adoption-gate.md`.

**Standing rule.** A defect is closed by a green repro, never by a changelog
entry. Both 0.6.0 and 0.7.0 shipped after the maintainer's own adversarial
battle-testing found release-blocking correctness bugs that thousands of passing
tests had not — which is a good sign about process and a cautionary one about
inference from test counts. We hold ourselves to the same standard: measure, do
not assume.

---

## 7. 0.8.0 re-evaluation outcome (2026-09-17)

Recording the result of §6's protocol, run against 0.8.0 (commit `9bf6065`).

### What upstream delivered

Of the 34 individually-filed issues: **23 FIXED-DEFAULT, 6 FIXED-OPT-IN,
5 PARTIAL, 0 NOT-FIXED.** All four filed Blockers closed. The suite grew from
2,805 to 3,170 tests with +13,115 lines of test code. Timer starvation improved
14.5× (2530 ms → 174.4 ms p95). Order-path headroom went 1.81× → 3.17×.
Five of seven benchmark thresholds now met, up from two.

The two features we most needed were probed adversarially and held:
`onUnhandled: "defer"` scored **9/9** and the bounded inbox with
`send(wait=True)` receipts scored **13/13**, including the original blocker
end-to-end (a `FILL` arriving one microstep before its handler is armed, while
the submit invoke is still running, is held and applied on `onDone`).

This is a substantial, good-faith response to the whole filing, and §4's promise
of contributions back stands — the repro corpus, the conformance suite and the
benchmark harness are all still on offer.

### What is still open, stated plainly

1. **Two of the four Blockers are closed by opt-in policy.** `actionErrorPolicy`
   defaults to `"continue"` and `onUnhandled` defaults to `"ignore"`, both
   preserving 0.7.x behaviour. The fixes are real and verified; they apply to a
   caller who sets the option. Since every Blocker in this register is a *silent*
   failure and an unenforced rule is not a rule, they are closed for us only once
   the mandate is mechanical.
2. **The mandated configuration costs ~22% throughput.**
   `actionErrorPolicy="rollback"` measures 35,532 → 27,586 ev/s while armed and
   never firing, which puts BENCH-1's headroom at ~2.46× — under its 3.0× bar.
   Accepted explicitly as constraint CV-C13 rather than quietly.
3. **BENCH-2 and BENCH-6 are still missed.** The rule pre-filter (MUST-05) and
   the ban on `after` in catalogue machines (CV-C12) both stand.
4. **17 new defects** (N-1…N-17: 2 High, 9 Medium, 6 Low, 0 Blocker). The two
   High ones sit inside features 0.8.0 added: `send(wait=True)` hangs forever on
   a reused `Event` instance (receipts keyed on `id()`), and `SyncInterpreter`
   `after` deadlines become unreachable by `tick()` inside a running asyncio
   loop. Five are drafted as new issues with runnable repros in `new-0.8.0/`;
   eleven follow-up comments are drafted in `followups-0.8.0/`. **Nothing has
   been filed.**

### Upstream disposition

- **Close as verified (23):** #29, #30, #32, #33, #34, #35, #36, #38, #40, #41,
  #42, #45, #46, #47, #48, #49, #53, #54, #55, #56, #57, #58, #59.
- **Follow-up comment first (11):** #27, #28, #31, #37, #39, #43, #44, #50, #51,
  #52, #60. Drafts in `followups-0.8.0/`.
- **New issues to file (5):** N-1, N-2, N-3, N-4, N-8. Drafts in `new-0.8.0/`.

### The single gating condition

Everything upstream needed for a Blocker-clean gate has landed. What remains is
**ours**: the machine-definition linter (`E29-T10`) enforcing the mandatory
configuration block, and `tests/xstate_contract/`. That is the MUST-09
prerequisite this file has carried since 2026-09-15 — the linter and the contract
suite must ship *before the first statechart*, because every mitigation fails
silently if a developer forgets it. Until both are green, the order path stays on
the shim.

Full detail, including the exact configuration block and the CI lint rule:
`../17-reeval-0.8.0-verdict.md` §4.
