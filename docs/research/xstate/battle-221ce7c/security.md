# Battle-test — SECURITY track — re-run on `221ce7c`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`221ce7c`** (unreleased 0.8.1, round-6 fixes #166-#175 + #157
reopened + #122-as-designed; also perf PRs #165/#176). `__version__` still
reports `0.8.0`; identified by commit only, per standing project convention.

**Date:** 2026-09-20. Python 3.13.7 (`.venv-main`), Windows 11 Pro.
Re-run of `battle-cec108b/security/` (round-6 track's predecessor) plus new
attacks targeted at this round's fixes. Time-budgeted (20-minute wall
clock): fuzz reduced to 120 configs (not 500), concurrency reduced to 200
plain services / 200 threadsafe sends (not larger), hook-snapshot property
reduced to 300 cases (not the full brief's "≥300 random machines" across
every listed hook — see Not-Covered for the ones not independently run
this pass). 12-minute soak was **not** run this pass — see Not-Covered.

No library source modified. No `git` command run in the adopting repo.
GitHub not queried this pass (no `gh api` calls) — the four carried-forward
governance findings (D-security-2/3/4/5) are **not** re-verified live.

---

## 1. Prior-defect re-run (round-6 security track findings, on `221ce7c`)

| ID | cec108b status | 221ce7c result | Status |
|---|---|---|---|
| D5-security-1 / R5-19 (`get_snapshot()` DEBUG-logs unredacted) | FIXED | `repro_D_security_1_snapshot_log_leak.py` re-run: `DEBUG_LOG_LEAKS_SECRET: False` (script's own `assert leaked` now fails, confirming the fix holds — expected, not a regression). `rerun_D_security_1_LoggingInspector.py`: default redacts, explicit `redact_keys=()` still opts out. | **FIXED (holds)** |
| D5-security-3 / R5-20 (`{"type": "GO"}` bypasses `InvalidEventError`) | RESOLVED BY DESIGN | `attack_invalid_event_hostile.py` re-run: identical result — 8/9 hostile shapes raise `InvalidEventError`; `{'type': 'GO'}` is accepted as a documented, explicitly-validated dict-event shape (`BAD_COUNT: 1`, unchanged). | **UNCHANGED — still resolved-by-design, not a defect** |
| **D6-security-1** (`machine_hash: None` silently disables `from_snapshot()` drift verification) | High, open | `probe_r6_gap_fields.py`: `machine_hash -> None` still `ACCEPTED (no error)`; `machine_hash -> 'wrong-hash-value'` still correctly raises `SnapshotDriftError`. `attack_snapshot_corrupt_fuzz.py` (300 mutations, seed 42): `accepted_bad=196`, `uncontrolled_exceptions=0` — **identical counts to cec108b**. Confirmed also by `battle-221ce7c/persistence.md` (`R6-07`, filed as `D7-persistence-2`): not in the #166-#175 fix set, `persistence.py:277` (the `snap_hash is not None` guard in `check_identity()`) is unchanged this round. | **STILL-PRESENT, unchanged** (tracked project-wide as `R6-07` / `D7-persistence-2`) |
| D6-security-2 (`send_threadsafe(internal=True)` forgery, honesty-based trust boundary) | Low/Informational, open | `attack_threadsafe_forgery.py` re-run: `[forged internal=True] bump_count=200 status=running last_error=None` — same mechanics, no crash induced, no library change to this boundary. New targeted attack this round (`attack_chain_budget_concurrent_external.py`, below) probes the adjacent, now-fixed property (external sends must not reset the chain budget) and finds it holds. | **STILL-PRESENT, unchanged (informational)** |
| D-security-2 (branch protection) | STILL-PRESENT | Not re-queried live this pass (no `gh api` call; time budget). | **CARRIED FORWARD, NOT RE-VERIFIED** |
| D-security-3 (Actions on mutable tags) | STILL-PRESENT | Not re-checked (no CI/workflow changes claimed in the round-6 CHANGELOG). | **CARRIED FORWARD, NOT RE-VERIFIED** |
| D-security-4 (no SBOM/signing) | STILL-PRESENT | Not re-checked (no supply-chain changes claimed). | **CARRIED FORWARD, NOT RE-VERIFIED** |
| D-security-5 (`except: pass`, stripped `assert`) | STILL-PRESENT, informational | Not re-checked (unrelated to round-6 scope). | **CARRIED FORWARD, NOT RE-VERIFIED** |

---

## 2. New attacks targeted at this round's fixes

| Attack | Script | Result |
|---|---|---|
| **Async chain/settle budget under 16 concurrent external threadsafe senders during a self-generated `always`/`always` chain** (#166-#168) — external sends must NOT reset the per-macrostep chain budget; the chain must still trip | `attack_chain_budget_concurrent_external.py` | Baseline (0 external senders): tripped (`last_error` is `RunawayChainError`). Concurrent (16 senders, 811 threadsafe sends delivered during the run): **also tripped**. Property holds: external traffic did not extend/reset the chain-budget counter and did not starve the trip. |
| **Loop-side `RAISE` refusal from `send_threadsafe()` fires `on_event_dropped(reason="queue_full")` exactly once per refusal** (#157 reopened, this round's headline fix) | `attack_raise_refusal_exactly_once.py` | 200 threadsafe sends against `max_queue_size=1`/`OverflowPolicy.RAISE`: `refused_futures=199`, `queue_full_hook_fires=199` — **1:1, no double-count, no silent drop.** Confirms the fix: pre-fix behaviour (cec108b and earlier) was that this refusal landed only on the unread future with zero hook fires; #157's re-fix makes it observable exactly once. |
| **`service_pool_size=1` with 50 plain (blocking) services + `stop()` mid-service** (#173, #174 interaction) | `attack_concurrency_service_executor.py` (reused, 200 runs at default pool size 4 — not re-parameterized to `service_pool_size=1`/50 this pass; see Not-Covered) | `runs=200 errors=0 statuses={'stopped'}`; thread count flat before/after (`1 -> 1`). No crash, no hang, no leaked threads across 200 `stop()`-mid-service cycles. |
| **Persistence-hook snapshot property, reduced (300 parallel-machine cases, `on_transition`/`on_action`/`on_guard` hooks)** — must be refused-or-legal, never torn | `attack_hook_snapshot_never_torn.py` | `n=300 refused=600 legal=300 torn=0`. Never torn; every accepted snapshot has exactly one active leaf per region. Consistent with `persistence.md`'s independently-run, larger (320-machine, six-hook) `q1`/`t6_action_boundary.py` result for this commit. |
| **Config fuzzer for livelock across both engines, 30s watchdog** (nested invoke cycles, `always` cycles, rollback+onDone, sendTo self-loops), reduced to 120 generated configs | `attack_livelock_config_fuzz.py` (reused `fuzz/q5_livelock_fuzz.py` at n=120) | `sync:settled 120/120`. `async:settled 62`, **`async:RUNAWAY 58`** (34 nested_invoke, 24 rollback_ondone) — trip **is** observable via the harness's own instrumentation (event-count explosion + no settle within watchdog), consistent with the fuzz track's independently-run, larger (500-config) result for this commit: this is the pre-existing async-engine livelock (`D7-fuzz-1`, filed against `#144`/`#151`/`#166` scope, **not** part of this round's fix set) reconfirmed at reduced N, not a new finding. |
| **Hook matrix: `on_plugin_error`/`on_resolve_error` for new error classes** | `attack_hook_matrix_observability.py` (re-run unchanged) | `on_plugin_error` fires correctly for a hostile plugin hook raising `TypeError`; `on_resolve_error` path for an unresolved `sendTo` target routes through `on_event_dropped` instead (documented behaviour, not a gap this pass investigated further). |
| **Persistence quiescence property** (500 events, snapshot at every quiescent point) | `attack_persistence_quiescence_property.py` (re-run unchanged) | `mid_step_at_quiescence=0 roundtrip_failures=0` over 500 events. |
| **Semantics 4-way matrix** (guard-crash vs denied vs deferred vs unhandled) + `RootTargetError` non-downgrade + `actionErrorPolicy: fail` | `attack_semantics_matrix.py` (re-run unchanged) | All assertions pass, including `Receipt.denied` correctly distinguishing guard-refused `(True, False)` from undeclared-event `(False, False)` — consistent with `semantics.md`'s independent, larger confirmation of `R6-10` FIXED for this commit. |

---

## 3. Defects (this track)

No **new** defect is filed by the security track itself this round: the one
concrete new-attack finding that would have been novel here —
`send_threadsafe`'s loop-side `RAISE` refusal hook firing exactly once — is
a **confirmation that the round's own headline fix (#157 reopened) holds**,
not a defect.

The two defects this track carries forward are already filed and tracked
elsewhere in this round's findings register, and are restated here for the
security lens specifically:

- **`D6-security-1` / `R6-07` / `D7-persistence-2` (High, STILL-PRESENT).**
  `machine_hash: None` (or a malformed non-`None` value that
  `check_shape()` tolerates) silently disables the drift-verification
  guarantee `verify_machine_hash=True` is supposed to provide in
  `check_identity()` (`src/xstate_statemachine/persistence.py`, the
  `snap_hash is not None` guard around line 277 — unchanged from cec108b;
  confirmed not in the #166-#175 diff). Repro:
  `security/probe_r6_gap_fields.py`, `security/attack_snapshot_corrupt_fuzz.py`
  (identical `accepted_bad=196` count to the prior round). Security
  framing: a hostile-or-corrupted persistence store that zeroes this one
  field defeats the one check whose entire purpose is "does this snapshot
  still belong to this machine" — a silent-wrong-resume, ranked above a
  crash under the standing OMS risk model.

- **`D6-security-2` (Low/Informational, STILL-PRESENT).**
  `send_threadsafe(internal=True)` remains an honesty-based, unverified
  trust boundary — the caller's thread self-declares `internal`, and
  nothing on the loop side cross-checks the claim against the
  interpreter's own notion of in-flight state. No working exploit was
  built (forging `internal=True` from a plain external thread doesn't
  itself crash or corrupt anything observable in this pass's harness), but
  the mechanism is unchanged and the docstring's honesty assumption is
  still unverified in code.

---

## 4. Not covered this pass (time-budget trade-offs, stated not silently applied)

- **Full 500-config livelock fuzz** — reduced to 120 configs this pass
  (30s watchdog per case kept intact); the fuzz track's own 500-config run
  against this exact commit is the authoritative larger sample and is
  cited above rather than re-run at full size here.
- **`service_pool_size=1` with 50 services specifically** — the reused
  200-run concurrency attack exercises `stop()`-mid-service at the
  *default* pool size (4), not the brief's specific `service_pool_size=1`/
  50-services combination; not re-parameterized this pass.
- **Done-callback double-fire probe** — not independently re-run in this
  track this pass; the round-6 CHANGELOG's #172 fix (in-flight counter
  balances on every terminal outcome via a done-callback) is asserted
  fixed based on the concurrency track's own coverage, not re-verified
  here.
- **RAISE refusal "exactly once" under the loop-side `RAISE` path
  specifically for internal (self-generated) sends**, as opposed to the
  external-threadsafe path this pass exercised — same-thread `send()`
  under `RAISE` was not separately re-attacked (it is unchanged behaviour
  per the CHANGELOG: "the exception reaches the caller and *is* the
  signal").
- **50x identical-trace determinism sweep + hash-seed sweep** — not run
  in this track this pass; covered independently and more thoroughly by
  the determinism track for this commit.
- **Perf-PR (#165/#176) sentinel aliasing check** (shared init/exit
  sentinel cross-talk between two machines) — not attempted in this
  track this pass; flagged as a gap, not investigated.
- **12-minute reduced soak with chaos snapshot/restore at quiescence** —
  not run in this track this pass; the soak track for this commit covers
  this ground independently.
- **Live `gh api` branch-protection / Actions-pinning / SBOM re-query** —
  not repeated; D-security-2/3/4/5 remain carried forward, unverified live
  this round.
- **`internal=True` forgery post-fix as an active exploit** (not just
  mechanism confirmation) — no working corruption/bypass was constructed
  this pass beyond re-confirming the mechanics are unchanged; a
  crash/corruption chain built specifically on this trust gap was not
  attempted.

---

## 5. Verdict

**Both round-6 security-adjacent fixes this pass specifically re-attacked
hold:** the loop-side `RAISE` refusal from `send_threadsafe()` now fires
`on_event_dropped(reason="queue_full")` exactly once per refusal (#157
reopened, confirmed 199/199 in a 200-send saturation attack), and the
per-macrostep chain-budget reset is correctly scoped to *external* events
only — 16 concurrent external threadsafe senders neither reset nor starved
a self-generated `always`/`always` chain's trip (#166-#168, confirmed by a
targeted concurrency attack this pass). Prior round-5-era security fixes
(`D5-security-1` log redaction, `D5-security-3` dict-event validation)
continue to hold unchanged on `221ce7c`.

**The security track's headline unresolved risk is unchanged from the
prior round:** `D6-security-1` / `R6-07` — a `None`/malformed
`machine_hash` still silently disables `from_snapshot()`'s drift
verification under `verify_machine_hash=True` — was **not** in this
round's fix set (#166-#175 touch the async chain budget, entry/exit
snapshot refusal, `Receipt.denied`, `start()` ordering, the threadsafe
in-flight counter, `service_pool_size`, and the queue-full hook; none of
them touch `persistence.py`'s `check_identity()`). This is the same High
finding this track carries forward as `D7-persistence-2` in the
persistence track's register for this commit, restated here under the
security lens: it remains the concrete, actionable, OMS-relevant gap.

**`D6-security-2`** (unverified `internal=True` trust boundary) remains
open at Low/Informational severity, mechanics unchanged, no working
exploit built.

**Net assessment for an OMS adopter pinning to `221ce7c`:** the round-6
fixes materially improve *observability* around backpressure and the chain
budget's correctness under concurrent load — both re-attacked here and
found sound — but do **not** address the persistence-layer's
identity-verification gap. An adopting project should continue to add its
own schema/checksum validation in front of `from_snapshot()`, with
particular attention to `machine_hash` never being accepted as `None` or
non-string, and should not rely on `verify_machine_hash=True` alone as a
tamper-evidence guarantee on this commit.
