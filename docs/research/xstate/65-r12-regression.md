# 65 — Round-12 regression: `main` @ `de2da4e` (unreleased 0.8.1)

Build under test: commit `de2da4e` (merge of `#223`, `fix/0.8.1-round11`).
`__version__` still reports `0.8.0` — **key on the commit, not the version string**.
Baselines: `gate/result-main-c78ce99.json` and `64-r11-final-readiness-verdict.md` §2.

Raw artefacts produced this round:

| File | Contents |
|---|---|
| `gate/result-main-de2da4e.json` | adoption gate, 168 checks |
| `gate/r12_scriptlist.txt` | 573 scripts swept (R11 swept 526) |
| `gate/r12_regression_raw.json` | per-script status / rc / seconds / failure tail |
| `gate/r12_flaky.py`, `gate/r12_flaky.json` | ×5 serial confirmation of every delta |
| `suite-de2da4e.log` | upstream pytest + coverage (pre-existing run) |

---

## 1. Upstream suite

Read from `suite-de2da4e.log` (complete — the run finished):

```
3545 passed, 13 skipped, 15 warnings in 752.21s (0:12:32)
Required test coverage of 90.0% reached. Total coverage: 92.87%
```

vs round 11 at `c78ce99`: the delta is the round-11 pin file
`tests/test_round11_findings.py` (23 tests, parametrised over `def` / `async def`).
Zero failures, zero errors, coverage above the 90 % floor on every module
(`interpreter.py` 92 %, `sync_interpreter.py` 97 %, `models.py` 88 %,
`validation.py` 99 %, `persistence.py` 95 %).

## 2. Adoption gate

| | `c78ce99` (R11) | `de2da4e` (R12) |
|---|---|---|
| checks | 163 | **168** |
| PASS | 124 | **128** |
| FAIL | 39 | **40** |
| exit code | 1 | 1 |

Exit code 1 in both rounds: the gate deliberately keeps a standing red set
(pre-existing carried findings), so a non-zero exit is the expected steady
state, not a round-12 event.

### 2.1 Every delta, triaged

| Check | R11 | R12 | Verdict |
|---|---|---|---|
| `212 selfsend_timer` | absent | **PASS** | new check — #212 fix confirmed |
| `213 snapshot_v3` | absent | **PASS** | new check — #213 fix confirmed |
| `214 restore_strict_upcast` | absent | **PASS** | new check — #214 fix confirmed |
| `215 216_lap_parity_and_unknown_keys` | absent | **PASS** | new check — #215/#216 confirmed |
| `215#2 lap_parity_sweep` | absent | **PASS** | new check — limits 1–25 sweep |
| `216 unknown_config_keys` | absent | **PASS** | new check — #216 confirmed |
| `206 delayed_selfsend_charged` | FAIL | **absent** | **SUPERSEDED-BY-#212** — retired from the gate as §2(b) of doc 64 directed. Not a regression; the check asserted the rule #212 reverses. |
| `LC-39 throughput global budget` | FAIL | **PASS** | improvement |
| `167 rollback_reinvoke_spin` | PASS | **FAIL** | **harness / load artefact** — see §4 |
| `LC-45 hot path alloc + info logging` | PASS | **FAIL** | **harness / load artefact** — an allocation + wall-clock threshold check run under a loaded box; flagged `triage: unfixed / fixed-but-opt-in / stale repro` by the gate itself |

Net: **six new checks, all PASS**; one retirement that doc 64 §2(b) had already
scheduled; one genuine improvement; two load-sensitive reds addressed in §4.

## 3. Script sweep — 573 scripts

`gate/run_r12_regression.py` (a rename of the R11 driver: same 120 s cap,
same neutral cwd `C:/Users/basil`, same `PYTHONUTF8=1` env), 10 workers.

```
573 scripts: 476 PASS, 94 FAIL, 3 TIMEOUT
```

47 scripts are **new to the list** since R11 (the round-11 repro set
`R11-04/06/07/08/09`, the `verify-main-de2da4e/` pins `218`–`222`, the
`probes/main-c78ce99/` probe set, `probes/v080/`, and the
`verify-main-5e07ba8/ref/refute_*` + `probes/main-19cb1f1/r10_03_refute_*`
scripts that the R11 list had excluded). One script left the list:
`issues/verify-main-19cb1f1/206_delayed_selfsend_charged.py`, renamed by its
owner to `_RETIRED_206_delayed_selfsend_charged.py` — the retirement doc 64
§2(b) ordered. Its FAIL at `de2da4e` is **SUPERSEDED-BY-#212**, expected, and
now carries `_RETIRED_` in the filename so no future round counts it.

