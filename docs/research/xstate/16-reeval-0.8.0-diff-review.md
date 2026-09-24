# 16 — Re-evaluation: `xstate-statemachine` 0.7.0 → 0.8.0 diff review

**Date:** 2026-09-17
**Library under review:** `_ref/xstate-statemachine` @ `v0.8.0` (commit `9bf6065`), editable install in `.venv-gate`.
**Scope:** full `src/` diff `v0.7.0..v0.8.0` (+5,439 / −1,785 lines across 24 modules), the CHANGELOG `[0.8.0]` section, and a re-run of our 34 0.7.0 repro scripts.
**Ground rule applied throughout:** the release notes state that nearly every fix is a **per-machine policy or additive API whose default preserves 0.7.x semantics**. A repro that still exits 1 is therefore triaged into *unfixed*, *fixed-but-opt-in*, or *repro artefact* — never assumed unfixed.

---

## 1. Headline assessment

This is a large, serious, and generally well-executed release. The diff is not a veneer: `base_interpreter.py` grew by ~1,500 lines of real algorithm, `sync_interpreter.py` was rewritten (−1,550 net churn) to run off the same core, and three new modules (`clock.py`, `persistence.py`, `validation.py`, plus `_typing.py`) carry genuinely new contracts. Test code grew +13,115 / −264 lines across 46 test files. Code comments are unusually good — most non-obvious decisions carry an "Architecture decision" note naming the issue number and the failure it prevents.

The stated design discipline (default-preserving policies) is **substantially honoured**, but not perfectly. I found:

- **3 behaviour changes not in the CHANGELOG** that can break 0.7.x callers (§4).
- **2 correctness defects introduced or left in 0.8.0** (§5), one of which is a reproducible hang.
- **1 pre-existing data-loss bug that 0.8.0 documents as fixed but only fixed on one engine** (§5.3).
- The "two deliberate exceptions under **Changed**" claim is **unverifiable as written** — `Changed` lists 12 items, at least 5 of which are behavioural, and none is marked as *the* exception (§3).

Nothing here is a blocker for adoption on the async engine; §5.1 and §5.3 are worth filing.

---

## 2. Repro re-run: triage of all 34 scripts

Run with the gate venv. 14 exit 0, 20 exit 1. The exit code alone is misleading; triaged:

### 2a. Genuinely fixed — repro now passes (14)

