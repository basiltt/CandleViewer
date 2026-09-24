# Battle-test — SECURITY track — `c78ce99`

**Build under test.** `_ref/xstate-statemachine` @ **`c78ce99`** (merge #217,
round-10 fix set `#212`–`#216` per CHANGELOG `[Unreleased]`). `__version__`
still `0.8.0`; keyed on commit. Windows 11, `.venv-main`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`, every script run from the neutral cwd
`C:/Users/basil`. Scripts under `battle-c78ce99/security/`: the 21 prior-pass
files re-run verbatim, plus 11 new ones (`n1`–`n11`). No library source
modified; no `git`/`gh` writes; no project name in postable text.

**Two semantic reversals honoured.** (a) `#212` supersedes `#206`: a
`raise(delay=)` self-send is a **timer**, so a delayed ping-pong of any period
is legal periodic work and must **not** trip — every prior assertion of the
old rule is recorded **SUPERSEDED**, not FAIL, and re-asserted under the new
oracle. (b) `#213` introduces snapshot layout **v3** with `scheduled_sends`.

---

## 1. Prior-defect re-run (21 scripts, both service kinds where applicable)

| Prior item | `19cb1f1` verdict | `c78ce99` result | Status |
|---|---|---|---|
| D6-security-1 / #185 (null `machine_hash`) | FIXED | `attack_snapshot_corrupt_fuzz.py`: same shape; every "UNCONTROLLED" row is the documented `SnapshotDriftError` text (script's own broad `except`), `ACCEPTED_BAD` rows are all cosmetic mutations (`taken_at=null`, junk sidecars). Snapshot shape now shows `scheduled_sends` as a v3 key. | **FIXED, holds** |
| D6-security-2 (`send_threadsafe(internal=True)` forgery) | STILL-PRESENT (informational) | `def`: `bump_count=200`; `async def`: `bump_count=1`. Byte-identical to prior pass. | **STILL-PRESENT, unchanged** |
| #157 (loop-side RAISE refusal observability) | FIXED | `refused_futures=199 queue_full_hook_fires=199`, 1:1. | **FIXED, holds** |
| Async chain budget under concurrent external load | FIXED | baseline `tripped=True`; 16 senders / 709 delivered: `tripped=True`. | **FIXED, holds** |
| Async livelock fuzz | not re-run last pass | **Re-run and superseded** — see §2.4: the old oracle ("any self-raise cycle trips") is now wrong for delayed arms. New oracle run at 540 cells, all OK. | **SUPERSEDED → re-asserted, holds** |
| Persistence-hook snapshot never torn | FIXED | `n=300 refused=600 legal=300 torn=0`. | **FIXED, holds** |
| Persistence quiescence property | FIXED | `events=500 mid_step_at_quiescence=0 roundtrip_failures=0`. | **FIXED, holds** |
| Semantics 4-way matrix | FIXED | identical, incl. `Receipt.denied` discrimination and `guardErrorPolicy-raise-fallback`. | **FIXED, holds** |
| `{"type":"GO"}` bypasses `InvalidEventError` | resolved-by-design | identical: 8/9 hostile shapes raise, dict-event accepted. | **UNCHANGED, by design** |
| `service_pool_size` / `stop()` mid-service | FIXED | `runs=200 errors=0 statuses={'stopped'}`, threads 1→1. | **FIXED, holds** |
| Hook matrix `on_plugin_error`/`on_resolve_error` | documented | identical. | **UNCHANGED** |
| Engine-completion-marker forgery (call-site surface) | no surface | `engine_completion` still private-kwarg-only, not on public `send()`, not derived from the `Event`. | **UNCHANGED** |
| #192 provenance-shed under load | FIXED | sync `external_sent=246 tripped=True`; async `external_sent=453 tripped=True`; 0 dropped. | **FIXED, holds** |
| #193 def-service rollback cancellation | FIXED | `cycles=200 service_calls_leaked=0`. | **FIXED, holds** |
| #194 per-child `children_timeout` | FIXED | `elapsed_at_start=0.304s` (aggregate would be ~1.5 s), WARNING fires. | **FIXED, holds** |
| #198 configuration/state_ids agreement | FIXED | all 4 laundering mutations `SnapshotCorruptError`. | **FIXED, holds** |
| #199 `on_interpreter_start` in-flight window | FIXED | both engines `SnapshotMidStepError`. | **FIXED, holds** |
| `attack_priority_provenance_roundtrip.py` | documented boundary | resume clean (`{'m.b'}`); forged `engine:true` still mints (documented #195 boundary); v1 no-hash refused `SnapshotDriftError`. | **UNCHANGED** |
| R9-02 (forged public `AfterEvent`) | FIXED by #203 | `fires=False state={'m.waiting'}` — still refused. | **FIXED, holds** |
| **R9-01 / R10-01 (import-path `_EngineDone` forgery)** | STILL-PRESENT (Blocker) | `attack_r901_r902_reverify.py`: `_EngineDone` importable, `is_system_event=True`, decisive vector fires a forged `onDone` while the genuine service is still running → `{'m.done_state'}`. `_replace`/pickle on the **public** class correctly `False`. | **STILL-PRESENT, unchanged (Blocker)** |
| #207 stranded-invocation observability | FIXED | `stranded=('sub',)`, hook fires, `has_dormant=True`, `pending_invocations` populated — on `async/async`, `sync/def`. The `async engine + def service` cell reports `RuntimeError` from the entry action instead, as previously recorded. | **FIXED, holds (same known cell asymmetry)** |

**No prior-defect regression.** One class of prior assertion (any self-raise
cycle trips) is **SUPERSEDED** by `#212` and re-asserted under the new oracle
in §2.4.

---

## 2. New attacks

### 2.1 Persistence — v3 round-trip property (`n4_v3_property_async.py`)

**300 random machines**, random period (60/120/200/300 ms), snapshot taken at
a random point **inside** the armed window, restored, then asserted to fire
and to fire **no earlier** than the persisted `remaining_ms`:

```
v3 async roundtrip n=300 {'ok': 300}
```

`#213` holds exactly as specified on the async engine: the record is written,
the remaining delay is honoured, and nothing fires early. `n1_persistence_v3.py`
§A runs the same property on the **sync** engine and reports 0 fired — that is
a **harness artefact, not a defect**: the sync engine has no run loop, so a
plain `after:` timer does not fire on an idle `SyncInterpreter` either
(`n3_sync_pump.py` proves the parity: `after` idle 400 ms → `t.a`; one
`send()` → `t.b`). The restored `scheduled_sends` fire on the next pump
identically to a live one.

### 2.2 v2 upcast matrix and lane ordering (`n1`, `n2`)

| record | version | drives the transition? |
|---|---|---|
| `after`, no `engine` flag | v3 | **No** (`last_error=UnknownEventError`) — correct |
| `after`, `engine:true` | v3 | Yes — correct (#195) |
| `after`, no flag | **v2** | **Yes** — upcast mints it (#214) |
| `done`, no flag | **v2** | **Yes** — upcast mints it |
| `error`, no flag | v2 | No on this chart (no `onError` arm declared) |
| user `event` | v2 | user traffic — correct |
| `after`, no `kind` | v1 | No — correct (#162) |

**Lane restore ordering** is correct on the **async** engine: a
`lane:"priority"` `after` record restores **ahead of** a `lane:"inbox"` user
event (`['after.1000.l.w', 'EXT']`). On the **sync** engine the order is
reversed (`['EXT', 'after.1000.l.w']`) — the sync engine has a single queue by
construction (`sync_interpreter.py` holds no `_priority_queue`), so `lane` is
persisted but not honoured there. Recorded as **D11-security-5** (Low).

### 2.3 `machine_hash` does **not** cover `scheduled_sends` (`n1` §E)

`machine_hash` is a *structural* fingerprint and changes when the
`raise(delay=)` action is removed from the chart (`97edcda9…` vs `b6ba2f8e…`),
but it does **not** cover runtime payload. An attacker-injected
`scheduled_sends` record (`{"type":"EVIL","remaining_ms":1.0}`) is accepted
under an unchanged, valid hash. This is the same documented
trust-the-payload boundary as `state_ids`/`context` (#185), now extended to a
**new field that re-arms timers** — noted under D11-security-1's fix
direction (same trust boundary, wider blast radius); not filed separately.

### 2.4 Concurrency under the new `#212` rule (`n5_concurrency_212.py`)

```
A n=200 dur=10.0s cpu=10.00s cpu/wall=1.00 alive=200 errors={}
A RunawayChainError count: 0   (expect 0 -- delayed ping-pong is periodic work)
B zero-delay cycle tripped: RunawayChainError  (via last_error)
B mixed delayed+zero-delay tripped: RunawayChainError
C 100 concurrent starts elapsed=0.02s settled=100/100
D restore 200 v3 snapshots concurrently: 0.01s moved=200 errors=0
```

**The `#212` reversal is correct and complete.** 200 machines at a 1 ms
`raise(delay=)` ping-pong run 10 s with **zero** trips and all 200 alive — the
shape `#206` would have killed at 25 beats. A zero-delay cycle still trips,
and a **mixed** chart (delayed outer heartbeat feeding a zero-delay inner
spin) still trips on the inner loop — the reversal did not open a hole.

`C` (`#215` descent-settle wait) is bounded: 100 concurrent starts with
3-deep `always` cycles settle in 0.02 s, all reaching `s3`. `D` restores 200
v3 snapshots with armed sends in 0.01 s, 0 errors.

**CPU is *not* bounded by the clock at 1 ms.** A scaling sweep:

| n | period | cpu/wall | beats delivered | beats expected | ratio |
|---|---|---|---|---|---|
| 25 | 1 ms | 0.95 | 64 652 | 100 000 | 0.65 |
| 50 | 1 ms | 1.00 | 71 131 | 200 000 | 0.36 |
| 100 | 1 ms | 0.99 | 68 454 | 400 000 | 0.17 |
| 200 | 1 ms | 0.99 | 64 366 | 800 000 | 0.08 |
| 200 | 10 ms | 1.00 | 56 983 | 80 000 | 0.71 |
| 200 | 50 ms | **0.23** | 12 800 | 16 000 | 0.80 |

At 50 ms CPU is genuinely bounded (23 % of one core). At 1 ms the loop
saturates one core from **n=25** and the *delivered* beat rate then plateaus
at ~65 k/s regardless of n — the machines silently slow to ~8 % of their
declared period at n=200. Cost is flat at **~60 µs per beat**, i.e. this is a
throughput ceiling, not a leak: no trip, no error, no unbounded growth. It is
an **operational constraint, not a defect** (recorded as the new constraint
below): a `raise(delay=)` heartbeat faster than ~2 ms × n cannot keep its
period, and the library gives no signal that it is falling behind.

### 2.5 Livelock fuzz under the new oracle (`n7_livelock_fuzz_212.py`)

**540 cells** = 180 random 2–4-state self-raise cycles × {async/`def`,
async/`async def`, sync/`def`}. Oracle: a cycle with **any** arm at delay ≥1 ms
must not trip and must beat ≥3 times; an all-zero-delay cycle must trip.

```
periodic/async/async/OK 81   periodic/async/def/OK 81   periodic/sync/def/OK 81
zero/async/async/OK     99   zero/async/def/OK     99   zero/sync/def/OK     99
```

**540/540 agree with the `#212` oracle on both engines and both action
kinds.** (Reduced from the requested ≥500 *configs* to 180 configs × 3 lanes
= 540 cells to fit the ≤120 s per-script bound; stated for honesty.)

### 2.6 `#216` config-key fuzz (`n6_config_key_fuzz_216.py`)

Default mode, 7 misspelled policy keys (`actionErrorPolicyy`, `Strict`,
`maxIteration`, `onUnhandledEvent`, `guardErrorPolicyy`,
`spawnBlockingTimeoutMs`, `strictTarget`): **all 7** build with
`warned=True hint=True`. The declared value is still dropped
(`maxIteration: 5` → `machine.max_iterations == 1000`) — by design; the
warning is the fix.

`strict_config=True` and in-config `"strictConfig": true` both raise
`InvalidConfigError`. The kwarg wins over the config key
(`strict_config=False` + `"strictConfig": true` → builds), which is the
documented precedence.

**Bypass vectors, all under `strict_config=True`:**

| vector | result |
|---|---|
| `ACTIONERRORPOLICY` (case) | refused ✅ |
| `"strict "` (trailing space) | refused ✅ |
| `"strіct"` (Cyrillic і) | refused ✅ |
| zero-width char in key | refused ✅ |
| `x-actionErrorPolicy` | **built** — documented reserved namespace |
| `x-strict` | **built** — documented |
| non-`str` key `1` | **built** — `validate_top_level_keys` filters `isinstance(k, str)` |
| `meta: {strict: true}` | **built** — documented metadata |

The `x-` and `meta` results are the specified contract, not bypasses: they
smuggle nothing, because the parser does not read them either. The non-`str`
key is a genuine (Low) gap — a JSON-loaded config cannot produce one, but a
Python-dict config can, and `strict_config=True` promises to refuse keys the
parser does not read.

**Nested (state-level) unknown keys are NOT covered** — `#216` is top-level
only. A state carrying `entrry`, `onn`, `afterr`, `unknownThing` builds
silently under `strict_config=True` with **no warning at all**, and the
declared `onn` handler vanishes (`a.on` is empty). This is the same class of
defect `#216` was raised to close, one level down: **D11-security-2**.

### 2.7 `#214` restore-strict matrix (`n11_restore_strict_214.py`)

Both engines, 5 record shapes. `strict` **is** applied on restore — an
undeclared restored event is dropped, the machine stays in `s.w`, a WARNING
is logged and `last_error=UnknownEventError`. A `done` record **without** the
`engine` flag is correctly treated as user traffic and refused; one **with**
it drives `onDone`. Identical on sync and async.

**But `on_invalid_event` never fires on the restore path** — `spy.invalid`
is `[]` in all 10 cells, on both engines, while `last_error` is set and the
WARNING is logged. Root cause: `_admit_restored` (`base_interpreter.py:1211`)
calls `_report_invalid_event` from inside `from_snapshot`, **before** the
caller can attach a plugin (`use()` is only reachable on the returned
interpreter). The hook the CHANGELOG names as the reporting channel is
structurally unreachable for the events it was added for: **D11-security-4**.

### 2.8 Determinism + hash-seed (`n10_determinism_soak.py ab`)

50× identical traces per lane, each including a mid-run `scheduled_sends`
snapshot/restore:

```
A async/def    50x distinct traces=1  (init, GO, TICK) -> t.c
A async/async  50x distinct traces=1  (init, GO, TICK) -> t.c
A sync/def     50x distinct traces=1  (init, GO, TICK) -> t.c
B structure_hash stable over 50 rebuilds: True ['27214621ffcfd274']
    at PYTHONHASHSEED = <unset>, 0, 1, 12345 -- identical in all four
```

Fully deterministic across both engines, both kinds, and the hash seed.

### 2.9 Soak — 100 s, 200 machines, both kinds (`n10 ... c`)

```
C soak n=200 dur=100s cpu/wall=0.44 beats=602841 heartbeats_dead=0
C   external sent=12048 send_failures=0 delivered=12048 dropped=0
C   chaos snapshot/restore cycles=49 ss_restored=39 ss_empty=10 failures=0
C   interpreter.error={} last_error={}
```

200 machines (100 `def` / 100 `async def`) with `raise(delay=)` heartbeats at
10–50 ms, a continuous external **priority** producer, and a chaos
snapshot/stop/restore of a random machine every 2 s. **0 dropped external
events of 12 048**, **0 heartbeats dead** (every machine's beat counter
strictly increased over the second half), 49/49 chaos cycles clean, CPU at
44 % of one core, no error on any of the 200.

**Reduced from the requested 12 minutes to 100 s** to fit the ≤120 s
per-script bound; the shape and every assertion are as specified. Re-run with
`SOAK_S=700` in a session without that bound for the full 12-minute figure.

---

## 3. Defects filed this track

### D11-security-1 — the `#214` v2 upcast lets an attacker-written blob mint an engine event

**Severity (OMS): High.** Class: LIBRARY-DEFECT. New this round — introduced
by the `#214` fix. Repro: `n9_v2_upcast_minting.py`.
Source: `persistence.py:410-444` (`upcast`), `events.py:414`
(`trusted = record.get("engine") is True`).

Machine: `strict: True` + `onUnhandled: "error"` (our own hardened config),
`after: {86400000: ...}` — a 24-hour margin-call deadline. `machine_hash` is
**correct** in every vector (an attacker holding the chart computes it; it is
a fingerprint, not a MAC — the documented #185 boundary).

```
V1 v3 after, NO engine flag (control)        -> oms.holding  last_error=UnknownEventError  OK
V2 v3 after, engine:true (control, #195)     -> oms.margin_called breached=True
V3 v2 after, NO engine flag -> UPCAST MINTS  -> oms.margin_called breached=True  <- DEFECT
V4 v1 after (no kind)                        -> oms.holding  last_error=UnknownEventError  OK
V5 v2 done  -> onDone                        -> oms.settled                      <- DEFECT
V6 v2 error -> onError                       -> oms.failed                       <- DEFECT
V7 v2 after + minimum_version=3 (mitigation) -> REFUSED SnapshotVersionError      OK
V8 v0 (no version key at all)                -> oms.margin_called breached=True  <- DEFECT
```

**#195 closed exactly this vector at v3; #214 reopened it at v2.** `upcast`
sets `rec.setdefault("engine", True)` for every `done`/`error`/`after` record
in a payload declaring `version < 3`. The rationale ("a v2 writer had exactly
ONE minter of those records — the engine itself") is sound for blobs the
library wrote and **false for a blob an attacker wrote**, because the
attacker also chooses `version`. Writing `"version": 2` is a one-token
downgrade that converts inert user traffic into a trusted engine completion.
The v0 vector (`V8`) is worse still: no `version` key at all, same result.
A 24-hour deadline fires in 50 ms with `error=None` and `last_error=None`,
under `strict`.

This is strictly stronger than R10-01's snapshot half: R10-01 needs the
attacker to write `"engine": true` explicitly — a flag a reviewer can grep
for and a wrapper can strip. D11-security-1 needs the attacker to write
*nothing*, only to **omit** the flag and lower the version number.

**Mitigation that works today:** `from_snapshot(..., minimum_version=3)`
(V7). This should be the wrapper default. **Fix direction:** gate the upcast
on the same authenticated channel `#205`'s `expected_machine_hash` uses, or
do not upcast provenance at all — demote loudly (a warning + `last_error`) as
R10-05 asked, rather than silently promoting.

### D11-security-2 — `#216` does not cover nested (state-level) keys

**Severity (OMS): Medium.** Class: LIBRARY-DEFECT. Repro:
`n6_config_key_fuzz_216.py` §D. Source: `validation.py:315-361`
(`validate_top_level_keys` — iterates `config` only, never descends).

A state carrying `entrry`, `onn`, `afterr`, `unknownThing` builds clean under
`strict_config=True` with **no warning**: `D nested ... -> BUILT`, warning
text `<none>`, and `machine.get_state_by_id("k.a").on` is empty — the declared
`onn` handler silently vanished. For an OMS, a mistyped `onn` on a kill-switch
state is the same hazard `#216` was filed to close, and `strict_config=True`
reads as a promise it does not keep. `KNOWN_MACHINE_KEYS` already contains the
state-level names (`on`, `entry`, `exit`, `after`, `always`, `invoke`,
`onDone`), so the recursion is the only missing part.

**Wrapper constraint:** validate the full nested key set before
`create_machine`; `strict_config=True` alone is not sufficient.

### D11-security-3 — a chain trip reaches only `last_error`, and one benign event erases it

**Severity (OMS): Medium.** Class: LIBRARY-DEFECT. Extends R10-13 with a new
half (the *clearing*). Repro: `n8_last_error_clearing.py`, all three lanes:

```
SYNC/def     last_error@trip=RunawayChainError  error=None status=running  after ONE benign send()=None
ASYNC/def    last_error@trip=RunawayChainError  error=None status=running  after ONE benign send()=None
ASYNC/async  last_error@trip=RunawayChainError  error=None status=running  after ONE benign send()=None
HOOKS fired on a chain trip: ['on_action_execute','on_event_dropped','on_event_received','on_interpreter_start','on_transition']
```

`interpreter.error` stays `None`, `status` stays `"running"`, **no hook names
the trip** (`on_event_dropped` fires, but it fires on ordinary drops too and
carries no chain context), and the sole surface — `last_error` — is **cleared
by the next successful event**. A supervisor polling at any interval longer
than the event rate cannot observe that the machine discarded work. This
materially complicated this track's own harness: the first fuzz run reported
99 false violations purely because the pump cleared the flag between the trip
and the read.

**Fix direction:** either raise on `on_error` / set `interpreter.error`, or
add a monotonic `chain_trips` counter that nothing clears.

### D11-security-4 — `on_invalid_event` is unreachable on the restore path

**Severity (OMS): Low.** Class: LIBRARY-DEFECT. Repro:
`n11_restore_strict_214.py` — `on_invalid_event=[]` in all 10 cells.
Source: `base_interpreter.py:1211-1232` (`_admit_restored` →
`_report_invalid_event`), called from `from_snapshot`
(`base_interpreter.py:1908-1915`).

The `#214` CHANGELOG states a restore refusal "is reported
(`on_invalid_event`, `last_error`)". `last_error` and the WARNING are both
correct; the hook is not, because `_admit_restored` runs inside
`from_snapshot` — strictly before the caller can reach the constructed
interpreter to call `use(plugin)`. There is no ordering in which a plugin
observes a restore refusal. `from_snapshot` takes no `plugins=` argument.

### D11-security-5 — the priority lane is not honoured on restore on the sync engine

**Severity (OMS): Low.** Class: LIBRARY-DEFECT (documented-gap shape).
Repro: `n1_persistence_v3.py` §D (sync) vs `n2_rearm_lane_parity.py` (async).

Async restores `lane:"priority"` ahead of `lane:"inbox"`
(`['after.1000.l.w', 'EXT']`) — `#214` as specified. Sync restores in inbox
order (`['EXT', 'after.1000.l.w']`), because `SyncInterpreter` has one queue
by construction. The `lane` field is persisted on both and honoured on one.
Low because the sync engine has no lane semantics live either, so this is an
engine-parity documentation gap rather than a lost guarantee — but a restored
deadline that loses its precedence is worth naming.

### D11-security-6 — `SimulatedClock` does not fire restored `scheduled_sends` either

**Severity (OMS): Low.** Class: LIBRARY-DEFECT. **Extension of R10-12**, not a
new class. Under `SimulatedClock`, a 1000 ms `raise(delay=)` persists
correctly (`remaining_ms: 1000.0`), but after `clock.increment(2.0)` plus a
pump the machine is still in `h.a`. The requested "remaining delay honoured
exactly under `SimulatedClock`" property is therefore **untestable on this
build** — the real-clock property is verified instead (§2.1, 300/300).

---

## 4. Not covered / reduced this pass

- **Full 12-minute soak** — run at **100 s** (`SOAK_S=100`) to fit the ≤120 s
  per-script bound. Re-run `n10_determinism_soak.py c` with `SOAK_S=700`.
- **Livelock fuzz at ≥500 *configs*** — run at 180 configs × 3 lanes = **540
  cells**. The cell count meets the bar; the config count does not.
- **`SimulatedClock` remaining-delay property** — blocked by D11-security-6 /
  R10-12; only the real-clock property was provable.
- **Sync-engine v3 property at n=300** — the sync engine needs an external
  pump, so the property is structurally different; proved by construction
  (`n3_sync_pump.py`) rather than at scale.
- **Redaction / `__slots__` hostile-key fuzz** — not re-exercised (unchanged
  surface; no round-10 change touches it).
- **R10-01 fresh construction vectors** (`type(held)(...)`, `deepcopy`) — only
  the import-path and snapshot-flag vectors re-checked; `events.py`'s private
  classes are byte-identical in the round-10 diff.
- **D-security-2..5** (branch protection, mutable-tag Actions, no SBOM/
  signing, `except: pass`) — carried forward unverified (no `gh` writes).

---

## 5. Verdict

**Round 10's fix set is sound on four of five items and introduces one new
High.**

- `#212` (delayed self-send is a timer) — **correct and complete.** 200
  machines × 1 ms ping-pong × 10 s: zero trips, all alive. Zero-delay and
  *mixed* charts still trip. 540/540 fuzz cells agree. The reversal opened no
  hole; it closed a behaviour break. One operational ceiling found (~60 µs per
  beat, one core saturated from n=25 at 1 ms) — a constraint, not a defect.
- `#213` (v3 `scheduled_sends`) — **holds**, 300/300 on the async engine, with
  the remaining delay honoured and nothing firing early. Closes R10-04.
- `#215` (descent-settle) — **bounded**: 100 concurrent starts settle in
  0.02 s.
- `#216` (unknown keys) — **holds at the top level**, fails one level down
  (D11-security-2); the two "bypasses" that succeed (`x-`, `meta`) are the
  documented contract.
- `#214` (restore strict + upcast) — the `strict` half **holds** and closes
  R10-05(a). The **upcast half reopens #195**: `D11-security-1`, a High, is
  the answer to this round's headline question. *Yes* — a forged v2-shaped
  record mints an engine event and drives a 24-hour `after`, an `onDone` and
  an `onError`, under `strict` + `onUnhandled:"error"`, with a valid
  `machine_hash` and `last_error=None`.

**R10-01 remains the standing Blocker, unchanged**: the import-path
`_EngineDone` forgery still fires a forged `onDone` while the genuine service
runs. D11-security-1 is its restore-path sibling and is *easier* to reach.

**Gate impact.** Two wrapper constraints become mandatory before Phase 3
touches persistence: (1) `from_snapshot(..., minimum_version=3)` everywhere —
it is the only mitigation for D11-security-1 (verified, V7); (2) validate the
**full nested** config key set before `create_machine`, since
`strict_config=True` covers only the top level. Neither blocks adoption
beyond what R10-01 already does; both must be in the wrapper, not in review
guidance.
