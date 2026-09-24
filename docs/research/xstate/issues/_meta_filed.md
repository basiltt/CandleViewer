# Meta: CandleViewer adoption readiness

**Status on 0.7.0: 34/34 repro scripts still reproduce their defect. 0 closed.**
Re-verified 2026-09-15 with `gate/run_gate.py` (`repro 0/34 pass, probe 1/3 pass`).

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

`#27 (LC-01)`, `#29 (LC-02)`, `#28 (LC-03)`, `#31 (LC-07)`, `#30 (LC-08)` and `#32 (LC-36)` are all the same design
decision wearing different clothes: **resolution and execution failures degrade
to silent no-ops instead of errors.** If that single philosophy were inverted —
fail loudly by default, opt into forgiveness — most of this list evaporates.

---

## 2. The checklist

Every row below has a standalone issue file in `issues/` with a full write-up and
a runnable repro in `issues/repro/` that **exits 1 while the defect is present
and exits 0 once it is fixed**. Check a box when its repro exits 0.

### Blockers (4 filed) — CandleViewer cannot go live while any of these is open

- [ ] **#27 (LC-01)** — An action that raises still commits the transition, with no programmatic error channel. `on_transition` reports success; the failed state is then durably persisted as truth.
- [ ] **#29 (LC-02)** — An `always` transition with a self-target deadlocks silently: the guard is never re-evaluated, `is_running` stays `True`, nothing is raised.
- [ ] **#28 (LC-03)** — Events with no handler in the current state are silently discarded; there is no `defer`/`error` option, and "ignore" is both the only behaviour and the silent one.
- [ ] **#40 (LC-16)** — `sendTo` cannot address an actor by its `invoke` `id` or `systemId`; the event is silently dropped, and a duplicate `systemId` silently replaces the previous actor.

> The register carries three further Blockers (`LC-15` durable persistence of a
> failed action's state, `LC-17` un-drained deferral buffer after a crash,
> `LC-40`/pre-filter) that are **consequences of #27 (LC-01) and #28 (LC-03) in our
> architecture** rather than separable library defects. They are not filed
> upstream; they close automatically when #27 (LC-01) and #28 (LC-03) close.

### High (20 filed) — each needs a fix or a documented, tested mitigation

**Semantics & resolution**
- [ ] **#36 (LC-05)** — `raise` is queued behind pending external events; no macrostep/microstep distinction.
- [ ] **#34 (LC-06)** — Over-forgiving 4-stage target resolution can silently bind an unrelated state in another region by matching the last id segment.
- [ ] **#31 (LC-07)** — Relative `.child` targets resolve to nothing and are silently dropped.
- [ ] **#30 (LC-08)** — An unknown target is never validated at `create_machine()` and is a silent runtime no-op (contrast: an unknown *action* name correctly raises).
- [ ] **#35 (LC-09)** — A guard that raises is swallowed as `False` and is invisible to every observer; a crashing risk check and a failing one are indistinguishable.
- [ ] **#51 (LC-34)** — No strict mode: event names and payloads are unvalidated, so a typo'd event is a silent no-op.
- [ ] **#32 (LC-36)** — Built-in action params must nest under `params`; the obvious spelling parses fine and silently does nothing.

**Persistence & recovery**
- [ ] **#44 (LC-19)** — Restore does not restart invokes or re-run entry actions; parked machines report `running`.
- [ ] **#45 (LC-21)** — Persisted snapshots carry no schema version and no machine identity.
- [ ] **#46 (LC-22)** — `from_snapshot` assigns the restored context wholesale: machine defaults are not merged, and the caller's dict is aliased.
- [ ] **#47 (LC-24)** — Pending events in the interpreter queue are lost on stop and invisible in the snapshot.

**Timing**
- [ ] **#48 (LC-26)** — `after` timers degrade catastrophically under event-loop load: a 100 ms timer fires ~2.53 s late (p95) with 500 busy interpreters, and the absolute error is roughly constant regardless of the requested delay — the signature of loop starvation.
- [ ] **#49 (LC-27)** — No clock injection / virtual time, so `after` transitions cannot be made deterministic in tests or replay.

**Concurrency & flow control**
- [ ] **#50 (LC-38)** — `SyncInterpreter` is not single-threaded: `after` timers run on background threads and mutate context with no locks.
- [ ] **#53 (LC-39)** — Throughput is a fixed *global* budget shared by all interpreters, not per-machine capacity; undocumented.
- [ ] **#38 (LC-41)** — The interpreter event queue is unbounded, unobservable, and has no backpressure signal.
- [ ] **#39 (LC-42)** — `send()` is fire-and-forget with unbounded queueing latency; a statechart cannot answer a question synchronously.
- [ ] **#37 (LC-43)** — Cross-thread `send()` silently loses every event, returning an un-awaited coroutine with no error.

**Observability & docs**
- [ ] **#33 (LC-48)** — No error-observability hooks: no `on_transition_failed`, no `on_guard_error`, no unhandled-event signal.
- [ ] **#56 (LC-53)** — Three production-critical characteristics are undocumented: timer starvation under load, the `SyncInterpreter` threading model, and the global throughput budget.

### Medium (9 filed) — triaged; must have an owner and a decision, not necessarily a fix