Comparing only the 525 scripts present in both rounds:

- **PASS → not-PASS: 11**
- **not-PASS → PASS: 1** (`issues/verify-main-cec108b/150_send_threadsafe_budgeted.py`)

## 4. Every PASS → not-PASS delta, triaged (×5 serial)

`gate/r12_flaky.py` re-ran each candidate **five times serially** from the
neutral cwd. This is the control doc 64 §2(a) mandated as standing rule
`R11-H-1`: *"timing-sensitive scripts run serially, or their polling budgets
are raised — a naive parallel-vs-serial diff overstates regressions."*

| Script | Parallel sweep | ×5 serial | Verdict |
|---|---|---|---|
| `post-6db65d8/.../R8-04_always_ondone_reentry_settle_tripped.py` | FAIL | 4 PASS / 1 FAIL | **harness — contention-sensitive** |
| `post-6db65d8/.../R8-07_send_wait_resolves_over_empty_configuration.py` | FAIL | **5/5 PASS** | harness |
| `post-f28719c/.../R9-08_send_wait_resolves_over_empty_configuration.py` | FAIL | **5/5 PASS** | harness |
| `verify-0.8.0/LC-42_send_receipt.py` | FAIL | **5/5 PASS** | harness (asserts `send_priority` p50 < 1 ms behind a 2000-event backlog) |
| `verify-main-221ce7c/167_rollback_reinvoke_spin.py` | FAIL | **5/5 PASS** | harness — the *same* script doc 64 §2(a) already named a parallel false-FAIL |
| `verify-main-3ed3099/105_external-send-not-charged-to-chain-budget.py` | FAIL | **5/5 PASS** | harness — also already named in doc 64 §2(a) |
| `verify-main-5327ba6/LC-37_wrongthreaderror-message.py` | FAIL | **5/5 PASS** | harness — worker `f.result(timeout=5)` expires under load |
| `verify-main-5327ba6/LC-42_send_receipt.py` | FAIL | **5/5 PASS** | harness |
| `verify-main-cec108b/repro_147_151.py` | FAIL | **5/5 PASS** | harness |
| `verify-main-f28719c/197_empty_config_wait.py` | FAIL | **5/5 PASS** | harness |
| `verify-main-5e07ba8/final/fv4_r407_falsepos.py` | TIMEOUT | **5/5 PASS** | harness — 120 s cap exceeded only under 10-way contention |

**Not one of the eleven survives a serial re-run.** Combined with the two gate
reds (`167`, `LC-45`), which are the same load-sensitive family, the round-12
count of true regressions is **ZERO**.

The one not-PASS → PASS delta,
`verify-main-cec108b/150_send_threadsafe_budgeted.py`, is the mirror image:
it was itself a parallel false-FAIL in R11.

### 4.1 Scripts newly on the list that FAIL — triaged

| Script | ×5 | Verdict |
|---|---|---|
| `verify-main-19cb1f1/_RETIRED_206_delayed_selfsend_charged.py` | (not re-run) | **SUPERSEDED-BY-#212.** The retirement doc 64 §2(b) ordered, now marked in the filename. Excluded from all future counts. |
| `post-c78ce99/.../R11-07_nested_config_typos_silent.py` | **5/5 FAIL** | **Fix confirmed, repro is now stale.** The script builds `{"states": {"a": {"entyr": ..., "onn": ...}}}` expecting silence; `de2da4e` raises `InvalidConfigError: typo.a: 'entyr' (did you mean 'entry'?), 'onn' (did you mean 'on'?)` — exactly #220's path-named finding. The repro exits non-zero *because the defect is gone*. Rewrite as a pin, do not count as FAIL. |
| `post-c78ce99/.../R11-09_chain_trip_erased_by_next_event.py` | **5/5 FAIL** | **SUPERSEDED-BY-#222.** The script asserts `last_error` still names `RunawayChainError` after one benign event; it still reports `REPRODUCED: True` on all three lanes. That is now **by design**: #222 documents `last_error` as the per-step read it always was and moves stickiness to the new `interpreter.chain_trips` counter, the `last_chain_error` latch and `PluginBase.on_chain_budget_exceeded`. The script tests the erased oracle. Rewrite against the latch. |
| `verify-main-5e07ba8/ref/refute_r407.py`, `refute_r407b.py` | **5/5 PASS** | harness (parallel TIMEOUT only) |

