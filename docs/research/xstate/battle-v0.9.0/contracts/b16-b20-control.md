# B16–B20 control charts end-to-end on v0.9.0

**Library:** `xstate-statemachine` tag **v0.9.0 = `91bd979`**, `__version__ = "0.9.0"`.
`main = e3a1f22` is 2 commits ahead — **verified** with
`git diff v0.9.0..HEAD --stat`: a single file,
`.github/workflows/publish.yml` (+14/−1), a CI publish smoke test. **No
runtime source differs between the tag and `main`**, so every reading below
is a reading of the tag.

**Not on PyPI.** `pip download xstate-statemachine==0.9.0` fails; the tag is
the only artefact. Adoption must pin a VCS ref until the release lands.

**Suite (already running, not re-started):** `suite-v0.9.0.log` →
**3577 passed, 13 skipped, 15 warnings in 597 s; coverage 92.86 %** (gate 90 %).

## 1. What was run

Charts: **B16 AuthSession, B17 LiveEnablement, B18 KillSwitch,
B19 Reconciliation, B20 RiskLockout**, from the corrected catalogue JSON
(`battle-de2da4e/contracts/<B>.machine.json`, copied byte-identical).

Mandatory config on every build: `strictConfig`, `actionErrorPolicy:
rollback`, `onUnhandled: defer`/`error` per chart, `guardErrorPolicy: raise`,
`strictTargets`, `strict`, bounded RAISE inbox (`max_queue_size=64`,
`OverflowPolicy.RAISE`), `SimulatedClock`, and a `CvErrorHooks`-equivalent
plugin stub. **Every restore goes through `from_snapshot(..., plugins=[...],
minimum_version=3)`** (#230), and every quiescence point does a
snapshot→restore→compare with **`chain_trips` asserted `0` and preserved**
(#226).

Every driver ran **twice — pass 1 `async def` services, pass 2 `def`** — and
under **`-W error::RuntimeWarning`** (#232), proving no contract stub drops a
`wait=True` receipt. All scripts are standalone (stdlib +
`xstate_statemachine` only) and `os.chdir("C:/Users/basil")`. Library source
was never modified or imported-for-patching.

| Driver | What it pins | `async` | `def` |
|---|---|---|---|
| `v1_build.py` | build under recursive `strictConfig` (#220) + both engines start + v3 snapshot round-trip | **15/15** | **15/15** |
| `v2_b16_b17.py` | B16/B17 happy path + every catalogue invariant | 11/14 | 11/14 |
| `v3_b18_b20.py` | B18/B19/B20 happy path + invariants + `send_priority` + rollback/`onDone` | 26/27 | 26/27 |
| `v4_c04_c07b.py` | C-04 / C-07b are closed by a **config-only** edit | **6/6** | **6/6** |
| `v5_sharp.py` | C-07b bricking, #207 stranding, #204, 5-chart sync parity | **13/13** | **13/13** |
| `v6_r12.py` | #225 self-send provenance, #219, #232 on the order path | **4/4** | **4/4** |
| `v7_timers.py` | #218 handle leak, #221 v3 `scheduled_sends` compaction | **13/13** | **13/13** |
| `v8_restore.py` | #226 envelope, #227 strict on restored lanes, #233 sync priority lane | **5/5** | **5/5** |

**97 checks per style, 194 total; 8 failures, all 4 distinct and all OURS.**
Zero library defects found this round.

## 2. Findings

### LIBRARY — none

No new library defect. Every round-12 fix (#225–#235) that the control path
can exercise was re-verified on the tag and **holds on both service
spellings**:

- **#225** — a kill-switch action that spawns a drain worker outliving the
  action, and the documented hand-out idiom
  (`ensure_future(i.send(..., wait=True))`), are both treated as **external
  traffic**: the machine advances with the loop otherwise idle
  (`kill_switch.engaged → clear`, `chain_trips=0`). The genuine in-step
  await is still refused with **`ReentrantWaitError`, not a deadlock**.
- **#232** — a `def` action that drops a `wait=True` receipt emits the
  `RuntimeWarning`; our stubs never trip it (all runs under `-W error`).
- **#226** — `chain_trips` / `last_chain_error` are v3 envelope fields and
  survive the round trip on all five charts.
- **#227 / #230** — an undeclared type forged into restored
  `scheduled_sends` on `strict: true` B18 is **refused, reported through
  `on_invalid_event` and `last_error` (`UnknownEventError`), and the rest of
  the restore survives** — identically on both engines.
- **#233** — a `lane: "priority"` `RELEASE` restores at the head and drives
  the machine on the **sync** engine as well as the async one.
- **#218 / #221** — a 200-beat `raise(delay=)` heartbeat holds **≤1 clock
  handle**; an armed deadline survives two-hop journal compaction with
  `remaining_ms` intact.

### OUR-CONTRACT — 4 findings, all pre-existing, all config-only

**R12-13 (was C-04) — Blocker, B16.** Unchanged on the tag.
`LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE` leave
`['session.auth.revoked', 'session.elevation.elevated']` — **elevation
outlives the revoked session** — and `REVOKE` lands in `elevation.normal`,
from which a later `STEP_UP_OK` **re-elevates a dead session**
(`INV-a`, `INV-d` fail on both spellings, byte-identical notes). This is
engine-correct: SCXML / XState v5 select transitions per parallel region
independently, and our own `onUnhandled: defer` swallows the miss.

`v4_c04_c07b.py` proves the **config-only** fix closes it **6/6 on both
spellings**: hoist the four revocation events to the **root** targeting a
terminal `elevation.dead`, **and delete the region-level
`elevated.on.REVOKE` handler** — the round-12 correction stands, the root
hoist alone fixes only 9 of 12 lanes because the deeper handler outranks the
root arm.

**R12-14 (was C-07b) — Blocker, B18.** Unchanged, and re-confirmed
`bricked: true` on both spellings (`v5_sharp.py`): under root
`onUnhandled: "error"`, a **guard-denied** `RELEASE` makes the machine fatal
(`status='error'`, `UnhandledEventError`), and the subsequent **authorised**
`RELEASE` is accepted by `send()` (`ok: true`, ~0.3 ms) but dropped —
`final = ['kill_switch.engaged']`. One wrong press permanently wedges the
kill switch on the order path. Documented behaviour (opt-in
`onUnhandled:'error'` + #153 `guard_denied`), which is exactly what makes it
**ours**, not the library's. Fix proven **6/6** and **13/13**:
`onUnhandled: 'defer'` plus an ordered **unguarded auditing `RELEASE`
fall-through**.

**C-04b / C-04c — Medium, B16.** `INV-c` still fails identically: the
`elevated → elevated` re-enter arm on `STEP_UP_OK` does not audit, so two
successful step-ups yield `audit_step_up=1`. Closed by the same
config-only patch (add `audit_step_up` to the re-enter arm).

**B19 INV-b2 — Medium, B19.** `OPERATOR_RESOLVED` is deferred, not handled,
in `reconciliation.stale_lockout` (`deferred: 1`) — the operator cannot
clear a stale lockout. Config-only: add the handler.

### NEEDS-WRAPPER — none

Nothing this round required a wrapper. Two candidates were investigated and
**refuted as harness artefacts, not defects**:

1. **`plugins=` does not fire `on_interpreter_start`.** Correct and
   documented: a restored interpreter is already `status='running'`, so
   `start()` is a no-op for that hook, and `docs/_guide/snapshots.md`
   states `status` **is not a liveness signal** after a restore (#135); use
   `has_dormant_invocations` / `has_dormant_timers`. `plugins=` promises
   *registration before persisted events are admitted*, and that is what it
   delivers — verified directly and asserted that way. The R10-01 pattern:
   a documented boundary is not a defect.
2. **A priority-lane record did not replay on the sync engine.** Caused by
   my own driver calling `SimulatedClock.increment()` from inside a running
   event loop, where it returns a `_MustAwait` sentinel — **and the library
   emits a `RuntimeWarning` saying exactly that**. Driving the sync engine
   off-loop makes it pass. The library's diagnostic was what found this.

## 3. BENCH-6 — loaded timer lateness

**Their** `benchmarks/production_characteristics.py --quick`, §2 =
`after: 10` lateness (median ms beyond the 10 ms deadline), **5 runs**:

| busy machines | run 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| 0 | +0.1 | +0.1 | +0.1 | +0.1 | +0.1 |
| 10 | +1.0 | +1.0 | +0.8 | +1.0 | +1.0 |
| 100 | +9.3 | +9.3 | +10.0 | +9.3 | +10.0 |
| **500** | **+55.7** | **+52.0** | **+52.6** | **+55.1** | **+55.5** |

**At 500 busy machines: median +52.0 … +55.7 ms, spread 3.7 ms.** Our bar is
**≤100 ms**; v0.9.0 **clears it with ~45 % headroom**, and this is a real
improvement on round 12's **+89.6 / +94 / +113 / +110 / +111 ms** — roughly
**half** the lateness, and far tighter (3.7 ms spread vs ~23 ms). Note the
metric is a **median**, not p99, so the bar is met on the statistic the
benchmark reports, not on a tail figure.

## 4. Verdict

**v0.9.0 is clean for the five control charts.** 194/202 checks pass across
both service spellings; all 8 failures are the **4 known OUR-CONTRACT
catalogue defects**, every one closed by a **config-only** edit already
proven in this round's drivers. **No library finding, and no wrapper needed.**

The two blockers (R12-13 / R12-14) are **ours and unlanded for an eighth
round** — E50-T43 remains the highest-value item on the board, and the
amended C-04 acceptance criterion (**delete the region-level `REVOKE`
handler as well as hoisting to the root**) is re-confirmed here.

Remaining adoption caveat is packaging, not behaviour: **the tag is not on
PyPI**.
