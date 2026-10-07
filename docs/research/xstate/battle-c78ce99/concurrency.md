# Battle test (round 11) — CONCURRENCY, BACKPRESSURE & RESOURCE LIMITS

Target: `xstate-statemachine` @ `c78ce99` (merge of #217, round-10 fixes
#212–#216; unreleased 0.8.1, `__version__` still reports `0.8.0` — keyed
on the commit).

Scripts: `battle-c78ce99/concurrency/u1`–`u8`. Every probe is standalone
(stdlib + `xstate_statemachine` only, helpers inlined), proven from the
neutral cwd `<home>`. Every service/action check runs BOTH `def`
and `async def`; every engine check runs BOTH engines.

---

## 0. Bottom line

The two headline round-10 mechanisms are **opposite in quality**.

* **#212 (delayed self-send is a timer) is CORRECT and holds under
  attack.** 540 fuzz cells with a two-sided oracle, 200 machines × a
  1 ms ping-pong for 10 s, a 90-second soak: 0 violations, CPU paced by
  the clock (`cpu/wall = 0.26`), 0 chain trips on periodic work, and
  zero-delay cycles still trip. The `after` parity claim is exact.
* **#213 (`scheduled_sends`) is functionally correct but is an
  UNAUTHENTICATED EXECUTION CHANNEL.** The 300-machine remaining-delay
  property passes 300/300 — and the same field, forged, delivers an
  arbitrary event into a running machine, **bypassing `strict`**, and
  mints `done` / `after` completions that drive `onDone` and fire a
  60-second timer instantly. #214 applies `strict` to `pending_events`
  only; `scheduled_sends` was added beside it with no check at all.
* **#214's v2 upcast rule is a version-declared privilege escalation.**
  A blob that merely *declares* `"version": 2` gets its hand-written
  `done`/`error`/`after` records stamped `engine: true`. This is the
  question the round was called to answer: **the mitigation for
  D10-concurrency-3 created a second, wider door.**

| ID | Sev | One line |
|----|-----|----------|
| **D11-concurrency-1** | **High** | `scheduled_sends` is restored with **no `strict` check and no provenance gate**. A forged record delivers any event into a `strict: True` machine (silently — no `on_invalid_event`, no `last_error`), and with `"kind": "done"/"after", "engine": true` drives a real `onDone` and fires a declared `after: {60000}` in ~1 ms. Both engines, both kinds. |
| **D11-concurrency-2** | **High** | **Declaring `"version": 2` is a privilege.** `upcast()` stamps `engine: true` onto every v2 `done`/`error`/`after` record on the theory that only the engine could have written one — but the attacker writes the version field too. 6/6 forged cells drove `onDone` / `onError` / a 60 s `after`. The v3 control is correctly refused. `minimum_version=3` shuts it, but is **not** the default. |
| **D11-concurrency-3** | Medium | Restore → re-persist **without `start()`** drops every armed delayed self-send. `scheduled_sends` goes 1 → 0 on the second hop, silently. An operator who inspects-and-rewrites a blob, or a supervisor that restores then re-persists before scheduling, loses every timer #213 exists to preserve. |
| **D11-concurrency-4** | Medium | **#216 validates the TOP LEVEL only.** 120/120 top-level misspellings caught under `strict_config=True`; **0/120** caught when the same key is misspelled **inside a state** — `entryy`, `onn`, `alwaysX`, `maxIterationss` are all accepted **silently, with no warning at all**, under `strict_config=True`. The keys in `KNOWN_MACHINE_KEYS` are mostly *state-level* keys, so the validator's own list advertises coverage it does not provide. |
| **D11-concurrency-5** | Low | `on_invalid_event` for a restore-time `strict` refusal is **unobservable**. The refusal happens inside `from_snapshot`, before any `use()` call is possible: `invalid_count == 0` with two refused records. `last_error` survives (last one only) and a WARNING is logged, so it is not silent — but the hook #214 names as the reporting path cannot fire. |

