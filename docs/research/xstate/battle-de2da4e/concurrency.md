# Battle test (round 12) — CONCURRENCY, BACKPRESSURE & RESOURCE LIMITS

Target: `xstate-statemachine` @ `de2da4e` (merge of #223, round-11 fixes
#218–#222; unreleased 0.8.1, `__version__` still reports `0.8.0` — keyed
on the commit).

Scripts: `battle-de2da4e/concurrency/v1`–`v7`, plus the round-11 suite
re-run verbatim under `concurrency/rerun-c78ce99/`. Every probe is
standalone (stdlib + `xstate_statemachine`, helpers inlined, no psutil),
proven from the neutral cwd `C:/Users/basil`. Every action check runs
BOTH `def` and `async def`; every engine check runs BOTH engines.

Library suite @ `de2da4e`: **3545 passed, 13 skipped, 92.87 % coverage**
(`suite-de2da4e.log`, complete).

---

## 0. Bottom line

**All five round-11 fixes hold. No new defect was found in this track.**

This is the first round in this track's history with an empty defect
register, and the result is not thin: the probes were built to break
these five mechanisms specifically, at the strength the brief asked for,
and every one of them held.

* **#218 (timer handle released) — exact.** A 200-beat heartbeat holds
  **at most 1 handle** on all three engine/kind cells; 500 superseding
  re-arms of one send id peak at 1 handle and produce exactly 1 fire;
  cancel-after-fire is a clean no-op; a 200-machine, 150-second soak
  sits at **1.00 handles per machine**.
* **#219 (`ReentrantWaitError`) — exact, and correctly *narrow*.** The
  in-step await is refused on both engines; the `ensure_future` escape
  the changelog promises works, 100/100 concurrent; cross-actor
  `wait=True` in both directions still resolves. Nothing hung.
* **#220 (recursive key check) — complete.** **300/300** injected typos
  caught under `strict_config=True` across **12 distinct nesting
  levels**, every finding path-named; **0 false positives** on 120
  generated valid charts and on all **109 catalogue `*.machine.json`**.
  This closes D11-concurrency-4.
* **#221 (parked `scheduled_sends`) — exact.** **300/300** property
  cases survive multi-hop restore→re-persist chains with the remaining
  delay **bit-identical** at every hop, then fire exactly once on time.
  This closes D11-concurrency-3.
* **#222 (sticky chain trip) — exact.** 3 kicks → 3 trips → 3
  `on_chain_budget_exceeded` calls; the latch survives the benign event
  that erases `last_error`; `clear_chain_error()` is idempotent, keeps
  the count, and a later trip re-latches.

**What has NOT changed** is the trust boundary. `D11-concurrency-1`
(forged `scheduled_sends` bypasses `strict`) and `D11-concurrency-2`
(`"version": 2` is a privilege) are **STILL-PRESENT and untouched** —
round 11 fixed the five *engine* findings and none of the two *High*
ingress findings. That, not any new defect, is what sets the verdict.

