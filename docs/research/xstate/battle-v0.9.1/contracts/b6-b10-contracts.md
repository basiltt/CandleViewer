# Contract machines end-to-end — B6, B7, B8, B9, B10 @ `v0.9.1`

**Library:** tag `v0.9.1` = `45bb7f3`, `main` = `801eacd`. `git diff v0.9.1..HEAD --stat` is **empty**: the merge commit changes no files. `__version__ == "0.9.1"`. The PyPI wheel at both `/tmp/xsm091/` and `C:/Users/basil/AppData/Local/Temp/xsm091/` has sha256 `d832d4d9…87162`, which matches the brief.
**Library suite** (`suite-v0.9.1.log`, the run already in progress, not restarted): **3601 passed, 13 skipped, 92.93 % coverage** (the gate is 90 %).
**Contracts:** B6–B10 JSON copied **unchanged** from `battle-v0.9.0/contracts/`, with the same sha1 prefixes as last round (`97f57ff035de`, `38ddf600a6f2`, `03586b051082`, `04b1d029b493`, `f0a0aa4824cd`). **No JSON edit was needed.**
**Workdir:** `battle-v0.9.1/contracts/b6b10/`. The parent directory is shared with another track that deletes files in it, so everything here runs from this isolated subfolder.
**Config:** the same mandatory set as round 13: strictConfig, rollback, defer, guard raise, strictTargets, `strict=True` stubs, bounded `RAISE` inbox, `SimulatedClock`, restore through `from_snapshot(minimum_version=3, plugins=[…])`. Every script ran under `-W error::RuntimeWarning`, **pass 1 `async def`, pass 2 `def`**.

## 0. Headline

| Suite | async | def |
|---|---|---|
| e0 build + policy read-back | 45/45 | 45/45 |
| e1 invariants + scenarios (happy paths, OC fixes) | 52/52 | 52/52 |
| e2 mandated drives (rollback+onDone, always→invoked child, B18 `send_priority`) | 14/14 | 14/14 |
| e3 #207 storm / #204 no-arm | 14/14 | 14/14 |
| e4 #212/#213 timers | 10/10 | 10/10 |
| e5 sync parity | 20/20 | 20/20 |
| e6 round-11 / e7 round-12 obligations | 8/8 · 24/24 | 8/8 · 24/24 |
| **r13_drain_restore.py (new, standalone)** | **66/66** | **66/66** |
| f9 C-04/C-07b config-only re-check | 6/6 | 6/6 |
| g4 C-04/C-07b fixed charts (R13-13, R13-14) | 11/11 | 11/11 |
| g2 B11 fixed chart (R13-15, the third Blocker) | 32/35 * | 32/35 * |

\* The 3 FAILs are the `G1.*` rows, which run the **unfixed** B11 chart to demonstrate the bug. They are expected to fail and match `battle-v0.9.0/res_g2_b11_fix.*.json` exactly. All `G2.B11.fixed.*` rows pass: the chart lands in stopped, the gap is counted, both services run, `chain_trips` is 0, and sync parity holds.

**Library defects: 0. Our-contract defects: 0 new** (C-04, C-07b and B11 remain ours, config-only, and their fixes are re-proven). **NEEDS-WRAPPER:** W-01..W-03 are unchanged. **One harness lesson** is recorded in §3.

## 1. Round-13 fixes, checked on the five contracts (`r13_drain_restore.py`)

For each Bx the script does: start → enqueue 2 inbox + 1 `send_priority` + 1 `wait=True`, with no yield in between → `drain_pending()` → persist → `stop()` → `from_snapshot(plugins=[h2])` → `start()` → replay the drained events.

| Check | Result (both lanes, all 5) |
|---|---|
| #239 drain returns all 4 events, **priority lane first** | ✅ e.g. B7 `['CHILD_PARTIAL'(prio), 'BOOK_TARGET_MOVED', 'CHILD_FILLED', 'BOOK_TARGET_MOVED']` |
| #239 the `wait=True` receipt resolves with `error=InterpreterStoppedError("drained…")` and does not hang | ✅ |
| both queues are empty after the drain | ✅ |
| #240 the boot hook fires once with `restored_from_snapshot=False`; the restore hook fires once with `True` (async and `SyncInterpreter`) | ✅ |
| configuration is identical after restore | ✅ |
| **every drained event is delivered exactly once** (tracked by distinct `seq` payload) | ✅ `{1:1,2:1,3:1,4:1}` |
| `chain_trips == 0` before and after, `dropped_receipts == 0`, `on_receipt_dropped` not called | ✅ |
| #241 `chain_trips` set to `"NaN"`, `[1]`, `{}`, `True` or `-1` → `SnapshotCorruptError` | ✅ |
| #245 `SyncInterpreter(max_queue_size=8)` → `ValueError`; `None/None` accepted | ✅ |
| #243 `RestoredChainError` ⊂ `RunawayChainError` and ⊂ `RestoredError` | ✅ |

Standalone repros, stdlib plus the library only, run from `C:/Users/basil`, in `b6b10/repro/`:
- `s1_drain_both_lanes.py`: drains `['Y'(prio),'X','X']`; the receipt carries `InterpreterStoppedError`.
- `s2_dropped_receipts.py` (#244): an un-awaited `send(wait=True)` from an action or at top level gives `dropped_receipts=1` and hook `['B']`.
- `s3_restored_chain_isa.py` (#243): a live trip → persist → restore gives `RestoredChainError` for which `isinstance(…, RunawayChainError)` is True.
- `s4_re_mint_gate.py` (#248): `re_mint()` on a user dict raises `TypeError`, so it cannot create engine provenance.

## 2. Re-checks of the three round-13 catalogue Blockers (all ours, all config-only)

- **C-04 / R13-13 (B16 revocation):** config-only fix re-proven, f9 6/6 and g4 11/11 on both lanes; all 4 revocation events drop elevation.
- **C-07b / R13-14 (B18 kill switch):** a denied RELEASE is non-fatal (`status='running'`, `kill_switch.engaged`), the authorised RELEASE reaches `kill_switch.clear`, and `chain_trips=0`.
- **R13-15 (B11 guard-before-own-action):** unfixed, it still wedges in `recording.degraded`, which is spec-correct engine behaviour. The fixed chart is green (see §0).

These remain **catalogue work items**. The fixed charts must be merged into `28-statechart-catalogue.md` before adoption.

## 3. Harness lesson (not a defect)

In my first draft, B8's all-`False` guard stubs made `exchange_reports_sl` false. That drove the known **CD-03** `naked ⇄ verifying` invoke cycle (round 7). Driven directly, it trips the chain budget in both lanes (`chain_trips=1`, `on_invocation_stranded` in `sl.verifying`). This is our chart shape, already on the register with a fix: a bounded fallback counter plus lint XS16. It is not a v0.9.1 regression. The script now sets `exchange_reports_sl=True` for the happy path, like e1. **Action carried forward:** the CD-03 counter must be in the adopted B8.

## 4. Verdict for this track

On v0.9.1, every round-13 library fix (#239–#245, #248) is **genuinely closed** on our five order-path contracts, in both service styles and under `-W error::RuntimeWarning`. The drain → persist → stop → restore recipe now loses nothing and delivers nothing twice. **GO for B6–B10**, conditional on our config-only items (C-04, C-07b, B11 fix, B8 CD-03 counter) and W-01..W-03 wrappers being in place.
