# Round-11 Regression Sweep — `main` @ `c78ce99` (unreleased 0.8.1)

Library: `xstate-statemachine`, `main` @ `c78ce99` ("Merge PR #217 —
round-10 fixes #212–#216"). `__version__` still reports `0.8.0`; keyed on
commit throughout, per the environment note.

Baselines diffed against:
- `gate/result-main-19cb1f1.json` (round-10 recorded gate baseline)
- `gate/tmp_regrun/results.json` (round-10 broad sweep, 238 scripts)
- `59-r10-final-readiness-verdict.md` §2

## Headline

**NO TRUE REGRESSION.** Across the full gate (163 checks) and a
527-script sweep, exactly **one** stable, reproducible PASS→FAIL delta
exists, and it is **category (b) SUPERSEDED-BY-#212** — our own test
encoding the old #206 rule that #212 deliberately reversed.

**No previously-bounded shape became unbounded** as collateral of the
#212 rule change. Verified explicitly with watchdogs on both the `def`
and `async def` lanes (§4).

## 1. Method

1. `gate/run_gate.py --timeout 120 --json gate/result-main-c78ce99.json`
   → exit 0. Diffed every `(kind, id)` against `result-main-19cb1f1.json`.
2. Built `gate/r11_scriptlist.txt` (527 scripts) covering every directory
   named in the task: `issues/verify-*/`, `issues/verify-main-c78ce99/`,
   `issues/new-0.8.0/repro/`, `issues/new-main/repro/`,
   `issues/post-*/new/repro/`, `probes/*.py`, `probes/main-*/*.py`.
   Excluded `refute/` and `__pycache__`. 120 s cap each.
3. Ran them via `gate/run_r11_regression.py` (new; resumable, 6 workers)
   from **neutral cwd `<home>`** → `gate/r11_regression_raw.json`.
   Result: **444 PASS / 83 FAIL / 0 TIMEOUT**, 182 s.
4. The round-10 sweep baseline covers only 238 of these 527 scripts. For
   the 45 failures with no baseline entry, I **re-ran each against a
   `19cb1f1` git worktree** (`PYTHONPATH` override, same venv) to
   separate pre-existing from new → `gate/r11_newfail_at_19cb1f1.json`.
5. Flaky ×5, **run serially**, on every candidate delta.
6. Wrote and ran a purpose-built collateral-unboundedness probe (§4).

### Methodological correction worth recording

The 6-worker parallel sweep produced **four false FAILs** that pass
5/5 when run serially (`107`, `154`, `158` at the classification stage;
`167`). These scripts poll wall-clock deadlines and are sensitive to CPU
contention. **Every delta in this report was confirmed serially.** The
round-10 baseline was produced by a *serial* driver, so a naive
parallel-vs-serial diff overstates regressions; future rounds should run
timing-sensitive scripts serially or raise their polling budgets.

## 2. Gate diff — `19cb1f1` → `c78ce99`

| | 19cb1f1 | c78ce99 |
|---|---|---|
| PASS | 117 | 124 |
| FAIL | 38 | 39 |
| total | 155 | 163 |

**Every single delta is the `verifyM7` set appearing for the first
time.** No pre-existing `verify` / `verifyM`–`verifyM6` / `repro` /
`probe` id changed status — the pre-existing FAIL set is bit-identical
to the round-10 baseline (LC-01, LC-12, LC-26, LC-48, LC-57; LC-01,
LC-07, N-1, N-3, N-8; 150/154/157/158; the 21 informational `repro`
FAILs; PROBE-01 16/20 and PROBE-03 13/17 on the *same* cells).

| kind / id | 19cb1f1 | c78ce99 | Verdict |
|---|---|---|---|
| `verifyM7` / 203, 204, 205, 207, 208, 209, 210 | MISSING | **PASS** | Round-9 pins, now wired into the gate. Clean. |
| `verifyM7` / **206** | MISSING | **FAIL** ×5/5 | **(b) SUPERSEDED-BY-#212.** See §3. |

The round-10 report recommended wiring `verify-main-19cb1f1` in as
`verifyM7`; that has happened, which is why these eight rows are new.

## 3. The one true delta: `206` — SUPERSEDED-BY-#212

### Category (b) — scripts asserting the reversed #206 rule

Exactly **one** script in the whole corpus asserts the old rule *and*
regressed as a result:

| Script | Status | Why |
|---|---|---|
| `issues/verify-main-19cb1f1/206_delayed_selfsend_charged.py` | PASS @19cb1f1 → **FAIL ×5/5 @c78ce99** | Asserts a 1 ms `raise(delay=)` ping-pong trips `RunawayChainError`. #212 makes that legal by design. |

Its observed failure:

```
== Criterion 1: delayed self-send cycle is bounded (trips RunawayChainError) ==
  ticks=506 last_error=NoneType dropped_reasons=[]
FAIL: 206-c1-runaway-error  -- last_error is NoneType, expected RunawayChainError
FAIL: 206-c1-dropped-reason -- no 'chain_budget' drop observed: []
FAIL: 206-c1-unbounded      -- ticks=506 suggests unbounded spin
== Criterion 2 ==
  immediate cycle ticks-at-trip=21, delayed cycle ticks-at-trip=506
FAIL: 206-c2-parity -- lap counts diverge: immediate=21 delayed=506
== Criterion 3 ==
  ok: external delayed sends remain unshielded (#192 preserved)
```

This is **exactly and only** the behaviour #212 specifies. Note the
script's *own criterion 2* records the zero-delay cycle still tripping at
21 laps — the `maxIterations`-bounded path is untouched. The 506 ticks
over an 8 s watchdog is ≈63/s ≈ 16 ms per lap: **Windows timer
granularity, not a spin** (confirmed at 1 % CPU in §4). Criterion 3
still passes, so #192 is preserved.

**Verdict: not a defect. `206_delayed_selfsend_charged.py` is a stale
pin encoding a deliberately-reversed rule and must be retired**, exactly
as the CHANGELOG's own #206 entry says ("superseded by #212 in round
10"). Its replacement already exists and passes:
`issues/verify-main-c78ce99/212_selfsend_timer.py`.

### Related scripts that assert the old rule but do NOT regress

These were already FAILing at `19cb1f1` (pre-existing), so they are not
deltas, but they encode the superseded rule and should be retired or
rewritten in the same pass:

- `issues/post-f28719c/new/repro/R9-06_delayed_selfsend_unbounded.py`
- `probes/main-f28719c/p3_delayed_selfsend_unbounded.py`

Both are the round-9 *reporter-side* repros: they assert the delayed
self-send is unbounded and call that a defect. Under #212 the
unboundedness is the intended contract, so they now describe correct
behaviour with an inverted verdict.

### Category (c) — hand-built v1/v2 snapshot fixtures: NONE regressed

`154_sync-restore-clock-attach.py`, `158_non_str_event_type_restore.py`
and `R5-17_non-str-event-type-via-restore.py` hand-build v1/v2 blobs and
now raise `SnapshotDriftError` ("declares version N but carries no
`machine_hash`"). I confirmed by worktree that **all three fail
identically at `19cb1f1`** — the cause is #185/#205 hash checking from an
earlier round, not the v3 layout. Pre-existing, not a round-11 delta.

The v3 layout itself is clean: `213_snapshot_v3.py` and
`214_restore_strict_upcast.py` both PASS, including v2→v3 upcast of
engine-minted `done`/`error`/`after` records.

### Category (d) — other

No delta in this category. The two remaining non-baseline candidates
resolved as harness artifacts:

| Script | Resolution |
|---|---|
| `issues/verify-main-6db65d8/167_rollback_reinvoke_spin.py` | **Not a regression.** FAILed once under 6-way parallelism; **5/5 PASS serially**, all cells PASS (`bounded=True chain_budget=True`, 1003 calls plateaued, `RunawayChainError.stranded` naming invoke `['s']` per #207). |
| `107`, `154`, `158` | Confirmed identical FAIL at `19cb1f1` — pre-existing. `107` fails on `[e.type for e in i._priority_queue]`; the queue has held `(event, bool)` tuples since round-8 `061d619`, well before this round. Stale probe reaching into a private attribute. |

The other 43 non-baseline failures all reproduce at `19cb1f1` — the
long-standing "fixed but opt-in" / stale-repro triage set, unchanged.

## 4. Collateral unboundedness — explicitly cleared

The task's central risk: did #212 make any previously-bounded shape
unbounded? Probe:
`probes/main-c78ce99/r11_collateral_unbounded.py` (standalone, stdlib +
library only, neutral cwd, watchdogged, **both lanes**).

```
--- lane: def ---
  ok  S1 zero-delay-raise      n=21  err=RunawayChainError dropped=1  wall=0.05
  ok  S3 always-cycle          n=20  err=RunawayChainError dropped=0  wall=0.56
  ok  S6 delay=1ms             n=195 rate=65/s  cpu_frac=0.01
  ok  S6 delay=20ms            n=95  rate=32/s  cpu_frac=0.00
  ok  S6 rate scales with delay  rate(1ms)=65/s  rate(20ms)=32/s
--- lane: async def ---
  ok  S1 zero-delay-raise      n=21  err=RunawayChainError dropped=1  wall=0.06
  ok  S3 always-cycle          n=20  err=RunawayChainError dropped=0  wall=0.57
  ok  S6 delay=1ms             n=195 rate=64/s  cpu_frac=0.01
  ok  S6 delay=20ms            n=97  rate=32/s  cpu_frac=0.01
  ok  S6 rate scales with delay  rate(1ms)=64/s  rate(20ms)=32/s

VERDICT: ALL BOUNDED AS EXPECTED
```

Findings:

- **Zero-delay `raise` self-cycle: still bounded**, trips
  `RunawayChainError` at 21 ticks (`maxIterations`=20) on both lanes.
- **`always` self-cycle: still bounded**, trips at 20 on both lanes.
- **`rollback + onDone` re-arm storm: still bounded** — covered by `167`
  (1003 calls, plateaued, `chain_budget` drop, stranded-invoke naming)
  and `verifyM4/M5` `167`, all PASS serially.
- **Invoke ping-pong: still bounded** — `verifyM7/207` PASS.
- **Delayed ping-pong is unbounded *by design*, and is genuinely
  timer-paced, not a spin.** The decisive evidence is
  `cpu_frac ≈ 0.01`: the process is idle ~99 % of the wall clock, and
  the tick rate halves (65/s → 32/s) when the period grows 1 ms → 20 ms.
  A runaway chain would show `cpu_frac ≈ 1.0` and a flat, delay-
  independent rate. This is precisely the "legal periodic process"
  #212 intends, and behaves as `after:` has always behaved.

The round-6/7/8/9 livelock repros were re-run as part of the 527-script
sweep with the 120 s cap; none timed out, and none changed status for a
reason other than those triaged above.

## 5. Round-11 pins (#212–#216) verified

All six scripts in `issues/verify-main-c78ce99/` PASS:

```
212_selfsend_timer.py                    ok (bounded alike) (0/6 cells cut)
213_snapshot_v3.py                       ok (0/2 kinds)
214_restore_strict_upcast.py             ok (0/2 symptoms)
215_lap_parity_sweep.py                  ok (0/7 swept limits differ)
215_216_lap_parity_and_unknown_keys.py   ALL PASS
216_unknown_config_keys.py               PASS: all #216 criteria verified
```

`212` confirms a `raise(delay=)` heartbeat and an equivalent `after`
heartbeat now run alike and uncut across 6 cells (both lanes, 250 ms
periods) — the reversal is implemented symmetrically, which is the real
content of #212.

Note `issues/post-19cb1f1/new/repro/R10-07_unknown_config_keys_accepted_silently.py`
FAILs — correctly. It is the round-10 *reporter* repro asserting unknown
keys are swallowed; #216 fixed that, so the repro now fails as a fixed
defect should. Pre-existing at `19cb1f1` (where it legitimately
reproduced). Informational.

## 6. Recommended follow-ups (no edits made — read-only mandate)

1. **Retire `issues/verify-main-19cb1f1/206_delayed_selfsend_charged.py`**;
   `verify-main-c78ce99/212_selfsend_timer.py` supersedes it. Until it is
   retired the gate will carry one permanent, meaningless blocking FAIL.
2. Retire/invert `R9-06_delayed_selfsend_unbounded.py` and
   `p3_delayed_selfsend_unbounded.py` (same superseded rule).
3. Retire `201_lap_parity_stated_exactly.py` in favour of
   `209_lap_parity_sweep_1_25.py` / `215_lap_parity_sweep.py` — carried
   over from round 10, still unactioned.
4. Rewrite `107_priority-lane-persisted.py` to stop unpacking
   `_priority_queue` elements as bare events (they are `(event, bool)`
   since round-8) and to use the #214 public `lane` field.
5. Wire `issues/verify-main-c78ce99/` into `run_gate.py` as `verifyM8`
   and record `c78ce99` as a baseline commit.
6. Run timing-sensitive scripts serially in the sweep driver (§1).

## 7. Verdict

**No true regression from `19cb1f1` to `c78ce99`.** The sole stable
PASS→FAIL is `206`, which is **(b) SUPERSEDED-BY-#212** — our test
encoding a rule the library intentionally reversed, with a passing
replacement already in place. The #212 reversal is implemented
symmetrically with `after`, and introduced **no collateral
unboundedness**: every zero-delay `raise`, self-`send`, `always`,
`rollback + onDone` and invoke-ping-pong shape remains bounded on both
lanes. Snapshot layout v3 round-trips and upcasts v2 cleanly.

The row-8 **ADOPT** verdict of `59-r10-final-readiness-verdict.md` and
constraints **CV-C01..C48** carry forward unchanged; nothing here
warrants revisiting Phase-3.

### Artefacts

- `gate/result-main-c78ce99.json` — full gate, exit 0
- `gate/r11_scriptlist.txt` — 527 scripts swept
- `gate/run_r11_regression.py` — resumable parallel driver
- `gate/r11_regression_raw.json` — per-script status + failure tails
- `gate/r11_newfail_at_19cb1f1.json` — 45 non-baseline failures re-run at `19cb1f1`
- `probes/main-c78ce99/r11_collateral_unbounded.py` — collateral probe
