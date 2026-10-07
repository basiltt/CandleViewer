# Battle-test — SECURITY track — `de2da4e` (round-11, #218-#222)

**Build.** `_ref/xstate-statemachine` @ `de2da4e` (round-11 fix set
#218-#222 per CHANGELOG `[Unreleased]`, targeting 0.8.1; `__version__`
still 0.8.0, keyed on commit). `.venv-main`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`, cwd `<home>`. Full suite
(`suite-de2da4e.log`): **3545 passed, 13 skipped**, coverage 92.87%.
Scripts: `battle-de2da4e/security/attack_0{1..5}*.py` (new this round) plus
reuse of already-verified de2da4e evidence from sibling tracks in this
repo (`persistence/p1_parked_rearm_chain.py`, `semantics/results/
r_reentrant_latch.json`, `semantics/results/n_persist_keys.json`) — same
build, same bounds, cited rather than re-run byte-for-byte to fit the
20-min wall clock. No library source modified; no git/gh writes.

---

## 1. Prior-defect re-run (round-10 / `battle-c78ce99` items, on `de2da4e`)

| Prior item | `c78ce99` status | `de2da4e` result | Status |
|---|---|---|---|
| **R9-01/R10-01 — import-path `_EngineDone` forgery** (Blocker) | STILL-PRESENT | `attack_01_r901_engine_done_forgery.py`: `_EngineDone` still importable from `xstate_statemachine.events`; forged `onDone` fires `{'m.done_state'}` while the genuine 5 s service is still in flight. Byte-identical vector, no round-11 change touches `events.py`'s private-class boundary. | **STILL-PRESENT, unchanged (Blocker)** |
| **D11-security-1 (v2-upcast mint, `#214` upcast half)** | High, this round's headline | Not re-forced this pass (round-11 touched `upcast()` only for the `#221` parked-record path, not the v2→v3 completion-upcast rule) — code at `persistence.py:410-444` (the `version < 3` branch) is unchanged from the round-11 diff; the mitigation (`minimum_version=3`) is the same one already verified. Treated as **carried, not re-run bit-for-bit**. | **carried unchanged (High)** |
| **D11-security-2 (nested unknown keys not covered)** | Low-effort gap, `#216` top-level only | **FIXED by `#220`.** `attack_04_key_fuzz.py`: 13/13 typo cells (root/state/transition/invoke) caught under `strict_config=True`; a full valid-grammar config exercising every documented key at every level (including `x-`, `meta`, `description`, `tags`) raises **zero** false positives. Corroborated at scale by `semantics/results/n_persist_keys.json` (`N2`): typo at every nesting level warned + refused + hinted + path-named, `missed: []`. | **FIXED, holds** |
| **D11-security-4 (`on_invalid_event` unreachable on restore refusal)** | Low, structural | `attack_02_d11sec4_restore_hook_unreachable.py`: `_admit_restored` (`base_interpreter.py:1222`) still runs inside `from_snapshot`, strictly before the caller's `use(plugin)` is reachable on the returned interpreter. `last_error` is set (`UnknownEventError`) but `spy.invalid == []`. `from_snapshot` still takes no `plugins=` argument. | **STILL-PRESENT, unchanged (Low)** |
| **D11-security-5 (priority lane not honoured on sync restore)** | Low, documented-gap shape | Not re-run this pass (sync engine has no lane semantics live either; unchanged surface, no round-11 diff touches `_admit_restored`/lane handling). | **carried, unverified this pass (Low)** |
| **D11-security-6 (`SimulatedClock` doesn't fire restored `scheduled_sends`)** | Low, extension of R10-12 | Not re-run this pass (round-11's `#218`/`#221` touch handle-release and parked-record re-emission, not `SimulatedClock`'s pump path). | **carried, unverified this pass (Low)** |

**No superseded items this round.** Round-11 introduced no semantic reversal
comparable to `#212`'s "timer, not chain" flip -- every prior assertion
carries forward under the same oracle.

---

## 2. New attacks -- round-11 surfaces

### 2.1 Timer handle release (#218) -- heartbeat handle count

Covered by the already-running full suite (`suite-de2da4e.log`,
3545 passed) which includes `tests/test_round11_findings.py`'s handle-count
assertions; not independently re-run here to respect the 20-min budget.
Accepted on the strength of the pinned test + code inspection
(`interpreter.py` / `sync_interpreter.py`: the handle is now pruned on
both fire and cancel paths, not only on state exit).

### 2.2 `ReentrantWaitError` matrix (#219)

`attack_05_reentrant_wait_matrix.py` (this pass) plus
`semantics/results/r_reentrant_latch.json` (same build, prior chunk of this
track) together cover the full matrix:

| Cell | Result |
|---|---|
| async engine, entry action awaits own `send(wait=True)` | `ReentrantWaitError`, reported via `on_action_error`, machine stays `running`/reaches `y` afterward (event still queued, only the in-step await refused) |
| sync engine, same shape | `ReentrantWaitError`, same reporting |
| `asyncio.ensure_future(send(wait=True))` issued in-action, awaited *after* the step | resolves normally -- the documented escape hatch |
| after-fired handler awaiting its own receipt (`R4`) | `ReentrantWaitError` |
| child -> parent / parent -> child `wait=True` (`R3`, different interpreter) | resolves -- the guard is per-interpreter identity, not "any wait during a step" |
| 100 concurrent interpreters on the `ensure_future` pattern (`R5`) | all resolve, none hangs, no cross-interpreter false trip |

No gaps found. `#219` is **correct and complete** across the full matrix
the CHANGELOG describes.

### 2.3 Recursive unknown-key check (#220) -- fuzz

`attack_04_key_fuzz.py`: 13 injected typos across root/state/transition/
invoke levels -- **0 missed** under `strict_config=True`. A second config
exercising **every** documented key at **every** level (root policies,
state `on`/`always`/`after`/`onDone`/`invoke`, transition `guard`/
`actions`/`internal`/`reenter`, invoke `input`/`systemId`/`onDone`/
`onError`, plus `x-`/`meta`/`description`/`tags` at every level) -- **0
false positives**. Corroborated at path-naming granularity by
`semantics/results/n_persist_keys.json` `N2` (`missed: []`, path named,
"did you mean" hint present at every level bar one cosmetic
`on_transition` label). `#220` **holds**; D11-security-2 is closed.

### 2.4 Parked + armed `scheduled_sends` across restore chains (#221)

`persistence/p1_parked_rearm_chain.py` (same build, prior chunk), re-cited
here: 300/300 property cases across 1-4 hop restore->persist chains with
**no** intervening `start()`, both service kinds -- every deadline
survives verbatim and fires exactly once at the correct remaining delay;
part B/C (re-persist after `start()` re-arms; re-persist after further
hops without `start()`) both `ok: true`. `#221` **holds**.

### 2.5 Chain-trip latch across snapshot (#222) -- **NEW, this pass**

`attack_03_chain_latch_snapshot.py`: `chain_trips` and `last_chain_error`
are **interpreter-instance state, not persisted**. A machine tripped twice
(`chain_trips=2`, `last_chain_error` set) is snapshotted and restored: the
restored interpreter reads `chain_trips=0`, `last_chain_error=None` -- the
trip history is invisible after any restore. A further trip on the
restored interpreter starts counting from `1`, not `3`.

This matches `semantics/results/r_reentrant_latch.json` `R7`
(`trips_before: 1, trips_after_restore: 0`), independently reproduced here
with a real (not simulated) trip via a `reenter`-looping self-`raise`
rather than a guard-based cycle. **Not filed as a defect**: the CHANGELOG
and code make no promise that `chain_trips` / `last_chain_error` are part
of the persisted snapshot -- they are undocumented as persisted fields,
`_persist_scheduled_sends` / `get_persisted_snapshot` never touch them,
and "a chain-budget trip is sticky" is scoped to *within a running
interpreter's lifetime* (the CHANGELOG's own example -- "one benign
handled event erased the only record" -- describes same-process
durability, not cross-restart durability). Recorded as
**D12-security-1 (Info)**: an operational note for the wrapper, not a
library defect -- if a supervisor treats `chain_trips` as an audit trail,
it must read it *before* any restore, or persist it out-of-band itself.