- [ ] **#41 (LC-12)** — `spawn_blocking_<key>` is silently ignored by the async `Interpreter` (sync-only), so the same action name means different things on the two engines.
- [ ] **#43 (LC-28)** — Every invoked child actor costs two asyncio tasks, one busy-polling its status at 5 ms.
- [ ] **#42 (LC-29)** — `invoke.input` is static and is ignored entirely for child-machine actors.
- [ ] **#57 (LC-32)** — Terminal machines are not reaped: a `done` interpreter keeps its children, tasks, context and registry entry.
- [ ] **#52 (LC-37)** — `MachineLogic` subclass auto-registration classifies callables **by arity** and silently misclassifies them.
- [ ] **#54 (LC-44)** — The pure API (`transition`/`get_next_snapshot`) is 3–4× slower per event than a real `SyncInterpreter` **and does not run imperative actions** — undocumented.
- [ ] **#55 (LC-45)** — Hot path rebuilds transition-candidate lists per event and logs at INFO on every event, guard and state entry/exit (~6× slowdown with logging left on).
- [ ] **#58 (LC-49)** — No hierarchical `state.value`; active states are only a flat `Set[str]` of ids.
- [ ] **#60 (LC-57)** — The two engines duplicate rather than share the core algorithm (umbrella for the code-quality group: LC-58, LC-59, LC-61).

### Low (1 filed)

- [ ] **#59 (LC-47)** — Target resolution writes `transition.target_str` on definition objects shared across every interpreter of a machine.

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

**Current verdict: DEFER.** 4 filed Blockers open, 20 High open. See
`00-README.md` for the executive summary.

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
   `SyncInterpreter` and asserts identical observable outcomes. #41 (LC-12) and #50 (LC-38)
   are both "the two engines disagree" bugs that this class of test is designed
   to catch, and `test_engine_conformance.py` does not currently cover them.

3. **The benchmark suite.**
   `bench/` — 11 scripts covering single-interpreter throughput, scaling to 10k
   interpreters, timer precision under load, snapshot/restore cost, actor
   spawn/teardown, sync-vs-async, and the error channel. All emit machine-readable
   JSON via a shared `common.report()`. We will contribute these as a
   `benchmarks/` directory plus a CI job that records numbers per release, so
   regressions like #55 (LC-45)'s INFO-logging overhead are caught by measurement
   rather than by a downstream user.

4. **Pull requests, in the priority order of §5.**
   We will start with the three that unlock the most (`#27 (LC-01)`, `#28 (LC-03)`, `#29 (LC-02)`)
   and the cheap validation wins (`#30 (LC-08)`, `#31 (LC-07)`, `#32 (LC-36)`). We will follow the
   project's existing style (`black`, `flake8`, the emoji-sectioned docstring
   convention) and add tests alongside each fix.

5. **Documentation PRs** for `#56 (LC-53)`, `#53 (LC-39)`, `#54 (LC-44)` and `LC-54` — the
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
| 1 | **#27 (LC-01)** `action_error_policy: continue \| rollback \| fail` | The rollback machinery already exists for *transition* failures (0.6.0 "Transition atomicity") — this reuses it. Also closes LC-11, and LC-15/LC-17 on our side. |
| 2 | **#28 (LC-03)** `on_unhandled: ignore \| defer \| error` | Retires the single most invasive workaround in our design (a `"*": defer` handler on every transient state plus a drain in every `entry`), and with it LC-17 and LC-18. |
| 3 | **#29 (LC-02) + LC-04** external self-target semantics | One-line root cause at `base_interpreter.py:1769`; read `internal` as well as `reenter`. Closes a silent deadlock *and* an XState divergence together. |
| 4 | **#30 (LC-08) + #31 (LC-07)** target validation at `create_machine()` | Actions are already validated this way — targets should be too. Cheap, self-contained, and turns two silent no-ops into build-time errors. |
| 5 | **#33 (LC-48)** error-observability hooks | `on_transition_failed`, `on_guard_error`, unhandled-event signal. Makes #27 (LC-01)/#28 (LC-03)/#35 (LC-09) *observable* even before they are fixed, so it has value on its own. |
| 6 | **#37 (LC-43) + #38 (LC-41) + #39 (LC-42)** the flow-control group | Cross-thread `send()` losing events silently is a correctness bug, not just ergonomics; queue depth and a request/response path are the natural companions. |
| 7 | **#48 (LC-26) + #49 (LC-27)** timers: starvation + clock injection | The hardest and the most valuable for algos and replay. Clock injection alone would let us test deterministically even if starvation remains. |
| 8 | **#56 (LC-53) + #53 (LC-39) + #54 (LC-44)** documentation of measured behaviour | Zero code risk, immediate value to every user. |
| 9 | **#34 (LC-06)** `strict_targets=True` by default | Behaviour change; worth a major-version note. |
| 10 | **#51 (LC-34) / LC-35** strict mode + typed context/events | Largest design surface; naturally last. |

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

### Provenance

Found during the **CandleViewer** trading-terminal evaluation of `xstate-statemachine` **0.7.0** (commit `42612cf`) on Python 3.13.7.


Happy to open a PR for this one — see the contribution offer in the tracking issue.

