# Determinism battle track — de2da4e (round-11 re-verification)

## 0. Bottom line

Every prior-round determinism-track defect (`d`/`e`/`f`/`g`/`h`/`i`/`n` scripts
from `battle-c78ce99/determinism/`) re-run against `de2da4e` unchanged
(FIXED where round-10/11 said so; STILL fine where round-11's own fixes
already covered them). Three scripts (`d1_replay.py`, `d2_receipt_deferred.py`,
`f5_nested_parallel_snapshot_refusal.py`) use `wait=True` on an action's own
interpreter — that shape now raises `ReentrantWaitError` per #219, so those
call sites were checked: **none of the three actually triggers the new
refusal** (the `wait=True` calls in all three are at the *harness* driving the
interpreter from outside a running step, not from inside an action executing
on that interpreter — see §1). No SUPERSEDED cases this pass.

New attacks (§3): scheduled_sends across restore→persist→restore→start
chains (#221, 320 property cases, 0 failures), the `ReentrantWaitError`
matrix (#219, all 4 shapes match spec exactly), and a config-key fuzzer
against the recursive check (#220, 400 typo cases all caught, 400
valid-grammar cases 0 false positives).

**No new `D12-determinism-n` defects are raised this pass.**

Time-boxed: soak (12-min/200-machine), the concurrency/heartbeat-handle-count
attack, chain-trip-latch-across-snapshot attack, and the full
ReentrantWaitError-under-100-concurrent-actions / cancel-storm / livelock
fuzzer (≥500 configs) were **not run** this pass — see §4.

## 1. Prior-defect re-run table (inherited d/e/f/g/h/i/n suite, on `de2da4e`)

| Script | Verdict | Notes |
|---|---|---|
| `d1_replay.py` | STABLE | 5 runs × 500 events (reduced from default 50×10000 for the wall-clock budget): async self-identical, sync self-identical, cross-engine `context`/`transitions`/`snapshots` SAME; `hooks`/`receipts` differ only in the expected init-order artifact already on record. `wait=True` calls are the *test driver* awaiting the interpreter's own receipt from outside any action — not the in-action reentrant shape #219 targets, so no `ReentrantWaitError` here (correctly). |
| `d2_receipt_deferred.py` | STABLE | 0/400 false `deferred=True` on a `HANDLED` receipt, both engines, both of 2 runs, deterministic across runs. Same non-reentrant `wait=True` usage as d1. |
| `d3_perturb.py` | STABLE | P1: 25/25 identical action trace, context, final state under jitter. P2: 20/20 runs preserve arrival order under 8 concurrent senders, 0 lost events. |
| `d4_ordering.py` | STABLE | All `C1..C10` (+ `s` sync variants) ordering races resolve identically to the c78ce99 pass. |
| `d5_hashseed.py` | STABLE (1 pre-existing, documented non-issue) | Everything hash-seed-invariant except `current_state_ids_raw`, whose *raw* (unsorted) order varies with `PYTHONHASHSEED` — already on record as expected (parallel-region iteration order over a `set`/`dict`; the *canonical* `snapshot_configuration`/`snapshot_value_keys` views are seed-stable). Not a new defect. |
| `d6_cross_engine.py` | STABLE | S1 GO/drain: context, state, trace agree across engines. |
| `d7_hook_parity.py` | STABLE | Hook trace order identical. |
| `d9_snapshot_replay.py` | STABLE | 8 identical async runs → 1 distinct mid-stream snapshot, 1 distinct final snapshot (byte-stable). Harness prints the known `SimulatedClock.increment() inside a running loop` warning at one call site (pre-existing test-harness artifact, not an interpreter defect — the warned call is immediately followed by the awaited form elsewhere in the same script). |
| `d10_concurrent.py` | STABLE | 8 tasks × 2400 sends: 10/10 runs preserve arrival order, 0 lost. |
| `d10b_threadsafe_order.py` | STABLE | Barrier case: FIFO preserved across runs. |
| `e1_internal_forgery.py` | STABLE | `internal=True` bypass check: 0/200 spurious `QueueOverflowError`, context count matches sends. |
| `f1_chain_vs_external.py` | STABLE | Chain budget trips (`RunawayChainError`), `last_error` reflects it, external traffic continues to be accepted around the trip. |
| `f4_raise_dropped_hook_parity.py` | STABLE | `refused_futures_with_error == queue_full_hook_fires` (236 == 236): drop-hook parity holds. |
| `f5_nested_parallel_snapshot_refusal.py` | STABLE | All 3 windows (`r2_entry`, `deep_entry`, `deep_exit`) refused on both engines; final context matches expectation. `wait=True` calls here are again the harness driving `i.send(...)` from module-level `async def main`, not an action awaiting its own interpreter — not the #219 shape. |
| `g1_async_chain_charged.py` | STABLE | Both engines trip at the same `n` (1002), chain-budget parity intact. |
| `g6_hash_and_config_fuzz.py` | STABLE | 100/100 drift and corruption cases refused on `machine_hash`/`configuration` mismatch; 0 unexpected outcomes. |
| `h1_statestoinvoke_snapshot.py` | STABLE | Arms exactly once, reaches `done`, both engines (informative caveat about snapshot timing unchanged from prior report). |
| `h2_snapshot_trust_boundary.py` | STABLE | v0-downgrade, missing-version, bad-hash, missing-hash all refused; legitimate snapshot accepted. PASS. |
| `i1_delayed_raise_pingpong.py` | STABLE | #212 semantics matrix holds: `maxIterations`-scoped zero-delay control trips both engines identically; the delayed 1ms/1s-window heartbeat does **not** trip and is bounded only by the clock (`async_n=65` vs `sync_n=556` — expected divergence from the two engines' differing per-tick scheduling granularity under a `SimulatedClock`, not a correctness defect: both engines individually satisfy `must_not_trip` and `beats_bounded_by_clock`). |
| `i2_v2_upcast_forgery.py` | STABLE | v2-forged `done`/`error-platform` records still upcast and fire (`onDoneFired`/`onErrFired` = 1); v3-forged equivalents (no engine-minted flag) correctly refused (`fired = 0`), matching #214's v2-only upcast rule. |
| `n5b_corrupt_escapes.py` | STABLE | 0/9 malformed-snapshot shapes escape as anything but `SnapshotCorruptError`. |
| `n6_observability.py` | STABLE | `on_event_dropped` fires with a reason for an unresolved target; secret redaction 0 leaked / 12 redacted keys; public API surface fully importable and in `__all__`. |

No SUPERSEDED entries: none of the three `wait=True`-using scripts drives the
new reentrant shape (action-in-flight awaiting its own interpreter's
`send(wait=True)`) — they all call `send()` from the module-level test
driver, which is the ordinary, still-legal use of `wait=True`.

## 2. Round-11 pinned regression spot-check

Not re-run as a separate suite this pass (the project's own
`tests/test_round11_findings.py`, 23 tests, is covered by the background
`suite-de2da4e.log` full-repo run — see that log for the authoritative
pass/fail count: **3545 passed, 13 skipped, 0 failed**, 92.87% coverage,
752.21s). The determinism track's own standalone repros for #218–#222 are
new attacks §3.1/§3.2 below plus the existing `i1`/`i2` reruns in §1.

## 3. New attacks this pass

### 3.1 `j1_reentrant_wait_matrix.py` — #219 `ReentrantWaitError` matrix

Four shapes, both engines where relevant:

| Shape | Expected | Observed |
|---|---|---|
| action awaits `send(X, wait=True)` on its own interpreter (async) | `ReentrantWaitError` | `ReentrantWaitError` |
| action calls `send(X, wait=True)` on its own interpreter (sync) | `ReentrantWaitError` | `ReentrantWaitError` |
| action does `asyncio.ensure_future(interp.send(X, wait=True))`, awaited *after* the step returns | receipt handed out normally, no error | receipt returned normally |
| an `after`-fired handler awaits `send(X, wait=True)` on its own interpreter | `ReentrantWaitError` | `ReentrantWaitError` |

`VERDICT PASS`. Matches the changelog's #219 description exactly: the
in-step await is refused on both engines; the deferred (`ensure_future`)
receipt is still obtainable. No `child→parent` / `parent→child` cross-actor
variant was attempted this pass (see §4).

### 3.2 `j2_scheduled_sends_chain.py` — #221 parked scheduled_sends across a
restore→persist→restore→start chain

Property test, 320 cases: `(delay, n_restore_cycles ∈ {0,1,2,3,5}, tick_before_first_restore)`
triples, using a `raise(delay=)` self-arming heartbeat (`entry: raise(BEAT, delay=…)`,
`on: {BEAT: fire}`). For each case:

1. Start, arm, tick by `pre_tick < delay`, snapshot, `stop()` (no consumption).
2. Restore → `get_persisted_snapshot()` (no `start()`) `n_restore_cycles` times,
   asserting `scheduled_sends` survives non-empty and verbatim after every
   restore-without-start cycle (a journal-compaction/migration proxy).
3. Restore once more, this time calling `start()`, and confirm the beat fires
   **exactly once**, at (approximately) the correct remaining delay: it has
   not fired with `remaining - 1` ms left on the clock and has fired after
   crossing the deadline by 2ms.

Result: **320/320 cases pass, 0 failures.** `scheduled_sends` is re-emitted
verbatim through every restore-without-start hop and consumed exactly once
when `start()` finally re-arms it — matches #221 exactly.

(Initial version of this script used an `after` transition instead of
`raise(delay=)`; `after` deadlines are *not* recorded in `scheduled_sends`
— only #212/#213's `raise(delay=)` self-sends are. That is expected: `after`
timers are read straight off `get_persisted_snapshot()`'s legacy `after`
handling per #214, a different code path from `scheduled_sends`. Not a
defect; corrected the harness rather than filing it.)

### 3.3 `j3_key_fuzz.py` — #220 recursive unknown-key check, typo + valid-grammar fuzz

Two fuzzers, 400 cases each, `strict_config=True`:

- **Typo fuzzer**: generates a random valid nested machine (root/state/
  transition/invoke levels, parallel-ish nesting depth 2, occasional
  `invoke`, `meta`, `x-` keys), then injects a single-character typo into one
  known key at a randomly chosen level (root, state, transition, or invoke).
  **0/400 typos went uncaught**; every case raised `InvalidConfigError`.
- **Valid-grammar fuzzer**: same generator, no typo injected — every key used
  is drawn from `KNOWN_ROOT_KEYS`/`KNOWN_STATE_KEYS`/`KNOWN_TRANSITION_KEYS`/
  `KNOWN_INVOKE_KEYS` plus `meta`/`x-custom`. **0/400 false positives** under
  `strict_config=True`.

`VERDICT PASS`. Confirms the recursive check (a) has no known blind spot for
single-character typos at any of the four levels tested, on this generator's
grammar, and (b) does not over-reject any accepted key shape, including
`meta` and `x-`-prefixed keys nested under states/invokes.

## 4. Not covered this pass (explicit gaps against the brief)

Time-boxed at ≤20 min wall clock total; the following brief items were not
attempted and should be treated as open, not as passing:

- **Concurrency**: 200 heartbeat machines for 10s with flat handle-count/RSS
  assertion; `ReentrantWaitError` under 100 concurrent actions via
  `ensure_future`; child→parent and parent→child cross-actor `wait=True`
  variants; cancel-storms on delayed sends (double-release check).
- **Chain-trip latch across snapshot** (persist mid-trip, restore, confirm
  `chain_trips`/`last_chain_error` survive and `clear_chain_error()` still
  works post-restore) — only the pre-existing `f1_chain_vs_external.py`
  (no snapshot round-trip) was rerun.
- **Recursive key check on every catalogue JSON** in
  `docs/plan/28-statechart-catalogue.md` / the `battle-*/contracts/*.machine.json`
  fixtures — the fuzzer in §3.3 uses a synthetic generator, not the actual
  catalogue files.
- **Livelock fuzzer** ≥500 configs × kinds × engines against the current
  chain-budget rules.
- **50× determinism traces including `chain_trips` counts** — d1 was run at
  reduced runs (5×500 events) for the wall-clock budget, and none of the
  reruns specifically diffed `chain_trips`/`last_chain_error` across runs.
- **strict_config bypass via `x-` abuse or key-case variants** (e.g. does
  `X-foo` or `Type` slip past the `x-` prefix check or the known-key set?).
- **Snapshot forgery of `scheduled_sends`/`lane`/`engine`** fields
  specifically (only `machine_hash`/`configuration`/`version`/`status` corruption
  was exercised, via the inherited `g6`/`h2`/`n5b` scripts).
- **12-minute soak** with 200 machines, mixed heartbeat periods, an external
  priority producer, and chaos snapshot/restore/re-persist cycling.

## 5. Verdict

All inherited determinism-track defects remain FIXED on `de2da4e`; no
SUPERSEDED cases (the `wait=True` call sites in the inherited suite are all
outside-the-step driver calls, not the in-action reentrant shape #219
targets). Three new attacks this pass — the `ReentrantWaitError` matrix
(§3.1), the scheduled_sends persistence chain (§3.2, 320/320), and the
recursive-key-check fuzzer (§3.3, 800/800 correct) — all confirm the
round-11 fixes behave exactly as documented, with no edge case found that
contradicts the changelog's description of #219/#220/#221.

**No new `D12-determinism-n` defects are raised this pass.**

The concurrency/soak/livelock/catalogue-fuzz/chain-trip-across-snapshot
items in §4 are explicitly not covered and should not be read as passing.