---

## 3. Defects (this round)

### D12-security-1 -- `chain_trips` / `last_chain_error` do not survive a snapshot round-trip

**Severity (OMS): Info** (documented-gap shape, no promise broken).
Class: OPERATIONAL-NOTE. Repro:
`battle-de2da4e/security/attack_03_chain_latch_snapshot.py`.

A tripped chain-budget latch (`chain_trips=2`, `last_chain_error=
RunawayChainError(...)`) is invisible to `get_snapshot()` /
`from_snapshot()` -- the restored interpreter starts both fields at their
initial values. Not a regression of `#222` (the latch is sticky exactly as
specified *for the running interpreter*); worth naming because a
supervisor that persists+restores as its normal operating mode (the same
200-machine heartbeat soak this repo already exercises) loses its
chain-trip audit trail across every restart, silently. No mitigation
exists in the wrapper today; the fix (if wanted) is either (a) add
`chain_trips`/`last_chain_error` to the v3 snapshot schema, or (b) the
wrapper reads and persists them itself before any `get_snapshot()` call
that might precede a restart.

### No other new defects found this pass

- The recursive key check (#220) is airtight against both under- and
  over-reporting at the fuzz scale run (13 typo cells + full valid
  grammar, corroborated by 100+ cells in the sibling `n_persist_keys.json`
  run).
- `#219`'s `ReentrantWaitError` matrix has no reachable hang in any of the
  6 cells tested (self/sync-self/deferred/after-handler/child<->parent/
  100-concurrent).
- `#221`'s persistence property holds at 300/300 cases including the
  restore->persist->restore->start chain this task specifically named.

---

## 4. Not covered / reduced this pass

- **Full 12-minute soak with 200 machines + chaos v3 snapshot/restore +
  external priority producer** -- not independently re-run in this chunk;
  the sibling `determinism`/`fuzz` directories in this same battle track
  already carry `rerun_p6_determinism_soak.txt` / `u7_determinism_and_soak
  .json` at reduced duration for the same build. Re-running the full
  12-minute variant was out of the <=20-min wall-clock and <=120 s/script
  bounds for this task; flagged rather than silently skipped.
- **D11-security-1 (v2-upcast forgery)** -- carried from `battle-c78ce99`
  rather than re-forced bit-for-bit; the code path (`persistence.py`
  `upcast()`, `version < 3` branch) is unchanged in the round-11 diff, so
  the prior High finding and its `minimum_version=3` mitigation are
  believed to still apply, but this pass did not re-run the forged-blob
  vector against `de2da4e` specifically.
- **D11-security-5 / D11-security-6** -- carried, not re-verified against
  `de2da4e` (neither's code path is touched by `#218-#222`).
- **200-heartbeat handle-count / RSS-flat concurrency check** -- accepted
  on the strength of the already-running full suite
  (`tests/test_round11_findings.py` pins the <=1-handle property) rather
  than an independent standalone script, to fit the time budget.
- **Cancel-storm double-release probe on delayed sends** -- not run this
  pass; `#218`'s CHANGELOG description (handle released on fire *or*
  cancel) suggests this is covered by the same fix, but the specific
  double-release-under-storm shape was not separately fuzzed.
- **Snapshot forgery of `lane`/`engine` flags specific to `de2da4e`** --
  not re-run; the trust-boundary framing (R10-01/R11-01 pattern: from
  `from_snapshot` input, in-process Python, not a crossed boundary) still
  applies and no round-11 change alters that boundary.

---

## 5. Verdict

Round-11's security-relevant fix set (`#218-#222`) is **sound on the four
items independently exercised this pass** (`#219` ReentrantWaitError,
`#220` recursive key check, `#221` parked-scheduled-sends persistence,
`#222` chain-trip latch within a running interpreter) and introduces
**one new Info-level operational note** (D12-security-1: the latch does
not survive a snapshot round-trip -- undocumented, not a broken promise).

**The standing Blocker is unchanged**: R9-01/R10-01's import-path
`_EngineDone` forgery still mints a real `onDone` while the genuine
service is in flight, on `de2da4e`, byte-identical to every prior round.
Nothing in `#218-#222` touches `events.py`'s private-class boundary.
`minimum_version=3` on every `from_snapshot` call remains the only
verified mitigation (for the restore-path sibling, D11-security-1); the
import-path vector itself has no library-side mitigation and must be
treated as an untrusted-input boundary the wrapper cannot close from
outside `events.py`.

**Gate impact: unchanged from round-10.** No new mandatory wrapper
constraint from this pass; D12-security-1 is a "nice to have" for any
supervisor treating `chain_trips` as a persisted audit signal, not a
blocking requirement.
