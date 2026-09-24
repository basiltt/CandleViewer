# B16–B20 control charts (+ B11 R13-15) end-to-end on v0.9.1

**Library:** `xstate-statemachine` checkout `main = 801eacd`, which is the merge of
#249 on top of `5c3b25b`. The runtime prints `__version__ = "0.9.1"` and imports from
`_ref/xstate-statemachine/src` through `.venv-main`. I did not install or hash the
PyPI wheel on this track.
**Suite (already running, not restarted):** `suite-v0.9.1.log` → **3601 passed,
13 skipped, coverage 92.93 %** (gate 90 %).
**Charts:** the corrected JSON from `battle-v0.9.0/contracts/` (byte-identical to
`battle-de2da4e/contracts/`), copied here. `strictConfig: true` is injected at load.
**Time bound:** this track was cut down to one driver plus two triage probes
(20-minute task bound). Each script runs in under 30 s.

## 1. Scripts (standalone: stdlib + `xstate_statemachine`, cwd `C:/Users/basil`)

| Script | What it pins | `async def` | `def` |
|---|---|---|---|
| `w1_contracts.py` | 5 charts: happy path, invariants, C-04/C-07b/R13-15, rollback+onDone, guard raise, `always`→invoke chain, `send_priority`, **drain→persist→stop→restore→start→replay**, #245 | **48/48** | **48/48** |
| `w1b_probe.py` | triage of 3 first-run anomalies (see §3) | 3/3 | 3/3 |
| `w1c_rollback_storm.py` | rollback + raising `onDone` action is bounded | exit 0 | exit 0 |

Every run uses `python -W error::RuntimeWarning`. The run config is bounded
`max_queue_size=64` + `OverflowPolicy.RAISE`, `SimulatedClock`, `strict=True`
logic, `strict_targets`, `strict_config`, and a `PluginBase` stub. Every restore
goes through `from_snapshot(..., plugins=[stub], minimum_version=3)`. Results are
in `w1_results.{async,def}.json`.

## 2. Round-13 fixes, re-verified on the control path

| Fix | Result on 5/5 charts, both spellings |
|---|---|
| **#239** `drain_pending()` both lanes, priority first | B17/B18/B20 drained `[prio, *inbox]` in that order. The priority event is no longer lost. |
| **#239** a `wait=True` receipt on a drained event | Resolves to a `Receipt` with `error=InterpreterStoppedError("drained: …")` and `changed=False`, so the waiter no longer hangs. (It is **not raised**; this matches the CHANGELOG's "failed", which follows the receipt convention.) |
| **#240** `on_interpreter_start` on restore | `starts == 1`, `restored_from_snapshot == [True]` on every restore |
| restore fidelity | the restored configuration equals the pre-shutdown configuration on every chart |
| exactly-once replay | nothing leaks in before the replay. Each drained event gets exactly one `wait=True` replay with one receipt. |
| #244 `dropped_receipts` | 0 on both the pre-shutdown and restored interpreter, every chart |
| chain health | `chain_trips == 0` on every happy path and every shutdown/restore |
| **#245** `SyncInterpreter(max_queue_size=64)` | `ValueError`, as documented |

## 3. Findings

### LIBRARY — none

All three anomalies from the first run were triaged to harness errors or
documented semantics:

1. *"receipt did not raise"*: the harness was wrong. The receipt convention is
   `Receipt.error`, never a raise (same as `RunawayChainError`). Fixed in the
   harness; `w1b_probe.py::A`.
2. *"B17 drained event delivered 3×"*: `on_event_received` fires on each
   **`defer` re-offer**. One `send` of an unhandled `EMERGENCY_DISABLE` in
   `locked` is re-offered after each later transition. That is the defer
   contract, not a duplicate delivery. Receipts are 1:1 (`w1b_probe.py::B`).
3. *"B19 rollback + raising `onDone` action loops"*: this is the documented
   `rollback that re-arms an invoke` chain (api `RunawayChainError` row). It is
   **cut by `maxIterations`**: `chain_trips` goes to 1, the counter stalls, and the
   machine stays `running` on both spellings (`w1c_rollback_storm.py`, exit 0).
   The high `act_err` counts in w1 are that bounded storm. It needs an
   operator alert on `chain_trips > 0`, which is already our wrapper rule.

### OUR-CONTRACT — 3 Blockers, all still in the catalogue, all closed by config/logic

| ID | Catalogue as shipped (expected-fail check) | Config-only fix |
|---|---|---|
| **R13-13 / C-04** (B16) | `LOGOUT`, `IDLE_DEADLINE`, `ABSOLUTE_DEADLINE` leave `elevation.elevated` (`REVOKE` alone drops it) | root-hoisted kill events → `elevation.dead`: **0/4 stay elevated** |
| **R13-14 / C-07b** (B18) | denied `RELEASE` under `onUnhandled: error` → `status=error` (bricked) | `defer` + unguarded audit arm: denied stays `engaged`/running, then the legit `RELEASE` → `clear`, `chain_trips 0` |
| **R13-15** (B11) | naive `all_streams_healthy` reads pre-action ctx → wedged in `degraded` | event-aware guard (NEEDS-WRAPPER guard idiom) → back to `recording` |

The engine behaves correctly in all three. These are catalogue edits that have been
owed for nine rounds, and none of them waits on the library.

### NEEDS-WRAPPER — unchanged
- Alert on `chain_trips > 0` / `last_chain_error`, as in the rollback storm above.
- Shutdown recipe: `drain_pending()` → persist the events **and** the snapshot →
  `stop()`. On restore, replay each persisted event once with `wait=True`. For
  any drained receipt, treat `receipt.error` as `InterpreterStoppedError`.
- Any code that counts `on_event_received` must understand `defer` re-offers.
  Count receipts for delivery instead.

## 4. Verdict for this track

**LIBRARY: 0 defects. All the round-13 fixes on the control path (#239, #240,
#244, #245) hold on both service spellings under `-W error::RuntimeWarning`.**
The library is ready on this track. What is left is **our own work**: land
R13-13/14/15 in `28-statechart-catalogue.md` and `tests/xstate_contract/`.

Scope note: this track covers the tag-equal `main` source (the diff
`v0.9.1..HEAD` is empty). It did **not** re-hash or install the PyPI wheel. It
did not redo the full per-invariant matrix from the v0.9.0 track (`v2`–`v8`); a
reduced invariant set was re-run.