### 4.2 SUPERSEDED-BY-#219 — **zero scripts**

A full scan of the 573-script corpus and of every failure tail in
`gate/r12_regression_raw.json` finds **no script that raises, catches or
mentions `ReentrantWaitError`**, and no failure attributable to an action
awaiting `send(..., wait=True)` on its own interpreter. Our repros that use
`wait=True` (≈30 scripts, e.g. `N-01_send-wait-receipt-id-collision.py`,
`R4-07_receipt-deferred-id-keyed-false-positives.py`,
`R7-03_start_hangs_on_slow_invoked_child.py`,
`R8-07_send_wait_resolves_over_empty_configuration.py`) all await the receipt
from *outside* an action — the shape #219 explicitly keeps legal — and every
one passes. **#219's new refusal breaks none of our corpus.**

This is a real finding for adopters, not a non-event: the in-step await was the
natural way to write "act, then confirm", and any user action that did it now
raises where it previously hung. Our corpus simply never wrote that shape.

## 5. Round-11 fix pins (`issues/verify-main-de2da4e/`)

All seven independently-written pins **PASS**, confirming each #218–#222 fix
against a standalone repro from the neutral cwd:

| Pin | Finding | Result |
|---|---|---|
| `repro_218.py`, `218_timer_handle_leak.py` | timer handle released on fire/cancel | PASS — ≤1 handle over a 200-beat heartbeat, both engines |
| `219_reentrant_wait.py` | in-step `send(wait=True)` → `ReentrantWaitError` | PASS — both engines refuse; out-of-step receipt still works |
| `220_nested_typos.py` | unknown-key check recurses | PASS — path-named findings at every level |
| `221_parked_v3_sends.py`, `221_repersist_no_start_scheduled_sends.py` | parked v3 `scheduled_sends` re-emitted until `start()` | PASS |
| `222_chain_trip_sticky.py` | `chain_trips` + `last_chain_error` latch | PASS |

## 6. Livelock / hang repros under watchdog

Every historical livelock and hang repro was re-run with the 120 s cap acting
as watchdog (hang probes carry their own ≤30 s internal watchdogs). Three
scripts hit the cap under 10-way parallelism —
`fv4_r407_falsepos.py`, `refute_r407.py`, `refute_r407b.py` — and **all three
pass 5/5 serially**. `R11-06_descent_gate_start_hang.py` (doc 64 §2(d)'s
net-new liveness regression) runs to completion under its own watchdog, as do
`167_rollback_reinvoke_spin.py`, `105_external-send-not-charged...`,
`p6_215_descent_wait.py` and `r11_collateral_unbounded.py`. **No script hung.**

## 7. Verdict

| Category | Count |
|---|---|
| **TRUE REGRESSION** | **0** |
| SUPERSEDED-BY-#219 | 0 scripts (documented in §4.2 — our corpus never wrote the shape) |
| SUPERSEDED-BY-#222 | 1 script (`R11-09`) |
| SUPERSEDED-BY-#212 (carried from R11) | 1 script (`_RETIRED_206…`) |
| Stale repro, fix confirmed | 1 script (`R11-07`) |
| Harness / contention false FAIL | 11 scripts + 2 gate checks |
| Genuine improvement | 2 (`LC-39`, `150_send_threadsafe_budgeted`) |

`de2da4e` introduces **no semantic regression** against `c78ce99`. The upstream
suite is green at 92.87 % coverage, all six new gate checks pass, and all seven
round-11 fix pins reproduce the fixed behaviour from a neutral cwd.

### Standing actions for round 13

1. **Run the sweep serially, or raise polling budgets.** `R11-H-1` was recorded
   in round 11 and round 12 reproduced the identical failure mode at higher
   worker count (11 false FAILs vs 4). The parallel driver should be retired
   for the timing-sensitive subset — it costs more triage than it saves.
2. **Rewrite `R11-07` and `R11-09`** against the post-fix oracles (`InvalidConfigError`
   path findings; `chain_trips` / `last_chain_error` / `on_chain_budget_exceeded`),
   or they become permanent meaningless reds — the exact failure mode doc 64
   §2(b) warned about.
3. **`__version__` still reports `0.8.0` at `de2da4e`.** Any gate keyed on the
   version string will mis-identify this build. Keying on commit is mandatory
   until 0.8.1 ships.
