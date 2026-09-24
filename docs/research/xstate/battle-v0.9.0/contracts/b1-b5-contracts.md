# B1–B5 contract machines end-to-end on v0.9.0

**Library:** `xstate-statemachine` @ `main` = `e3a1f22`; tag `v0.9.0` = `91bd979`.
`git diff v0.9.0..HEAD --stat` = `.github/workflows/publish.yml | 15 +++++-` only
(1 file, CI publish-smoke-test) — **the ENVIRONMENT claim is verified**: main is
CI-only ahead of the tag, so every result below is a v0.9.0 result.
`__version__ = "0.9.0"`. **Not yet on PyPI** (`pip download` fails) — adoption
must pin a git ref, not a version specifier.

**Their suite (already running at session start):** `3577 passed, 13 skipped,
15 warnings in 597 s`, coverage **92.86 %** (gate 90 %).

## Method

Harness `cv9.py` (ported from `battle-de2da4e/contracts/cvde.py`), charts copied
byte-identical from `battle-de2da4e/contracts/<B>.machine.json`. Library source
read-only; never imported-for-patching.

Mandatory round-12 config on every chart: `strictConfig`, `strict_targets`,
`strict: True` logic, rollback, defer/error, guard raise, bounded RAISE inbox on
the order path, `SimulatedClock`, and a `CvErrorHooks`-equivalent plugin stub
passed via **`from_snapshot(plugins=…)`** (#230) at **every** restore, with a v3
snapshot/restore round-trip at **every** quiescence point and `chain_trips`
asserted `0` and preserved (#226).

**Pass 1 `async def`, pass 2 `def`** for every driver (`CV_SVC_STYLE`), all
under `-W error::RuntimeWarning` (#232) — no dropped guard receipts in our stubs.

## Scoreboard (async / def identical throughout)

| Driver | Checks | Fail |
|---|---|---|
| `v0_build.py` — build/start/snapshot/sync-restore, B1–B5 | 25 | 2 (both B3, OUR-CONTRACT) |
| `v1_b1.py` — B1 Order end-to-end | 15 | 0 |
| `v2_b2345.py` — B2/B3/B4/B5 + #225 provenance | 28 | 0 |
| `v3_c04_c07b.py` — C-04 (B16), C-07b (B18) re-check | 6 | 0 |
| `v4_mandates.py` — #232/#233/#226/bounded inbox | 6 | 0 |

**No LIBRARY finding.** Every failure reproduced is OUR-CONTRACT or a harness bug
I fixed; both are recorded below rather than counted against the library.

## Findings

### CV-V01 — OUR-CONTRACT — B3 `leg` self-destructs at t0 under default guards
`B3.states.pending.always` is `[skipped ⇐ should_skip, submitting ⇐
passes_preflight, → #leg.error]`. With both guards false (our stub default) the
unguarded third arm fires during initial entry, so the machine lands
`['leg.error']`, `status=done`, before any event is sent — on both engines and
both styles. This is our chart's fallback doing exactly what it says.
Supplying `{"should_skip": False, "passes_preflight": True}` lands
`['leg.submitting']`, `running` (`V2.B3.preflight_ok_*`, 6/6 green).
**Action for adoption:** the OMS must guarantee `passes_preflight` is decidable
at leg-entry, or the `always` fallback needs a real `preflight_pending` state —
an unguarded `always` to a terminal error is a live hazard in a leg chart.

### CV-V02 — OUR-CONTRACT (confirmed closed) — C-04 (B16) and C-07b (B18)
Both re-checked on v0.9.0 and both still close with a **config-only** edit, no
library change, 6/6 both styles:
- **C-04**: hoisting the four revocation events (`LOGOUT`, `IDLE_DEADLINE`,
  `ABSOLUTE_DEADLINE`, `REVOKE`) to the root + a terminal `elevation.dead` drops
  elevation on all four (`all 4 revocation events drop elevation`).
- **C-07b**: `onUnhandled: "defer"` + an unguarded `RELEASE` fall-through that
  audits the denial un-bricks the kill switch: denied `RELEASE` leaves it
  `running` in `engaged`, and a later authorised `RELEASE` reaches
  `kill_switch.clear`. `chain_trips=0`.

### CV-V03 — NOT A DEFECT (trust-boundary / R10-01 pattern) — `on_interpreter_start` does not fire on a restored interpreter
My harness first asserted `plugins=` wiring via `on_interpreter_start` and got
`started=0` on all 5 charts, both engines. Isolated in `v0c_restored_hooks.py`:
the **`.use()`-after-`from_snapshot` control shows `started=0` too**, so this is
not #230-specific — `start()` on a restored actor is a documented *resume*
(status is already `"running"`), and the start hook is a bring-up hook.
Plugins passed via `plugins=` are fully live: registration confirmed, and they
receive `on_transition`, `on_action_execute` and `on_interpreter_stop` normally
(restored `VALIDATE` → `transitions=1, actions=['stamp_validated',
'persist_event', 'reserve_rate_token']`). The live-vs-restored delta of exactly
1 transition / 1 action is the initial-entry macrostep the restored actor
correctly does not repeat. **Harness assertion corrected** to check registration
+ runtime hooks. *Wrapper note:* `CvErrorHooks` must not rely on
`on_interpreter_start` for per-process init on the restore path.

### CV-V04 — CONFIRMED FIXED — #225 self-send provenance by task identity
Both OMS-relevant shapes pass on v0.9.0, both styles:
- **spawned worker** that outlives its action and later does a plain
  `i.send("SEND")` → admitted as external traffic (`worker_send='ok'`), machine
  advances, `chain_trips=0`;
- **hand-out** `asyncio.ensure_future(i.send("SEND", wait=True))` from an action
  that then awaits again → not refused, and the receipt resolves when awaited
  elsewhere.

### CV-V05 — CONFIRMED FIXED — #232 dropped `wait=True` receipt warns
A `def` action that calls `i.send("SEND", wait=True)` and discards the result
emits the RuntimeWarning naming the machine and the supported alternatives; the
`ensure_future` hand-out shape stays **silent**. This is why all drivers can run
under `-W error::RuntimeWarning` cleanly.

### CV-V06 — CONFIRMED — #226 / #233 / bounded inbox
- `chain_trips` is a v3 envelope field, `0` and preserved across every restore on
  all 5 charts (both engines).
- #233 sync priority lane: the same B18 blob restored into `SyncInterpreter`
  lands the same configuration as the async engine (`kill_switch.engaged`),
  `chain_trips=0`.
- Bounded RAISE inbox (`max_queue_size=4`): a 40-event burst gives `sent=4,
  refused=36, dropped=[]` — **loud refusal, zero silent drops**, machine stays
  `running`. Exactly the order-path property the OMS needs.

### CV-V07 — BENCH-6 (their `production_characteristics.py --quick`, §2)
Loaded timer lateness, median ms beyond a 10 ms deadline, 5 runs:

| busy machines | r1 | r2 | r3 | r4 | r5 |
|---|---|---|---|---|---|
| 0 | +0.2 | +0.2 | +0.2 | +0.2 | +0.2 |
| 10 | +2.4 | +2.4 | +1.5 | +1.3 | +1.7 |
| 100 | +22.0 | +20.5 | +16.9 | +15.0 | +14.2 |
| **500** | **+122.8** | **+117.5** | **+82.3** | **+87.5** | **+85.3** |

At 500 busy machines: min 82.3, median **87.5**, max 122.8 ms. Against our
≤100 ms bar, **3 of 5 runs pass and 2 exceed it** — but this is a clear
improvement on the round-12 readings (+89.6/+94/+113/+110/+111, median 110):
the distribution has shifted down ~20 ms and the median now sits under the bar.
The metric is host-load-sensitive and the benchmark itself says so. **Verdict:
BENCH-6 is no longer a blocker at our fan-out, but a 500-machine deployment must
not put a ≤100 ms hard deadline on `after` timers** — the OMS already routes
hard deadlines through explicit `SimulatedClock`-driven deadline events, which is
the right shape.

## Bottom line

B1–B5 build, start, drive, snapshot and restore correctly on v0.9.0 under the
full mandatory config, on both engines and both service spellings, with
`chain_trips` clean everywhere and no dropped-guard warnings. **Zero LIBRARY
findings in this track.** The only chart-level hazard is CV-V01 (B3's unguarded
`always` → error), which is ours to fix in the catalogue; CV-V03 is a wrapper
note, not a defect. Adoption blockers remaining from this track: none from the
library — but v0.9.0 is **not on PyPI**, so the dependency must be pinned to
`91bd979`.

## Artefacts

`cv9.py` (harness), `v0_build.py`, `v0b_signals.py`, `v0c_restored_hooks.py`,
`v1_b1.py`, `v2_b2345.py`, `v3_c04_c07b.py`, `v4_mandates.py`, plus
`*.async.json` / `*.def.json` result files, all in
`docs/research/xstate/battle-v0.9.0/contracts/`.