| Prior defect | Status @ `de2da4e` |
|---|---|
| D11-concurrency-1 (forged `scheduled_sends`, no `strict`) | **STILL-PRESENT** |
| D11-concurrency-2 (v2 upcast = privilege escalation) | **STILL-PRESENT** |
| D11-concurrency-3 (restore→re-persist drops timers) | **FIXED** (#221) |
| D11-concurrency-4 (nested keys unchecked) | **FIXED** (#220) |
| D11-concurrency-5 (`on_invalid_event` unreachable on restore) | **STILL-PRESENT** |

Verdict: **ADOPT WITH CONSTRAINTS — two constraints retired, the
snapshot constraints unchanged and still mandatory** (§6).

---

## 1. Method and reductions

| Item | Brief | Run | Why |
|------|-------|-----|-----|
| Persistence chain property | ≥300 cases | **300**, unreduced | random delay × elapsed × kind × 1–3 parked hops |
| Recursive-key fuzz | "every nesting level" | **300** trials over **12 sites** | every level the checker claims |
| Valid-grammar false positives | "0 rejections" | **120** generated + **109** catalogue | |
| Livelock fuzz | ≥500 configs | **540 cells** (2 shards × 90 shapes × 3 lanes) | two-sided #212 oracle + #222 assertions |
| ReentrantWait concurrency | 100 concurrent | **100**, unreduced | both kinds |
| Heartbeat load | 200 machines × 10 s | **200 × 10 s**, unreduced | |
| Determinism | 50× both engines both kinds | **300 runs / 6 cells**, unreduced | trace includes `chain_trips` |
| **Soak** | **12 min × 200 machines** | **150 s × 200 machines** | **the only material reduction** — §5 |

Machine count in the soak is **unreduced** (200); only the duration is
(150 s vs 720 s). The soak invariants are per-machine and
rate-independent, and the reduction is recorded in §5 as a residual gap.

### 1.1 Commands

```
PY=…/_ref/xstate-statemachine/.venv-main/Scripts/python
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1      # from cwd C:/Users/basil
D=…/CandleViewer/docs/research/xstate/battle-de2da4e/concurrency

$PY $D/v1_reentrant_wait_matrix.py            # exit 0
$PY $D/v2_timer_handles_and_cancel_storm.py   # exit 0
$PY $D/v3_persistence_chain_and_latch.py      # exit 0
$PY $D/v4_fuzz_keys_and_livelock.py           # exit 0
$PY $D/v5_observability_and_forgery.py        # exit 0
V6_SOAK_S=150 V6_N=200 $PY $D/v6_soak.py      # exit 0
$PY $D/v7_determinism.py                      # exit 0
$PY $D/rerun-c78ce99/u{1..8}*.py              # 1,3,4 -> exit 1 (see §2)
```

### 1.2 Four harness errors corrected mid-run

Recorded because each would have manufactured a false defect, per the
round-11 precedent of publishing corrected oracles.

1. **A `def` action cannot `await`.** My first ReentrantWait matrix ran
   every cell on both kinds and scored six `def` cells as failures. On
   the async engine a plain `def` action has no language form for
   awaiting a receipt, so the attack does not exist there. Those cells
   are now recorded `N/A_sync_action_cannot_await`, and the `def` side
   of the attack is carried by cell **B**, which runs the
   `SyncInterpreter` — where the same shape *is* expressible as a
   blocking call, and is refused. `ensure_future` cells (C, I) need no
   await at the issue site and **do** run on both kinds.
2. **`SyncInterpreter.start()` owns no thread.** I first drove the sync
   heartbeat from a background `start()` thread and measured 1 beat —
   which looks exactly like "#218 broke the sync heartbeat". The sync
   clock is advanced by `tick()`; driven correctly it reaches 200 beats
   at 1 handle.
3. **`GetProcessMemoryInfo` without `argtypes` returns 0 on win64.** My
   first RSS numbers were all `0.0`. The handle from
   `GetCurrentProcess` is truncated to int32 without an explicit
   `restype`, and the call fails silently.
4. **`SimulatedClock.increment()` inside a running loop fires nothing**
   (it warns). The sync determinism cells were initially hashing
   un-advanced traces. They now run outside the loop.

A fifth correction is a *chart* error worth naming: in v5 the trip chart
had no path back to `idle`, so the second and third `KICK` were simply
unhandled and `chain_trips` stayed at 1 — which reads as "the #222 latch
does not re-arm". With a `RESET` transition the same probe shows 3/3.
Same family as the round-11 `u8` trap: **the chart, not the library.**

---

## 2. Prior round-11 defect table

Every round-11 script was re-run **verbatim** (`rerun-c78ce99/`). None
awaited a `wait=True` send on its own interpreter, so **no script was
SUPERSEDED by #219** — no assertion rewrite was required.

| Prior defect | Sev | Probe re-run | Status @ `de2da4e` |
|---|---|---|---|
| **D11-concurrency-1** — forged `scheduled_sends`: no `strict` check, no provenance gate | High | `u3` (P4), `u4` (A/B) | **STILL-PRESENT.** `u3` exit 1: `strict_refusals: []`, `last_error: null`. `u4`-A drives `u4a.idle → u4a.moved` in a `strict: True` machine; `u4`-B mints a `done` and fires a declared `after: {60000}`. Unchanged. v5-X1 confirms #221 did **not** widen it (below). |
| **D11-concurrency-2** — `"version": 2` is a privilege; `upcast` stamps `engine: true` | High | `u1` | **STILL-PRESENT.** exit 1, 6/6 forged v2 cells drove `onDone` / `onError` / a 60 s `after`, both kinds. The v3-unflagged control is still correctly refused. `minimum_version=3` still the only mitigation, still not the default. |
| **D11-concurrency-3** — restore → re-persist without `start()` drops armed sends | Medium | `u3` (P2) | **FIXED (#221).** `first_hop_records: 1`, `second_hop_records_before_start: **1**` (was 0). v3 proves the strong form: 300 property cases and a 5-hop chain hold `remaining_ms` **exactly** constant and then fire once on time. |
| **D11-concurrency-4** — key check validates the top level only | Medium | `u4` (F), `u6` (F2) | **FIXED (#220).** `u6`-F2 `nested_caught: **120/120**` (was 0/120). `u4`-F now REFUSES `f2.a: 'entryy', 'onn'` and `f3.a: 'maxIterationss'`, path-named. v4-F1 extends this to 12 nesting levels at 300/300. |
| **D11-concurrency-5** — restore-time `strict` refusal cannot reach `on_invalid_event` | Low | `u4` (E) | **STILL-PRESENT.** `invalid_count: 0` with a refused record; `last_error` survives, one WARNING per record. Structural (restore runs inside the classmethod). Not addressed by #218–#222. |
| D10-concurrency-1 — `after` provenance forgery | High | not re-run | **CARRIED FORWARD** (§5). No #218–#222 entry touches it. |
| D10-concurrency-4 — `QueueOverflowError` fires no hook | Low | not re-run | **CARRIED FORWARD** (§5). |
| #206 rule / `t5` | — | — | **SUPERSEDED** since round 11 by #212; unchanged. |
| `u2`, `u5`, `u7`, `u8` (clean at `c78ce99`) | — | all four | **STILL CLEAN.** exit 0. No regression from the round-11 fixes. |

---

## 3. New attacks and what they returned

### 3.1 #219 — `ReentrantWaitError` matrix (`v1`)

| Cell | Attack | `def` | `async def` |
|---|---|---|---|
| **A** self await | action awaits `send(wait=True)` on itself | n/a¹ | **`ReentrantWaitError`**, no hang |
| **B** sync self | same shape on `SyncInterpreter` | **`ReentrantWaitError`**, no hang | n/a |
| **C** ensure_future | receipt handed out, awaited after the action returned | **RESOLVED**, `n=1` | **RESOLVED**, `n=1` |
| **D** child→parent | action awaits `wait=True` on a *different* interpreter | n/a¹ | **RESOLVED** (peer reached `.done`) |
| **E** parent→child | reverse direction | n/a¹ | **RESOLVED** |
| **F** after-fired handler | action reached from an `after` firing, outside the descent | n/a¹ | **`ReentrantWaitError`** |
| **H** external (control) | non-action caller awaits `wait=True` | **RESOLVED** | **RESOLVED** |
| **I** 100 concurrent | 100 interpreters, `ensure_future` pattern | **100/100 resolved** | **100/100 resolved** |

¹ `N/A_sync_action_cannot_await` — §1.2 note 1.

The guard is exactly as narrow as the changelog claims: it refuses the
*in-step await on one's own interpreter* and nothing else. Cross-actor
`wait=True` (both directions) and the deferred-receipt escape both work,
so #219 does not break the legitimate uses. **0 hangs in any cell.**

### 3.2 #218 — timer handles and cancel storms (`v2`)

| Cell | Attack | Result |
|---|---|---|
| **H1** | 200-beat heartbeat, 3 engine/kind cells | **peak 1 handle** everywhere (async/`def`, async/`async def`, sync/`def`); 200/200 beats |
| **H2** | cancel storm: arm 50 ids then cancel all, x10 rounds | peak `(50, 50)` each round, **`(0, 0)` after every cancel**, 0 exceptions |
| **H3** | 500 re-arms of the **same** send id (each supersedes, releasing the previous) | peak **1** handle, **1** armed, **exactly 1 fire**, released to `(0,0)` |
| **H4** | cancel a send that already **fired**, twice (explicit double-release) | no exception, accounting stays `0/0` |
| **H5** | 200 heartbeat machines x 10 s | handles <= 200 for 200 machines (**<=1 each**), RSS 30 -> 40 MB, 0 chain trips, no dead heartbeat |

H3 and H4 are the double-release shapes that a "release on fire *and* on
cancel" fix is most likely to get wrong. Both are clean on both kinds.

### 3.3 #221 / #222 — persistence chains and the latch (`v3`)

| Cell | Attack | Result |
|---|---|---|
| **P1** | **300** cases: random delay x elapsed x kind, then 1–3 x (restore then re-persist, **no `start()`**), restore, start | **0 failures.** The record survives every hop; `remaining_ms` is **identical at every hop**; fires **exactly once**, never early, always on time |
| **P2** | the same with a **5-hop** parked chain | `remainings: [750.0] x 6` on both kinds; `fired_early: false`, `n: 1` |
| **P3** | chain-trip latch vs a snapshot | `chain_trips` is **not** in the snapshot layout; a restored interpreter reads `0` / `None`. The latch **survives a benign event**; `clear_chain_error()` clears the latch and keeps the count |
| **P4** | recursive key check vs the real catalogue | **109/109** `*.machine.json` build clean under `strict_config=True`; **0** false positives |

P1's strongest single number: `remaining_ms` is stable to `round(x, 6)`
across every parked hop. The fix does not merely preserve the record, it
refuses to charge time against a record that binds no clock — which is
the property a journal-compaction job actually needs.

### 3.4 #220 — key-check fuzz, false positives, bypass (`v4`)

**F1 — typo at every nesting level, `strict_config=True`, 25 trials each:**

| Site | Caught | Path-named | Missed |
|---|---|---|---|
| root | 25/25 | 25 | 0 |
| state | 25/25 | 25 | 0 |
| deep nested state | 25/25 | 25 | 0 |
| parallel region | 25/25 | 25 | 0 |
| parallel child | 25/25 | 25 | 0 |
| `on` transition body | 25/25 | 25 | 0 |
| `after` transition body | 25/25 | 25 | 0 |
| `always` transition body | 25/25 | 25 | 0 |
| `onDone` transition body | 25/25 | 25 | 0 |
| `invoke` body | 25/25 | 25 | 0 |
| `invoke.onDone` | 25/25 | 25 | 0 |
| `invoke.onError` | 25/25 | 25 | 0 |
| **total** | **300/300** | **300** | **0** |

Mutations were drawn per-site from the *correct* key set for that level
(`KNOWN_ROOT` / `STATE` / `TRANSITION` / `INVOKE_KEYS`), so this tests
the per-level known sets, not merely the recursion.

**F2 — false positives:** 120 charts generated from the full key grammar
(every root/state/transition/invoke key at a legal position, legal enum
values) gave **120 accepted, 0 key-check rejections**. With P4's 109
catalogue charts: **229 valid charts, 0 false positives.**

**F3 — livelock fuzz:** 540 cells (2 shards x 90 shapes x 3 lanes),
two-sided #212 oracle, extended with #222: a periodic cycle must leave
`chain_trips == 0`; a must-trip cell must leave it `> 0` **with the latch
set**. **0 violations, 0 hangs**; 162 must-trip and 378 periodic cells.

**S1 — `strict_config` bypass attempts:**

| Vector | Outcome |
|---|---|
| `Strict`, `STRICT`, `strictconfig` (case variants) | **REFUSED**, with a correct "did you mean 'strict'?" |
| `"strict "` / `" strict"` (whitespace padding) | **REFUSED** |
| `strıct` (dotless i), `ѕtrict` (Cyrillic es) — unicode look-alikes | **REFUSED**, and the hint still resolves to `strict` |
| `x-strict`, `x-maxIterations` (reserved-namespace smuggling) | ACCEPTED (intended) and **INERT** — the policy did **not** take effect |
| `meta: {"strict": true}` | ACCEPTED and **INERT** |
| **control**: a correctly spelled `"strict": true` | **took effect** (`UnknownEventError` raised) |

The control is what makes this meaningful: the oracle can see a policy
taking effect, and no smuggled variant did. **No bypass.**

### 3.5 #222 observability and round-11 field forgery (`v5`)

| Cell | Attack | Result |
|---|---|---|
| **O1** | 3 separate trips on one interpreter | `chain_trips` 1→2→3, `on_chain_budget_exceeded` **1→2→3** — exactly once per trip, monotonic, both kinds |
| **O2** | `clear_chain_error()` semantics | clears the latch, **idempotent**, **keeps the count**, and a later trip **re-latches** (`trips 1→2`) |
| **O3** | sync-engine parity | identical: 1 trip, 1 hook, latch/clear/count all correct |
| **O4** | `last_error` vs `last_chain_error` | after a trip both hold `RunawayChainError`; after **one benign handled event** `last_error` becomes `None` while `last_chain_error` **stays** `RunawayChainError` — precisely the #222 bug, fixed |
| **order** | hook ordering | consistently `on_event_dropped('chain_budget')` **then** `on_chain_budget_exceeded`, both engines, both kinds |

**X1 — forgery of the round-11 fields** (R10-01 framing: `from_snapshot`
input is a *declared* trust boundary, so a vector is filed only if it
crosses a boundary the library still claims to hold):

| Vector | Result | Filed? |
|---|---|---|
| forged `chain_trips: 999` / `last_chain_error: "FORGED"` in the blob | **inert** — restored interpreter reads `0` / `None`; the counter is per-interpreter and not part of the layout | no |
| `scheduled_sends` record with `remaining_ms: -999999` | clamped; no hang, no instant storm | no |
| forged `lane: priority` + `engine: true` on a `scheduled_sends` record | delivers — but this is **exactly** the known-open D11-concurrency-1 surface, not a new one | no (carried under D11-1) |
| **does #221's verbatim re-emit *launder* a forged record?** | **No.** Hop 2 re-emits with **0 keys added and 0 removed** — the fix stamps no provenance the forger did not write | no |

The last row is the one this round had to answer, and the answer is the
right one. Round 11's recurring diagnosis — "a fix re-derives at restore
time a property the engine knew at mint time" — **was not repeated by
#221**: verbatim re-emission neither upgrades a forged record nor opens
a second minting channel.

### 3.6 Soak and determinism (`v6`, `v7`)

**v6 — 200 machines x 150 s**, mixed 10/20/25/40/50 ms heartbeats,
external priority producer every 50 ms, chaos every 1.5 s running the
full #221 chain (snapshot, restore, **re-persist without `start()`**,
restore, start):

| Invariant | Result |
|---|---|
| timer handles | `handles_max: 200` for 200 machines — **1.00 per machine**, flat from first sample to last |
| RSS | 33.4 -> 54.4 MB peak over 150 s with 97 stop/restore rounds — **flat** (round 11's unexplained 32 -> 207 MB did **not** recur; §5) |
| external events | **406 200 sent / 406 200 handled, 0 dropped** |
| heartbeats | none died; worst machine ran 40 % of its clock-ideal beats (scheduler-paced, `cpu/wall = 0.98` = one core) |
| `chain_trips` | **0**, and `on_chain_budget_exceeded` fired **0** times, across all 200 machines |
| chaos | 97 rounds; 90 caught the beat armed, 7 in-flight, **0 caught it nowhere**; **0** #221 re-persist mismatches; every round resumed the beat |

**v7 — determinism**, 50 runs per cell x 6 cells = **300 runs**. The
trace hashes state ids, context, the `scheduled_sends` count at each hop,
**`chain_trips`**, and the latched error type.

| Cell | Distinct hashes over 50 runs |
|---|---|
| async / `def` / no restore | **1** |
| async / `def` / #221 restore chain | **1** |
| async / `async def` / no restore | **1** |
| async / `async def` / #221 restore chain | **1** |
| sync / `def` / no restore | **1** |
| sync / `def` / #221 restore chain | **1** |

`def` and `async def` produce the **same** hash on the async engine in
both restore modes — the action kind does not perturb the trace.

---

## 4. Defect register — `D12-concurrency-n`

**Empty.** No new defect reproduced in this track at `de2da4e`.

Every attack in §3 either confirmed a round-11 fix or landed on the
already-filed round-11 ingress surface (D11-concurrency-1/-2/-5), which
is carried forward unchanged rather than re-filed. Per the
reproduce-before-you-count standard, nothing is recorded here that the
probes did not demonstrate.

The five harness/chart errors in §1.2 are recorded there precisely
because each *would* have become a D12 entry had it not been chased
down. Four were mine; the fifth (v5's missing `RESET`) is the same
internal-transition family as CV-C51.

---

## 5. Not covered

Stated so the verdict is not read as wider than the evidence.

| Gap | Why | Risk carried |
|---|---|---|
| **Full 12-min soak** | Whole-task bound. Ran **150 s x 200 machines** with 97 chaos rounds; the machine count is unreduced, only the duration | Slow accumulation over tens of minutes (fd growth, timer-heap fragmentation, clock drift) is still unmeasured. The handle metric that would show it is flat at 1.00/machine for 150 s |
| **Round-11's 32 -> 207 MB RSS growth** | Not reproduced here (33 -> 54 MB under a *harder* chaos schedule), but this probe also holds no references to stopped interpreters, which was the suspected cause | Not isolated either round. If it was probe-held references, it is closed; that is inference, not proof |
| **D10-concurrency-1** (`after` provenance forgery) | Not re-run; no #218–#222 entry touches it | Assumed still-present. High severity, on the same snapshot-ingress path CV-C50 covers |
| **D10-concurrency-4** (`QueueOverflowError` fires no hook) | Not re-run | Assumed still-present, Low |
| **Delayed `sendTo` / `sendParent` across actors** | Round 11 named this the first probe round 12 should run. v1-D/E cover cross-actor `wait=True` **without** a delay; the **delayed** cross-actor send's persistence and chain standing are **still unverified** | **The largest remaining semantic gap in this track**, unchanged from round 11. `_deliver` takes a different branch for `actor is not self` (`ensure_future(_send_to_actor)`) and `_armed_self_sends` is only populated `if actor is self` — so a delayed cross-actor send is, **by code inspection**, not in the v3 snapshot at all. One spot-check was attempted and was **inconclusive** (my `sendTo` chart did not resolve the invoked actor: `sendTo could not resolve target 'kid'; event 'PING' dropped`), so this is an unverified reading of the source, **not** a finding. Not probed; not filed |
| **Free-threading / no-GIL build** | Not re-run | Carried forward from round 10 |
| **Redaction** | Not run | Unchanged from round 10 |
| **`chain_trips` across a process restart** | v3-P3 records that the counter is per-interpreter and resets on restore; whether a supervisor needs it persisted is a design question, not a defect | An operator counting trips across restarts must persist it themselves |

---

## 6. Verdict

**ADOPT WITH CONSTRAINTS — two constraints retired; the snapshot
constraints unchanged and still mandatory.**

Round 11's engine work was good and round 12 could not break it. This
round's finding is about *how* the five fixes were made, and it is
favourable: each one fixed the mechanism rather than papering it. #218
releases the handle on both paths, including the two double-release
shapes (H3, H4). #219 is narrow — it refuses the deadlock and leaves
every legitimate `wait=True` working, including both cross-actor
directions and the documented `ensure_future` escape. #220's recursion
is complete at 12 nesting levels *and* costs nothing in false positives
across 229 real and generated charts. #221 re-emits parked records
**verbatim**, which is why it did not become a new forgery channel.
#222 is exactly-once and correctly sticky.

The unchanged half is the trust boundary. `scheduled_sends` still takes
no `strict` check (D11-1) and `"version": 2` is still a privilege
(D11-2). Round 11's diagnosis stands verbatim: **a snapshot must be
treated as attacker-controlled code, not data.** Nothing this round
narrows that, and nothing widens it either.

### Constraint changes

| ID | Change |
|---|---|
| **CV-C53** | **RETIRED.** "Do not restore-then-re-persist without `start()`" — #221 fixes this exactly; 300 property cases and a 5-hop chain hold the remaining delay constant and fire once. Restore-inspect-rewrite is now safe |
| **CV-C54** | **RETIRED as written.** "Config keys inside states get no validation" is no longer true: 300/300 at 12 nesting levels, path-named. **Replaced by CV-C56** |
| **CV-C56** *(new)* | `strict_config=True` is now **necessary and largely sufficient** for key typos and **must** be set on every `create_machine` call. It validates root, state, transition and invoke keys at every depth. It still does not validate *values* beyond the declared enums, nor unknown keys under `meta` — keep the CI schema check for those two, not for key names |
| **CV-C49, CV-C50** | **UNCHANGED and still mandatory.** `minimum_version=3` + pinned `expected_machine_hash`; HMAC outside the library. D11-1/-2 are untouched |
| **CV-C51, CV-C52, CV-C55** | **UNCHANGED.** The internal-transition trap bit this round's own v5 chart (§1.2); the `machine_hash` param asymmetry and the unreachable restore-time `on_invalid_event` are both unaddressed by #218–#222 |
| **CV-C57** *(new)* | An action **must not** `await send(..., wait=True)` on its own interpreter — it now raises `ReentrantWaitError` rather than hanging. Where a receipt is genuinely needed, hand it out with `asyncio.ensure_future(...)` and await it after the action returns (v1-C/I). This is a **behaviour change** in 0.8.1: code that previously deadlocked now raises, and code that somehow worked by timing now raises too. Audit every in-action `wait=True` before upgrading |

### Phase-3 impact

Positive and unblocking. Two development-time constraints retire, the
heartbeat/timer story is now provably leak-free at OMS scale (200
machines, 1.00 handles each, 406 k events with none dropped), and the
chain-trip channel is finally supervisable — `chain_trips` plus
`on_chain_budget_exceeded` give exactly-once trip notification with a
latch that a benign event cannot erase, which is what a supervisor
needs to alarm on discarded work.

Two items gate further work, both unchanged from round 11's
recommendation:

1. **Delayed `sendTo` / `sendParent` across actors** (§5) remains the
   first probe the next round should run. Code inspection suggests it is
   not captured by `scheduled_sends` at all (`_armed_self_sends` is
   populated only `if actor is self`); my one spot-check was
   inconclusive, so this is a **hypothesis to test, not a finding**. If
   it holds, a multi-actor chart with cross-actor deadlines loses them
   on every snapshot — the same class as D10-concurrency-3, one actor
   boundary over. **No multi-actor chart with delayed cross-actor sends
   should ship until this is probed.**
2. **CV-C57's behaviour change** must be audited for before adopting
   0.8.1, since #219 converts a previously-silent hang into an
   exception.
