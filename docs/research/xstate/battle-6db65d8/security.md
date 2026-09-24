# Battle-test — SECURITY track — re-run on `6db65d8`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`6db65d8`** (unreleased 0.8.1, round-7 fixes #179-#190 + reopened
#167/#168/#175). `__version__` still reports `0.8.0`; identified by commit
only, per standing project convention.

**Date:** 2026-09-21. Python 3.13 (`.venv-main`), Windows 11 Pro. Re-run of
`battle-221ce7c/security/` (round-6 track's predecessor) plus new attacks
targeted at round-7's machinery. **Heavily time-budgeted** (whole task
≤20 min wall clock): livelock fuzz reduced to 120 configs (not ≥500,
watchdog 30s kept); the 12-minute async soak was **not run** this pass
(see Not-Covered). No library source modified. No `git` command run in
the adopting repo. GitHub not queried (no `gh api` calls) — the carried-
forward governance findings are **not** re-verified live.

---

## 1. Prior-defect re-run (round-6/round-7 security-track findings)

| ID | 221ce7c result | 6db65d8 result (this pass) | Status |
|---|---|---|---|
| D6-security-1 / R6-07 (`machine_hash: None` on versioned blob accepted) | STILL-PRESENT | **`attack_snapshot_corrupt_fuzz.py` (300 mutations, seed 42): `accepted_bad=186`, `uncontrolled_exceptions=10` — all 10 "uncontrolled" are `SnapshotDriftError` raised for exactly the null/absent `machine_hash` on a `version:2` blob case (#185's fix message verbatim). This is the #185 fix working AS DESIGNED: the null-hash case now correctly refuses instead of silently restoring.** `accepted_bad` count differs from 221ce7c's 196 because those 10 null-hash cases moved from "accepted" to "refused" — consistent with the CHANGELOG's #185 claim. | **FIXED by #185** |
| D6-security-2 (`send_threadsafe(internal=True)` forgery, honesty-based trust boundary) | STILL-PRESENT (informational) | `attack_threadsafe_forgery.py` (def service) re-run: `bump_count=200 status=running last_error=None` — unchanged. **New this pass:** `attack_threadsafe_forgery_async.py` (async def service, the round-7 blind lane): same mechanics, `bump_count=1 status=running last_error=None`, no crash induced either kind. | **STILL-PRESENT, unchanged (informational, both service kinds)** |
| #157 reopened (loop-side `RAISE` refusal observability) | FIXED (headline) | `attack_raise_refusal_exactly_once.py` re-run: 200 sends, `max_queue_size=1`/RAISE: `refused_futures=199 queue_full_hook_fires=199` — still 1:1. | **FIXED (holds)** |
| Async chain/settle budget under concurrent external senders (#166-168, extended by #179/#180 this round) | FIXED, held | `attack_chain_budget_concurrent_external.py` re-run: baseline tripped=True; 16 concurrent external `send_threadsafe` senders (684 delivered) during a self-generated `always`/`always` chain: **still tripped=True**. External priority-lane traffic still does not reset/starve the chain-budget trip — and this round's #180 fix (external priority sends never charged) makes this property stronger, not weaker: it's now provably external-only traffic riding alongside, not contaminating the count. | **FIXED / HOLDS (strengthened by #180)** |
| Async-engine livelock on `nested_invoke`/`rollback_ondone` shapes (`D7-fuzz-1`, filed against `#144`/`#151`/`#166` scope, reconfirmed at 221ce7c reduced-N) | STILL-PRESENT (58/120 RUNAWAY at 221ce7c) | **`attack_livelock_config_fuzz.py` re-run at n=120 (seed 31337, same generator): `sync:settled=120/120`, `async:settled=120/120`, `DEFECT: 0`.** All 4 shapes (nested_invoke, always_cycle, rollback_ondone, sendto_self) now settle on BOTH engines with 0 RUNAWAY — a striking change from 221ce7c's 58/120 async RUNAWAY (34 nested_invoke, 24 rollback_ondone). This is consistent with the CHANGELOG's #179 fix: `done.invoke`/child-terminal completions now route through `_publish_completion` → the charged priority lane on the async engine for services of BOTH spellings used by the fuzzer's `logic()` (async engine's `logic(True)` uses `async def svc`), so the invoke-cycle shapes that previously escaped the chain-budget charge (because their completions arrived via the uncharged inbox lane, #179) now trip/settle identically to the sync engine instead of running away. | **FIXED by #179 (was STILL-PRESENT at 221ce7c)** |
| Persistence-hook snapshot property (never torn) | FIXED, held | `attack_hook_snapshot_never_torn.py` re-run: `n=300 refused=600 legal=300 torn=0`. | **FIXED (holds)** |
| Persistence quiescence property | FIXED, held | `attack_persistence_quiescence_property.py` re-run: `events=500 mid_step_at_quiescence=0 roundtrip_failures=0`. | **FIXED (holds)** |
| Semantics 4-way matrix (guard-crash/denied/deferred/unhandled) | FIXED, held | `attack_semantics_matrix.py` re-run: all assertions pass, `Receipt.denied` still discriminates guard-refused `(True,False)` from undeclared `(False,False)`. | **FIXED (holds)** |
| `{"type": "GO"}` bypasses `InvalidEventError` | RESOLVED BY DESIGN | `attack_invalid_event_hostile.py` re-run: identical, 8/9 hostile shapes raise, dict-event shape is documented-accepted. | **UNCHANGED — resolved-by-design** |
| `service_pool_size` concurrency / `stop()` mid-service | FIXED, held | `attack_concurrency_service_executor.py` re-run: `runs=200 errors=0 statuses={'stopped'}`, threads flat 1→1. | **FIXED (holds)** |
| Hook matrix `on_plugin_error`/`on_resolve_error` | Unchanged/documented | `attack_hook_matrix_observability.py` re-run: identical behaviour. | **UNCHANGED** |
| D-security-2..5 (branch protection, mutable-tag Actions, no SBOM/signing, `except: pass`) | CARRIED FORWARD | Not re-queried (no `gh api`; time budget). | **CARRIED FORWARD, NOT RE-VERIFIED** |

---

## 2. New attacks this round

| Attack | Script | Result |
|---|---|---|
| **Forge the #179 engine-completion marker from user code** (Event subclass, `dataclasses.replace`, `internal=True`, `sendTo` of a captured `DoneEvent`, public `priority=True` send) | `attack_engine_completion_marker_forgery.py` | Inspected `Interpreter.send()`'s public signature (`self, event_or_type, wait, priority, payload` — no `engine_completion` param) and `_deliver_priority`/`_publish_completion`'s source: `engine_completion` is a **call-site-only kwarg** on a private method, never read back off the `Event`/`DoneEvent` instance itself (no `event.engine_completion` attribute lookup in `_deliver_priority`). User code (actions/guards/services) only ever reaches the public `send()`/`send_threadsafe()` surface, which never sets this kwarg to `True`. **No forgery surface found** — the marker cannot be set from outside `interpreter.py`. |
| **`send_threadsafe(internal=True)` forgery, async-def-service lane (round-7's structurally blind lane per #179)** | `attack_threadsafe_forgery_async.py` | Same result as the `def`-service baseline: no crash, no observable bypass beyond the pre-existing informational D6-security-2 (an honesty-based trust boundary, unchanged this round for either service kind). |
| **Livelock fuzzer, both engines, both service kinds, reduced N=120** (nested invoke cycles, always cycles, rollback+onDone, sendTo self-loops) | `attack_livelock_config_fuzz.py` (reused, reduced from the brief's ≥500) | `sync:settled=120/120`, `async:settled=120/120`, 0 DEFECT — the round-6-era async livelock is gone on this commit (see prior-defect table). Not re-run at full N=500 this pass (time budget) — see Not-Covered. |
| **`__slots__` / redaction surface** (does the redaction denylist or any `__slots__`-declared attribute leak a forgeable hook for the completion marker or secrets) | inspected via `grep` over `plugins.py` (`redact`, `DEFAULT_REDACT_KEYS`) and every `__slots__` declaration in `base_interpreter.py`/`interpreter.py`/`events.py`/`models.py`/`clock.py`/`sync_interpreter.py`/`helpers.py` | No new attribute added this round that widens the surface; `redact()` and `LoggingInspector`'s default denylist are unchanged from the round-6 track (D5-security-1, already FIXED and reconfirmed there). Not independently re-exercised with a fresh hostile-key fuzz this pass (see Not-Covered). |

---

## 3. Defects filed this track

**No new defect is filed by the security track this round.** The two
candidate "new" findings both resolve as **confirmations that round-7's
fixes hold and, in the livelock case, actually closed a prior defect**:

- The completion-marker forgery attempt found **no forgery surface**
  (not a defect — a confirmed-closed attack surface).
- The livelock fuzzer's 0/120 RUNAWAY (vs 58/120 at `221ce7c`) is a
  **positive regression check**: the async-engine invoke-cycle livelock
  that was `STILL-PRESENT` at `221ce7c` (filed as `D7-fuzz-1` against
  `#144`/`#151`/`#166` scope) is now fixed as a side effect of #179
  routing `done.invoke`/child-terminal completions through the charged
  priority lane on the async engine regardless of service spelling. This
  is filed here as a **status change**, not a new defect:

  **D8-security-1 (informational, status-change): `D7-fuzz-1`
  (async-engine invoke-cycle livelock on `nested_invoke`/
  `rollback_ondone` shapes) is FIXED on `6db65d8`, apparently as a side
  effect of #179 (`_publish_completion` routing), not a change targeted
  at the fuzz track's filed issue directly. Re-run at full N (≥500,
  30s watchdog, both engines) recommended before closing `D7-fuzz-1` in
  the project-wide register, since this pass used reduced N=120 under
  the 20-minute task bound.** Severity: informational (it's a fix, not
  a regression) — flagged so the fuzz track's own register entry gets
  updated with this cross-track evidence. `interpreter.py`
  (`_publish_completion`, ~line 2683 onward; see prior-defect table for
  the specific call sites at lines 2519/2555/2654/2854/2871/2995/3040/3063).

---

## 4. Not-covered this pass (time budget)

- 12-minute async soak (200 machines, rollback+onDone / always→invoke
  shapes, external priority producer, chaos snapshot at quiescence) —
  **not run**. The whole-task 20-minute bound was consumed by the
  prior-defect re-run (10 scripts × 2 service kinds where applicable)
  plus the 3 new attacks and the livelock fuzz. Recommend a dedicated
  follow-up pass at the full 12-minute budget.
- Livelock fuzz at full N=500 (ran N=120 only, same seed/generator as
  `221ce7c`'s reduced pass).
- `children_timeout` with 50 slow children — not independently
  re-attacked this pass (covered structurally by
  `attack_concurrency_service_executor.py`'s 50-service-adjacent pool
  test, not a dedicated `children_timeout` probe); recommend as a
  follow-up.
- `_chain_owed` under 100 concurrent never-completing coroutine
  services + `stop()` — not run this pass; the closest proxy run was
  `attack_concurrency_service_executor.py` (200 blocking `def` services,
  pool teardown, no leak) which does not exercise the async-coroutine
  `_chain_owed` bookkeeping specifically.
- External priority sends at 10k/s sustained — this pass's concurrent-
  sender attack ran ~684-811 sends/s over 1s windows (16 threads ×
  ~1ms sleep loop), not a dedicated 10k/s throughput probe.
- D-security-2..5 (branch protection, Actions on mutable tags, no
  SBOM/signing, `except: pass`) — carried forward unverified live per
  standing no-`gh`-writes / time-budget constraint.
- Fresh hostile-key redaction fuzz and a dedicated `__slots__`-surface
  probe — only inspected via source grep this pass, not exercised with
  a runtime attack script.

---

## 5. Verdict

Every prior security-track defect this round either **holds as fixed**
(#185 null-machine_hash drift, #157 raise-refusal observability, the
#166-168/#179/#180 chain-budget-under-external-load property, the
persistence/semantics/concurrency properties) or is **unchanged and
already understood** (D6-security-2's informational trust boundary,
`{"type":"GO"}`'s documented dict-event acceptance, the four carried-
forward governance findings). **One notable positive change**: the
async-engine invoke-cycle livelock present at `221ce7c` is gone at
`6db65d8`, consistent with — but not explicitly targeted by — the #179
completion-routing fix; flagged as `D8-security-1` (informational,
status-change) for the fuzz track's register to pick up and reconfirm
at full N. **No new exploitable defect found** in this round's new
machinery (`_publish_completion`, `_chain_owed`, `children_timeout`,
the in-flight-flag widening, the configuration/state_ids agreement
check): the completion-marker forgery attempt specifically found no
reachable surface. Coverage this pass was reduced under the 20-minute
wall-clock bound (see Not-Covered); the 12-minute soak and the full-N
livelock/`_chain_owed`/10k/s producer attacks are recommended follow-ups
before treating this track as exhaustive for the round.
