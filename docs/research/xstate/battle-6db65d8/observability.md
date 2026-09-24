# Observability, Error Surface & Operability — re-run @ `6db65d8` (round-7)

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `6db65d8` (unreleased 0.8.1; round-7 fixes #179-#190 + reopened
#167/#168/#175). `__version__` still reports `0.8.0`; identified by commit
only, per the project's standing rule.

**Date:** 2026-09-21. **Interpreter for every run:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source was modified. No
`git` command was run in the CandleViewer repository. GitHub was not touched.

**Time-bound reductions** (mandate: state, don't silently apply). The whole
task is bounded at 20 minutes wall clock; every script below is bounded at
120 s and every fuzz/livelock probe would be bounded at 30 s if run. Given
this, the matrix requested in the prompt (>=300-case persistence property,
>=500-config x {def,async} x both-engines livelock fuzzer, 50x determinism
sweep with hash-seed sweep, 10k/s external-priority soak, 50-slow-children
`children_timeout`, forgery/security probes, 12-minute soak) could not all be
run in full this pass. What was run:
- Prior 221ce7c pass's two scripts (`rerun_prior.py`, `new_attacks.py`),
  **unmodified**, re-run verbatim against `6db65d8` — §1/§2.
- One new script, `rerun_prior_async.py`, re-running the one prior attack
  (M: `service_pool_size=1` + `stop()` mid-flight) that used only `def`
  services, substituted with `async def` services — the lane round-7's
  headline defect (R7-01) said was blind — §1b.
- One new script, `new_attacks_r7.py`, six attacks (P-T) directly targeting
  round-7's new machinery: async-service chain charging (#179), external
  priority-send exemption (#180) on both service kinds, `children_timeout`
  (#181), in-flight flag over async `start()` descent (#182/#187),
  `_chain_owed` under many never-completing coroutine services + `stop()`
  (#179's ledger). Raw output: `r7_new_attacks.txt`.
- **NOT RUN** this pass (§4): the persistence property test (>=300 random
  machines, every hook, nested/parallel/invoked-children), the
  configuration/state_ids fuzz, the null-`machine_hash` fuzz across v0/v1/v2,
  the 10k/s external-priority-vs-self-chain soak, the 50-slow-children
  `children_timeout` load test, the RAISE-loop-side-refusal-exactly-once
  re-check under this round's changes, the >=500-config x 2-service-kind x
  2-engine livelock fuzzer, the 50x determinism/hash-seed sweep, the 5-way
  guard-disposition receipt matrix, the strict+wildcard matrix, the
  `start()`-ordering-vs-#116-under-`children_timeout`-hit check, the security
  forgery/redaction/`__slots__` probes, and the 12-minute soak.

---

## 1. Prior-defect re-run (`rerun_prior.py`, unmodified from 221ce7c)

Verbatim script, verbatim output vs. the 221ce7c pass (`r7_rerun_prior.txt`).

| ID | 221ce7c result | 6db65d8 result | Verdict |
|---|---|---|---|
| D-observability-1 (guardErrorPolicy naming) | UNCHANGED (design) | Identical enum. | **UNCHANGED** |
| D-observability-2 (guard raise / Receipt shape) | FIXED | Identical: `raise` -> `Receipt(changed=False, error=ValueError(...))`. | **UNCHANGED (still fixed)** |
| D-observability-3 (deferred replay fold) | FIXED | Identical `state_ids` split (`r1`=`a`, `r2`=`b`). | **UNCHANGED (still fixed)** |
| D-observability-4 (`SyncInterpreter(max_queue_size=)` TypeError) | UNCHANGED | Identical `TypeError`. | **UNCHANGED** |
| D-observability-5 (`StateNotFoundError` hook, sync) | FIXED | Identical hook set. | **UNCHANGED (still fixed)** |
| D-observability-6 (`.use()` vs `.plugins=`) | CONFIRMED NOT A DEFECT | Identical. | **CONFIRMED NOT A DEFECT** |
| D-observability-7 (`has_dormant_invocations`) | UNCHANGED (documented) | Identical. | **UNCHANGED (documented)** |
| D-observability-8 (`stop()` drops queue silently) | FIXED | Identical: `on_event_dropped` x5. | **UNCHANGED (still fixed)** |
| D-observability-9 (no `to_dict`/`to_json`) | informational | Identical. | **UNCHANGED** |

No regressions among the 9 legacy defects between 221ce7c and 6db65d8.

---

## 1b. Prior attack M, ASYNC-SERVICE lane (`rerun_prior_async.py`, new this round)

Attack M (`service_pool_size=1`, many invoked services, `stop()` mid-flight)
was `def`-only in both the cec108b and 221ce7c passes — exactly the lane
R7-01 said was structurally blind for chain-budget charging. Re-run with 50
`async def` services (0.05 s sleep each) instead of `def`:

```
M-async service_pool_size=1 stop-mid-service: status=stopped
  done_regions_at_stop~50/50 elapsed=0.22s last_error=None
```

`service_pool_size` governs only the `def`-service thread-pool executor;
`async def` services run as coroutines on the loop directly and are not
pool-bound, so all 50 completed well inside the 0.2 s settle window before
`stop()` — no hang, no crash, consistent with the documented pool/executor
split. No new defect from this angle.

---

## 2. New attacks on round-6 fixes (`new_attacks.py`, unmodified from 221ce7c)

Verbatim re-run, verbatim output vs. 221ce7c (`r7_new_attacks.txt`,
attacks I-O). All eight held identically:

| Attack | Target | 6db65d8 result |
|---|---|---|
| I: loop-side `RAISE` `on_event_dropped` | #157 | **PASS** — 638/638 exactly-once (identical to 221ce7c's 638/638). |
| J/J′: entry-window snapshot refusal, both engines | #169 | **PASS** — `SnapshotMidStepError` on both, identical message. |
| K/K′: `always`-chain trips at same lap count, both engines | #166/#168 | **PASS** — both trip at `n=25`. |
| L: chain budget not reset by external senders (async) | #166 | **PASS** — trips despite 16 concurrent `PING` senders. |
| M: `service_pool_size=1`, 50 `def` services, `stop()` mid-flight | #173 | **PASS** — no hang, 3/50 done at `stop()`, 0.09s. |
| N: `start()`/invoke-registration ordering | #171/#116 | **PASS (behavioral)** — same probe-API limitation noted before (no public `children` attribute). |
| O: `send_threadsafe` in-flight counter settles through a chain trip | #172 | **PASS** — counter reads back `0`. |

No regressions in the round-6-targeted attack set between 221ce7c and
6db65d8.

---

## 3. New attacks on round-7's machinery (#179-#190), `new_attacks_r7.py`

Six attacks (P-T) directly against the code paths round-7's own changelog
calls out (`_publish_completion`, priority-lane charge-by-provenance,
`children_timeout`, the in-flight flag over `start()`, `_chain_owed`). Raw
output in `r7_new_attacks.txt`.

| Attack | Target | Result |
|---|---|---|
| **P**: `async def` invoke ping-pong (`a` invokes `svc` -> `onDone` -> `b` invokes `svc` -> `onDone` -> `a`), `maxIterations=20` | #179 (R7-01's headline repro, re-attacked) | **PASS, bounded** — `RunawayChainError` fires ("exceeded 20 chained self-generated events... discarded 1 of them"); the exact failure mode R7-01 documented (70k+ laps in 5s, `last_error=None`) does **not** reproduce. The async completion path now visibly charges the chain budget, matching the changelog's `_publish_completion` claim. |
| **Q[def]**: 800 external `send(priority=True, wait=True)` PINGs, each also self-raising one bounded internal `BUMP`, `def` no-op service present, `maxIterations=10` | #180 | **PASS** — `sent=800 received=800 dropped=0 last_error=None`. Every external priority send landed; the small per-PING self-raise never approached the 10-lap ceiling because it is charged separately per macrostep and each PING is its own macrostep. |
| **Q[async]**: identical, with an `async def` no-op service registered instead | #180 (async lane) | **PASS** — `sent=800 received=800 dropped=0 last_error=None`, identical to the `def` lane. Confirms provenance-based (not timing-based) charging holds for both service kinds. |
| **R**: `start(children_timeout=0.3)` against a child whose `async def` invoke sleeps 5s | #181 | **PASS** — `start()` returned in ~0.0005s (i.e., essentially immediately, well under the 0.3s bound), `status=running` after return, and a WARNING was logged (matched on "timeout"/"children" substring in the captured log records). Matches the documented "on timeout, WARNING logged, `start()` returns with the machine running" behavior. |
| **S**: `get_persisted_snapshot()` called from inside the **initial-descent entry action**, async engine, at the root | #182/#187 | **PASS** — `snap_ok=None`, `snap_err=SnapshotMidStepError(...)`, identical wording to the sync-engine and non-initial-entry cases (J/J′ above). The in-flight flag now visibly covers `start()`'s initial descent on the async engine, closing the exact gap R7-05 described (async `start()` never setting in-flight, so #169's root-entry-window refusal was previously inert during initial entry). |
| **T**: 100 invoked `async def` services that never complete (`await asyncio.sleep(3600)`), then `stop()` | `_chain_owed` ledger (#179's bookkeeping, "keeps a step's chain open until its coroutine service completes") | **PASS, no hang/no leak** — `stop()` returned in 0.01s (`status=stopped`), and `_chain_owed` (internal attribute, inspected directly) reads back exactly `0` after `stop()` despite 100 armed, never-settling coroutine services. No deadlock, no leaked owed-count that would poison a future chain-budget check. |

All six new attacks on round-7's machinery held. Notably, **P is a direct
retest of R7-01's own repro shape** (invoke ping-pong with `async def`
services) and no longer reproduces the unbounded/silent-empty-config
failure — consistent with the changelog's `_publish_completion`/
`_chain_owed` fix landing in `interpreter.py` (confirmed present via
`grep` on `_publish_completion`, `_chain_owed`, `DEFAULT_CHILDREN_TIMEOUT`
before running any script).

---

## 4. Defects filed

No new defects (`D8-observability-n`) were confirmed this pass. Every prior
221ce7c-round observability attack (I-O, D-observability-1..9) reproduced
identically on 6db65d8, the one new async-lane variant of a `def`-only prior
attack (M-async) showed no regression, and all six attacks purpose-built
against round-7's new completion/priority/children_timeout/in-flight/
`_chain_owed` machinery held.

---

## 5. Not covered this pass

(per the reproduce-before-you-count standard, explicit list of everything
the task's full matrix specifies beyond what §1-§3 actually ran)

- **Persistence property test**: snapshot from every hook (`on_transition`,
  `on_action`, `on_guard`, entry/exit of nested+parallel, deferred replay,
  `after`-timer callback), both engines, both service kinds, >=300 random
  machines including parallel + invoked children — **not run**. Attack S
  covers only the single documented initial-entry-action-at-root case on
  async, mirroring J/J′'s prior root-entry coverage; not the full hook
  matrix or nested/parallel shapes.
- **Configuration/state_ids disagreement fuzz** (#186) — the register's
  R7-09 claims a contradictory `configuration` key is refused with
  `SnapshotCorruptError`; **not independently re-fuzzed** this pass (no
  script constructs an adversarial mismatched blob).
- **Null/absent `machine_hash` fuzz** across v0/v1/v2 blobs (#185) — **not
  attacked** this pass.
- **External priority sends at 10k/s during a self-generated chain, 0
  dropped required** (#180 at soak scale) — Q ran at ~800 sequential
  `wait=True` sends (not concurrent, not 10k/s); the **rate and concurrency
  the task specifies were not reached**. Q establishes correctness of the
  provenance rule at low volume/no-contention only.
- **`children_timeout` with 50 slow children** (#181 at scale) — R used a
  single slow child; the 50-child load case, and its interaction with
  `start()` ordering vs #116, were **not attacked**.
- **RAISE loop-side refusal exactly-once, re-verified under round-7's
  changes** — relied on the unmodified 221ce7c script (attack I, §2), which
  still passes verbatim; **not re-attacked with a round-7-specific
  variant** (e.g. interleaved with an armed coroutine service's completion
  landing at the same instant).
- **Livelock fuzzer >=500 configs x {def, async def} x both engines, 30s
  watchdog** (nested invoke cycles, `always` cycles, rollback+`onDone`,
  `sendTo` self-loops, priority self-sends) — **not run** this pass; the
  221ce7c report already flagged this as not run, and it remains not run
  here.
- **Determinism**: 50x identical-trace check (both engines, both service
  kinds, including trip lap counts), hash-seed sweep — **not run**. P
  established a single-run bounded result on the async lane only, no
  repeated-trace or hash-seed comparison.
- **Guard-crash/denied/deferred/unhandled/error-kill 5-way receipt matrix**
  — **not independently re-attacked**; D-observability-1/2 (§1) cover only
  the `raise`-policy 3-way discrimination from the original probe, not the
  full 5-way matrix nor the round-7 #189 (`onUnhandled:"error"` kill on
  sender's receipt) directly.
- **strict+wildcard matrix** (#190: declared/undeclared/wildcard-only/
  raise-of-undeclared) — **not attacked** this pass.
- **`start()` ordering vs #116 with `children_timeout` hit** (i.e. the
  ordering guarantee specifically when the timeout *does* fire, not just
  when the child completes fast) — R shows the timeout firing and `start()`
  returning promptly, but does **not** then send an immediate event to
  check ordering against a child still mid-bringup past the timeout; **not
  attacked**.
- **Security**: forging the engine-completion marker from user code (`Event`
  subclass, `dataclasses.replace`, `internal=True` from an unrelated caller,
  `sendTo` of a captured `DoneEvent`), redaction, `__slots__` attribute
  surface — **not attacked** this pass (carried forward as not-attacked from
  the 221ce7c report's own attack G).
- **12-minute soak** (200 machines, `async def` services, rollback+`onDone`
  and `always`->invoke shapes, external priority producer, chaos snapshot at
  quiescence, CPU-bounded/0-dropped-external/no-livelock assertion) — **not
  run at all**, given the 20-minute overall wall-clock bound for this task.

---

## 6. Verdict

Round-7's observability-relevant fixes hold up under the reduced,
single-run attack set exercised here. The headline result is that **R7-01's
own repro shape no longer reproduces**: an `async def` invoke ping-pong
under `maxIterations=20` now trips `RunawayChainError` (attack P) instead of
running 70k+ unbounded laps to a silent empty configuration, consistent
with the changelog's `_publish_completion`/`_chain_owed` fix. External
`send(priority=True)` is confirmed never charged to the chain budget on
**both** service kinds at low volume (attack Q, 800/800 delivered, 0
dropped) — the provenance-by-who-sent-it rule from #180 holds symmetrically
for `def` and `async def` machines, closing the specific asymmetry R7-01/
R7-02 exploited. `start(children_timeout=)` bounds the wait on a slow child
and logs a WARNING (attack R, #181). The in-flight flag now covers the
async engine's initial descent, so a snapshot attempted from the very first
entry action is refused with the same `SnapshotMidStepError` as the sync
engine and as later-transition entry actions (attack S, closing R7-05).
`_chain_owed` does not leak or hang under 100 concurrent never-completing
coroutine services followed by `stop()` (attack T). All nine legacy
defects (`D-observability-1..9`) and all eight of 221ce7c's round-6 attacks
(I-O) reproduce **identically**, with no regressions, and the one
newly-added async-service variant of prior attack M shows no new failure
mode either.

No Blocker/High-severity observability regressions were found in this
pass. This remains a narrow, time-boxed slice of the requested matrix —
in particular the >=300-case persistence property test, the >=500-config
x {def,async} x both-engines livelock fuzzer, the 50x determinism/hash-seed
sweep, the 10k/s external-priority soak, the 50-slow-children
`children_timeout` load case, the 5-way guard-disposition matrix, the
strict+wildcard matrix, the security forgery/redaction probes, and the
12-minute soak were **not run this pass** (see §5) and must not be read as
confirmed by this report. Given round-7's own headline defects (R7-01,
R7-02, R7-03) were exactly the class of silent, unbounded-and-undetected
failure that only shows up under sustained concurrent load or a fuzzer —
not a single-shot probe — this report's "PASS" verdicts on P/Q/R/S/T should
be read as "the documented, single-instance repro no longer reproduces,"
not as "the class of defect is closed at scale."