`LC-05` (SCXML internal queue), `LC-08` (build-time target validation), `LC-16` (`sendTo` by invoke id), `LC-21` (snapshot envelope), `LC-26` (timer starvation), `LC-32` (terminal teardown), `LC-34` (strict mode), `LC-38` (sync timer threads gone), `LC-45` (hot-path/INFO logging), `LC-47` (shared `TransitionDefinition` mutation), `LC-48` (error hooks), `LC-49` (hierarchical `value`), `LC-57` (one core algorithm), `LC-06`/`LC-02` (now raise `InvalidConfigError` at build time — the repro's own `create_machine` call is what fails, which *is* the fix).

Spot-verified independently, not just by exit code:

- `on_guard_error` and `on_unhandled_event` **fire under the 0.7.x defaults** (`guardErrorPolicy: "false"`, `onUnhandled: "ignore"`). Confirmed with a live plugin. This is the right shape: observability is unconditional, recovery is opt-in.
- Structure hash is stable across `meta`/`description` edits and key reordering, as documented. Confirmed.
- `pending_events` round-trips: 50 queued events appear in the snapshot, `stop(drain=True)` processes all 50, and `from_snapshot(...).start()` replays all 50. Confirmed.
- `SimulatedClock` makes a 600 ms `after` fire in 0.2 ms of wall clock. Confirmed.

### 2b. Fixed but opt-in — repro exercises the 0.7.x default (7)

| Repro | Status |
|---|---|
| `LC-01` action raise commits transition | Fixed via `actionErrorPolicy: "rollback"/"fail"`. Default `"continue"` retained → repro fails **by design**. A one-shot `DeprecationWarning` now fires. |
| `LC-03` unhandled events discarded | Fixed via `onUnhandled: "defer"/"error"`. Default `"ignore"` retained. `on_unhandled_event` fires even under `ignore`. |
| `LC-09` guard exception swallowed | Fixed via `guardErrorPolicy`. Default `"false"` retained; `on_guard_error` fires regardless. The repro asserts on *state + raised + `on_guard_evaluated`* only, so it cannot see the new hook — **repro is now stale**, not the library. |
| `LC-41` unbounded queue | Fixed via `max_queue_size=` / `OverflowPolicy`. Unbounded is still the default; `queue_depth` and `pending_events` are now public (the repro prints them as OBSERVED and still fails on the unbounded default). |
| `LC-42` send cannot answer | Fixed via `send(wait=True)` / `send_priority()`. Fire-and-forget remains the default; the repro's "state immediately after `await send`" assertion is unsatisfiable by design and is now stale. |
| `LC-19` restore does not restart invokes | Fixed via `from_snapshot(restart_services=True)` + `pending_invocations()`. Default static restore retained. |
| `LC-22` `from_snapshot` context wholesale | Fixed (deep-copy + shallow merge over defaults). The repro now dies *earlier*, on the new `SnapshotDriftError` — the second machine is structurally different, which is exactly what #45 is for. Repro needs `verify_machine_hash=False`. |

### 2c. Repro artefacts — script needs updating, library is fine (4)

- `LC-28`: `AttributeError: module has no attribute '_ACTOR_POLL_INTERVAL'` — the symbol was **removed**, which is the fix. Script asserts on a private name.
- `LC-27`: script defines its *own* `SimulatedClock` stub that the library correctly ignores. With the library's `SimulatedClock` + `await clock.increment(700)`, the timer fires in 0.2 ms. Fixed.
- `LC-36`: script now dies on the new build-time `InvalidConfigError` that names the exact defect ("params must be nested under `params`"). That is the fix firing.
- `LC-53`: `XSM_REPO` not set; the guide page does exist (`docs/_guide/production-characteristics.md`, 103 lines).

### 2d. Still open (5)

- **`LC-12` `spawn_blocking_` async/sync disagreement — PARTIALLY fixed.** The async engine now honours the marker, but the repro shows `spawn_worker` (non-blocking) *also* blocks 251 ms on async, because `await child_interpreter.start()` runs the child's synchronous entry action inline on the parent's loop. The two engines still disagree: async blocks on both spellings, sync blocks only on `spawn_blocking_`. The CHANGELOG claims "Both engines now wait" for the blocking form — true — but does not note that the async *non*-blocking form is also effectively blocking for a sync-bodied child.
- **`LC-29` `invoke.input`.** Callable `input` is now resolved and forwarded, but a **plain-dict child context receives it only at `context["input"]`** — observed `{'snapshot': None, 'input': {...}}`. This is documented behaviour ("declared keys are never overwritten"), so it is a deliberate deviation from the repro's expectation, not a bug. Worth confirming it matches XState.
- **`LC-44` pure API.** Claimed "~3x faster"; measured **1.27× the interpreter's per-event cost**, i.e. still slower than `send()`. Big improvement over 4×, but the CHANGELOG wording ("~3x faster") is relative to 0.7.0, not "no slower than the interpreter". Not a defect; a docs-precision issue.
- **`LC-39` throughput.** Aggregate 295k–341k ev/s but flat in N (0.86× from N=1 to N=500) — the single-event-loop budget is real and now documented in Production Characteristics. Repro asserts an expectation the docs explicitly refute. Closed-by-documentation.
- **`LC-24` pending queue.** Snapshot now carries `pending_events` and `drain_pending`/`pending_events` exist, but the repro's plain `await i.stop()` still loses 50 events. Correct by design (`drain=True` is opt-in and a loud `WARNING` is logged), so this is 2b in substance. Listed here because the warning-only default is a real production foot-gun: a `stop()` in a shutdown handler silently drops the inbox unless the author knows to pass `drain=True`.

---

## 3. Cross-check of the two "Changed" items

The header claims *"Every new behaviour is a per-machine policy or an additive API whose default preserves 0.7.x semantics, **with two deliberate exceptions called out under Changed**."*

**This claim does not hold as written.** `### Changed` contains 12 bullets, and at least **five** are behavioural changes a 0.7.x user can observe without opting in:

1. **`[wave 2]` Reaching a top-level final state now tears down** (#57) — children stopped, timers cancelled, actor-system registration removed at the moment `status` becomes `done`. Explicitly flagged: *"Machines that relied on children outliving a completed parent must restructure."* **This is clearly one of the two.**
2. **`[wave 2]` Invoked child actors no longer poll** (#43) — `onDone` latency drops from a 5 ms floor to ~0, *"which can expose tests that used the delay as a settling window."* **This is plausibly the second.**
3. **`[wave 3]` SCXML internal event queue** (#36) — trace order changes from `['entry','EXTERNAL','RAISED']` to `['entry','RAISED','EXTERNAL']`. This is listed under **Added**, but it is a *behaviour change to existing machines*: any machine using zero-delay `raise` now observes a different event order. Misfiled.
4. **`Interpreter.send()` is a regular method** — see §4.1; this breaks a documented 0.7.x cross-thread idiom.
5. **`.child` targets resolve into the source's descendants** (listed under **Fixed**) — with the sibling reading demoted to a fallback. Where a machine has *both* a child and a sibling named `X`, `.X` silently retargets from the sibling to the child. Verified: a machine with `m.A.A2` and `m.A2` and `on: {"GO": ".A2"}` on `m.A` lands on **`m.A.A2`** in 0.8.0; the 0.7.x reading was `m.A2`. Silent, not warned, not in `Changed`.

**Recommendation:** either name the two exceptions explicitly ("these two and only these two"), or drop the count. As written it understates the migration surface by roughly 3 items.

---

## 4. Behaviour changes NOT in the changelog

### 4.1 `run_coroutine_threadsafe(interp.send(...))` now raises — silently undocumented break

0.7.x code that crossed threads correctly using the standard asyncio idiom:

```python
asyncio.run_coroutine_threadsafe(interp.send("F"), loop).result()
```

now raises `WrongThreadError` ("Events sent this way would be silently lost"). **Verified.** The thread check runs *eagerly* in `send()` on the caller's thread, before the coroutine is ever scheduled onto the owning loop — so the one correct 0.7.x cross-thread pattern is rejected along with the broken bare-`send()` one. The error message is actively misleading for this case: events sent *this* way were **not** being lost in 0.7.0.

The CHANGELOG documents `send_threadsafe()` as the new API and the bare-`send()` fix, but nowhere says the `run_coroutine_threadsafe` idiom stopped working. `docs/_guide/interpreters.md:1010` even describes `send_threadsafe` as internally doing `run_coroutine_threadsafe`, which invites the reader to believe the manual form is equivalent.

**Severity:** medium. Silent-at-review-time, loud-at-runtime; easy to fix (`send_threadsafe`), hard to discover.

### 4.2 `TEvent` type parameter removal is a runtime break, filed only as a typing improvement

The `Changed` entry frames this as *"The unused `TEvent` type parameter is gone… It appeared in zero signatures."* True of *signatures*, but:

- `from xstate_statemachine.models import TEvent` now raises `ImportError` — `TEvent` was a module-level public name in 0.7.0 (`models.py:67`).
- `Interpreter[Ctx, Any]` — the spelling the 0.7.0 generics forced users to write — now raises `TypeError: Too many arguments … actual 2, expected 1` **at runtime**, not merely under a type checker.

Both verified. This belongs under a "Removed"/breaking heading, not inside a type-safety bullet.

### 4.3 `_matching_descriptors` system-event exemption widened to `___xstate`

0.7.0 exempted `("done.", "error.", "after.", "xstate.")` from wildcard/partial matching; 0.8.0 adds `"___xstate"`. Benign and correct (init/exit sentinels), but the *user-facing* consequence of the existing list is still undocumented and now load-bearing in three places (matcher, `onUnhandled` policy, `_check_strict`): **any user event namespaced `error.*` or `done.*` is invisible to `on: {"*": …}` and is exempt from `onUnhandled: "error"`.** Verified: `error.myapp.validation` does not match a bare `"*"`, and `done.review` does not trip `onUnhandled: "error"`. For a domain that naturally names events `done.review` / `error.validation` this is a silent-drop class the release otherwise set out to eliminate.

---

## 5. Defects found

### 5.1 `send(event_obj, wait=True)` with the **same** `Event` object concurrently in flight hangs forever — CONFIRMED

`_make_receipt` / `_resolve_receipt` key the receipt map on **`id(event_obj)`**:

```python
self._receipts[id(event_obj)] = fut          # interpreter.py:~690
fut = self._receipts.pop(id(event_obj), None)
```

Two concurrent `send(ev, wait=True)` calls with the *same* `Event` instance collide on the key: the second `_make_receipt` overwrites the first future, which is then never resolved and never failed.

Reproduced:

```python
ev = Event(type="T", payload={})
await asyncio.gather(i.send(ev, wait=True), i.send(ev, wait=True))   # hangs
```

vs. `send("T", wait=True)` twice (fresh objects each time) → both resolve. Sequential reuse of the same object also works. A 200-way concurrent `send("T", wait=True)` resolves all 200, so `id()` recycling of *dead* objects is not the issue — object identity reuse by the caller is.

Reusing a pre-built `Event` as a template is an obvious and documented-looking pattern (`send()` accepts `Event` instances in every overload). The fix is a monotonic per-send token instead of `id()`. **Severity: high** — an unkillable coroutine with no error, in the exact API added to make `send` answerable.

### 5.2 `SyncInterpreter` macrostep budget still discards legitimate external events — CONFIRMED (partially-fixed regression)

The CHANGELOG fixes this **only for replayed deferred events**:

> `SyncInterpreter`: replayed deferred events no longer count against the macrostep runaway budget… The async engine already behaved correctly; the two now agree.

They do not agree. `_process_event_queue` still does `processed += 1` per event and, past `max_iterations` (default 1000), calls **`self._event_queue.clear()`** — discarding every queued event. `replay_credit` exempts only deferred replays.

Reproduced via the public API: an action that calls `i.send("F")` 1500 times inside one macrostep →

- **Sync:** 999 of 1500 processed, 501 silently discarded (`ERROR` logged, no exception, no hook).
- **Async:** 1500 of 1500 processed.

The async engine's own comment states the correct design ("measure the RAISE CHAIN, not queue depth… 5,000 legitimate concurrent `send()` calls lost 3,999 of them"), and `_raise_depth` implements it — but only on `interpreter.py`. The sync engine never got the equivalent. Given that 0.8.0's headline is "the library fails silently by default", a silent 501-event drop on the default sync engine is a notable miss, and the changelog's "the two now agree" is inaccurate.

**Severity: medium-high** for anyone using `SyncInterpreter` with fan-out actions.

### 5.3 `strict` mode is bypassed by `send_threadsafe()` — CONFIRMED

`_check_strict` is called in `Interpreter.send` (line 601), `SyncInterpreter.send` (474) and the `raise` built-in (2555) — but **not** in `send_threadsafe()`, which calls `_prepare_event` and then `_enqueue` directly. Verified on a `strict: True` machine: `send("FIL")` raises `UnknownEventError` with a `Did you mean 'FILL'?` suggestion; `send_threadsafe("FIL")` is accepted, its future completes with no exception, and the event is silently dropped at dispatch. Registered `event_schemas` validators are bypassed on the same path.

`send_threadsafe` is the *recommended* API for foreign threads (§4.1 now forces its use), so this is the path a multi-threaded production app will take — and it is the one without the guardrail. **Severity: medium.**

### 5.4 One-shot `actionErrorPolicy` `DeprecationWarning` is per-**machine**, not per-process or per-interpreter

`_apply_action_error_policy` sets `self.machine.action_error_policy_is_default = False` on the *shared* `MachineNode`. Verified: two `SyncInterpreter`s built from the same machine → only the first warns. A long-lived process that creates interpreters per request from a module-level machine gets exactly one warning ever, likely during a warm-up path nobody reads. Intentional ("warn once per machine", per the comment), but worth knowing before the 1.0 default flip: the deprecation signal is far quieter than the migration it heralds.

---

## 6. Silent-failure paths review

0.8.0 substantially *reduces* silent failure. Remaining broad `except Exception` swallows in `src/`, audited:

| Site | Verdict |
|---|---|
| `_notify_subscribers`, `_emit` (listener raised) | Justified — matches XState v5.20.2 contract; logged with `logger.exception`. |
| `can()` | Logged, returns `False`. Acceptable for a predictive API. |
| `_resolve_output` / `_resolve_output_value` (output fn raised) | **Silently becomes `None`.** No hook, no policy. An `output` callable that raises produces a `done` machine with `output=None` and only a log line. This is the same class of defect #27/#35 set out to fix, and it is untouched. Candidate follow-up. |
| Named delay callable raised | Timer is **dropped**, log only. Same class — a machine can lose an `after` with no observable signal. Candidate follow-up. |
| Actor factory raised during restore | Logged; restore proceeds with a missing child. |
| `_cancel_scheduled_send` | `pragma: no cover` defensive. Fine. |
| guard / action / user-param / user-validator sites | All now routed through the new policies and hooks. Good. |

The `plugins.py` `pass  # pragma: no cover` hits are abstract no-op hook bodies, not swallows.

---

## 7. Thread-safety review of the unified core

Broadly improved:

- **`SyncInterpreter` timer threads are genuinely gone** (`_after_threads`, `_after_events`, `_pending_send_cancels` removed). Timers are now a `_DeadlineHeap` drained on the caller's thread via `_pump_timers()` / `tick()`. This removes the 0.7.0 unlocked-`context`-mutation-from-a-timer-thread hazard, which was the worst threading defect in 0.7.0.
- **`_DeadlineHeap` is `threading.Lock`-guarded** with lazy cancellation. Correct.
- **Pure-API probe cache is `threading.local`** with an explicit comment that the pre-#54 code was *accidentally* thread-safe and that caching must not give that up (they cite 502 wrong results from 8 threads on a shared cache). This is exactly the right reasoning and the right fix.
- **`send()` thread check is eager**, so cross-thread misuse raises at the call site rather than being GC-reported later.

Residual concerns:

- `SyncInterpreter` **still spawns an OS thread per non-blocking spawned actor** (`threading.Thread(...)`, ~line 950) and that thread acts as the child's pump. The class-level "single-threaded" contract therefore still has an asterisk; the new Production Characteristics page does describe the threading contract, so this is disclosed rather than hidden.
- `send_threadsafe` returns a future that resolves when the event is **queued, not processed**, and (per §5.3) skips strict/schema validation. The asymmetry with `send(wait=True)` is a sharp edge.

---

## 8. Snapshot format & upcaster

Solid. `persistence.py` is a clean, well-scoped 177-line module owning the contract.

- `SNAPSHOT_VERSION = 1`; version 0 = unversioned 0.7.x, accepted unchecked (correct — they carry no hash to check).
- `check_version` refuses a newer payload; `check_identity` refuses a different `machine_id` or a changed `machine_hash`; both run **before** any state is touched. Good ordering.
- `upcast(0→1)` is a no-op `setdefault("pending_events", [])`. Honest and minimal.
- Context restore is deep-copied and **shallow**-merged over machine defaults, with an explicit comment on why a recursive merge would be wrong (resurrecting intentionally deleted nested keys). Correct call.

**One gap in the hash contract:** `_transition_shape` hashes actions by **`type` name only** — action **params are excluded**. Verified: changing `{"type":"raise","params":{"event":"Z"}}` to `"event":"OTHER"` leaves the hash identical, so a snapshot restores cleanly into a machine whose actions now do something different. The docstring justifies excluding params ("a docstring edit or a reordered dict must not invalidate every stored snapshot"), but params are not docstrings — a `sendTo` target or a `raise` event type is behaviour. Guards get the careful treatment (`_guard_shape` recurses into composite children and `stateIn` targets after review F9); actions did not get the same pass. Worth raising: this is drift the restore is *supposed* to refuse.

---

## 9. Public API removals / renames

| Symbol | 0.7.0 | 0.8.0 | Documented? |
|---|---|---|---|
| `models.TEvent` | public TypeVar | **removed** | Only as a typing note (§4.2) |
| `Interpreter[Ctx, Any]` | valid | **`TypeError`** | Same |
| `interpreter._ACTOR_POLL_INTERVAL` | module-level | **removed** | Yes (Changed) |
| `PluginBase.on_guard_evaluated` | present | present (+ new `on_guard_error`) | Yes |
| `create_machine(strict_targets=)` | — | new, **default `True`** (rejects unresolvable targets) | Yes, incl. the 1.0 removal of the hatch |

**New defaults that change build outcomes:** `strict_targets=True` means a 0.7.x machine relying on the fuzzy last-segment fallback now **fails at `create_machine()`**. This is correct and loudly documented, and the error message names the absolute `#machine.path` fix — genuinely the best part of this release. But it *is* a default change, and it is filed under **Added**, not **Changed**.

New exports are all additive and correctly listed in `__all__`: `BaseInterpreter`, `PendingInvocation`, `Receipt`, `OverflowPolicy`, `Clock`/`RealClock`/`SimulatedClock`, and 9 new exception classes.

---

## 10. TODO/FIXME, tests, coverage

- **TODO/FIXME in `src/`:** 18 hits, **all in `cli/` code-generation templates** as intentional `# TODO: implement` stubs emitted into generated user code. Zero left in the runtime library. Clean.
- **Deleted/renamed files:** none (`--diff-filter=DR` empty).
- **Weakened/deleted tests:** the only test file with significant deletions is `tests/test_docs_site.py` (+173/−209). Seven tests were removed: `test_every_sample_executes`, `test_every_sample_actually_transitions`, `test_no_broken_guide_links`, `test_every_guide_page_is_reachable` — these four are **replaced by stronger equivalents** in the new `test_docs_executable.py` (executes every ```python block, resolves every cross-link/anchor). Net upgrade.
  However, three were removed with **no replacement anywhere in `tests/`**: `test_hero_badge_matches_package_version`, `test_nav_badge_matches_package_version`, `test_no_hardcoded_version_in_layout`. `grep` across `tests/` finds no successor. `docs/index.html:9` currently hard-codes `v0.8.0 — Fortify` and `docs/_config.yml:9` `version: "0.8.0"` — correct today, now **unguarded** against the next release. Minor, but it is a coverage regression introduced by this release.
- **Coverage gate:** `pyproject.toml` configures `[tool.coverage.run]`/`[report]` but sets **no `fail_under`**. There is no enforced coverage floor, so a coverage drop could not be detected from config alone. Test volume grew enormously (+13,115 lines, 46 files, incl. dedicated `test_v080_review_findings.py` / `test_wave2_review_findings.py` / `test_wave3_edge_paths.py` totalling ~2,700 lines of self-audit tests), so the *direction* is clearly right — but the claim is unverifiable without running the suite with coverage.
- **`mypy` "zero errors (was 61)" claim: unverified** — `mypy` is not installed in `.venv-gate`, so I could not check it. The CI lint job is asserted in the changelog.

---

## 11. Recommended follow-ups (draft only — no issues filed)

Ordered by severity. To be drafted as comment files if we pursue them.

1. **`send(wait=True)` receipt keyed on `id(event)` hangs on a reused `Event` object** (§5.1). Reproducer is 4 lines. Suggest a monotonic send token.
2. **`SyncInterpreter` macrostep budget still `clear()`s legitimate external events** (§5.2); port `_raise_depth` from the async engine. Also correct the changelog line claiming the engines agree.
3. **`send_threadsafe()` bypasses `strict` mode and `event_schemas`** (§5.3).
4. **Snapshot `machine_hash` ignores action params** (§8) — drift a restore should refuse is currently invisible.
5. **Document the `run_coroutine_threadsafe(send(...))` break** (§4.1) and soften the `WrongThreadError` message for that case.
6. **File `TEvent` removal / `Interpreter[Ctx, Any]` `TypeError` under a Removed heading** (§4.2).
7. **Fix or drop the "two deliberate exceptions" claim** (§3) — it currently undercounts by ~3.
8. **`output` callables and named-delay callables still fail silently** (§6) — the last two untreated members of the class this release targeted.
9. **Restore the three docs version-badge tests** (§10), or add a `fail_under` coverage gate.
10. **Clarify async `spawn_` vs `spawn_blocking_`** (§2d / `LC-12`): the non-blocking spelling still blocks the parent loop for a sync-bodied child.

---

## 12. Bottom line

0.8.0 delivers on its premise. The silent-failure surface that motivated the audit is materially smaller: unresolvable targets and dead `always` loops now fail at build time with actionable messages; guard errors, action errors and unhandled events are all observable through hooks that fire *under the 0.7.x defaults*; timers are injectable and starvation-resistant; snapshots have a real envelope; the sync engine no longer mutates context from timer threads.

The migration cost is higher than the changelog implies — roughly five observable behaviour changes rather than two, plus two undocumented runtime breaks (§4.1, §4.2). And the release does not entirely escape its own critique: §5.1 is a new silent hang in the very API added to make `send` answerable, §5.2 is a silent 501-event drop on the default sync engine, and §5.3 leaves the recommended cross-thread entry point without the new guardrail.

**Verdict: adopt, on the async engine, with `actionErrorPolicy` and `onUnhandled` set explicitly and `send(wait=True)` used only with freshly-constructed events.** Re-evaluate `SyncInterpreter` after §5.2.
