# Battle-test — SECURITY track — `v0.9.0` (`ff8ffe6`, round-12 #225-#235)

**Build.** `_ref/xstate-statemachine` @ tag `v0.9.0` = `91bd979`
(`main` = `ff8ffe6`, 2 commits ahead of the tag — `git diff v0.9.0..HEAD
--stat` shows only `.github/workflows/publish.yml` (CI publish-smoke-test),
**no library-source diff**, so testing against `main`'s checkout is
equivalent to the tag for this track). `__version__ == "0.9.0"`. **Not yet
on PyPI** (pip download fails) — installed from the local `src/` checkout
via `sys.path.insert`. `.venv-main`, `PYTHONIOENCODING=utf-8
PYTHONUTF8=1`, cwd `C:/Users/basil`. A full pytest+coverage run was
already in flight (`suite-v0.9.0.log`) and not duplicated here. No library
source modified; no git/gh writes. Scripts:
`battle-v0.9.0/security/a{1..6}_*.py` (this round), reusing the de2da4e
`attack_05_reentrant_wait_matrix.py` byte-for-byte (cited, re-run) to
confirm the #219 matrix is untouched by round-12.

---

## 1. Prior-defect re-run (round-11 `battle-de2da4e/security` items, on `v0.9.0`)

| Prior item | `de2da4e` status | `v0.9.0` result | Status |
|---|---|---|---|
| **R9-01/R10-01/R12-03 — import-path `_EngineDone` forgery** (Blocker→refuted-as-boundary in R12-03) | STILL-PRESENT (accepted trust-boundary reading as of round 12) | `a1_engine_done_forgery.py`: `_EngineDone` still importable from `xstate_statemachine.events`; forged `onDone` still fires `{'m.done_state'}` while the genuine 5 s service is in flight. **New this round**: `forged._replace(data=...)` now returns a plain `DoneEvent` with `is_system_event() == False` (#235) — the forgery still works via direct construction/`send()` of the private class, but the demotion-on-`_replace` hardening lands exactly where R12-03 recommended it (a caller-chosen variant of an engine event is now provably user traffic). | **STILL-PRESENT for the core vector (unchanged, accepted per R12-03's boundary framing); #235's `_replace`-demotion hardening confirmed present and correct** |
| **D11-security-4 — `on_invalid_event` unreachable on restore refusal** | STILL-PRESENT | **FIXED by `#230`.** `a3_restore_hook_and_strict.py` Part A: `from_snapshot(snapshot, m, plugins=[spy])` reaches `on_invalid_event` for a forged `UNDECLARED` `pending_events` record — `spy.invalid == [('UnknownEventError', Event(...))]`, `last_error` set. The **old** `.use()`-after-the-fact path is still structurally too late (confirmed, unchanged) — `plugins=` is the documented fix, not a change to `.use()` semantics. | **FIXED (new `plugins=` param closes it); old `.use()` path knowingly still too late** |
| **D12-security-1 — `chain_trips`/`last_chain_error` not persisted** | Info, operational note | **FIXED by `#226`.** `a2_chain_latch_snapshot.py`: v3 envelope now carries both keys (`"chain_trips" in snap` / `"last_chain_error" in snap` → `True`); a restore reports the same count and a `RestoredError` wrapping the original message; **monotonic across 4 consecutive restart hops** (`2→3→4→5`, one further trip per hop); `clear_chain_error()` clears the message but leaves the count unchanged; a v2 blob upcasts to `chain_trips=0, last_chain_error=None` (additive field, no crash on old blobs). | **FIXED, exact, no residual found** |
| **`#219` `ReentrantWaitError` matrix** | Sound (round-11) | Re-ran `battle-de2da4e/security/attack_05_reentrant_wait_matrix.py` byte-for-byte on `v0.9.0`: async self (`ReentrantWaitError`, `status=stopped`), sync self (`ReentrantWaitError`, `status=running`), deferred `ensure_future` escape hatch (resolves, no error) — **identical results to round 11**. Separately, `a5_task_identity_matrix.py` R2 (entry action reenters via `await i.send(..., wait=True)` before ever reaching a stable state) also trips `ReentrantWaitError` via `on_action_error`. | **Unchanged, still sound** |
| **`#220` recursive key check / `#221` parked scheduled_sends persistence** | Sound (round-11/round-12) | Not independently re-forced this pass (round-12's diff to these paths is nil per the CHANGELOG; `#227`/`#231` extend adjacent surfaces, tested fresh below). Carried on the strength of the round-12 catalogue review (`69-r12-final-readiness-verdict.md` rows for #220/#221: 5 FIXED, 0 regressed). | **carried, not re-run bit-for-bit this pass** |

---

## 2. New attacks — round-12 surfaces (#225-#235)

### 2.1 Task-identity provenance (#225) — `a5_task_identity_matrix.py`

Three cells, all against the new `_action_tasks` predicate (`ContextVar`
gone):

| Cell | Result |
|---|---|
| Worker `ensure_future`'d from an entry action, outliving the action, later `send(wait=True)`s | Resolves normally at 0.3 s past the action's own return — the worker is ordinary external traffic, not stuck in the internal-only lane. **No hang.** |
| Genuine in-step `await i.send(..., wait=True)` from an entry action reaching for its own step | Still refused with `ReentrantWaitError` via `on_action_error` — the narrowed predicate did not loosen the guard for the case it exists for. |
| 100 concurrent `ensure_future(send(wait=True))` hand-outs, each awaited 10 ms later from a *different* task than the spawning action | All 100 resolve; no cross-task false trip, no hang. |

No gap found: the round-11→round-12 predicate rewrite (task identity, not
context inheritance) preserves the guard's intent while fixing the
documented escape hatch's flakiness.

### 2.2 `def`-action dropped `wait=True` receipt (#232) — `a6_*.py` Part A/B

- Inside `asyncio`, dropping the receipt a `def` action receives from
  `send(..., wait=True)` raises `RuntimeWarning` **at GC time** (via
  `_PendingReceipt.__del__`), naming `#232`, the action, and the fix
  (`ensure_future`/no `wait=True`). Confirmed with `warnings.catch_warnings
  (record=True)`.
- **Observability nuance (new, not in prior rounds):** under `-W error`
  (`warnings.simplefilter("error", RuntimeWarning)`), the warning does
  **not** propagate as an exception to the caller's `await interp.start()`
  — it surfaces as `Exception ignored in: ... _PendingReceipt.__del__`
  printed to stderr, because CPython suppresses exceptions raised inside
  `__del__` (an "unraisable exception", `sys.unraisablehook`). A
  supervisor running under `-W error` to make warnings fatal will **not**
  see this one fail its `pytest`/`asyncio.run` call; it must install
  `sys.unraisablehook` or rely on `warnings.catch_warnings(record=True)`
  around the suspect window instead. Recorded as **D13-security-3** below
  (Low — documentation/observability gap, not a functional defect).

### 2.3 Inline-dict `invoke.src` (#231) — `a6_*.py` Part C

`create_machine` on a config whose `invoke.src` is an inline machine dict
(the XState-JS shape) now raises `InvalidConfigError` naming the state,
invoke id, the type received, and the supported alternative — not the
prior `TypeError: unhashable type: 'dict'`. Confirmed. `#231` **holds**.

### 2.4 `strict`/schema admission on restored `scheduled_sends` (#227) — `a4_scheduled_sends_strict_bypass.py`

300/300 property cases: a `scheduled_sends` record's `type` forged to an
undeclared/mistyped event name (`UNDECLARED_X` / `ping` / `PING_TYPO`)
is refused — but **only once `start()` re-arms it**, not at
`from_snapshot()` time itself (`_rearm_restored_self_sends` is called from
`start()`, per `base_interpreter.py:1273-1302`). `plugins=[spy]` given to
`from_snapshot` still catches the refusal correctly once `start()` runs,
because plugin registration precedes the re-arm call. Machine state stays
consistent (`m.w`) in every case; `on_invalid_event` fires once per
forged record; `last_error` is set. `#227` **holds** — with the
documented sequencing (`from_snapshot()` → `start()`) required for the
admission check to run, exactly as `#227`'s own docstring states.

### 2.5 `plugins=` at restore time (#230) — `a3_restore_hook_and_strict.py`

Confirmed: `from_snapshot(snapshot, machine, plugins=[spy])` reaches
`on_invalid_event` for a forged `pending_events` record — closing
D11-security-4. The old pattern (`from_snapshot(...).use(spy)`) remains
structurally too late, as before; this is not a regression, `plugins=`
is the documented remedy and callers must switch to it.

### 2.6 Chain-trip latch persistence (#226) — `a2_chain_latch_snapshot.py`

Covered in §1's table (D12-security-1 closure). Additional finding:
across 4 consecutive restart hops with one further trip forced per hop,
`chain_trips` incremented `2→3→4→5` (monotonic, matches the pre-restart
count plus new trips each time) and `last_chain_error` was replaced with
the newest `RestoredError`/live message at each hop — no stale message
survived past a fresh trip, and no count was lost across any hop.

### 2.7 Provenance under pickle/deepcopy (#235) — `a6_*.py` Part D

- `pickle.loads(pickle.dumps(forged))` and `copy.deepcopy(forged)` both
  preserve `_EngineDone`/`is_system_event() == True` — documented intent
  (persisted inboxes must keep provenance), not a hole.
- `forged._replace(data={})` returns a plain `DoneEvent`,
  `is_system_event() == False` — the demotion R12-03 flagged as a
  residual hardening option is now implemented exactly as recommended.

---

## 3. Defects (this round)

### D13-security-3 — `RuntimeWarning` from a dropped `wait=True` receipt does not propagate under `-W error` inside asyncio

**Severity (OMS): Low** (observability/documentation gap, not a functional
defect — the underlying #232 warning content and trigger are correct).
Class: OPERATIONAL-NOTE. Repro: `battle-v0.9.0/security/
a6_runtimewarning_inline_invoke_provenance.py` Part B.

The `#232` `RuntimeWarning` fires from `_PendingReceipt.__del__` at
garbage-collection time, which is architecturally correct (mirrors
CPython's own never-awaited-coroutine warning) but means a supervisor
that hardens itself with `warnings.simplefilter("error", RuntimeWarning)`
to make warnings fatal will **not** see `asyncio.run(...)` or
`await interp.start()` raise — CPython suppresses exceptions raised
inside `__del__` and instead prints `Exception ignored in: ...
_PendingReceipt.__del__` to stderr as an "unraisable exception". A
supervisor relying on `-W error` to fail CI/tests on this warning gets
silent stderr noise instead of a failed test. Mitigation: install
`sys.unraisablehook`, or wrap the suspect window in
`warnings.catch_warnings(record=True)` rather than relying on
`simplefilter("error", ...)` for this specific warning class. Not filed
higher because the warning's *content* and *trigger condition* are both
correct per `#232`'s docstring — only the "make it fatal" idiom fails
silently, and that idiom fails silently for the same structural reason
CPython's own GC-time warnings do.

### No other new defects found this pass

- `#225`'s task-identity rewrite (`_action_tasks`) is sound across all
  three matrix cells: no hang, no false trip, no cross-task leak.
- `#226` (chain-trip persistence), `#227` (restored-`scheduled_sends`
  admission), `#230` (`plugins=`), `#231` (inline-`invoke.src` naming),
  and `#235` (`_replace` demotion) all hold exactly as the CHANGELOG
  describes, with no residual gap found in the vectors tried this pass.
- The standing Blocker (import-path `_EngineDone` forgery) is unchanged
  and continues to be accepted under the R12-03 trust-boundary framing
  (private-`_`-prefixed import, not reachable from the public API).

---

## 4. Not covered / reduced this pass

- **Full 12-minute soak** (200 machines both kinds + action-spawned
  workers + heartbeats + external priority + chaos v3 restore with
  `plugins=`) — not independently re-run in this chunk; out of the
  ≤20-min wall-clock / ≤120 s-per-script bounds. The already-running
  `suite-v0.9.0.log` full pytest+coverage pass is the closest available
  substitute and was not duplicated.
- **Livelock fuzzer ≥500 configs × kinds × engines** and **config fuzzer
  incl. inline-dict `invoke.src` variants at scale** — only a single
  targeted inline-`invoke.src` cell was run (`a6_*.py` Part C); the
  broader ≥500-config sweep from the task brief was not run this pass to
  fit the time budget. `#220`'s recursive key-fuzz result is carried from
  round-12's own catalogue (638/640, 240/240) rather than re-run here.
- **200-machine / 100-concurrent-`ensure_future` soak-scale concurrency**
  — the 100-concurrent cell (`a5_*.py` R3) was run; the 200-machine
  variant named in the task brief was not, to fit the ≤20-min bound.
- **`def`-service `send()` task identity specifically under a thread-pool
  executor** — not separately probed; `a5_*.py`'s cells cover asyncio-task
  identity (entry action vs. spawned task vs. concurrent hand-outs) but
  not a `def` service literally running inside
  `loop.run_in_executor`/`ThreadPoolExecutor`.
- **Determinism (50× traces both engines, both kinds, incl. chain_trips
  and latch)** — not run this pass; `a2_*.py` establishes the
  monotonic-across-restarts property at n=4 hops on the sync engine only,
  not a 50-trace determinism comparison against the async engine.
- **12-minute soak's "0 dropped external events" / "no RuntimeWarning
  noise"** claims — not independently measured.
- **D11-security-5 (priority lane not honoured on sync restore)** —
  `#233` (CHANGELOG) claims this is now fixed (`SyncInterpreter.
  _enqueue_restored` honours `priority`), but this pass did not
  independently re-verify it; carried as **likely FIXED by #233, not
  re-run this pass**.
- **D11-security-6 (`SimulatedClock` doesn't fire restored
  `scheduled_sends`)** — not re-run; no round-12 changelog entry touches
  `SimulatedClock`'s pump path, so it is carried unchanged.

---

## 5. Verdict

Round-12's security-relevant fix set (`#225-#227`, `#230-#232`, `#235`)
is **sound on every vector independently exercised this pass**: the
task-identity rewrite (`#225`) fixes the documented round-11 escape-hatch
flakiness without loosening the reentrant-wait guard it exists to
enforce; the chain-trip latch (`#226`) closes round-11's D12-security-1
exactly, with no residual found across 4 restart hops; restored
`scheduled_sends` are now admission-checked (`#227`) at the documented
`start()`-time sequencing point; `from_snapshot(plugins=...)` (`#230`)
closes the long-standing D11-security-4; inline-dict `invoke.src` is
refused by name (`#231`) instead of a bare `TypeError`; a dropped
`wait=True` receipt in a `def` action now warns (`#232`) — with one new
Low-level observability note about how that warning interacts with
`-W error` under asyncio (**D13-security-3**); and `#235`'s `_replace`
demotion on engine-minted events is exactly the hardening R12-03
recommended.

**The standing Blocker is unchanged**: the import-path `_EngineDone`
forgery still mints a real `onDone` while the genuine service is in
flight, byte-identical to every prior round, and remains accepted under
R12-03's trust-boundary framing (private `_`-prefixed import, not a
public-API vector). Nothing in round-12's fix set touches that boundary
— by design, per R12-03's own disposition.

**Gate impact: unchanged from round-11/round-12.** No new mandatory
wrapper constraint from this pass. D13-security-3 is a documentation/
observability note for any supervisor that specifically relies on
`-W error` to make the `#232` warning fatal — it should install
`sys.unraisablehook` or use `warnings.catch_warnings` instead. All other
round-12 fixes verified this pass require no wrapper-side compensating
control; existing contract-vector constraints from `69-r12-final-
readiness-verdict.md` (CV-C60 for D11-security-4/#230, CV-C63 for
D12-security-1/#226) can be marked **library-closed, retained as defence
in depth** per that document's own stated pattern for #221/CV-C49′.
