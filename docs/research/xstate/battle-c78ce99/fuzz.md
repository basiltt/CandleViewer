# FUZZ — fuzzing & property-based battle test of `xstate-statemachine` @ `c78ce99`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit **`c78ce99`** ("Merge pull request #217 from basiltt/fix/0.8.1-round10").
`CHANGELOG.md` `[Unreleased] — targeting 0.8.1`. **`__version__` still reports
`0.8.0`; this build is identified by commit.**

**Date:** 2026-09-22. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`
with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. Every script run from the neutral
cwd `C:/Users/basil`.

**Track:** FUZZ, re-run of `battle-19cb1f1/fuzz.md` plus a new attack set aimed
at round 10's fixes (#212–#216). New scripts under
`docs/research/xstate/battle-c78ce99/fuzz/`; raw output under `fuzz/out/`.
No library source was modified. No `git` command was run in the adopting
project's repository. GitHub was read-only throughout.

**Standard applied.** This library is being evaluated to run an
order-management system handling real money. Every silent failure,
nondeterminism and ordering ambiguity is treated as a defect and reproduced
before it is counted. **Every service/action check was run with both `def`
and `async def` implementations.** Plateaus and hangs are polled to
convergence, never sampled at a fixed instant.

---

## 0. Bottom line

**Round 10 is the cleanest behavioural round this track has measured. #212's
semantic reversal is exactly right and verifies perfectly — 1000/1000 fuzzed
livelock cells agree with the new oracle, and a 60 s / 200-machine heartbeat
soak applied 992 600 of 992 600 external sends with zero loss and zero
runaway trips. #213's `scheduled_sends` is correct to the microsecond over
600 property-checked machines. But #214's upcast rule hands an attacker the
engine-mint boundary for free, and it does so by design: writing
`"version": 2` in a payload is easier than writing `"engine": true`, and it
needs no flag at all.**

- **NEW D11-fuzz-1 (Blocker) — #214's v2 upcast is a universal mint, and it
  is strictly easier to use than the forgery this track has reported for
  three rounds.** #214 upcasts any v2 `done`/`error`/`after` record as
  engine-minted, reasoning that "a v2 writer had exactly ONE minter — the
  engine itself". That is true of records the *library* wrote and false of
  records an *attacker* writes, because the version number lives in the same
  attacker-controlled blob. `p2_upcast_minting.py`: at v3 the trust boundary
  holds exactly as documented — an unflagged `done`/`after` record is
  **inert** on both kinds. Declare the identical blob `"version": 2` and both
  **DRIVE**: a 60 000 ms timer fires instantly (`['fa.armed'] → ['fa.expired']`)
  and a forged completion lands `{'filled': 999999}` through a real `onDone`
  while the genuine 30-second service is still running. Both engines, both
  kinds, 8/8 cells. `minimum_version=3` refuses it — but it is opt-in and
  defaults to `0`.

- **D10-fuzz-1 (Blocker) is STILL PRESENT, unchanged.**
  `n1_after_forgery.py` verbatim: still **4 of 5 `after` vectors forge**
  (`events.engine_after`, `type(held)(...)`, `pickle`, `engine:true` record);
  control V1 correctly `REFUSED:UnknownEventError`. Combined with
  D11-fuzz-1 the mint surface now has **five** independent doors, one of
  which needs no private name, no import and no flag.

- **NEW D11-fuzz-2 (High) — a `RunawayChainError` trip is erased from
  `last_error` by the next clock tick, so an inert machine reports healthy.**
  `p4_rule_matrix.py` §B, a chart that arms a 5 ms delayed `SLOW` and raises
  a zero-delay `FAST` in the same entry: the zero-delay half trips **40/40**
  runs (ERROR logged, machine permanently inert at `n=24`), but on **6/40
  (`def`) and 8/40 (`async def`)** runs `last_error` reads `None`,
  `last_transition_ok` reads `True` and `status` reads `'running'` — the
  delayed lane's next clock event resets the per-event error record. Polled
  to convergence over 12 s and 2 s later: the machines never move again.
  Only the log remembers. Every programmatic health check sees a healthy
  machine.

- **NEW D11-fuzz-3 (Medium) — #216 checks the ROOT config only, so a
  misspelled `after` on a state node is a deadline that never fires.**
  `p5_livelock_keys.py` §B3, under `strict_config=True`: `'afer'` for
  `'after'` is **ACCEPTED silently** and the timer never fires
  (`['nt.a']` vs `['nt.b']`); `'entyr'` for `'entry'` is accepted and the
  entry action runs **0** times instead of 1. The top-level check itself is
  flawless — 200/200 misspellings warned with a hint, 200/200 raised under
  `strict_config=True`, 0 silent. Nested *policy* misspellings are inert
  either way (policies are read from the root only) and are **not** counted
  as a defect here; the structural keys are the exposure.

- **NEW D11-fuzz-4 (Low) — `structure_hash` does not cover a
  `raise(delay=)` delay, though it covers `after` delays.**
  `p1_v3_roundtrip.py` §B: change `delay: 60000` to `delay: 100` and the
  hash is byte-identical (`9d405469b8afe69d`). A v3 snapshot carrying a
  60 000 ms armed send restores against the 100 ms chart and still waits the
  full 60 s. Asymmetric with `_node_shape`, which does include `after`.

- **NEW D11-fuzz-5 (Low) — neither half of #214's reporting claim survives a
  non-empty inbox.** The changelog says a refusal is "reported
  (`on_invalid_event`, `last_error`) and the event dropped". The drop is
  real and `last_error` is set — but the hook fires *inside*
  `from_snapshot()`, which has no `plugins=` parameter, so no caller can
  attach a plugin in time (0 hooks observed, both kinds); and `last_error`
  resets per processed event, so one legitimate neighbouring record erases
  it (`UnknownEventError` → `None`, both kinds).

- **#212 verifies perfectly — the headline reversal is real and exact.**
  `p4_rule_matrix.py` §A, 16 cells: zero-delay and `delay: 0` trip at
  `maxIterations`; `delay: 1ms`, `delay: 30ms`, a delayed raise armed by an
  external send, and `after: 1` / `after: 30` all run indefinitely with
  **identical beat counts** (65 vs 65, 31 vs 31) — `raise(delay=)` and
  `after` are now the same rule to the beat. A cancelled armed send fires
  **0** times. `p5` §A: **1000/1000** fuzzed cells unanimous — 930 legal
  periodic rings never tripped and never stopped beating, 70 must-trip rings
  all tripped.

- **#213 verifies clean to the microsecond.** `p1_v3_roundtrip.py`: **600
  machines** (300 × 2 kinds) with 1–3 armed sends at random remaining
  delays on a `SimulatedClock` — **0 defects**. Every armed send is
  recorded, every cancelled one leaves no record, `remaining_ms` is exact to
  1e-6 ms, and every restored send fires at exactly its remaining delay.
  `p3` §D: 200 concurrent v3 restores, **200/200** fired.

- **#215 verifies clean.** `p3` §C: 100 concurrent `start()`s on an
  `always`-cycle chart complete in **0.05 s**, 100/100 tripped — no
  descent-settle stall. `n6_shrunk_repros.py` re-run: lap parity
  **0/25 mismatches**, down from 24/25.

- **R10-06 (D10-fuzz-2, Medium) is FIXED.** The `always` + zero-delay
  `raise` shape that disagreed at 24 of 25 limits now agrees at **every**
  limit 1–25 on both engines, gap no longer grows.

- **Determinism is total.** 50 identical `SimulatedClock` runs including
  `scheduled_sends` records and a restore-and-continue leg collapse to **1
  distinct trace** per engine/kind cell; the `PYTHONHASHSEED` sweep is **1
  distinct result** over 5 seeds.

- **The pattern, fourth round running.** The behavioural engineering is
  excellent and it stays fixed. The *trust claims* are the liability: #214
  reasoned about who could write a record from what the library does, not
  from what an attacker can, and shipped a mint that needs no flag.

---

## 1. Prior-defect table (round 9 → round 10)

| Prior defect | Verdict at `c78ce99` | Evidence |
|---|---|---|
| `D10-fuzz-1` / `R10-01` — `after` provenance forgeable (Blocker) | **STILL PRESENT, unchanged** | `n1_after_forgery.py` verbatim: 4/5 vectors forge (V2 import path, V3 `type(held)(...)`, V4 pickle, V5 `engine:true` record); V1 correctly `REFUSED:UnknownEventError`. `out/rerun_n1_after_forgery.txt` |
| `D9-fuzz-1` / `R9-01` — completion forgery (Blocker, carry-forward) | **STILL PRESENT**, and **WIDENED** by D11-fuzz-1 | `p2_upcast_minting.py` §A/B: the v2-upcast door mints completions with no flag at all |
| `D10-fuzz-2` / `R10-06` — lap parity false on `always`+`raise0` (Medium) | **FIXED** | `n6_shrunk_repros.py` §D2 re-run: **0/25** mismatches at limits 1–25 (was 24/25, gap growing to 53 vs 78). `out/rerun_n6_shrunk_repros.txt` |
| `R9-15` / `D9-fuzz-5` — `SnapshotMidStepError` reports `child=False` (Low) | **NOT RE-MEASURED** this pass (observability track owns `r14`); out of this track's new scope |
| #204 `statesToInvoke` | **STILL CLEAN** | `n2_states_to_invoke.py`: **0 failing cells / 10** |
| #207 stranded storm | **STILL CLEAN** | `n4` §C/D: 200/200 tripped, hook hist `{1: 200}`, ids `('st.starting','fill')` 200/200, stable order `dropped → stranded`, both kinds |
| #208 empty-configuration receipt | **STILL CLEAN** | `n5` B1/B2 both **0**; `n5` §D1 |
| #203/#186/#198 snapshot asymmetry | **STILL CLEAN** | `n3_persist_arming.py`: **0 defects**, mid-step snapshot `REFUSED:SnapshotMidStepError` on both kinds |
| #206 "delayed self-send is a chain" assertions | **SUPERSEDED by #212 — not a FAIL** | `n4` §A/B and `n5` §P1 now report "defects" only because they encode the OLD rule; see §2 |
| Determinism + soak (`n7`) | **STILL CLEAN** | 1 distinct trace × 50 runs per cell; 45 s soak 714 300/714 300 applied, **0 lost**, 0 dormant-without-hook |

### 1.1 The SUPERSEDED entries, stated exactly

Two prior scripts assert the #206 rule that #212 reversed. Their failures
this round are **expected reversals, not regressions**:

- **`n4_concurrency_stranded.py` §A/B — 6 reported "defects", all
  SUPERSEDED.** The script requires 100 concurrent 1 ms `raise(delay=)`
  ping-pongs to trip at `maxIterations` ≈ 12. They now trip **0/100** and
  run to lap 536–587 in 4.5 s with `errs={None: 100}`. Under #212 this is
  the *correct* outcome.
  **New assertion added** (`p3_concurrency.py` §A): 200 machines × 1 ms
  ping-pong × 10 s → **0 RunawayChainError, 200/200 still beating**, beat
  count 836 vs a clock ceiling of 10 020 (i.e. paced by the period, not
  spinning), CPU 100 % of *one* core for 200 machines on both kinds.
- **`n5_livelock_receipt_fuzz.py` §P1 — 38 reported "non-settling engine-work
  -only" cells, all SUPERSEDED.** Every one of the 38 carries a
  `raisedelay` shape (`['other','raisedelay']` in all samples); under #212
  they are timer-paced, so "engine work only" no longer describes them.
  P3's `def`-lane parity mismatch count for genuinely engine-work-only
  charts is **0**, unchanged.
  **New assertion added** (`p5_livelock_keys.py` §A): the rewritten oracle
  below.

---

## 2. New attacks

Scripts are standalone (stdlib + `xstate_statemachine` only) and run from
`C:/Users/basil`.

### 2.1 `p1_v3_roundtrip.py` — v3 round-trip property (#213)

300 random machines × 2 service kinds, each arming 1–3 delayed self-sends at
delays drawn from {1, 5, 17, 50, 250, 1000, 60000} ms, a random sub-set
cancelled in the same entry, all on a `SimulatedClock` so timing is exact.
Properties R1 (every armed send recorded), R2 (cancelled → no record), R3
(`remaining_ms` exact to 1e-6 ms), R4 (restored send fires at exactly its
remaining delay, measured from the action's own `clock.now()` stamp), R5
(round-trip is a fixpoint, `version == 3`, hash stable).

**Result: 600/600 machines, 0 defects.** Part B found D11-fuzz-4.

> ⚠️ Harness note worth recording: `SimulatedClock.increment()` returns a
> `_MustAwait` wrapper inside a running loop, **not** a bare coroutine, so
> `if asyncio.iscoroutine(r): await r` silently discards the advance. The
> first draft of this script reported 77 false defects for that reason. Any
> adopter driving a simulated clock in tests must `await` anything
> awaitable, not anything `iscoroutine`.

### 2.2 `p2_upcast_minting.py` — #214 restore-strict, v2 upcast, minting

§A/B the 8-cell upcast matrix (`done`/`after` × v1/v2/v3 × flagged/unflagged)
× 2 kinds; §C restore-strict reporting; §D lane ordering.
**§D is clean** (`['PRIO','INBOX']`, both kinds). §A/B and §C produced
D11-fuzz-1 and D11-fuzz-5.

### 2.3 `p3_concurrency.py` — concurrency under #212/#213/#215

§A 200 × 1 ms ping-pong × 10 s; §B mixed delayed+zero-delay chain, polled to
convergence; §C 100 concurrent `start()`s with an `always` cycle under a 25 s
watchdog; §D 200 concurrent v3 restores. **§A, §C, §D clean on both kinds.**
§B surfaced the observability defect pinned properly in `p4`.

### 2.4 `p4_rule_matrix.py` — the #212 rule matrix and trip observability

§A 8 shapes × 2 kinds against the `after` rule; §B 40 trials × 2 kinds of the
mixed chart. **§A: 16/16 cells correct.** §B produced D11-fuzz-2.

### 2.5 `p5_livelock_keys.py` — livelock fuzzer (new oracle) + #216

§A **500 configs × 2 kinds = 1000 cells in 98 s.** The oracle was rewritten
for #212 and then corrected once during this pass: a ring trips iff some run
of *consecutive* zero-delay edges reaches `maxIterations` — a delayed or
`after` edge ends the chain, and the zero-delay edges after it are chained
work within one step. (The first version charged any ring containing a
zero-delay edge, which mis-flagged 8 legitimate trips as false positives at
`maxIterations=3`; the corrected oracle is unanimous.) **930 legal / 70
must-trip, 0 disagreements.**
§B 200 misspellings at top and nested level; §B2 the `x-` bypass surface;
§B3 structural keys. Produced D11-fuzz-3.

### 2.6 `p6_determinism_soak.py` — determinism, hash seed, 60 s soak

§A 50 runs × 2 engines × 2 kinds on a `SimulatedClock`, trace including
`scheduled_sends` and a restore-and-continue leg → **1 distinct trace per
cell**. §B 5 `PYTHONHASHSEED` values → **1 distinct result**. §C 200 machines
(both kinds interleaved), `raise(delay=)` heartbeats at 10/20/35/50 ms, an
external priority producer, and chaos v3 snapshot+restore every 2 s:

```
elapsed=60.0s cpu=59.8s (100% of one core)
ext_sent=992600 ext_applied=992600 lost=0
beats min=942 max=3239 still_beating=200/200 runaway=0
chaos={'ok': 580, 'refused': 0, 'restored': 580, 'sched_missing': 0}
```

**0 defects.**

> ⚠️ Oracle note: an intermediate version of §C counted "snapshot with no
> `scheduled_sends`" as a lost timer and reported 28 hits. Reproduced and
> refuted: those snapshots were taken in the instant *after* the send fired
> and *before* it was consumed, so the beat sits in `pending_events` with
> `lane: "priority"`. 6/400 such snapshots were restored and **0** were
> parked — all resumed beating. The oracle now accounts a heartbeat as
> present if it is either armed or queued, and the defect count is 0.

---

## 3. Defects

### D11-fuzz-1 — the v2 upcast mints engine events from an unflagged blob

**Severity (OMS): Blocker.** Class: **SECURITY / trust boundary.**
**Repro:** `battle-c78ce99/fuzz/p2_upcast_minting.py` §A/B
(`out/p2.txt`). **Source:** `persistence.py:426–443` (`upcast`, the
`version < 3` branch) feeding `events.py:421` (`trusted = record.get("engine")
is True`).

The `version < 3` branch sets `rec.setdefault("engine", True)` on every
`done`/`error`/`after` record. The gate it feeds is the same one #195 and
#203 use to decide whether an event may drive `onDone` and `after`. Because
`version` is a field of the payload being validated, a blob selects its own
upcast path — the exact "payload cannot select its own level of checking"
property #205 was written to establish, reintroduced one layout version
later.

Observed, both engines and both service kinds (8/8 cells):

| record | declared version | `engine` flag | result |
|---|---|---|---|
| `after.60000.fa.armed` | 3 | `true` | DROVE (correct) |
| `after.60000.fa.armed` | 3 | *absent* | inert (correct) |
| **`after.60000.fa.armed`** | **2** | ***absent*** | **DROVE — 60 s timer fires instantly, `['fa.armed'] → ['fa.expired']`** |
| `after.60000.fa.armed` | 1 | *absent* | inert (correct) |
| `done.invoke.job` | 3 | `true` | DROVE (correct) |
| `done.invoke.job` | 3 | *absent* | inert (correct) |
| **`done.invoke.job`** | **2** | ***absent*** | **DROVE — `ctx.fill={'filled': 999999}` via a real `onDone`, genuine 30 s service still running** |
| `done.invoke.job` | 1 | *absent* | inert (correct) |

For an OMS: an order that expires on a forged tick, and a fill booked for a
trade that never happened. `from_snapshot(..., minimum_version=3)` refuses
the payload (`SnapshotVersionError`) — but it defaults to `0`, so every
caller who has not read #205 closely is exposed. **CV constraint: pass
`minimum_version=3` on every restore, unconditionally.**

### D11-fuzz-2 — a runaway trip is erased from `last_error` by the next tick

**Severity (OMS): High.** Class: **SILENT FAILURE / observability.**
**Repro:** `battle-c78ce99/fuzz/p4_rule_matrix.py` §B (`out/p4.txt`); first
surfaced by `p3_concurrency.py` §B. **Source:** `base_interpreter.py:4165–4174`
(`last_error` is `None if self.last_transition_ok else ...`, reset per
processed event).

Chart: one entry arms a 5 ms delayed `SLOW` **and** raises a zero-delay
`FAST`. The `FAST` cycle is work within a step, so `maxIterations` correctly
trips it — **40/40 runs, both kinds**, ERROR logged
(`🛑 Exceeded 10 chained self-raised events on 'mx'`). The machine is then
permanently inert at `n=24`, confirmed by polling to convergence over 12 s
and re-checking 2 s later.

But the 5 ms timer keeps delivering clock events, and each one resets the
per-event error record. On **6/40 (`def`)** and **8/40 (`async def`)** runs
the post-mortem state is:

```
n=24  status='running'  last_transition_ok=True  last_error=None
pending_events=0  scheduled_sends=0
```

A dead machine that answers every health-check question with "healthy". The
race is in the ordering of the trip and the next tick, so it is intermittent
— which is worse, not better, for an OMS: the same chart passes staging and
goes quiet in production. `has_dormant_invocations` does not cover it (no
invoke involved). Only the log remembers.

### D11-fuzz-3 — #216 validates the root config only

**Severity (OMS): Medium.** Class: **SILENT FAILURE.**
**Repro:** `battle-c78ce99/fuzz/p5_livelock_keys.py` §B3 (`out/p5.txt`).
**Source:** `validation.py:337` — the unknown-key comprehension runs over the
root `config` only.

Under **`strict_config=True`**, on a state node:

| key | accepted? | consequence |
|---|---|---|
| `entry` | yes | action runs 1× (correct) |
| **`entyr`** | **yes, silently** | **action runs 0×** |
| `after` | yes | `['nt.b']` — timer fires (correct) |
| **`afer`** | **yes, silently** | **`['nt.a']` — timer NEVER fires** |

A chart that reads as though it has a deadline has none. For an OMS, an
order timeout that never expires. The top-level check is excellent by
contrast — **200/200 warned with a "did you mean" hint, 0 silent, 200/200
raised under `strict_config=True`** — which is precisely what makes the gap
dangerous: a team that adopts `strict_config=True` will reasonably believe
their config is validated.

Nested *policy* misspellings (200/200 silent) are **not** counted: policies
are read from the root config only (`models.py:1590–1610`), so a policy key
on a state node is inert whether spelled correctly or not.

§B2 bypass surface, all under `strict_config=True`: `x-anything`,
`x-maxIterations`, `x-` (empty suffix) accepted; `X-upper`, `x`, `_private`
refused. `x-maxIterations` accepted is by design but is worth stating: the
`x-` prefix is a deliberate escape hatch, so a key one character away from a
policy can be waved through.

### D11-fuzz-4 — `structure_hash` omits `raise(delay=)` delays

**Severity (OMS): Low.** Class: **DRIFT-DETECTION GAP.**
**Repro:** `battle-c78ce99/fuzz/p1_v3_roundtrip.py` §B (`out/p1.txt`).
**Source:** `persistence.py:_node_shape` — includes `"after": sorted(...)`
and excludes action params.

`delay: 60000` → `delay: 100` in a `raise` action leaves the hash at
`9d405469b8afe69d`. A v3 snapshot carrying a 60 000 ms armed send restores
against the 100 ms chart without complaint and still waits the full 60 s:
the *persisted* deadline wins over the *declared* one, silently. The
exclusion is defensible in general (action params are excluded on purpose)
but is asymmetric with `after`, whose delays *are* hashed — and #213 has now
made a `raise` delay persistent state, which is exactly the drift a
fingerprint exists to catch.

### D11-fuzz-5 — neither half of #214's reporting claim is usable

**Severity (OMS): Low.** Class: **DOC-DEFECT / observability.**
**Repro:** `battle-c78ce99/fuzz/p2_upcast_minting.py` §C (`out/p2.txt`).
**Source:** `base_interpreter.py:1211–1232` (`_admit_restored`) called from
`from_snapshot` at `:1912`.

The changelog: "A refusal is reported (`on_invalid_event`, `last_error`) and
the event dropped."

- The **drop** is real (`pending_events == []`, both kinds). ✅
- **`on_invalid_event`: 0 hooks observed**, both kinds. The hook fires inside
  `from_snapshot()`, which takes no `plugins=` parameter; `use()` exists only
  on the object `from_snapshot` returns. The library's own pin
  (`test_round10_findings.py:305–313`) constructs `_Invalid()`, calls
  `r.use(plug)` **after** the restore, and then asserts only on `last_error`
  — never on `plug.seen`. The hook half is untested and unreachable.
- **`last_error` survives only an empty inbox.** With one legitimate
  neighbouring record it reads `UnknownEventError` at restore and **`None`**
  after `start()`, both kinds — a restore that silently dropped traffic
  becomes indistinguishable from a clean one. Same root cause as D11-fuzz-2.

---

## 4. Not covered

- **`r14_observability.py` §C** (`SnapshotMidStepError` reports
  `child=False`, `R9-15`) was not re-measured; it belongs to the
  observability track and is outside this round's new attack scope. Its
  round-9 verdict (STILL PRESENT, Low, diagnostic quality only) is carried
  forward unverified.
- **Redaction** and **forged `lane` field** were listed in the brief.
  `lane` was covered only positively (§D, correct `priority` ordering); a
  forged `lane` on an otherwise-valid record was not attacked separately
  because D11-fuzz-1 already grants the stronger primitive (arbitrary
  engine mint), which subsumes lane elevation. Redaction was not reached.
- **12-minute soak** was run at **60 s** to stay inside the 20-minute
  wall-clock bound; 200 machines, both kinds, full chaos schedule. The
  shorter window is stated rather than extrapolated. A 45 s independent
  soak (`n7` re-run) agrees: 714 300/714 300 applied, 0 lost.
- **Sync-engine `after`-lane cells**: `SyncInterpreter` never fires timers
  without a caller tick, and `SyncInterpreter` + `async def` raises
  `NotSupportedError` by design. Both are documented exclusions, counted as
  such throughout, not as defects.
- **`p5` §A ran 1000 cells** (500 configs × 2 kinds) on the async engine
  with a sync probe available; a full 500 × 2 × 2 engine cross-product was
  not run inside the time bound.

---

## 5. Verdict

**Round 10's behavioural work is correct and this track can confirm it
without qualification: #212, #213 and #215 all verify clean under
adversarial load, on both engines and both service kinds, and #216's
top-level check is flawless. The livelock oracle was rewritten to the new
rule and 1000/1000 cells agree with it. Determinism is total. A 200-machine
heartbeat soak lost nothing.**

**But the adoption gate must not move on the strength of that, because
#214 shipped a new Blocker while closing an old one.** The v2 upcast is a
mint that requires no flag, no private name and no import — strictly easier
than the four `after` vectors (D10-fuzz-1) that have been open since round
9, which remain open and unchanged. The engine-mint boundary now has five
independent doors.

**Recommendation for the adopting project: HOLD row 8 at ADOPT-with-
constraints; do not relax it, and add these constraints.**

- **CV-C49 (from D11-fuzz-1).** Every `from_snapshot` call site must pass
  `minimum_version=3` **and** `expected_machine_hash=<value held by the
  caller>`. Treat a snapshot as untrusted input regardless of storage.
- **CV-C50 (from D11-fuzz-2).** Never use `last_error` / `status` /
  `last_transition_ok` as a liveness signal on a chart that mixes a delayed
  self-send with zero-delay work. Liveness must be a monotonic heartbeat
  counter the application owns, checked for *movement*, not a library flag.
- **CV-C51 (from D11-fuzz-3).** `strict_config=True` is necessary but not
  sufficient. Add a project-side validator that walks every state node
  against the known structural key set before `create_machine`.
- **CV-C52 (from D11-fuzz-4).** If a `raise(delay=)` delay is ever edited,
  invalidate stored snapshots explicitly — `structure_hash` will not.

**Phase 3 may continue** — every constraint above is a call-site discipline
the adopting project controls, and the engine behaviour underneath them is
sound. **The blocker on exposing any snapshot to a trust boundary the
project does not fully control stands, and is now firmer than it was at
`19cb1f1`.**
