# Battle track: PERSISTENCE on v0.9.1

**Target:** `origin/main` = `801eacd` (the merge of #249; tag `v0.9.1` = `45bb7f3`), `__version__ = 0.9.1`. PyPI wheel sha256 `d832d4d9…87162` matches the PyPI JSON digest.
**Library suite:** 3601 passed, 13 skipped, coverage 92.93% (`suite-v0.9.1.log`).
**Scripts:** `battle-v0.9.1/persistence/*.py`. All are STANDALONE and were run from cwd `C:/Users/basil` under `XS_SVC=async` and `XS_SVC=def` through `runall.sh`. Raw output is in `out/`.
**Time-box reductions:** the soak ran for **1.5 min, not 12 min**, at 200 machines per kind, because of the 120 s per-script bound. The `re_mint` fuzz is two targeted scripts, not a full random fuzzer.

## Verdict

**Not ready to adopt yet: one new High security defect, D14-persistence-1.** Every fix in this round that touches persistence holds on both kinds, and both D13 defects are FIXED. But the new public `events.re_mint()` lets application code turn a *genuine* completion from one invocation into a completion for **another, still-running invocation**. That completion drives the victim's `onDone`/`onError` with data chosen by the caller. This is exactly the forgery the #195 provenance gate exists to stop, and it was the question for this round.

## 1. Prior defects

| Prior | Script | Status @ v0.9.1 | Evidence |
|---|---|---|---|
| **D13-persistence-1**: malformed `chain_trips` raised a raw `ValueError` | `d13_p1` | **FIXED** (#241) | `'NaN'`, list, dict and `'1e3'` all raise `SnapshotCorruptError`. The script's final step expected a dict `last_chain_error` to be *accepted*; it is now rejected, which is the fix → that assertion is **SUPERSEDED** (it exits 1 on the new behaviour) |
| **D13-persistence-2**: `on_interpreter_start` never fired on restore | `d13_p2`, `n12` | **FIXED** (#240) | Every cell prints `['start','stop']`, "missing on: []". The soak's pinned oracle ("count stays 0") now sees 1 per restore → oracle **SUPERSEDED**. Its only "FAIL" is that pin |
| R11-08, #222, #219, #220, #218, #212, #233, #230 | `n1`–`n11`, `x6` | **FIXED (holds)** | All exit 0 on both kinds. `n2` 640/640 (needs 115 s) |
| Livelock oracle | `x6` | holds | 500 configs × 2 engines × 2 kinds: 439/439 delayed-cycle, 61/61 zero-cycle |
| v3 determinism | `x11` | holds | One digest, `74e07d063486da18`, on both kinds and all 3 hash seeds |
| **R11-01** `version: 2` mints provenance | `x2` | **STILL-PRESENT** | The v2 `onDone` minting is still present. `minimum_version=3` still refuses it (CV mitigation stands) |
| R11-11 `structure_hash` omits delays | — | not re-run | Not in #239–#248. Assumed STILL-PRESENT (CV-C61) |
| R10-09 `SnapshotMidStepError child=False` | — | not re-run | Low, unchanged |
| `q2` deadline in-flight | `q2` | **CHANGED (harness)** | The async kind now exits 1 every time: `get_persisted_snapshot()` raises the documented `SnapshotMidStepError` (#102) at one offset inside the slow entry. The harness has to retry after the step settles. There was no loss in the offsets that snapshot. Not a defect |

## 2. New attacks (`t1_v091_attacks.py`, `s1`, `s2`, `n12`; both kinds)

| Attack | Result |
|---|---|
| A. drain→persist→restore→start round-trip, 300 random cases, priority and inbox, with a macrostep in flight | **0 failures**. `drain_pending()` order == `pending_events` order in every case. Every event delivered exactly once |
| B. `restored_from_snapshot` across 10 chained restores | `[False, True×10]` ✔ |
| C. Chain-field fuzz: 13 `chain_trips` × 6 `last_chain_error` values | **0 raw exceptions**. Every bad cell raises `SnapshotCorruptError`. Accepted: `None`, `"12"`, `" 1"`, `10**30` (a numeric string is documented as accepted; the huge int is accepted as-is) |
| D. `drain_pending` with 16 concurrent senders (320 events, mixing wait / priority / plain) during a 200 ms in-flight step | 320 drained + 0 processed = 320: **0 lost, 0 duplicated**. 0 receipts left pending; every drained receipt → `InterpreterStoppedError` |
| E. 1000 dropped `wait=True` receipts from actions | `dropped_receipts = 1000`, hook calls = 1000 ✔ |
| F. 100 concurrent restores with `plugins=` | 100 starts, 100 unique, all `restored=True`, 100 stops ✔ |
| G. `RestoredChainError` isinstance matrix | IS-A `RunawayChainError` and IS-A `RestoredError` ✔ |
| H. `SyncInterpreter` kwargs | `None/None` ok; `max_queue_size=5` → `ValueError`. `overflow_policy="drop"` alone is accepted silently, which matches the docstring ("ignored unless a bound is requested"). Not a defect |
| Livelock fuzz / determinism | See §1 (`x6`, `x11`) — pass |
| s1. `re_mint` an `after` timer event → `done.invoke.victim` / `error.platform.victim` | The result claims `is_system_event=True` but does **not** drive the victim, because the `src` is still the timer's. No forgery |
| **s2. `re_mint` a genuine sibling completion with `src="victim"`** | **REPRODUCED** on both kinds, for both `done` (`victim_data={"approved":true}`) and `error` → **D14-persistence-1** |
| Attestation (PEP 740) | The PyPI provenance statement's subject sha256 == the wheel sha256. Publisher is GitHub `basiltt/xstate-statemachine`, `publish.yml`, env `pypi` ✔. The Sigstore certificate chain was not verified offline (`pypi-attestations` is not installed) |
| Forged chain fields | `n10` passes: a forged count or latch gates nothing |
| Soak (1.5 min, 200 machines × 2 kinds, 10 ms beats + external priority + chaos restore(plugins=)) | 68 800/68 800 external events handled, 0 lost. 43/43 restores ok, 0 mid-step refusals. 0 timer handles. RSS +0.7 MB. Hooks balanced (start = 1 per restore) |

## 3. Defects

### D14-persistence-1 — **High (security, provenance)** — `re_mint()` retargets a genuine completion to another outstanding invocation

`events.re_mint(original, **fields)` is gated only on `original` having been engine-minted (`events.py:687`). It then accepts **any** `type` / `src` / `data` (`events.py:697-701`). Invocation routing accepts a completion when `event.src == inv.id` and `is_system_event(event)` (`base_interpreter.py:4915-4926`, `_completion_is_for_live_invocation` at `:2214-2230`, which checks provenance only). So any action that receives one real `done.invoke.quick` can mint `done.invoke.victim` carrying chosen data, and the victim's `onDone` fires while its service is still running. The changelog's claim that re_mint "can carry provenance forward but never create it" is therefore false in practice: provenance carries forward onto a *different* identity.

Repro: `battle-v0.9.1/persistence/s2_remint_retarget_completion.py` (stdlib + library). Output, both kinds:
```
{"engine":"async","mode":"done","states":["m.pay.settled","m.probe.x"],"victim_data":{"approved":true},"forged_is_system":true,"FORGED":true}
{"engine":"async","mode":"error","states":["m.pay.failed","m.probe.x"],"victim_data":"q",...,"FORGED":true}
```
Sync engine: N/A here, because a sync service completes inside `start()`. Retyping an `AfterEvent` also yields `is_system_event=True` under a `done.invoke.*` name (`s1`); it is inert only because routing requires the matching completion class and `src`.

Suggested fix: freeze the identity fields (`type`, `src`), so that only payload fields (`data` / `error`) are re-mintable. Also refuse a `type` whose prefix differs from the original's.

**CV mitigation (CV-C68):** ban `re_mint` in app code (lint rule), or wrap it so `type`/`src` must equal the original's. Invoke-completion guards must not trust `onDone` data alone.

## 4. Not covered
12-minute soak (1.5 min was run). A random `re_mint` fuzzer (replaced by the two targeted cases above). Offline Sigstore chain verification. Sync-engine outstanding-invoke forgery (it cannot arise). R11-11 and R10-09 were not re-run.
