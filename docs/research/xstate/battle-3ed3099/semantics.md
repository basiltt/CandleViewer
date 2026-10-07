# Battle-test track re-run: SEMANTICS — round 5, commit `3ed3099`

**Build under test.** `_ref/xstate-statemachine` @ `main` =
`3ed3099` ("Merge pull request #139 from basiltt/fix/0.8.1-round4"),
unreleased 0.8.1. `__version__` still reports **`0.8.0`** — this build is
identified **by commit, never by version string**. `CHANGELOG.md`
`[Unreleased] — targeting 0.8.1` (round-4 fixes #102–#138, reopened #91/#99)
was read in full before any case was written.

**Date:** 2026-09-19. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter for every run below:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the adopting
project's repository. GitHub was read-only (not consulted this pass).

**Predecessor.** `battle-5e07ba8/semantics.md` (90 conformance cases, 4
defects D-semantics-1…6) and `battle-5e07ba8/semantics.triage.md`.

**Standard applied.** Candidate to run an order-management system handling
real money. Every silent failure, nondeterminism or ordering ambiguity is a
defect, reproduced with a standalone script before it is counted.

---

## 0. Bottom line

**Prior matrix re-run: 165/172 → 170/172. New attack suite: 33/35 PASS
across 6 groups. 5 of 6 prior defects FIXED. 3 new defects (1 High, 2
Medium) + 1 Low sharp edge, all in persistence.**

**The round-4 semantics work is real and it holds.** Everything this track
previously found on the actor/invoke boundary is fixed, and fixed properly —
not papered over.

- **Prior conformance matrix: 165/172 → 170/172.** Five previously failing
  case×engine runs now pass. The only remaining failures are the two rows of
  **D-semantics-4**, the known, deliberate, deterministic SCXML exit-order
  deviation.
- **All four prior LIBRARY-DEFECTs on the invoke/actor boundary are FIXED**,
  including both Highs: `done.invoke` now carries the child's declared
  `output` (#109), and `escalate` now reaches the parent's `onError` (#130).
  The two Lows are fixed as well, and **better than asked** — the ambiguous
  bare `stateIn` is now a hard `InvalidConfigError` rather than a silent pick
  (#132), and an unresolved `sendTo` now lands a typed error on the receipt
  (#133).
- **This round's headline fixes pass their own attacks.** 6/6 concurrency
  (#104 BLOCK under 16 producers, #105 per-task gate under `create_task`, 12
  OS threads and a child actor — *and* the gate still trips a genuine
  action self-send, so it was narrowed, not disabled); 9/9 semantics (#116
  engine parity, #108, #109, #113, #130, #132, #133, #136); 5/5 determinism
  (50× byte-identical traces on both engines, async trace now **identical**
  to the sync trace, stable across 5 hash seeds).
- **Three NEW defects, all in persistence, none a Blocker.** One **High**
  and two **Medium**. They share a root: the #102 mid-step guard and the #110
  `check_shape` validator each cover a *narrower* window than the contract
  they advertise.
  - **D5-semantics-1 (High).** `get_persisted_snapshot()` taken from inside
    an **entry action** is accepted and persists a **torn** state: the new
    state with a half-applied context. Restores are static, so the restored
    OMS is in `filled` with the fill never recorded. #102 refuses only the
    *no-leaf* window; the entry-action window has a leaf, so the guard passes
    while the macrostep is still open. Both engines.
  - **D5-semantics-3 (Medium).** A snapshot whose `configuration` list has
    its **leaf deleted** passes `check_shape` and restores to an **empty
    configuration reporting `status="running"`** — exactly #102's own
    failure mode, reached through a corrupt blob. Every *other* poisoning of
    that slot is correctly caught.
  - **D5-semantics-4 (Medium).** `from_snapshot()` leaks **untyped**
    `TypeError`/`AttributeError` for corrupt `status`, `history` and `system`
    values — 432 of 5000 fuzz mutations. `except XStateMachineError:` around
    a restore, which is what the #110 typed-error contract invites, does not
    catch them.
- **One Low sharp edge.** **D5-semantics-2**: `SimulatedClock.increment()`
  chooses sync-vs-async by the **ambient event loop**, not by the engine it
  drives, so a `SyncInterpreter` ladder driven from inside any running loop
  (a `pytest-asyncio` test, an async harness) silently never advances. The
  only signal is a GC-time `warnings.warn`. This one bit *me*: it produced a
  false FAIL in my own determinism group before I traced it.
- **Security and observability are clean.** Redaction (#126) leaks none of
  `password` / `api_key` / `token` while still logging `qty`; the exported
  provenance surface (#137) is complete and every new error class derives
  from `XStateMachineError`; provenance survives `deepcopy` and `pickle`
  (#138); `on_plugin_error` (#127) and unresolved-action reporting (#134)
  both fire.
- **A 6-minute chaos soak is spotless.** 3.38M events, 973k orders, 337k
  snapshots at quiescence and 84k restores: **zero** lost orders, **zero**
  restore drift, **zero** inert-while-`running`, **zero** spurious
  `SnapshotMidStepError`, and RSS flat at +1.7 MB.

**Verdict: the semantics track no longer blocks adoption.** The prior
adoption constraints CV-S02 (`done.invoke` workaround), CV-S03 (ban
`escalate`) and CV-S04 (fully-qualified `stateIn`) can be **retired**. They
are replaced by one new, narrow constraint — **never snapshot from inside an
action** (CV-S07) — and by hardening around a corrupt-blob restore (CV-S08).

---

## 1. Method and reductions

### 1.1 What was run

Two lanes:

1. **Prior-defect re-run.** Every script under
   `battle-5e07ba8/semantics/` was re-run unmodified on `3ed3099`: the full
   dual-engine matrix (`run_all_groups.py`, 172 case×engine runs) plus all
   eleven `repro/*.py` scripts. No script needed adapting for superseded
   behaviour — none of them takes a mid-step snapshot, so the new
   `SnapshotMidStepError` never fires in the prior corpus.
2. **New attack suite** under `battle-3ed3099/semantics/`, six groups
   (N1–N6), aimed specifically at this round's fixes.

### 1.2 Reductions against the brief (stated explicitly)

| Brief asked | Run as | Why |
|---|---|---|
| soak: **12-min** reduced run with chaos | **6 min** (`SOAK_SECONDS=360`) | The whole task budget is ~25 min wall clock and the prior-defect re-run plus six attack groups consumed most of it. The soak is parameterised — `SOAK_SECONDS=720 python n6_soak.py` restores the brief's figure unchanged. |
| *(all other items)* | **as specified, no reduction** | 2k-event property run, 5k fuzz mutations, 50× traces on both engines, 16 BLOCK producers, 64 `create_task` producers, 12 OS threads, 5 hash seeds all ran at full size. |

Every individual script completes well inside the 120 s per-run bound except
the soak, which is bounded by its own `SOAK_SECONDS`.

### 1.3 Honesty note — five of my own harness bugs, and what they show

I record these because in each case the **library's diagnostics are what
caught me**, which is itself a quality signal:

1. I wrote action callables with the wrong arity (`(ctx, e, am)`; the library
   passes `(interpreter, ctx, event, action_def)`). Actions silently did not
   run *from my point of view* — but the library reported it correctly:
   `last_transition_ok=False`, `last_error=TypeError(...)`, and
   `on_action_error` fired. **Not a defect**; I verified this before
   recording anything.
2. `asyncio.run_coroutine_threadsafe(interp.send(...), loop)` from a worker
   thread was rejected with a `WrongThreadError` whose message *names the
   correct replacement* (`send_threadsafe()`). Excellent error.
3. `{"type": "sendTo", "params": {"target": ...}}` was rejected at build with
   `missing required param(s) ['to']`.
4. Un-awaited `Interpreter.send_events(...)` — my bug, caught by a
   `RuntimeWarning`.
5. A false FAIL in the determinism group traced to **D5-semantics-2**, the
   `SimulatedClock` loop-context edge. That one *is* recorded as a (Low)
   defect, because the library's signal there is a GC-time warning rather
   than an error at the call site.

I also corrected an expectation before recording a defect: **N5-04**
originally demanded that `on_resolve_error` fire for an unimplemented action.
The library instead raises a typed `ImplementationMissingError` at the call
site. That is *observable*, which is the actual contract, so I relaxed the
assertion to "typed raise **or** hook **or** receipt error — silence is the
only failure". It passes.

### 1.4 Files

| Path (under `docs/research/xstate/battle-3ed3099/semantics/`) | Contents |
|---|---|
| `n_harness.py` | Minimal attack harness: `@attack(id, title, intent)`, JSON results writer |
| `n1_persistence.py` | **N1-01…07** — #102 at quiescence, #128, #117, #110, #131, #107, round-trip idempotence |
| `n2_concurrency.py` | **N2-01…06** — #105 under `create_task`/threads/child actor, #104 BLOCK |
| `n3_semantics.py` | **N3-01…09** — #116, #109, #108, #130, #132, #113, #136, #133 |
| `n4_determinism.py` | **N4-01…05** — 50× traces both engines, engine parity, 5 hash seeds, `SimulatedClock` ladder |
| `n5_fuzz_obs_sec.py` | **N5-01…07** — 5k snapshot mutations, hostile events, `on_plugin_error`, redaction, API surface, provenance round-trip |
| `n6_soak.py` | **N6-01** — reduced chaos soak (`SOAK_SECONDS`, default 360) |
| `repro/d5s1_entry_action_torn_snapshot.py` | **D5-semantics-1** minimal repro (both engines) |
| `repro/d5s2_simclock_loop_context.py` | **D5-semantics-2** minimal repro |
| `repro/d5s3_truncated_config_inert.py` | **D5-semantics-3** minimal repro |
| `repro/d5s4_untyped_snapshot_errors.py` | **D5-semantics-4** minimal repro |
| `results/*.json` | Per-group machine-readable results |

### 1.5 Exact commands

```bash
PY="<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1

# lane 1 — prior-defect re-run (unmodified scripts from the previous round)
cd .../battle-5e07ba8/semantics
"$PY" run_all_groups.py                       # 170/172
cd repro && for f in d*.py; do "$PY" "$f"; done

# lane 2 — new attack suite
cd .../battle-3ed3099/semantics
"$PY" n1_persistence.py     # 6/7
"$PY" n2_concurrency.py     # 6/6
"$PY" n3_semantics.py       # 9/9
"$PY" n4_determinism.py     # 5/5
"$PY" n5_fuzz_obs_sec.py    # 6/7
SOAK_SECONDS=360 "$PY" n6_soak.py

# new defect repros
cd repro
"$PY" d5s1_entry_action_torn_snapshot.py
"$PY" d5s2_simclock_loop_context.py
"$PY" d5s3_truncated_config_inert.py
"$PY" d5s4_untyped_snapshot_errors.py
```

---

## 2. Prior defects — FIXED / STILL-PRESENT / CHANGED

Re-run verbatim on `3ed3099`. "Adapted?" records whether the prior script
needed changing for superseded behaviour (none did).

| ID | Prior severity | Verdict | Adapted? | Evidence on `3ed3099` |
|---|---|---|---|---|
| **D-semantics-1** — `done.invoke` carries `child.context`, not the child's declared `output` | High | **FIXED** | no | `repro/d3_child_output.py` → `done event: {'type': 'done.invoke.kid', 'data': {'code': 7}}`, `VERDICT: ok`. New **N3-03** additionally asserts the child's private context does **not** leak: `context_leaked=False`. (#109) |
| **D-semantics-2** — `escalate` from an invoked child is unroutable, reaches neither `onError` nor `"*"` | High | **FIXED** | no | `repro/d6_escalate_route.py` → `parent state: ['m.caught']`, `VERDICT: ok`. New **N3-05** confirms the parent's `onError` target is entered. (#130) |
| **D-semantics-3** — `SyncInterpreter.tick()` delivers only ONE due `after` per call when deadlines chain | Medium | **FIXED** | no | `repro/d1_sync_after0_chain.py` → `sync after tick #1: ['m.d']` (all three links in one call; previously `['m.b']`), matching the async lane. `tick()` now drains until a pump delivers nothing (`sync_interpreter.py:1361-1369`). (#122) |
| **D-semantics-4** — parallel exit order is depth-major, not SCXML reverse-document-order | Low (DESIGN-CONSTRAINT) | **STILL-PRESENT (unchanged, still deterministic)** | no | `repro/d7_exit_order.py` → `["xb1","xa1","xB","xA","xp","eX"]` vs SCXML `["xb1","xB","xa1","xA","xp","eX"]`; **1 distinct order across 5 `PYTHONHASHSEED` values → DETERMINISTIC**. The only 2 remaining FAILs in the 172-run matrix (S-06, both engines). Was framed as WONTFIX-with-a-doc-note; that framing still stands. |
| **D-semantics-5** — ambiguous bare `stateIn` silently resolves to the active branch | Low | **FIXED (CHANGED — stricter than asked)** | no | `repro/d2b.py` now **raises** `InvalidConfigError: 'stateIn' guard 'work' is ambiguous: it names ['m.p.A.left.work', 'm.p.A.right.work']. Use a fully qualified id.` This is a **behaviour change**: a config that previously ran (wrongly) now fails at first use. Correct for an OMS — fail loudly beats pick-a-branch — but it is a migration hazard worth flagging. New **N3-06** pins it. (#132) |
| **D-semantics-6** — unresolved `sendTo` is a silent no-op, indistinguishable from success | Low | **FIXED** | no | `repro/d5_sendto_unresolved.py` → `Receipt(..., error=ActorSpawningError("sendTo target 'no_such_actor' did not resolve to a live actor; 'PING' was not delivered."))`, `last_transition_ok: False`. `VERDICT: observable`. New **N3-09** pins it. (#133) |

**Prior conformance matrix: 165/172 → 170/172 PASS.** The five newly-passing
runs are the D-semantics-1/2/5/6 cases in groups A and H plus the
D-semantics-3 sync row in group T. The 2 remaining FAILs are both
D-semantics-4 (S-06 async + sync).

**Summary: 5 of 6 prior defects FIXED (both Highs, the Medium, both Lows);
1 STILL-PRESENT and unchanged, and it is the deliberate design constraint.**

---

## 3. New attacks

### 3.1 N1 — Persistence (6/7)

| # | Attack | Result |
|---|---|:-:|
| N1-01 | **2000-event property run**: snapshot at EVERY quiescent point succeeds and round-trips (state + context) | **PASS** — 2000 events, 0 failures, `SnapshotMidStepError` never fired at quiescence |
| N1-02 | A snapshot taken from inside an **entry action** still raises `SnapshotMidStepError` | **FAIL → D5-semantics-1** — snapshot *succeeded*, torn |
| N1-03 | `restart_timers=True` re-arms a dormant `after` on a `SimulatedClock`; `has_dormant_timers` reports honestly | **PASS** — without: `dormant=True`, stays `t.arm`; with: `dormant=False`, reaches `t.fired` (#128) |
| N1-04 | Non-JSON pending payload raises `SnapshotSerializationError`, never stringified | **PASS** (#131) |
| N1-05 | Priority (fired-timer) lane survives a snapshot | **PASS** (#107) |
| N1-06 | `from_snapshot(clock=)` injects the caller's clock on both engines | **PASS** — `clock is c1`, ladder fires on the injected clock (#117) |
| N1-07 | Round-trip idempotence: `snapshot(restore(s)) == s` | **PASS** (modulo `taken_at`) |

### 3.2 N2 — Concurrency (6/6) — this round's #104/#105 work

| # | Attack | Result |
|---|---|:-:|
| N2-01 | 64 concurrent `create_task` producers × 20 events against `maxIterations: 25` | **PASS** — 1280/1280, no `RunawayChainError`, `status=running` (#105) |
| N2-02 | 12 OS threads × 25 events via `send_threadsafe()` against `maxIterations: 25` | **PASS** — 300/300 (#105) |
| N2-03 | `BLOCK` + `max_queue_size=4` under 16 concurrent producers × 25 | **PASS** — 400/400, no deadlock (#104) |
| N2-04 | Fire-and-forget `send()` under `BLOCK` with room in the inbox | **PASS** — the exact #104 shape, 5/5 enqueued |
| N2-05 | **Inverse test**: an *action's own* self-send is STILL charged | **PASS** — `RunawayChainError`, no hang. The gate was **narrowed, not disabled** |
| N2-06 | A child actor `sendParent`-ing 60× against the parent's `maxIterations: 25` | **PASS** — 60/60, no trip (#105) |

N2-05 is the load-bearing one: a fix that merely removed the budget would
have passed N2-01/02/03/04/06 and left a runaway self-send unbounded.

### 3.3 N3 — Semantics (9/9)

| # | Attack | Result |
|---|---|:-:|
| N3-01 | #116: identical `(GO, CANCEL)×10` script → same `ok`/`cancel` split on both engines | **PASS** — the exact #116 shape (async gave `cancel=10` where sync gave `ok=10`) |
| N3-02 | #116: `send_events([GO, X])` agrees with `send(GO); send(X)` on both engines | **PASS** — all four combinations identical |
| N3-03 | #109: `done.invoke` carries declared `output`, no context leak | **PASS** |
| N3-04 | #108: a transition targeting the machine ROOT is rejected at build | **PASS** — `RootTargetError` |
| N3-05 | #130: `escalate` from an invoked child reaches the parent's `onError` | **PASS** |
| N3-06 | #132: ambiguous bare `stateIn` rejected at first use | **PASS** — `InvalidConfigError` |
| N3-07 | #113: non-`str` event `type` (int/None/list/bytes) raises `InvalidEventError` | **PASS** — all four, and it is also a `TypeError` |
| N3-08 | #136: self-referential config raises `InvalidConfigError`, not `RecursionError` | **PASS** |
| N3-09 | #133: unresolved `sendTo` is observable on the receipt | **PASS** |

### 3.4 N4 — Determinism (5/5)

| # | Attack | Result |
|---|---|:-:|
| N4-01 | 50× the same 8-event script on `SyncInterpreter` (parallel regions + guards + `always` + plain-sync invoke + `after`) | **PASS** — 1 distinct trace |
| N4-02 | 50× the same script on `Interpreter` (async) | **PASS** — 1 distinct trace |
| N4-03 | The async trace and the sync trace are **byte-identical** | **PASS** — 27 actions and 19 transitions agree exactly. This is the strongest single result in the re-run: it is what #116 was *for*, and it did not hold before |
| N4-04 | Trace stable across 5 `PYTHONHASHSEED` values (subprocess) | **PASS** — 1 distinct SHA-256 |
| N4-05 | `SimulatedClock` timer ladder replay-identical 30× on both engines | **PASS** — after running the sync lane off-loop (see D5-semantics-2) |

### 3.5 N5 — Fuzz, observability, security (6/7)

| # | Attack | Result |
|---|---|:-:|
| N5-01 | **5000 structured snapshot mutations** (set/delete across every JSON path, 11 poison values) | **FAIL → D5-semantics-3 + D5-semantics-4** |
| N5-02 | 10 hostile event `type`s (int, None, float, bytes, list, dict, object, bool, tuple, set) | **PASS** — all `InvalidEventError` (#113) |
| N5-03 | `on_plugin_error` fires for an `async def` hook on the sync engine | **PASS** (#127) |
| N5-04 | An unimplemented action name is observable (typed raise / hook / receipt) | **PASS** — typed `ImplementationMissingError` (see §1.3) |
| N5-05 | `LoggingInspector` redacts by default | **PASS** — none of `hunter2` / `sk-live-xyz` / `t0k` reached the log; `qty=100` still logged; 13 default keys (#126) |
| N5-06 | Exported provenance API surface complete, all new errors derive from `XStateMachineError` | **PASS** (#137) |
| N5-07 | Provenance survives `deepcopy` and `pickle`; a user event is not a system event | **PASS** (#138) |

N5-01 outcome distribution over 5000 mutations:

| Outcome | Count |
|---|---:|
| `accepted-legal` (faithful restore) | 2725 |
| `typed:SnapshotCorruptError` | 1362 |
| `typed:SnapshotDriftError` | 330 |
| `typed:StateNotFoundError` | 74 |
| `typed:SnapshotVersionError` | 15 |
| **`accepted-illegal`** (empty configuration) | **62** → D5-semantics-3 |
| **`UNTYPED:AttributeError`** | **261** → D5-semantics-4 |
| **`UNTYPED:TypeError`** | **137** → D5-semantics-4 |
| **`UNTYPED:ValueError`** | **34** → D5-semantics-4 |

**1781/5000 (35.6%) correctly typed; 432 (8.6%) untyped; 62 (1.2%)
silently illegal.** The validator does real work — it is incomplete, not
absent.

### 3.6 N6 — Soak (reduced to 6 min)

A long-lived OMS-shaped actor under continuous traffic with a chaos loop
(snapshot/restore, hostile events, unknown types), checking continuously
that the configuration is never empty while `status=="running"`, that
`filled + rejected <= submitted` (no lost orders), that a snapshot at
quiescence always succeeds and round-trips, and that RSS stays bounded.
**PASS — zero violations over 360.0 s.**

| Measure | Value |
|---|---:|
| Events processed | **3,382,000** |
| Orders submitted / filled / rejected | 973,687 / 680,897 / 292,789 |
| Outstanding at stop (1 order mid-flight) | 1 |
| Snapshots taken at quiescence | **337,754** |
| Snapshot→restore round-trips | **84,436** |
| Hostile / unknown events injected | 1,096,873 |
| **`SnapshotMidStepError` at quiescence** | **0** |
| Restore-drift violations | **0** |
| Inert-while-`running` violations | **0** |
| Lost-order accounting violations | **0** |
| RSS start → end | 30.1 MB → **31.8 MB** (+1.7 MB) |

This is the strongest single piece of evidence in the re-run. Over 3.4M
events and 337k snapshots, `SnapshotMidStepError` **never once** fired at a
quiescent point (the #102 fix does not over-refuse), every one of 84k
restores matched the live configuration exactly, order accounting never
broke, and RSS grew 1.7 MB — flat, not a leak. A 30 s smoke run of the
identical script passed before the full run was launched.

---

## 4. Defects — D5-semantics-n

Severity scale (from the findings register): **Blocker** = money loss or
silent state corruption on the order path; **High** = silent wrongness or a
hard architectural constraint; **Medium**; **Low**.

---

### D5-semantics-1 — a snapshot taken inside an ENTRY ACTION is accepted and persists a TORN state

- **Severity: High.** Silent state corruption on the order path, but it
  requires the adopter to call `get_persisted_snapshot()` from inside an
  action — a narrow, avoidable trigger, which is what holds it below Blocker.
- **Classification:** LIBRARY-DEFECT (incomplete #102).
- **Engines:** both (`Interpreter` and `SyncInterpreter`).
- **Repro:** `repro/d5s1_entry_action_torn_snapshot.py`; also **N1-02**.
- **Root cause:** `base_interpreter.py:1156` —
  ```python
  if self._step_in_flight() and not self._active_leaf_present():
      if _seen is None:
          raise SnapshotMidStepError(self.id)
  ```
  The refusal requires **both** "a step is in flight" **and** "no active
  leaf" (`_active_leaf_present`, `base_interpreter.py:1112-1115`). #102 was
  scoped to the *no-leaf* window — between the exit set and the entry set.
  But the macrostep is still open **after** the entry set is applied, while
  the new state's own entry actions run. In that window a leaf **is**
  present, so the guard passes and the snapshot is taken against a
  half-applied context.

- **Observed:**
  ```
  --- SyncInterpreter
    live after settle : ['oms.filled']  ctx={'filled_qty': 100}
    snapshot mid-entry: ACCEPTED state_ids=['oms.filled'] ctx={'filled_qty': 0}
    last_transition_ok=True  last_error=None
    restored          : ['oms.filled']  ctx={'filled_qty': 0}
    >>> TORN: state says filled, context says 0 filled
  --- Interpreter (async)
    ...identical...
  ```
- **Why it matters for an OMS.** The machine is in `filled`; the context says
  nothing was filled. Because a restore is deliberately **static** (entry
  actions are not re-run — `base_interpreter.py:1310-1313`), the fill is lost
  permanently, and nothing anywhere reports a problem:
  `last_transition_ok=True`, `last_error=None`. This is precisely the class
  of silent corruption #102 was raised to eliminate; the guard just stops one
  window too early.
- **Suggested fix.** Refuse whenever `_step_in_flight()` is true at the root
  of the call, regardless of leaf presence — i.e. drop the
  `and not self._active_leaf_present()` conjunct for `_seen is None`. The
  child-actor branch, which legitimately needs the leaf check to avoid
  failing a parent snapshot on a race, is unaffected.
- **Adoption constraint (CV-S07).** Never call `get_persisted_snapshot()`
  from inside an action, guard or service. Snapshot only from outside the
  interpreter at a known-quiescent point. N1-01 shows 2000 such snapshots are
  reliable.

---

### D5-semantics-3 — a truncated `configuration` restores to an empty, permanently inert machine reporting `running`

- **Severity: Medium.** Silent inertness of an order actor, but it requires a
  pre-existing corrupt blob (storage corruption, a bad migration, a hostile
  write) rather than arising in normal operation.
- **Classification:** LIBRARY-DEFECT (incomplete #110).
- **Repro:** `repro/d5s3_truncated_config_inert.py`; 62/5000 in **N5-01**.
- **Root cause:** `persistence.py:178-195` (`check_shape`). The validator
  checks element **types** and has an explicit empty-configuration guard:
  ```python
  if status == "running" and not (
      snapshot.get("configuration") or snapshot["state_ids"]
  ):
      fail("status is 'running' but the configuration is empty")
  ```
  but that guard only fires when the list is *empty*. A **truncated**
  `configuration` (`['oms','oms.filled']` → `['oms']`) is non-empty and all
  strings, so it passes — and `base_interpreter.py:1442` prefers
  `configuration` over `state_ids`:
  ```python
  restore_ids = snapshot.get("configuration") or snapshot["state_ids"]
  ```
  so the surviving ancestor restores with **no leaf at all**. `state_ids`,
  which still names the correct leaf, is never consulted.
- **Observed** — note only DELETION slips through:
  ```
  healthy snapshot: configuration=['oms', 'oms.filled'] state_ids=['oms.filled']
    leaf -> None    -> SnapshotCorruptError: ... must be a list of state-id strings.
    leaf -> ''      -> StateNotFoundError: Could not find state with ID ''.
    leaf -> 'xxx'   -> StateNotFoundError: Could not find state with ID 'xxx'.
    leaf DELETED    -> ACCEPTED ids=[] status='running'
                       after 3x FILL: ids=[] ctx={'qty': 0}
                       last_transition_ok=True last_error=None status='running'
  ```
- **Why it matters.** This is #102's own failure mode — "a permanently inert
  machine reporting `running`" — reached by a different route. The actor
  accepts orders forever, changes nothing, reports no error, and every health
  signal reads green.
- **Suggested fix.** In `check_shape`, require the restored configuration to
  contain at least one **atomic** state (the `_active_leaf_present` predicate
  already exists), and/or cross-check `configuration ⊇ state_ids`.

---

### D5-semantics-4 — `from_snapshot()` leaks untyped exceptions for corrupt `status` / `history` / `system`

- **Severity: Medium.** Not corruption — a restore correctly fails — but it
  breaks the #110 typed-error contract, so a correctly-written adopter
  crashes instead of handling the failure.
- **Classification:** LIBRARY-DEFECT (incomplete #110).
- **Repro:** `repro/d5s4_untyped_snapshot_errors.py`; 432/5000 in **N5-01**.
- **Root cause:** `persistence.py:166-195` validates `status` (membership),
  `context`, `state_ids`, `configuration`, `pending_events` and `deferred` —
  but not the **type** of `status`, nor `history`, nor `system`. The restore
  then does `(snapshot.get("history") or {}).items()`
  (`base_interpreter.py:1481`) and `(snapshot.get("system") or {}).items()`
  (`base_interpreter.py:1518`), which raise `AttributeError` on a non-mapping;
  and `status not in _VALID_STATUSES` (`persistence.py:170`) raises
  `TypeError: unhashable type` when `status` is a `list` or `dict`, *before*
  it can `fail()`.
- **Observed:**
  ```
  field      poison     outcome
  status     []         UNTYPED TypeError: unhashable type: 'list'
  status     {}         UNTYPED TypeError: unhashable type: 'dict'
  status     0          typed  SnapshotCorruptError
  history    True       UNTYPED AttributeError: 'bool' object has no attribute 'items'
  history    x          UNTYPED AttributeError: 'str' object has no attribute 'items'
  system     x          UNTYPED AttributeError: 'str' object has no attribute 'items'
  system     []         ACCEPTED
  7/9 corrupt blobs escaped the XStateMachineError hierarchy.
  ```
- **Why it matters.** #110's whole point is that a restore fails *typed*. An
  adopter writing `except XStateMachineError:` around `from_snapshot()` — the
  documented contract — does not catch 8.6% of corrupt blobs, so a poisoned
  row in the snapshot store takes the process down rather than routing to
  recovery.
- **Suggested fix.** Guard the `status` membership test with an
  `isinstance(status, str)` check first, and add `history` / `system` mapping
  validation to `check_shape`.
- **Adoption constraint (CV-S08).** Wrap `from_snapshot()` in
  `except Exception`, not `except XStateMachineError`, until this is closed.

---

### D5-semantics-2 — `SimulatedClock.increment()` dispatches on the ambient event loop, not the engine

- **Severity: Low.** A test/harness sharp edge, not a production order-path
  defect — but it silently produces *false green* tests, which is how real
  defects get missed.
- **Classification:** DESIGN-CONSTRAINT (deliberate, per the `_MustAwait`
  docstring) with an observability gap.
- **Repro:** `repro/d5s2_simclock_loop_context.py`.
- **Root cause:** `clock.py:312-318` —
  ```python
  def _advance_to(self, target):
      try:
          asyncio.get_running_loop()
      except RuntimeError:
          self._drain_sync(target); return None
      return _MustAwait(self._drain_async(target))
  ```
  The branch keys on whether *any* loop is running on this thread, not on
  which engine the clock drives. Driving a `SyncInterpreter` from inside a
  loop therefore returns an awaitable that sync-style call sites discard.
- **Observed:**
  ```
  SyncInterpreter + SimulatedClock, NO running loop:
    outside loop    increment()->['NoneType','NoneType']   states=[['L.s1'],['L.s2'],['L.s3']]
  SyncInterpreter + SimulatedClock, INSIDE a running loop:
    inside loop     increment()->['_MustAwait','_MustAwait'] states=[['L.s1'],['L.s1'],['L.s1']]
  Is anything raised or logged at the call site? warnings at call site = 0 (GC-time only)
  ```
- **Why it matters.** The library *does* try to signal this: `_MustAwait`
  warns on `__del__`. But that is a GC-time `warnings.warn`, so it is
  invisible under `logging.disable`, `-W ignore`, or a pytest filter, and it
  arrives **after** the assertion has already passed against an
  un-advanced machine. Any `pytest-asyncio` suite that drives a
  `SyncInterpreter` on a `SimulatedClock` silently tests nothing. It produced
  a false FAIL in my own N4-05 before I traced it.
- **Suggested fix.** Dispatch on the interpreter the clock is attached to
  rather than the ambient loop, or raise immediately at the call site when a
  `SimulatedClock` with only sync settlers is advanced inside a loop.
- **Adoption constraint (CV-S09).** Drive `SyncInterpreter` + `SimulatedClock`
  ladders off-loop (`asyncio.to_thread`, as `n4_determinism.py` now does), or
  assert on state after every `increment()`.

---

## 5. Coverage — and what was NOT covered

### Covered this pass

- All six prior `D-semantics-n` defects, re-run verbatim, plus the full
  172-run dual-engine conformance matrix.
- Round-4 fixes attacked directly: #102, #104, #105, #107, #108, #109, #110,
  #111, #113, #116, #117, #122, #126, #127, #128, #130, #131, #132, #133,
  #134, #136, #137, #138.
- Concurrency under three distinct producer shapes (asyncio tasks, OS
  threads, a child actor) plus the inverse test that the gate still trips.
- Determinism at 50× per engine, engine-to-engine parity, and 5 hash seeds.
- 5000-mutation snapshot fuzz; 10 hostile event types.
- Redaction, exported API surface, provenance round-trip through
  `deepcopy`/`pickle`.

### NOT covered — stated plainly

1. **The soak is 6 min, not the 12 min the brief asked** (§1.2). Re-run with
   `SOAK_SECONDS=720`.
2. **#99 / #103 / #112 / #114 / #120 / #123 / #124 / #125 / #129 / #135 /
   #106 / #118 / #91 / #121 were not attacked in this track.** They are
   engine-lifecycle, receipt-bookkeeping and plugin-parity items that belong
   to the *concurrency* and *observability* tracks, not semantics. This
   track's `n3_semantics.py` covers the semantic subset only.
3. **No multi-process or cross-host snapshot exchange.** All restores were
   in-process. A snapshot written by one Python version and read by another
   is untested.
4. **No adversarial fuzz of the machine CONFIG** (only of snapshots).
   `create_machine` hardening beyond #108/#132/#136 is untested here.
5. **The 5k fuzz used a 2-state flat machine.** Parallel regions, history
   nodes and live child actors in the blob would widen the mutation surface
   considerably; 62 illegal + 432 untyped is therefore a **lower bound**.
6. **D5-semantics-1 was not swept across all action kinds** — it is confirmed
   for entry actions on both engines, but exit actions, transition actions,
   guards and services were not each enumerated. The root cause
   (`base_interpreter.py:1156`) implies they are all affected; I did not
   prove it case by case.
7. **No performance/latency measurement.** That is the `bench/` track.
8. **Windows only, CPython 3.13.7 only.** The CHANGELOG mentions 3.9–3.11
   behaviour for `AsyncMock` services; no other version was exercised.

---

## 6. Verdict

**The semantics track passes on `3ed3099`.** Round 4 did what it claimed: the
two High actor/invoke defects and the Medium timer-pump defect are genuinely
fixed, the two Lows are fixed more strictly than requested, and the one
remaining prior failure is the documented, deterministic SCXML exit-order
deviation that was always framed as WONTFIX-with-a-doc-note. Engine parity —
the thing #116 existed to establish — now holds byte-for-byte across a
50×-replayed script exercising parallel regions, guards, eventless hops, an
inline sync invoke and a timer.

The three new defects are all in **persistence**, and they rhyme: **#102's
mid-step guard and #110's `check_shape` validator each cover a narrower
window than the contract they advertise.** Both are real, incomplete
implementations of good ideas rather than wrong ideas — `check_shape`
correctly typed 35.6% of 5000 mutations and the mid-step guard correctly
refuses the no-leaf window. Closing them is bounded work:

- **D5-semantics-1 (High)** — drop one conjunct at `base_interpreter.py:1156`.
- **D5-semantics-3 (Medium)** — require an atomic state in `check_shape`.
- **D5-semantics-4 (Medium)** — type-guard `status`, validate `history` /
  `system`.
- **D5-semantics-2 (Low)** — dispatch on the attached interpreter, not the
  ambient loop.

**Adoption position.** No Blocker. The prior semantics constraints
**CV-S02** (write child results into context), **CV-S03** (ban `escalate`)
and **CV-S04** (fully-qualified `stateIn`) are **retired** — the library now
does the right thing natively, and in the `stateIn` case enforces it. They
are replaced by three narrower ones:

| New constraint | Rule |
|---|---|
| **CV-S07** | Never call `get_persisted_snapshot()` from inside an action, guard or service. Snapshot only from outside the interpreter at quiescence. |
| **CV-S08** | Wrap `from_snapshot()` in `except Exception`, not `except XStateMachineError`, and assert the restored configuration is non-empty before trusting it. |
| **CV-S09** | Drive `SyncInterpreter` + `SimulatedClock` off-loop, or assert state after every `increment()`. |

**CV-S05** (avoid cross-region exit-ordering dependencies, D-semantics-4) and
**CV-S01** (`invoke.input` via a `context` factory) carry forward unchanged.

One migration hazard to flag to any existing user, unrelated to our
adoption: **#132 turns a previously-running ambiguous bare `stateIn` into a
hard `InvalidConfigError` at first use.** That is the right call for an OMS,
but it is a breaking change that a release note should name explicitly.
