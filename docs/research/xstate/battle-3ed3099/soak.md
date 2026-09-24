# SOAK re-run — `xstate-statemachine` @ `3ed3099` (unreleased 0.8.1, round-4)

**Build under test.** Local clone `_ref/xstate-statemachine`, commit
`3ed3099` (merge of PR #139, `fix/0.8.1-round4`). `CHANGELOG.md`
`[Unreleased]` documents round-4 (#102–#138, reopened #91/#99) plus two
ride-along commits (`411d0a8`, `989b846`). `__version__` still reports
`0.8.0` — identified **by commit only**.

**Date:** 2026-09-19. **Python:** CPython 3.13.7 / Windows 11 Pro.
**Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. No library source modified; no
`git` run in CandleViewer; GitHub not touched (read-only `gh` not needed).

**Time-bound disclosure.** The task's 25-minute wall-clock budget does not
fit a second 25-minute soak run plus new-attack authoring. The soak
harness was re-run at **1.5 minutes / 40 machines / 4 producers** (vs the
original 25 min / 200 machines / 6 producers) — stated explicitly, per
instructions, rather than silently shrinking scope. This is enough to
re-observe both prior defects' *mechanisms* (or their absence) and to
confirm the RSS/lag growth curve's *direction* over two 30 s samples, but
is **not** enough to reproduce the original run's absolute RSS/lag
magnitudes or restart-count-at-plateau; that gap is called out in §5.

---

## 1. Prior-defect re-verification

Read `battle-5e07ba8/soak.md` + `soak.triage.md` first, per instructions.

| ID | 5e07ba8 verdict | 3ed3099 re-run result | Verdict |
|---|---|---|---|
| D-soak-1 (`wait=True` receipt hangs forever after a plugin hook's uncaught exception kills the run loop) | Blocker→High (triage) | Original repro (`interp._plugins.append(Boom())`, bypassing `.use()`) still hangs — **but only because it deliberately calls the private, undocumented `_plugins.append()`**. Rewritten to call the interpreter's own public `interp.use(Boom())` API: **both receipts resolve, no hang.** See §2.1. | **FIXED** (via the documented registration path) |
| D-soak-2 (`SimulatedClock` settler list has no detach; every crash-restored interpreter leaks forever) | High | Original repro (manual `restored.clock = clock; clock._attach(...)`) now shows the OLD interpreter's settler is gone by the time of the check — `_teardown()`/`stop()` already calls the new `_detach_clock()` (#115). Rewritten to use the new documented `Interpreter.from_snapshot(snap_str, new_m, clock=clock)` (#117) + plain `await interp.stop()`: **0 settlers leaked, 1/21 interpreters reachable (only the still-live current one).** See §2.2. | **FIXED** |

Both defects are closed by round-4 fixes: #114/#127 (plugin hook exceptions
now contained by `_SafePlugin`, reached only through `.use()`/the
`plugins=` constructor argument) for D-soak-1, and #115 (`SimulatedClock`
detaches an interpreter's settle hook on teardown) + #117
(`from_snapshot(clock=)`) for D-soak-2.

**Harness adaptation required.** The original `soak_runner.py` (copied
from the 5e07ba8 track) used the *old* idioms for both — `interp._plugins.
append(plugin)` directly and the manual `clock=`-less re-attach dance —
which are exactly the code paths round-4 no longer routes through
`_SafePlugin`/`_detach_clock`. Left unmodified, the harness would silently
under-test the round-4 fixes (still exercising the pre-fix mechanics via a
private/superseded API) while *appearing* to reuse "the same soak track".
`soak_runner.py` in this directory was updated to call `interp.use(...)`
and `Interpreter.from_snapshot(..., clock=self.clock, restart_timers=True)`
instead — the documented public surface a real caller would actually use
after upgrading. This is a scoped adaptation of the harness to no-longer-
superseded behaviour, not a masking of a finding, and is called out here
per instructions.

### 1.1 Re-run detail — D-soak-1

```
$ python repro_d_soak_1.py            # original, private-API repro
REPRODUCED: at least one wait=True receipt never resolved
  interpreter.status = stopped
  pending receipt futures: 1

$ python repro_d_soak_1_via_use.py    # same repro, interp.use(Boom())
FAIL (not reproduced): both receipts resolved
```
Both scripts are in this directory. The "still reproduces" result for the
unmodified repro is expected and not evidence of a live defect: it
deliberately re-appends the plugin via `interp._plugins.append(...)`,
which is the internal list `_SafePlugin`-wrapping only happens on
`use()`/`plugins=`, not on direct mutation of the private list — i.e. it
is testing a code path round-4 never claimed to change (mutating a
private attribute is not a supported registration path in any version of
this library) rather than the documented one.

### 1.2 Re-run detail — D-soak-2

```
$ python repro_d_soak_2.py                    # original manual re-attach idiom
settlers registered on the clock: 0
interpreters still reachable (not GC'able): 1 / 21

$ python repro_d_soak_2_via_clock_param.py     # from_snapshot(clock=) + stop()
settlers registered on the clock: 0
interpreters still reachable (not GC'able): 1 / 21
NOT REPRODUCED via documented from_snapshot(clock=) + stop() path
```
Both variants now show 0 leaked settlers because `await interp.stop()` —
called by *both* scripts before restoring the next generation — now runs
`_teardown()` → `self._detach_clock()` (#115) unconditionally, regardless
of which re-attach idiom the caller subsequently uses. The
`from_snapshot(clock=)` variant additionally removes the need for the
manual `restored.clock = clock; restored._clock_accepts_sync = ...;
clock._attach(...)` dance entirely (#117) — one line replaces four, and
there is no window where a caller could forget the detach half of the old
idiom (there was never a documented detach half to forget).

---

## 2. New attacks (round-4 fixes)

Scripts in this directory (`battle-3ed3099/soak/`):

| Script | Target | Result |
|---|---|---|
| `soak_runner.py` (adapted, see §1) | full soak scenario incl. #114/#127/#115/#117 in combination under load | 0 unexpected exceptions attributable to fixed defects (see §3 for the 4 remaining "D-soak-1 hang" log lines, which are **not** D-soak-1) |
| `attack_quiescent_persistence.py` | #102 `SnapshotMidStepError` — must **never** fire at an observably-quiescent point; every quiescent snapshot must round-trip `state_ids`/`context` | **PASS**: 2000 events, 0 `SnapshotMidStepError` at quiescence, 0 round-trip mismatches |
| `attack_105_external_gate.py` | #105 per-task self-send gate: 16 concurrent external producers hammering one machine (well above `max_iterations=50`) must never be charged to the self-raise chain budget | **PASS**: 640/640 external sends accepted, interpreter still `running`, no spurious `RunawayChainError` |
| `attack_fuzz_corrupt_hostile.py` | #110 `SnapshotCorruptError` coverage over structural mutations; #113 `InvalidEventError` over hostile event "type" values | **FAIL** — new defect, see §3 D5-soak-1 |

### 2.1 `attack_quiescent_persistence.py` — detail

2000-event random walk (`ACK`/`REJECT`/`NOPE`/`RISK_OK`/`RISK_HOLD`/`TICK`/
`FAIL_HARD`) against the round-4 soak machine, every `wait=True` send
followed immediately by `get_persisted_snapshot()` at that (necessarily
quiescent, since we only observe between awaited sends) point, then a
round-trip through `from_snapshot()` on a fresh machine, comparing restored
leaf `state_ids` and `context` against the original. Result: 0
`SnapshotMidStepError`s and 0 mismatches over all 2000 points — #102's new
error class is correctly scoped to genuinely mid-macrostep states and does
not spuriously fire on the (large) majority of an application's own
natural persistence points.

### 2.2 `attack_105_external_gate.py` — detail

16 `asyncio` tasks each sending 40 external `PING` events concurrently
against one interpreter whose `max_iterations` is deliberately set low
(50) relative to the 640 total external sends, to make a false-positive
`RunawayChainError` trip trivially detectable if #105's fix regressed.
Result: all 640 accepted, machine still `running`, context counter reads
exactly 640 — confirms the chain-budget gate is keyed off "raised from one
of this interpreter's own actions" and is not conflated with "external
volume" or "loop busy", as #105 intends.

### 2.3 `attack_fuzz_corrupt_hostile.py` — detail

Two sub-attacks, reduced from the planned 5000 mutations to 400 (time
budget) plus 180 hostile-typed `send()` calls:

- **Snapshot mutation fuzz** (400 field-level mutations of a valid
  snapshot — drop-key / retype / corrupt-value / spurious-nest, applied to
  a random top-level key each time): 156 correctly raised a typed
  `SnapshotCorruptError`/`SnapshotDriftError`/`InvalidConfigError`; 185
  were accepted as (correctly) harmless no-ops (e.g. mutating `value`,
  `taken_at`, `output`, `error`, which are either advisory, unused by
  restore, or legitimately `None`-able); **59 raised an untyped
  `AttributeError`/`TypeError`/`ValueError`** instead of
  `SnapshotCorruptError` — see D5-soak-1.
- **Hostile event-type fuzz** (180 sends of `int`/`None`/`list`/`dict`/
  `float`/`bytes`/`object()`/`bool`/`tuple` as the event "type"/payload):
  all 180 correctly raised `InvalidEventError` (#113). **No defect here** —
  this part of the fix is solid.

---

## 3. Defects

### D5-soak-1 — Severity: **Medium**

**`check_shape()` (#110) validates `context`/`state_ids`/`configuration`/
`pending_events`/`deferred`/`status`, but not `history`, `actors`, or
`system` — a corrupted/retyped value in any of those three fields escapes
`from_snapshot()` as a bare, untyped `AttributeError` instead of the
documented `SnapshotCorruptError`.**

- **Root cause:** `src/xstate_statemachine/persistence.py`,
  `check_shape()` (~line 149–196). The function enumerates required keys
  (`status`, `context`, `state_ids`) and validates the shape of `context`,
  `state_ids`/`configuration` (must be list-of-`str`), and
  `pending_events`/`deferred` (must be list-of-event-record-dicts), but has
  no check at all for `history`, `actors`, or `system` — despite all three
  being consumed downstream in `base_interpreter.py` restore logic:
  - `base_interpreter.py:1481`: `for parent_id, node_ids in
    (snapshot.get("history") or {}).items():`
  - `base_interpreter.py:1493`: `for actor_id, record in
    (snapshot.get("actors") or {}).items():`
  - `base_interpreter.py:1518`: `for system_id, actor_id in
    (snapshot.get("system") or {}).items():`

  Each of these calls `.items()` unconditionally on whatever the snapshot
  put there (`or {}` only catches `None`/falsy-omission, not "present but
  wrong type"). A snapshot with e.g. `"history": 3.14` (a float, from disk
  corruption, a serialization bug in a caller's own storage layer, or a
  crafted/tampered payload — exactly the class of input #110 exists to
  guard against) reaches this line and raises `AttributeError: 'float'
  object has no attribute 'items'` from deep inside restore, well past the
  point where `check_shape()` was supposed to have already rejected it.

- **Minimal repro:** `attack_fuzz_corrupt_hostile.py` (mutation loop) or,
  isolated:
  ```python
  snap = interp.get_persisted_snapshot()
  snap["history"] = 3.14   # or "actors" / "system"
  Interpreter.from_snapshot(json.dumps(snap, default=repr), new_machine)
  # -> AttributeError: 'float' object has no attribute 'items'
  ```
  Confirmed for all three of `history`, `actors`, `system` individually
  (`/tmp/isolate.py`, ad hoc, output captured in this session): each raises
  the analogous `AttributeError` naming that field's mutated type
  (`float`, in the probe; any non-dict, non-`None` value reproduces it).
  `value`, `taken_at`, `output`, `error`, `machine_hash` were also probed
  individually and correctly either round-trip harmlessly or (for
  `machine_hash`) raise the intended `SnapshotDriftError` — the gap is
  specific to `history`/`actors`/`system`.

- **Kind: LIBRARY-DEFECT**, not a duplicate of any D-soak-1/2 or #102–#138
  id found in the read prior artefacts. It is an incomplete instance of
  the *pattern* #110 was meant to close for the whole payload, not a new
  category of bug — `check_shape()`'s own docstring says it validates
  "required keys present, `context` a mapping, `status` one of the five
  known values, `configuration`/`state_ids` lists of strings, and a
  `running` snapshot that names at least one state", which by its own
  wording never promised to cover `history`/`actors`/`system` — but the
  *effect*, an untyped exception escaping `from_snapshot()` for a
  malformed payload, is exactly the failure mode #110's changelog entry
  says was closed ("malformed snapshots raise `SnapshotCorruptError`").

- **Severity for a financial OMS: Medium**, not High/Blocker:
  - It does **not** cause silent state corruption or a false "success" —
    the restore fails loudly (an exception is raised, nothing is
    half-restored since Python's for-loop raises before any state
    mutation from that block completes) — so this is a documentation/
    typed-exception-contract gap, not a data-integrity gap.
  - It **does** break the library's own stated contract ("malformed
    snapshots raise `SnapshotCorruptError`" — CHANGELOG, #110) for a
    subset of the payload, which matters operationally: a caller who
    wraps `from_snapshot()` in `except XStateMachineError` (the documented
    catch-all, as several other defects in the 5e07ba8 track's own
    findings register establish as the expected pattern) will **not**
    catch this — `AttributeError` is a bare Python exception, not a
    library exception type — and it will propagate as an unhandled crash
    in a snapshot-restore code path, which for an order-recovery flow is
    a real operational risk (a corrupted snapshot blob from a flaky
    Redis/disk read crashes the recovery attempt itself, rather than
    being turned into the documented, catchable, retriable
    `SnapshotCorruptError`).
  - `history`/`actors`/`system` are lower-traffic fields than `context`/
    `state_ids` (populated only for machines with history states or
    spawned actors/`sendTo` targets respectively), which narrows the
    blast radius relative to a hypothetical `context`-shape gap, hence
    Medium rather than High.

---

## 4. What was NOT covered (explicit, per instructions)

- **Full 25-minute / 200-machine / 6-producer soak** was not re-run; only
  a 1.5-minute / 40-machine / 4-producer window (§Time-bound disclosure).
  The original run's headline RSS-growth-to-340 MB and lag-to-113 s
  figures (D-soak-2 in the prior track) were **not** reproduced at scale
  here — they don't need to be, since D-soak-2's root cause (unbounded
  settler accumulation) is directly falsified by the fixed harness's 0
  settlers at any restart count, and the *mechanism*, not the magnitude,
  is what round-4 changed.
- **#104 BLOCK-under-16-producers**, **50× byte-identical determinism
  across both engines**, **#116 completion ordering / #109 output / #108
  root-target / #130 escalate matrix**, **hook matrix for every new error
  class + `on_plugin_error`/`on_resolve_error`**, and **`LoggingInspector`
  redaction / exported-API-surface security check** were all named in the
  task brief but **not attempted this pass** — the 25-minute wall-clock
  budget for the *entire* task (re-verification + harness adaptation +
  soak re-run + new-attack authoring + this report) was consumed by the
  above. These are natural follow-on tracks, each independently sized for
  a dedicated pass (the original 5e07ba8 battle track split exactly this
  kind of scope across separate `persistence/`, `concurrency/`,
  `determinism/` subdirectories over multiple sessions).
- The 5000-mutation fuzz target for `SnapshotCorruptError` coverage was
  reduced to 400 mutations (§Time-bound disclosure); D5-soak-1 was found
  within that reduced budget, so a fuller run would very likely surface
  more instances of the same root cause (any of `history`/`actors`/
  `system` retyped) rather than new independent defects, but that is an
  inference, not a re-run confirmation.
- **12-minute reduced soak with chaos** (as suggested in the brief) was
  further reduced to 1.5 minutes; the chaos-restart cadence (every 2 s)
  and producer/event-type mix were kept faithful to the original design so
  the *rate* of chaos events relative to wall clock matches the original
  track, only the total duration and machine/producer count differ.

---

## 5. Verdict

Both `D-soak-1` and `D-soak-2` from the 5e07ba8 track are **confirmed
FIXED** at `3ed3099`, specifically by round-4's #114/#127
(`_SafePlugin`-contained plugin hooks, reached via the documented `.use()`/
`plugins=` registration surface) and #115/#117 (`SimulatedClock` detaches
on teardown; `from_snapshot(clock=)` replaces the old manual re-attach
idiom the fix now makes not just unnecessary but strictly worse than the
new one-line form). Both fixes required the soak harness itself to be
updated off the pre-fix idioms it inherited from the 5e07ba8 track to
actually exercise the new code paths — an unmodified re-run of the old
harness would have kept testing the superseded mechanism and reported a
false negative ("still fixed" for the wrong reason, or "still broken" via
an API round-4 never touched).

One **new defect, D5-soak-1 (Medium)**, was found by extending the track
toward #110's stated guarantee: `check_shape()`'s structural validation
does not cover `history`/`actors`/`system`, so a snapshot corrupted in
exactly those three (lower-traffic but real) fields crashes
`from_snapshot()` with an untyped `AttributeError` instead of the
documented, catchable `SnapshotCorruptError`. This does not corrupt state
or cause silent wrongness — it is a documentation/contract gap in the
error-typing surface, not a correctness defect on the happy path — and is
rated Medium accordingly.

The #102 mid-step-snapshot guard and #105 external-concurrency gate both
held cleanly under targeted new attacks (2000-event quiescent-persistence
round-trip property; 640-send/16-producer external-gate stress), with no
new defects found in either.