Prior round-10 defects: **1 FIXED, 2 STILL-PRESENT, 1 SUPERSEDED**
(§2). Verdict: **ADOPT WITH CONSTRAINTS, constraints tightened** (§6).

---

## 1. Method and reductions

The 20-minute whole-task bound is the binding constraint. Every
reduction is stated with the reason it does not change what the probe
discriminates.

| Item | Brief | Run | Why |
|------|-------|-----|-----|
| v3 round-trip property | ≥300 machines | **300**, unreduced | Random delay × random elapsed × both kinds, `SimulatedClock`. |
| Livelock fuzz | ≥500 configs | **540 cells** (2 shards × 90 shapes × 3 supported lanes) | The union exceeds 500. Oracle is two-sided (153 must-trip cells, 387 must-not-trip). |
| Fuzz run window | 30 s watchdog | **0.1 s** run + 3 s hang watchdog | Every livelock in this family trips or hangs within tens of ms; measured against round 9's 3 s reference, which produced identical verdicts. |
| Ping-pong load | 200 machines × 1 ms × 10 s | **unreduced** | |
| Concurrent starts | 100 | **unreduced** | |
| Concurrent v3 restores | 200 | **unreduced** | |
| Determinism | 50× per cell + hash-seed | **unreduced** (6 cells = 300 runs, 3 child processes) | |
| Soak | 12 min, 200 machines | **90 s, 60 machines** | The only material reduction. Soak invariants (0 external dropped, heartbeat never dies, every chaos snapshot restores its heartbeat) are **per machine and rate-independent**; u5-L1 separately ran 200 machines at a 1 ms period for 10 s, and 44 chaos rounds is a large sample of the snapshot/restore window. Recorded in §5 as the residual gap. |

### 1.1 Commands

```
PY=…/_ref/xstate-statemachine/.venv-main/Scripts/python
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1      # from cwd <home>
D=…/CandleViewer/docs/research/xstate/battle-c78ce99/concurrency

$PY $D/u1_v2_upcast_minting.py            # exit 1  -> D11-2
$PY $D/u2_212_rule_matrix.py              # exit 0
$PY $D/u3_v3_roundtrip_property.py        # exit 1  -> D11-1, D11-3
$PY $D/u4_restore_trust_surface.py        # exit 1  -> D11-1, D11-4, D11-5
$PY $D/u5_concurrency_load.py             # exit 0
$PY $D/u6_fuzz_livelock_and_configkeys.py # exit 0  (F2 -> D11-4)
$PY $D/u7_determinism_and_soak.py         # exit 0
$PY $D/u8_self_target_heartbeat.py        # exit 0
```

### 1.2 Two oracles this round had to be corrected mid-run

Both corrections are recorded because they are the kind of mistake that
manufactures a false defect, and each turned into a real finding about
what the contract *is*.

1. **The fuzz oracle.** My first pass charged "any cycle containing a
   zero-delay hop must trip" and produced 219 violations. That is wrong
   under #212: a delayed hop **ends the step's chain**, so a mixed cycle
   is periodic work too. The correct discriminator is the longest run of
   **consecutive** zero-delay hops around the cycle versus
   `maxIterations`. Re-run with that oracle: **0/540**. The library was
   right and the first oracle was not.
2. **The heartbeat shape** (`u8`). My soak chart wrote
   `on: {TICK: {target: "beat"}}` — a self-target with no `reenter`,
   which is an **internal** transition: the state is never exited, so
   `entry` never re-arms and the beat fires exactly once. That looked
   like "#212's heartbeat claim is false". `u8` settles it: the
   **`after` reference behaves identically** (1 beat, both engines, both
   kinds), and `reenter: True` / a two-state hop run indefinitely
   (31–37 beats/s at a 25 ms period). #212's parity claim is **exact**.
   This is SCXML, not a defect — but it is a sharp authoring trap and is
   filed as a constraint (CV-C51), not a defect.

---

## 2. Prior round-10 defect table

| Prior defect | Sev | Probe re-run | Status @ `c78ce99` |
|---|---|---|---|
| **D10-concurrency-1** — #203's `after` provenance guard is type identity; 4 forgery vectors fire a 60 s timer | High | `t1_after_provenance_forgery.py` | **STILL-PRESENT.** exit 1, 8/8 forged cells reach `t1.late` on both engines; the public-class control is still correctly refused. Mechanism unchanged. Now **also reachable through `scheduled_sends`** (D11-1). |
| **D10-concurrency-2** — `onDone` targeting its own source state never re-arms the invoke; parks silently | High | `t4_self_target_ondone_never_rearms.py` | **STILL-PRESENT.** exit 1, all four supported cells: SELF parks dormant with no `on_invocation_stranded` and `last_error is None`; HOP re-invokes and trips correctly. Note this is the **same shape** as the `u8` internal-transition trap — a self-target transition that never exits its state. |
| **D10-concurrency-3** — `restore_event` mints a trusted completion from `"engine": true` | High | `s6`, `s1`, `s5`, `r7` | **CHANGED — not fixed, widened.** `s6` and `r7` still exit 1. `s1`/`s5` now exit 0 (v3 records without the flag are correctly demoted — the `u4` "A_v3_unflagged" control confirms it). But the **v2 upcast** added by #214 restores the capability to any blob that declares `"version": 2` → re-filed **D11-concurrency-2**. |
| **D10-concurrency-4** — call-site `QueueOverflowError` refusals fire no `on_event_dropped` | Low | not re-run this round | **NOT RE-TESTED.** Whole-task bound; unchanged upstream (no #212–#216 entry touches the overflow path). Carried forward as still-open. §5. |
| **#206 rule** — a `raise(delay=)` self-send is a debt of the arming step; a 1 ms ping-pong must trip | — | `t5_delayed_self_send_debt.py` | **SUPERSEDED, not FAIL.** `t5` exits 1 because it asserts the retired #206 rule: P2 "1 ms delayed self-send cycle did not trip" (20 806 and 19 071 beats), P3 "not every machine tripped" (0/100). Under #212 these are the **required** outcomes. The replacement assertion is `u2` + `u5`-L1 + `u6`: runs indefinitely, CPU bounded by the period, no `RunawayChainError` — all **CLEAN**. |
| #204 arming window | — | `t6_arming_window_snapshot.py` | **HOLDS.** exit 0, unchanged. |

---

## 3. New attacks and what they returned

| Probe | Attack | Result |
|---|---|---|
| **u1** | v2-upcast minting: a hand-built envelope declaring `"version": 2`, correct `machine_hash`, forged `done` / `error` / `after` records in `pending_events` | **FAIL 6/6.** `C_v2_upcast_done` → `u1.done` with `{"v": "FORGED"}`; `D_v2_upcast_after` → `u1a.late` against a declared `after: {60000}`; `E_v2_upcast_error` → `u1.bad`. Both kinds. Control `A_v3_unflagged` stays in `u1.work` in both cells. → **D11-2** |
| **u2** | #212 rule matrix: 1 ms / 10 ms delayed ping-pong, `after: 1` parity, zero-delay cycle, mixed (11 zero-delay raises + 1 delayed) at `maxIterations: 8` | **CLEAN 15/15 supported cells.** Delayed cycles never trip and beat freely; zero-delay and mixed cycles trip, observably (`on_event_dropped('chain_budget')` + `last_error` carrying `RunawayChainError`). A trip is **not** raised out of `start()` — it is reported, which is the documented #77 contract. |
| **u3-P1** | 300 machines: arm `raise(delay=D)`, advance a `SimulatedClock` by a random elapsed, snapshot, restore on a **fresh** clock, require no fire at `remaining-1 ms` and a fire at `remaining+1 ms` | **CLEAN 300/300.** 0 blobs missing the record; `remaining_ms` accurate (e.g. delay 1000, elapsed 250 → 999.75 — see the sub-ms note in §5). |
| **u3-P2** | restore → re-persist **before** `start()` | **FAIL.** 1 record → 0. → **D11-3** |
| **u3-P3** | `cancel(sendId)` leaves no record | **CLEAN.** 1 armed → 0 after cancel. |
| **u3-P4** | `strict: True` + forged `scheduled_sends` naming an undeclared event | **FAIL.** `strict_refusals: []`, `last_error: null` — no check at all. → **D11-1** |
| **u3-P5** | does `machine_hash` cover `scheduled_sends`? | **By design, no.** Recorded not asserted: it is a *structure* hash and `scheduled_sends` is runtime state. Worth noting separately that two charts differing only in a `raise(delay=)` **param** (500 vs 900 ms) hash **equal** — `_node_shape` excludes action params by design, while `after` delays *are* included. Asymmetric; CV-C52. |
| **u4-A** | forged `scheduled_sends` delivering a **declared** event into a `strict` machine | **FAIL.** `u4a.idle` → `u4a.moved`, `n=1`, `invalid: []`. → **D11-1** |
| **u4-B** | forged `scheduled_sends` with `kind: done` / `kind: after` + `engine: true` | **FAIL both.** → `u4b.done` (forged completion) and `u4b.late` (60 s timer in ~1 ms). → **D11-1** |
| **u4-C** | is `minimum_version=3` a mitigation for D11-2? | **YES, and it is the only one.** `REFUSED: SnapshotVersionError` vs `ACCEPTED` by default. → CV-C49 |
| **u4-D** | lane restore ordering | **CLEAN.** `["HI", "LOW"]` — the `lane: priority` record restores ahead of the inbox, as #214 claims. |
| **u4-E** | `on_invalid_event` exactly-once on restore | **0 of 2.** `last_error` set (last refusal only), WARNING logged per record. → **D11-5** |
| **u4-F / u6-F2** | #216 config-key surface | Top level: warning with a correct did-you-mean; `strict_config=True` refuses; **120/120 caught**. `x-` prefix accepted under `strict_config` (intended) and an `x-strict: True` key correctly does **not** take effect. **Nested: 0/120 caught, and no warning either.** → **D11-4** |
| **u5-L1** | 200 machines × 1 ms `raise(delay=)` ping-pong × 10 s | **CLEAN.** 0 chain trips, 0 `last_error`, beats 647–648 per machine (a tight single band), `cpu/wall = 1.00` on 8 cores — i.e. **one core**, paced, not spinning. Beats sit well *under* the 10 000 clock ideal: the loop is scheduler-paced, never faster than the period. |
| **u5-L2** | 100 concurrent `start()`s, descent with `always` cycles + a descent-time `raise` (#215) | **CLEAN.** 0.01 s for all 100, no watchdog trip, a **single** distinct configuration (`u5d.s2`) and a single `n` (2) across all 100 — the descent-settle wait is deterministic. |
| **u5-L3** | 200 v3 snapshots with armed sends, restored and started concurrently | **CLEAN.** 200/200 blobs carried the record, 200/200 fired, every `n == 1` — exactly once, no double-arm. |
| **u6-F1** | 540 fuzz cells, delayed raises in the grammar, two-sided #212 oracle | **CLEAN 0/540.** 153 must-trip cells all tripped; 387 periodic cells all ran ≥3 beats without tripping; **0 hangs**. |
| **u7-D1/D2** | 50× traces × 6 cells incl. a `scheduled_sends` restore hop; 3 `PYTHONHASHSEED` children | **CLEAN.** One hash per cell; restore and no-restore produce the **same** hash on each engine; identical across all three seeds. |
| **u7-S1** | 90 s soak, 60 machines, 25 ms heartbeats + external priority producer + chaos restore every 2 s | **CLEAN.** 78 600 external sent / 78 600 handled, **0 dropped**; beats 2788–2790 per machine (ideal 3600); `cpu/wall = 0.26`; 44 chaos rounds, every one restored a live heartbeat. |
| **u8** | `raise(delay=)` vs `after` on 4 heartbeat shapes | **CLEAN (parity exact).** See §1.2. |

### 3.1 One soak observation that is not a defect but is a constraint

RSS grew **32 MB → 207 MB** over 90 s across 60 machines with 44
stop/restore chaos rounds. Per machine-second that is small, and the
`u5` probes show no growth without chaos, so the likely cause is
retained stopped-interpreter objects held by this probe's own lists
rather than a library leak — **I did not isolate it**, so it is recorded
in §5 as untested rather than claimed either way.

---

## 4. Defect register — `D11-concurrency-n`

### D11-concurrency-1 — `scheduled_sends` is an unauthenticated execution channel: no `strict` check, no provenance gate

**Severity (OMS): High.** Class: **LIBRARY-DEFECT**.

**What.** #214 hardened the restore path for `pending_events`: a
restored user event passes the same `strict` check a `send()` does, and
a refusal is reported. `scheduled_sends`, added in the same release,
goes through a **different** path and gets **neither** check.

`base_interpreter.py:1902` stores the records verbatim:

```python
interpreter._restored_self_sends = [
    dict(r) for r in (snapshot.get("scheduled_sends") or [])
]
```

`_rearm_restored_self_sends` (`base_interpreter.py:1244`) then calls
`restore_event(rec)` and arms it — with `_processing` deliberately
raised (`interpreter.py:1411`) so the event is delivered with
**self-generated engine standing**. There is no `_admit_restored` call
on this path, and `restore_event` honours `"engine": true` exactly as it
does everywhere else.

**Three consequences, all reproduced on both engines and both kinds:**

1. A forged record delivers **any** event into a `strict: True` machine.
   `u4` cell A: `u4a.idle` → `u4a.moved`, `n=1`, `invalid: []`,
   `last_error: null`. Compare the `pending_events` route, which refuses
   the same event loudly.
2. `"kind": "done", "engine": true` drives a real `onDone`
   (`u4b.work` → `u4b.done`).
3. `"kind": "after", "engine": true` fires a declared `after: {60000}`
   in ~1 ms (`u4b.work` → `u4b.late`).

Note (2) and (3) are D10-concurrency-1/-3 reached through a **new,
unguarded field** — so even after those are fixed at `restore_event`,
this path still needs its own `strict` check.

**Repro.**
```
$PY battle-c78ce99/concurrency/u4_restore_trust_surface.py
$PY battle-c78ce99/concurrency/u3_v3_roundtrip_property.py    # P4
```
`u4_restore_trust_surface.json` → `A_forged_sched_declared_event.n == 1`
with `invalid == []`; `B_forged_done_via_scheduled_sends.states ==
["u4b.done"]`; `B_forged_after_via_scheduled_sends.states ==
["u4b.late"]`.

**Source.** `base_interpreter.py:1900-1904` (stored unchecked) vs
`base_interpreter.py:1909-1916` (the `_admit_restored` gate that
`pending_events` gets); `base_interpreter.py:1244-1260`
(`_rearm_restored_self_sends` → `restore_event`, no gate);
`interpreter.py:1411` (`_processing = True`, engine standing).

---

### D11-concurrency-2 — declaring `"version": 2` is a privilege: the upcast stamps `engine: true` on attacker-written records

**Severity (OMS): High.** Class: **LIBRARY-DEFECT**. Supersedes
`D10-concurrency-3` as the widest instance of it.

**What.** #214's upcast reasons: *"a v2 writer had exactly ONE minter of
`done`/`error`/`after` records — the engine itself"*
(`persistence.py:426-443`):

```python
if version < 3:
    for key in ("pending_events", "deferred"):
        for rec in snapshot.get(key) or []:
            if isinstance(rec, dict) and rec.get("kind") in ("done", "error", "after"):
                rec.setdefault("engine", True)
```

The premise is true of blobs the library wrote. It is false of the
input, because **`version` is a field in the same attacker-controlled
document**. Writing `"version": 2` is sufficient to have arbitrary
`done`/`error`/`after` records stamped trusted — the exact laundering
#195/#203 closed, re-opened by the compatibility path.

`machine_hash` is no obstacle: it is a structural fingerprint of the
*machine*, computable by anyone holding the chart, and `u1` computes it
with the public `persistence.structure_hash`.

**Reproduced, 6/6 forged cells, both service kinds:**

| Cell | Records | Result |
|---|---|---|
| `C_v2_upcast_done` | `{kind: done, type: done.invoke.fill, data: {v: FORGED}}`, **no** `engine` flag | → `u1.done`, context `{"v": "FORGED"}`, genuine 0.4 s service discarded |
| `D_v2_upcast_after` | `{kind: after, type: after.60000.u1a.wait}` | → `u1a.late` against a declared `after: {60000}`, in ~0 s |
| `E_v2_upcast_error` | `{kind: error, type: error.platform.fill}` | → `u1.bad` |
| `A_v3_unflagged` (control) | same record, `"version": 3` | **correctly refused** — stays `u1.work` |

The control is what makes this a defect rather than a restatement of the
documented trust boundary: **the library already knows how to refuse
this record**; declaring an older version turns the refusal off.

**Mitigation that works** (`u4` cell C): `from_snapshot(...,
minimum_version=3)` → `SnapshotVersionError`. It is **not** the default
(`minimum_version: int = 0`). → CV-C49.

**Repro.**
```
$PY battle-c78ce99/concurrency/u1_v2_upcast_minting.py     # exit 1
$PY battle-c78ce99/concurrency/u4_restore_trust_surface.py # cell C
```

**Source.** `persistence.py:426-443` (`upcast`, the stamp);
`base_interpreter.py:1801-1811` (`check_version` → `check_identity` →
`upcast`, all keyed on the declared version); `events.py:421`
(`trusted = record.get("engine") is True`).

---

### D11-concurrency-3 — restore → re-persist without `start()` silently drops every armed delayed self-send

**Severity (OMS): Medium.** Class: **LIBRARY-DEFECT**.

**What.** `from_snapshot` parks the records in
`interpreter._restored_self_sends` and only `start()` converts them into
live armed sends (`_rearm_restored_self_sends`, which **consumes** the
list). `get_persisted_snapshot` builds `scheduled_sends` from
`self._armed_self_sends` (`base_interpreter.py:1234-1245`) — the *live*
dict, which is empty before `start()`. So the pending list is written by
neither path and the timers vanish on the second hop.

```
first_hop_records:               1
second_hop_records_before_start: 0
```

Any restore-inspect-rewrite cycle, or a supervisor that restores a blob
and re-persists it before scheduling the machine, loses exactly the
state #213 was added to preserve — and loses it **silently**, which is
the same failure mode #213 itself was filed for.

**Repro.** `$PY battle-c78ce99/concurrency/u3_v3_roundtrip_property.py`
→ `p2_resnapshot.fail`.

**Source.** `base_interpreter.py:1234-1245` (`_persist_scheduled_sends`
reads `_armed_self_sends` only); `base_interpreter.py:1900-1904`
(restore writes `_restored_self_sends`);
`base_interpreter.py:1247-1260` (only `start()` moves one to the other).

---

### D11-concurrency-4 — #216 validates the top level only; a misspelled key inside a state is accepted silently under `strict_config=True`

**Severity (OMS): Medium.** Class: **LIBRARY-DEFECT** (incomplete fix).

**What.** `validate_top_level_keys` iterates `for k in config` — the
root dict only. But `KNOWN_MACHINE_KEYS` is overwhelmingly a list of
**state-level** keys: `entry`, `exit`, `on`, `after`, `always`,
`invoke`, `onDone`, `initial`, `type`, `states`. Those appear at the top
level of a machine only incidentally; where they actually do the work is
inside each state — and there nothing checks them.

Fuzzed over `KNOWN_MACHINE_KEYS` with four suffix mutations, 120 trials,
`strict_config=True`:

| Position | Caught | Missed |
|---|---|---|
| top level | **120 / 120** | 0 |
| inside a state | **0 / 120** | 120 |

Worse than the top-level pre-#216 behaviour in one respect: the nested
case produces **no WARNING either** (`nested_warnings: []`), so the
"did you mean" safety net is absent at the position where the typo is
most likely. `{"states": {"a": {"entryy": ["boom"], "onn": {...}}}}`
builds a clean machine with no entry actions and no transitions;
`{"a": {"maxIterationss": 3}}` likewise.

**Repro.**
```
$PY battle-c78ce99/concurrency/u6_fuzz_livelock_and_configkeys.py  # F2
$PY battle-c78ce99/concurrency/u4_restore_trust_surface.py         # cell F
```
→ `nested_under_strict_config: "ACCEPTED SILENTLY"`,
`nested_policy_misspelling: "ACCEPTED SILENTLY"`,
`nested_missed_count: 120`.

**Source.** `validation.py:313-357` (`validate_top_level_keys`, root
only); `validation.py:279-310` (`KNOWN_MACHINE_KEYS`, mostly
state-level keys).

---

### D11-concurrency-5 — a restore-time `strict` refusal cannot reach `on_invalid_event`

**Severity (OMS): Low.** Class: **LIBRARY-DEFECT** (observability).

**What.** #214 says a refused restored event is reported via
`on_invalid_event` and `last_error`. `_admit_restored` does call
`_report_invalid_event` — but it runs **inside the `from_snapshot`
classmethod**, which constructs the interpreter itself. There is no
instant at which a caller can attach a plugin first: `use()` requires
the object `from_snapshot` is still building. With two refused records,
`invalid_count == 0`.

`last_error` does survive (holding the **last** refusal only, so with
*n* refusals *n−1* are lost from that channel) and one WARNING per
record is logged, so a restore that dropped traffic is not wholly
silent — but the programmatic hook the fix names is unreachable.

**Repro.** `$PY battle-c78ce99/concurrency/u4_restore_trust_surface.py`
→ `E_on_invalid_event_restore.invalid_count == 0` with
`last_error == "Event 'NOPE2' is not declared …"`.

**Source.** `base_interpreter.py:1211-1232` (`_admit_restored` →
`_report_invalid_event`); `base_interpreter.py:1909-1916` (called from
inside `from_snapshot`, before the instance escapes).

---

## 5. Not covered

Stated so the verdict is not read as wider than the evidence.

| Gap | Why | Risk carried |
|---|---|---|
| **Full 12-min / 200-machine soak** | Whole-task bound; ran 90 s / 60 machines with 44 chaos rounds instead | Slow-accumulation effects (fd/handle growth, timer-heap growth, clock drift) over tens of minutes are unmeasured. `u5`-L1 covers 200 machines but only for 10 s. |
| **RSS 32 → 207 MB during the chaos soak** | Observed, **not isolated** (§3.1). Probe-held references are the likely cause | If it is a library leak in the stop/restore path it would matter at OMS uptimes. Needs a dedicated probe holding no references. |
| **D10-concurrency-4** (`QueueOverflowError` refusals fire no hook) | Not re-run; no #212–#216 entry touches that path | Assumed still-present. Low severity, carried forward unverified. |
| **`sendTo` child / `sendParent` with `delay=`** | The #212 matrix covered `raise(delay=)` self-sends and `after`; cross-actor delayed sends were not run | The persistence and chain-standing rules for a *delayed send to another actor* are unverified at this commit. This is the most substantive semantic gap. |
| **Sub-ms `remaining_ms` accuracy** | `u3` asserts a ±1 ms window; the observed `999.75` for delay 1000/elapsed 250 is inside it | Whether the 0.25 ms discrepancy is clock quantisation or an accumulating error over repeated snapshot/restore hops is untested. |
| **Forged `lane` field** | `u4`-D verified that a legitimate `lane: priority` restores correctly; a forged one was not run separately | A forged lane only reorders events the `strict` check already admits, so it is strictly weaker than D11-1 — but unmeasured. |
| **Redaction** | Not run this round | Unchanged from round 10. |
| **External sends at 5 k/s under a chain** | Not run separately; the soak sustained ~870 external/s with 0 dropped | The rate-independent invariant held at the rate tested. |
| **Free-threading / no-GIL build** | Not re-run (`h1`, `h2` unchanged upstream) | Carried forward from round 10. |

---

## 6. Verdict

**ADOPT WITH CONSTRAINTS — constraints tightened.**

The round-10 *engine* work is good. #212 is the right rule and survives
everything thrown at it: 540 two-sided fuzz cells, 200 concurrent 1 ms
ping-pongs at one core of CPU, a 90-second soak with zero external
events dropped and zero dead heartbeats, deterministic traces across
both engines, both service kinds, restore hops and three hash seeds.
#215's descent-settle wait is deterministic across 100 concurrent
starts. #213's core property — the *remaining* delay, honoured exactly —
is 300/300.

The *trust boundary* work is not. Three of this round's five defects say
the same thing in three places: **a property the engine knows at mint
time is being re-derived, after the fact, from a field the attacker
writes.** That is the identical diagnosis round 10 wrote for
D10-concurrency-1/-2 — the fixes reproduced the mistake rather than
retiring it. `"version": 2` is a privilege (D11-2); `scheduled_sends` is
a privilege (D11-1); `"engine": true` remains a privilege
(D10-concurrency-3, still present).

For an OMS the practical position is unchanged in shape but sharper in
degree: **a snapshot must be treated as fully attacker-controlled code,
not data.** The library's own docstring says exactly this
(`base_interpreter.py:1676-1691`) — but it then ships `strict`
enforcement on one restore field and not its neighbour, and makes the
one available refusal opt-in. Constraints below are mandatory, not
advisory.

### New constraints

| ID | Constraint |
|---|---|
| **CV-C49** | Every `from_snapshot` call site **must** pass `minimum_version=3` **and** `expected_machine_hash=<pinned>`. `minimum_version=3` is the only mitigation for D11-2 and it is not the default. |
| **CV-C50** | Snapshots **must** be HMAC-authenticated outside the library before `from_snapshot`. Given D11-1 and D11-2, a blob that reaches `from_snapshot` unauthenticated is arbitrary transition execution, not corrupt data. Verify the MAC over the exact bytes; do not parse first. |
| **CV-C51** | A self-targeting transition used as a heartbeat or a re-invoke loop **must** carry `reenter: True`, or be written as a two-state hop. Without it the transition is *internal*, the state never exits, and `entry` / `after` / `invoke` never re-arm — silently. This is the shared root of the `u8` trap and the still-open D10-concurrency-2. Add a chart-lint rule. |
| **CV-C52** | Do not rely on `machine_hash` to detect a changed **delay expressed as an action param**. `after:` delays are in the structure hash; `raise(delay=)` params are not — two charts differing only in a `raise` delay (500 vs 900 ms) hash equal. Pin delays in a reviewed constants table. |
| **CV-C53** | Do not restore-then-re-persist a snapshot without calling `start()` in between (D11-3): the armed timers are dropped silently. If a blob must be rewritten in place, edit the JSON directly rather than round-tripping it through an interpreter. |
| **CV-C54** | Config keys **inside states** get no validation, not even a warning (D11-4). `strict_config=True` is necessary but far from sufficient. Validate chart JSON against our own schema in CI, covering state-level keys. |
| **CV-C55** | Do not depend on `on_invalid_event` to observe restore-time refusals (D11-5) — it cannot fire. Check `last_error` immediately after `from_snapshot`, and count restored-vs-persisted `pending_events` to detect drops beyond the last one. |

### Phase-3 impact

None of the five blocks Phase-3 work already authorised by row-8 ADOPT.
D11-1/-2 are severity-High but sit entirely on the **untrusted-snapshot
ingress path**, which CV-C50 closes at our boundary and which our
current design does not expose. D11-3/-4/-5 are development-time and
operational hazards that constraints CV-C51–C55 cover. The item that
would change this assessment is the untested one: **delayed
`sendTo` / `sendParent` across actors** (§5) — that is the first probe
round 12 should run, before any multi-actor chart ships.
