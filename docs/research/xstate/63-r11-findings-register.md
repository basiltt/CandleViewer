# 63 — Round-11 findings register (triage + dedupe), library @ `c78ce99`

**Library under test.** `_ref/xstate-statemachine` @ `c78ce99` (merge of
PR #217, `fix/0.8.1-round10`; unreleased 0.8.1, `__version__` still `0.8.0` —
key on the commit). Round-10 fixes #212–#216.

**Inputs triaged.** 60 raw finding records from the eight round-11 battle
tracks (`battle-c78ce99/{persistence,concurrency,fuzz,semantics,security,
soak,determinism,observability,contracts}`), the P-1..P-7 set from
`62-r11-diff-review.md`, and the regression deltas from
`60-r11-regression.md`.

**Method.** Every record's repro re-run fresh from neutral cwd
`<home>` with the pinned venv, 120 s cap, both action kinds (`def` /
`async def`) and both engines where the record claims them, polled to
convergence. Source read at every cited line before classification. Records
sharing a root cause merged into one canonical `R11-nn`.

**Two semantic reversals honoured in triage.** (a) #212 supersedes #206 — a
`raise(delay=)` self-send is a timer, so a 1 ms self ping-pong is a legal
periodic process and any record charging it as a runaway is classified
`SUPERSEDED-RULE`, not a defect. (b) #213/#214 introduce snapshot layout v3
with `scheduled_sends`, strict-on-restore, lane, and v2 upcast — records are
judged against the v3 contract.

---

## Headline

| | Count |
|---|---|
| Canonical LIBRARY-DEFECTs | **12** (1 Blocker, 4 High, 4 Medium, 3 Low) |
| DESIGN-CONSTRAINT | 2 |
| NEEDS-WRAPPER | 3 |
| OUR-CONTRACT-DEFECT | 7 (2 Blocker, carried) |
| SUPERSEDED-RULE (our test encoded #206) | 1 |
| DUPLICATE / merged away | 34 |
| HARNESS-ERROR | 1 |
| Library-verified passes (no defect) | 19 |

**One-line verdict.** Round 10 is a genuine net improvement (#213 closes a
real wedge, #215's parity holds on the shapes it pins, #216 is correct at the
level it checks), but it ships **one Blocker-class security regression**
(`R11-01`, the `"version": 2` downgrade mint), a **second unchecked restore
door** (`R11-02`), a **new unbounded-CPU escape hatch** (`R11-05`), a **new
`start()` hang shape** (`R11-06`), and a **new unbounded memory leak**
(`R11-04`) that #212 created by removing the trip that used to stop it. The
row-8 ADOPT of `59-r10-final-readiness-verdict.md` cannot be carried forward
unamended.

---

## Canonical LIBRARY-DEFECT index

| ID | Sev | Kind | Title |
|---|---|---|---|
| R11-01 | **Blocker** | security | `"version": 2` in the payload is a privilege: `upcast()` stamps `engine: true` on attacker-written `done`/`error`/`after` records |
| R11-02 | High | security | `scheduled_sends` restores with no `strict` check and no provenance gate; `lane` is a payload-controlled ordering primitive |
| R11-03 | High | security | `after`-provenance boundary still forgeable four ways (carry-forward, unchanged) |
| R11-04 | High | resource-leak | Unbounded `_timer_handles` growth — one retained handle per `raise(delay=)` beat, both engines |
| R11-05 | High | semantics | #212's timer exemption keys on delay *truthiness*: `raise(delay=0.0001)` escapes `maxIterations` at ~20k laps/s |
| R11-06 | Medium | correctness (hang) | #215's `_descent_done` gate: an entry action awaiting its own receipt hangs `start()` forever, silently |
| R11-07 | Medium | correctness | #216 validates the root config only; a misspelled key inside a state is silently dropped even under `strict_config=True` |
| R11-08 | Medium | correctness | Restore then re-persist without `start()` silently drops every armed delayed self-send |
| R11-09 | Medium | silent-failure | A `RunawayChainError` trip reaches only `last_error`, which the next event erases; no hook names it |
| R11-10 | Low | observability | `on_invalid_event` is structurally unreachable on the restore path |
| R11-11 | Low | drift-detection | `structure_hash` omits `raise(delay=)` delays although it covers `after` delays |
| R11-12 | Low | engine-parity | Priority `lane` is persisted but not honoured on restore on the sync engine |
---

## R11-01 — **Blocker** — `"version": 2` is a privilege: `upcast()` mints engine provenance onto attacker-written records

**Classification.** LIBRARY-DEFECT (security). **Regression introduced by #214.**

**Merged records (12).** `D11-persistence-2`, `D11-concurrency-2`,
`D11-fuzz-1`, `D11-semantics-1`, `D11-security-1`, `D11-soak-1`,
`i2-v2-upcast-minting`, `P-1`, plus the informational `C` / `attack_cd` cells
that observed the same upcast from the benign direction.

**Source.** `persistence.py::upcast`, the `if version < 3:` block (lines
426–443), whose comment argues that *"a v2 writer had exactly ONE minter of
done/error/after records — the engine itself"*, and therefore applies
`rec.setdefault("engine", True)` to every such record. That feeds
`events.py:421`, `trusted = record.get("engine") is True` — the exact gate
#195/#203 exist to hold.

**Why the stated premise fails.** The argument is sound for blobs the
*library* wrote and false for any blob an *attacker* wrote, because `version`
is a plain unauthenticated field of the same document. `check_version`
accepts `2 <= SNAPSHOT_VERSION`; `upcast` then grants provenance. The attacker
writes a v3 blob and edits one integer. This re-establishes exactly the
property #205 was written to forbid: *a payload cannot select its own level of
checking*. `machine_hash` is no obstacle — it is a structural fingerprint of
the chart, computable by anyone holding the chart via the public
`persistence.structure_hash`, not a MAC.

**Re-verified this round** (neutral cwd `<home>`, fresh):

    $ python probes/main-c78ce99/p3_214_v2_upcast_forge.py
    baseline version: 3 states: ['vault.locked']
      after  v3 forged (control)      -> states=['vault.locked'] actions=0 TIMER_FIRED=False
      after  v2-DOWNGRADED forged     -> states=['vault.open']   actions=2 TIMER_FIRED=True
      done   v3 forged (control)      -> states=['pay.charging'] actions=0 ONDONE_FIRED=False
      done   v2-DOWNGRADED forged     -> states=['pay.paid']     actions=2 ONDONE_FIRED=True

The v3 controls refuse correctly — the gate works; the downgrade is the hole.
Independently confirmed across five other tracks: a **24-hour** `after`
(`d11_sem_1`), a **60 000 ms** `after` (`u1_v2_upcast_minting`,
`p2_upcast_minting`), an **86 400 000 ms** `after` on a machine hardened with
`strict: True` + `onUnhandled: "error"` (`n9_v2_upcast_minting`) — all firing
instantly on restore with `last_error=None`. A forged `done.invoke` lands
attacker context (`ctx.fill={'filled': 999999}`, `{"v": "FORGED"}`) through a
real `onDone` while the genuine service is still running. Reproduced on
**both engines** and **both service kinds** in every track. Omitting the
`version` key entirely (v0) works too (`n9` V8).

**OMS severity: Blocker.** The snapshot is the restart path for an order
manager. This turns any writeable journal into arbitrary
`onDone`/`onError`/deadline injection with attacker-chosen context, reported
as healthy.

**Mitigation (confirmed working in three tracks).**
`from_snapshot(minimum_version=3)` raises `SnapshotVersionError`. It defaults
to `0` (`base_interpreter.py:1802`). → **CV-C52: every restore call site must
pass `minimum_version=3`; lint for a bare `from_snapshot(`.**

**Upstream fix.** Do not infer provenance from a self-declared version. Either
drop the `setdefault` and accept that a genuine 0.8.0 `after` record demotes
(a documented migration cost), or gate the upcast on an out-of-band flag the
*caller* supplies: `from_snapshot(..., trust_legacy_completions=True)`.

---

## R11-02 — **High** — `scheduled_sends` is a second restore door with neither the `strict` check nor a provenance gate; `lane` is payload-controlled

**Classification.** LIBRARY-DEFECT (security). **New in #213/#214 — the two
fixes were not composed.**

**Merged records (4).** `D11-concurrency-1`, `P-3` (b) and (c),
`u3::p4_strict_forgery`.

**Source.** `base_interpreter.py:1900-1904` stores `scheduled_sends` records
verbatim into `_restored_self_sends`; `_rearm_restored_self_sends`
(`:1244-1260`) calls `restore_event(rec)` and arms through `_deliver` with
`_processing` deliberately raised (`interpreter.py:1411`), i.e. with
self-generated engine standing. `_admit_restored` — the `strict` mirror #214
added — is called only from the `pending_events` loop two lines below
(`:1909-1916`). `restore_event` honours `"engine": true` here as everywhere
(`events.py:421`), so `kind=done`/`after` records reach engine-only machinery
through a field with no gate at all.

**Re-verified this round:**

    $ python probes/main-c78ce99/p5_214_strict_lane.py
    b) scheduled_sends BOGUS under strict: err = None invalid hook = []
       known WAKE via scheduled_sends -> ['strictm.b']
    c) persisted [P inbox, Q forged-priority] -> processed ['Q', 'P']

    $ python battle-c78ce99/concurrency/u3_v3_roundtrip_property.py
      "p4_strict_forgery": {"strict_refusals": [], "last_error": null,
        "fail": "a forged scheduled_sends record bypasses `strict` entirely"}

`u4_restore_trust_surface.py` (exit 1) additionally shows forged
`scheduled_sends` driving `onDone` (`u4b.done`) and firing a declared 60 s
`after` in ~1 ms (`u4b.late`), with `invalid==[]` and `last_error==null`.
Both engines, both kinds.

**Note the asymmetry.** #214's stated invariant — "restored user events pass
the same `strict` check a `send()` does" — is *true* for `pending_events` and
*false* for the field added in the same release. Sub-finding (c) is a
distinct, lesser primitive: `lane: "priority"` is caller-writable and
`_enqueue_restored` honours it with no provenance check, so a blob can reorder
user traffic. It did not exist at `19cb1f1`.

**OMS severity: High.** Same journal-write threat model as R11-01 but a
*separate* door, so `minimum_version=3` does **not** close it — a fully valid
v3 blob suffices.

→ **CV-C53: treat the snapshot journal as an integrity-protected artefact
(MAC'd at rest by the wrapper). Neither `minimum_version=3` nor `strict` is
sufficient alone.**

**Upstream fix.** Route `_rearm_restored_self_sends` through
`_admit_restored`, and refuse `kind in (done, error, after)` in
`scheduled_sends` outright — a delayed *self-send* is never a completion.

---

## R11-03 — **High** — the `after`-provenance boundary remains forgeable four ways (carry-forward, unchanged)

**Classification.** LIBRARY-DEFECT (security), carried from round 10
unchanged. **Merged records:** `D10-fuzz-1`.

**Re-verified this round** — `battle-19cb1f1/fuzz/n1_after_forgery.py` re-run
verbatim against `c78ce99`:

    SUCCESSFUL AFTER-FORGERY VECTORS = 4
       - V2 import path engine_after()
       - V3 type(held_engine_event)(...)
       - V4 pickle round-trip
       - V5 hand-written snapshot record engine:true

Each drives a real `after` transition — a 60 000 ms timer firing immediately
under `strict: True`. Control V1 (hand-built public `AfterEvent`) correctly
refused with `UnknownEventError`.

**Root cause.** The engine-mint check is `isinstance(ev, _EngineAfter)` — the
same type-identity gate #195 used. Rounds 9, 10 and 11 did not change it.

**Interaction.** With R11-01 and R11-02 the mint surface now has **six**
independent doors (V2–V5, the v2 downgrade, `scheduled_sends`). Type identity
is not a capability in Python; the boundary needs a per-interpreter
unforgeable token, not a class.

---

## R11-04 — **High** — unbounded `_timer_handles` growth: one retained handle per `raise(delay=)` beat, both engines

**Classification.** LIBRARY-DEFECT (resource leak). **Newly *exposed* by
#212** — the mechanism predates it, but #206's trip used to kill the cycle at
~`maxIterations` beats, capping growth at ~12 entries. #212 makes the cycle
legal and therefore the growth unbounded.

**Merged records (3).** `D11-persistence-1`, `D11-semantics-4`, and the
`x13_rss_attribution` RSS observation.

**Source.** `interpreter.py:2354` (and `sync_interpreter.py:1194`) register
the delayed-send handle under `self._timer_handles[self.id]` — the
**interpreter/machine** id. The only pruner is state exit,
`interpreter.py:2557`, which pops `_timer_handles[state.id]`. The machine id
is never an exiting state, so the list is append-only for the interpreter's
life. `_fire` (`:2323-2340`) settles the #213 debt and clears
`_armed_self_sends` / `_scheduled_sends` but never discards the handle;
cleared only at `stop()` (`:1514-1517`). The `after` path (`:2748`) passes
`owner_id=state.id` and *is* pruned — which is exactly why the `after` control
arm stays flat.

**Re-verified this round:**

    $ python battle-c78ce99/semantics/repro/d11_sem_4_timer_handle_leak.py
    after:10        ping-pong: beats 615, timer_handles_retained 1    (0.002/beat)
    raise(delay=10) ping-pong: beats 614, timer_handles_retained 614  (1.00/beat)
    REPRODUCED: true  leaking_cells: ['raise_delay/plain','raise_delay/async']

Linear and never reclaimed (t=5 s → 376 handles … t=25 s → 1618). Independent
confirmation: `x14_timer_handle_leak.py` — 753 beats → 753 retained handles,
752 already fired, `after:` control retains 1 at 748 beats; sync engine
identical (501/501). `x13_rss_attribution.py`: **+463 MB in 24 s at 200
machines** on the raise-heartbeat arm while the idle and `after` arms are
flat; the 90 s soak reads **+753 MB RSS** against round-10's +1.2 MB.

**OMS severity: High.** A TWAP pacer or venue heartbeat realised as
`raise(delay=)` is the canonical use of the #212 reversal and is precisely
what leaks. A long-lived OMS process OOMs on a timescale of hours.

→ **CV-C54: realise every periodic deadline as `after:`, never as a
`raise(delay=)` heartbeat, until this is fixed.** This is in **direct tension**
with `OBS-213` / `CV78-T1`, which require `raise(delay=)` because `after`
deadlines are not persisted — see § Constraint deltas.

**Upstream fix.** One line: own the handle by the arming state, or discard it
in `_fire`.

---

## R11-05 — **High** — #212's timer exemption keys on delay *truthiness*, not on time: `raise(delay=0.0001)` escapes `maxIterations` entirely

**Classification.** LIBRARY-DEFECT (semantics). **New boundary defect in
#212.** **Merged records:** `P-2`. Related-but-distinct from `OBS-212` /
`D11-concurrency`'s `u2_212_rule_matrix`, which verify the *intended* 1 ms
behaviour and correctly pass.

**Source.** `interpreter.py::_deliver` — `if not delay:` selects the charged
zero-delay branch; **anything truthy** takes the timer branch, which since
#212 no longer counts as `_armed_this_step`. `delay` is milliseconds as a
float, so `0.0001` is 100 nanoseconds. The clock cannot enforce any floor at
that scale: arming returns immediately and the firing lands on the very next
loop turn.

**Re-verified this round** (`maxIterations=10`, both action kinds):

    A mixed delayed+zero-delay (delay=1)       beats=   129 err=None rate=  127.0/s
    A mixed (delay=0.0001)                     beats= 11851 err=None rate=23696.6/s
    B pure raise(delay=1)                      beats=    66 err=None rate=   65.2/s
    B pure raise(delay=0.0001)                 beats=  8774 err=None rate=17546.5/s
    B pure raise(delay=0) [control]            beats=    12 err=RunawayChainError
    (async def lane identical in shape: 12171 / 8980 / 12+RunawayChainError)

**Two separate results.**

1. **A chart can combine `raise(delay=1)` with genuine zero-delay work to
   escape `maxIterations` entirely** (row A). State `A` arms a delayed
   self-raise; `B` does a real zero-delay `raise`. Every period contains true
   same-step chain work, but the delayed arming resets the chain each period,
   so the zero-delay link never accumulates past 1. 129 laps in 1 s at
   `maxIterations=10`, no error, indefinitely. The changelog's framing
   ("`maxIterations` bounds work the machine feeds itself *within* a step") is
   honoured to the letter and useless in practice: **any runaway can be made
   unbounded by inserting one delayed hop.**

2. **Below ~0.01 ms there is no clock bound at all.** `delay=0` is falsy and
   correctly stays a chain (control trips at 12 laps, both kinds). Any
   positive value, however small, is a timer. At `0.0001` the effective bound
   is the event-loop turn rate: ~16–24 k laps/s, uncharged, forever. So #206's
   original concern is *defensibly accepted* at 1 ms (~64 laps/s, genuinely
   bounded by the OS timer floor) and **far worse than accepted** below
   0.01 ms.

**Engine parity holds** (`p8_sync_parity_version.py`): both engines apply the
reversal; the rule they agree on is the problem. Delayed `sendTo` a child is
unaffected — the exemption keys on `actor is self`, so a child send was never
charged and still is not.

**OMS severity: High** (not Blocker: it requires a hostile or careless chart,
not hostile input). But `maxIterations` is the *only* engine-level liveness
bound, and this voids it.

→ **CV-C50 (new): no chart may use a `raise`/`send` delay in the open interval
(0, 1) ms. Lint contracts for it; treat as a build failure.**
→ **CV-C55 (new): `maxIterations` may not be cited as a liveness guarantee in
any runbook; a per-machine wall-clock work-rate supervisor is mandatory.**

**Upstream fix.** Make the exemption time-*aware*: charge the timer exemption
only above a stated floor (1 ms, the OS timer resolution), or clamp `delay` to
a 1 ms minimum as `SimulatedClock` semantics already imply.

---

## R11-06 — **Medium** — #215's `_descent_done` gate: an entry action awaiting its own receipt hangs `start()` forever, silently

**Classification.** LIBRARY-DEFECT (correctness / liveness). **Regression
introduced by #215.** **Merged records:** `P-4` (b).

**Source.** `interpreter.py::_run_event_loop` — `await
self._descent_done.wait()` before the main `while`, set only at the end of
`start()`'s try-body (and in `finally`).

**The cycle.** An `async def` entry action that does
`await i.send("GO", wait=True)` cannot be satisfied: the receipt resolves only
when the run loop processes `GO`, and the run loop is parked on
`_descent_done`, which only the completion of that same entry action can set.

**Re-verified this round:**

    $ python probes/main-c78ce99/p6b_215_start_stall_timing.py
    start() took 3.01s  n=-1 states=['dead.x'] err=None      # 3 s == the probe's own wait_for
      after settle: ['dead.y']

    $ python probes/main-c78ce99/p6c_215_gate_is_the_cause.py
    gate pre-opened: start() took 0.00s n=1 states=['dead.y']

The second run is the identical chart on a subclass that opens the gate before
spawning the loop (pre-#215 behaviour, **library source untouched**) — so the
gate is causal and the shape is new at `c78ce99`. With no timeout in the
user's action, `start()` never returns.

**It is silent:** `last_error is None`, status `running`, configuration legal
— indistinguishable from a slow entry action. #207's
`on_invocation_stranded` does not cover it (no invoke involved).

**Correctly bounded control** (`p6_215_descent_wait.py` a): an `always`
self-cycle in the descent returns from `start()` with `RunawayChainError`
after 13 entries at `maxIterations=12`. The settle budget does cover the
descent; only the receipt cycle hangs.

**Severity Medium** — awaiting one's own receipt from an entry action is
unusual, but "await a helper that happens to await a receipt" is not, and the
failure mode is an unbounded hang inside `start()` with no diagnostic.

→ **CV-C51 (new): no entry/exit action may `await` a receipt
(`send(..., wait=True)`) on its own interpreter. Lint for it.**
→ **CV-C56 (new): every `start()` call must be wrapped in
`asyncio.wait_for(..., startup_timeout)`.**

**Upstream fix.** Bound the gate with `wait_for`, or set `_descent_done`
before running entry actions and use a re-entrancy flag — which is what the
#215 comment says it is mirroring from the sync engine.

**Sub-finding, not a defect (recorded as DESIGN-CONSTRAINT `R11-DC-1`).**
`P-4` (c) / `OBS-PLATEAU`: a descent-seeded `raise` chain runs **8** laps at
`maxIterations=6` where an externally seeded one runs **3**. That is the
intended #215/#77 parity (the sync drain gives descent raises seed standing)
and is the *sync* number the async engine was brought to. Deterministic and
lane-independent, but budget sizing done against the external number
under-provisions the descent case by ~2.7×.

---

## R11-07 — **Medium** — #216 validates the root config only; a misspelled key inside a state is silently dropped even under `strict_config=True`

**Classification.** LIBRARY-DEFECT (correctness / scope gap). **Merged
records (8).** `D11-persistence-3`, `D11-concurrency-4`, `D11-fuzz-3`,
`D11-semantics-3`, `D11-security-2`, `D11-soak-2`, `G-gap`, `P-6`.

**Source.** `validation.py:313-357` `validate_top_level_keys` iterates
`for k in config` — the **root dict only** — and is invoked once from
`factory.py:307-310`. But `KNOWN_MACHINE_KEYS` (`validation.py:279-311`) is
overwhelmingly a list of **state-level** names (`entry`, `exit`, `on`,
`after`, `always`, `invoke`, `onDone`, `initial`, `type`, `states`), which do
their work inside each state, where nothing checks them. `StateNode.__init__`
(`models.py:1544-1601`) reads only the keys it knows via plain `.get()` and
ignores the rest.

**Re-verified this round:**

    $ python probes/main-c78ce99/p7_216_known_keys.py
    KNOWN_MACHINE_KEYS: 26
    a) parser keys NOT in KNOWN_MACHINE_KEYS: []
    b) nested typos under strict_config=True -> ACCEPTED SILENTLY | warnings: []
    c) config strictConfig=true, no kwarg -> RAISED ; config false, kwarg True -> RAISED
    d) nested typos, default mode -> warnings: (none)

Corroborated independently at scale: `u6::F2` 120/120 top-level caught,
**0/120 nested** caught; `p5_livelock_keys.py` 200/200 top-level warned with
did-you-mean and 200/200 raised under `strict_config=True`, while nested
`afer` → a deadline that never fires and `entyr` → an entry action that runs
0×; `x7_config_key_fuzz_216.py` part B 30/30 nested mutations silently
accepted; `d11_sem_3` 17/17 top-level warned vs 17/17 nested silent.

**The top-level half of #216 is flawless** — this is purely a scope gap. But
note the nested case is *worse than the pre-#216 top-level behaviour in one
respect*: it emits **no WARNING either**, so the did-you-mean safety net is
absent exactly where a typo is most likely (state nodes vastly outnumber the
root).

**Not counted as part of the defect** (per `D11-fuzz-3`'s own correct read):
nested *policy* misspellings (`actionErrorPolicyy` under a state) are inert
either way, because policies are read from the root only
(`models.py:1590-1610`). The **structural** keys are the real exposure. The
`D11-soak-2` record, which pins the nested-policy case, is therefore merged
here but downgraded to the structural claim.

**OMS severity: Medium.** `{"states": {"a": {"entryy": [...], "onn": {...}}}}`
builds a clean machine with no entry actions and no transitions, under every
strict setting.

→ **CV-C57 (new): the wrapper must run its own recursive key check over every
state node against `KNOWN_MACHINE_KEYS` at build time. `strict_config=True`
covers only the root.**

**Upstream fix.** Recurse: `KNOWN_MACHINE_KEYS` already contains every
state-level name, so the recursion is the only missing part.

---

## R11-08 — **Medium** — restore then re-persist without `start()` silently drops every armed delayed self-send

**Classification.** LIBRARY-DEFECT (correctness). **New in #213.**
**Merged records:** `D11-concurrency-3`.

**Source.** `from_snapshot` parks records in
`interpreter._restored_self_sends` (`base_interpreter.py:1900-1904`); only
`start()` converts them into live armed sends via
`_rearm_restored_self_sends` (`:1247-1260`), which also *consumes* the list.
`get_persisted_snapshot` builds `scheduled_sends` from `self._armed_self_sends`
only (`_persist_scheduled_sends`, `:1234-1245`) — the live dict, which is
empty before `start()`. The pending list is written by neither path.

**Re-verified this round:**

    $ python battle-c78ce99/concurrency/u3_v3_roundtrip_property.py
      "p2_resnapshot": {"first_hop_records": 1,
                        "second_hop_records_before_start": 0,
                        "fail": "restore -> re-persist WITHOUT start() drops every armed delayed self-send"}

The same run's `p1` property (300 machines) shows the *normal* hop is sound —
0 failures, 0 missing records — so this is specifically the restore→re-persist
path.

**OMS severity: Medium.** Silent, and it is exactly the failure mode #213 was
filed to fix, re-appearing one hop later. A journal-compaction or
snapshot-migration job that loads and re-writes without starting destroys
every deadline.

→ **CV-C58 (new): never re-persist an interpreter that has not been
`start()`ed. Any snapshot-rewriting utility must `start()`, or copy
`scheduled_sends` through verbatim.**

**Upstream fix.** Have `_persist_scheduled_sends` union `_armed_self_sends`
with any unconsumed `_restored_self_sends`.

---

## R11-09 — **Medium** — a `RunawayChainError` trip reaches only `last_error`, which the next event erases; no hook names it

**Classification.** LIBRARY-DEFECT (silent failure). Extends round-10's
`R10-13` with the *clearing* half. **Merged records (2).** `D11-fuzz-2`,
`D11-security-3`.

**Source.** `base_interpreter.py:4165-4174` — `last_error` is
`None if self.last_transition_ok else self._last_action_error`, recomputed
**per processed event**. `interpreter.error` and `status` are untouched by a
chain trip, and no hook carries chain context.

**Re-verified this round:**

    $ python battle-c78ce99/security/n8_last_error_clearing.py
    SYNC/def    last_error@trip=RunawayChainError  interpreter.error=None status=running  after ONE benign send()=None
    ASYNC/def   last_error@trip=RunawayChainError  interpreter.error=None status=running  after ONE benign send()=None
    ASYNC/async last_error@trip=RunawayChainError  interpreter.error=None status=running  after ONE benign send()=None
    HOOKS fired on a chain trip: ['on_action_execute','on_event_dropped','on_event_received',
                                  'on_interpreter_start','on_transition']

All three lanes. **One benign event is enough to erase it.**

`D11-fuzz-2` supplies the timer-driven variant, which is the dangerous one: a
chart arming a 5 ms delayed `SLOW` alongside a zero-delay `FAST` trips 40/40
(ERROR logged, machine permanently inert at n=24, polled to convergence over
12 s and re-checked 2 s later) — yet on **6/40 (`def`) and 8/40 (`async def`)**
runs the post-mortem reads `status='running'`, `last_transition_ok=True`,
`last_error=None`, `pending_events=0`. A permanently inert machine reports
healthy. Intermittent because it races the trip against the next tick;
post-#212, a legal heartbeat guarantees ticks keep arriving, so in an OMS the
race is won by the eraser.

`has_dormant_invocations` / #207's `stranded` do **not** cover this shape (no
invoke involved). Only the log remembers.

**OMS severity: Medium** (High in effect, Medium in classification because a
log-scraping supervisor can see it). This produced **99 false violations** in
the security track's own fuzz harness before the read was latched — evidence
that the observable is genuinely unusable as written.

→ **CV-C59 (new): supervisors must not poll `last_error` for chain health.
Latch `RunawayChainError` from the log or from a latching plugin wrapper; a
poll slower than the event rate cannot observe discarded work.**

**Upstream fix.** Make a chain trip sticky (a `chain_trips` counter or a
dedicated `on_chain_budget_exceeded` hook), as #207 did for stranding.

---

## R11-10 — **Low** — `on_invalid_event` is structurally unreachable on the restore path

**Classification.** LIBRARY-DEFECT (observability / doc-defect). **Merged
records (5).** `D11-concurrency-5`, `D11-fuzz-5`, `D11-semantics-2`,
`D11-security-4`, `K7`, plus `P-3` (a).

**Source.** `_admit_restored` (`base_interpreter.py:1211-1232`) does call
`_report_invalid_event`, which iterates `self._plugins` (`:1304-1306`). But it
runs inside the `from_snapshot` classmethod (`:1908-1915`), which is still
*constructing* the interpreter. `from_snapshot` takes no `plugins=` parameter,
and the only registration path is `interpreter.use(p)` on the object
`from_snapshot` has not yet returned. **No ordering exists** in which a plugin
observes a restore refusal.

**Re-verified this round:**

    $ python probes/main-c78ce99/p5_214_strict_lane.py
    a) last_error BEFORE start(): UnknownEventError
       last_transition_ok: False
       on_invalid_event seen at restore time: []
       after start(): states = ['strictm.a']

Corroborated: `n11_restore_strict_214.py` — `on_invalid_event=[]` in **all 10
cells** (5 record shapes × both engines) while `last_error` is set and the
WARNING is logged; `d11_sem_2` `{'on_invalid_event_calls': 0}` both kinds;
`w8_214_hook.py` 4/4 per lane.

This contradicts the #214 CHANGELOG claim that the refusal *"is reported
(`on_invalid_event`, `last_error`)"*. **The drop and the WARNING are real; the
`last_error` half works but only before `start()`** — two tracks
(`D11-fuzz-5`, `D11-concurrency-5`) show `last_error` reverting to `None`
after `start()` once one legitimate neighbouring record is present (shared
root cause with R11-09's per-event reset), and it holds only the **last**
refusal, so with *n* refusals *n−1* are lost from that channel too.

**The library's own pin does not notice**: `tests/test_round10_findings.py:305-313`
constructs `_Invalid()`, calls `r.use(plug)` *after* the restore, and asserts
only on `last_error` — never on `plug.seen`.

→ **CV-C60 (new): the restore routine must read `last_error` /
`last_transition_ok` immediately after `from_snapshot` and before `start()`,
and must treat the count of admitted records vs. persisted records as the
authoritative refusal signal. Do not register `on_invalid_event` expecting
restore coverage.**

**Upstream fix.** Add `plugins=` to `from_snapshot`, or defer the refusal
report to `start()`.

---

## R11-11 — **Low** — `structure_hash` omits `raise(delay=)` delays although it covers `after` delays

**Classification.** LIBRARY-DEFECT (drift-detection gap). **Merged records
(2).** `D11-fuzz-4`, `u3::p5_hash`.

**Source.** `persistence.py::_node_shape` includes
`"after": sorted(str(d) for d in node.after)` but excludes action params by
design.

**Re-verified this round:**

    $ python battle-c78ce99/concurrency/u3_v3_roundtrip_property.py
      "p5_hash": {"hash_delay500": "590631a050c17318",
                  "hash_delay900": "590631a050c17318"}

`p1_v3_roundtrip.py` § B is the sharper form: changing `delay: 60000` to
`delay: 100` in a `raise` action leaves the hash byte-identical at
`9d405469b8afe69d`, and a v3 snapshot carrying a **60 000 ms** armed send
restores against the **100 ms** chart without complaint and still waits the
full 60 s — verified by advancing a `SimulatedClock` 30 s (still in `a`) then
30.1 s (moves to `b`).

**Why it is a defect and not just a design choice.** Excluding action params
in general is defensible, but it is **asymmetric with `after`**, and #213 has
now made a `raise` delay *persistent state* — exactly the drift a fingerprint
exists to catch. A chart change that shortens a deadline will not invalidate
snapshots carrying the old one.

→ **CV-C61 (new): the wrapper's own contract fingerprint must hash
`raise(delay=)` params; `machine_hash` alone does not detect a deadline
change.**

---

## R11-12 — **Low** — the priority `lane` is persisted but not honoured on restore on the sync engine

**Classification.** LIBRARY-DEFECT (engine-parity gap). **Merged records:**
`D11-security-5`.

**Source.** `SyncInterpreter` has a single queue by construction (no
`_priority_queue`), so the `lane` field #214 persists is honoured on the async
engine only.

**Evidence.** `n1_persistence_v3.py` § D (sync) → `['EXT', 'after.1000.l.w']`;
`n2_rearm_lane_parity.py` (async) → `['after.1000.l.w', 'EXT']`. A restored
deadline loses its precedence on the sync engine.

Not a lost *live* guarantee — the sync engine never had lanes — but #214
persists a field one engine cannot honour, so cross-engine restore is not
order-equivalent.

→ Pairs with R11-02(c): `lane` is both **unenforceable on sync** and
**forgeable on async**. The wrapper must not depend on restored ordering at
all.

---

# Non-library classifications

## DESIGN-CONSTRAINT (not defects)

### R11-DC-1 — descent-seeded chains get ~`limit+2` laps, external-seeded ~`limit/2`
**Merged:** `P-4` (c), `OBS-PLATEAU`, `R9-DOC-01`.
Intended #215/#77 parity: the sync drain gives the initial descent's raises
seed standing, and the async engine was brought to the *sync* number. Measured
and deterministic: at `maxIterations=6`, descent-seeded = **8** laps,
external-seeded = **3**. On the plateau question, `q3_sharp.py` § A (4 shapes ×
2 lanes, polled to convergence) settles the CHANGELOG's own contradiction
(#207 says `maxIterations+2`, #210 says `+3`): **`+3` only for seed standing**
(B7 native seed, limit 7 → plateau 10; sweep over limits {3,5,7,9} gives
`limit+3` at every point) and **exactly `+2` for an externally kicked cycle**
(B6 limit 5 → 7, B9 limit 6 → 8, B10 limit 4 → 6), identical cell-for-cell in
the `def` lane. The library's own pin (`test_round9_findings.py:610`) asserts
`1000+2`, i.e. the external case.
→ **CV-C62: any runbook asserting `+3` for an externally triggered cycle is
reliably wrong by one; budget sizing against the external number
under-provisions the descent case by ~2.7×.** The `#210` CHANGELOG sentence is
a genuine (trivial) doc defect and is worth sending upstream as such.

### R11-DC-2 — `after` deadlines are not persisted while `raise(delay=)` is
**Merged:** `CV78-T1`, `W-10-02`, `OBS-213`, `K3`.
#213's v3 `scheduled_sends` covers **delayed self-sends only**; #128
deliberately excludes `after`. Both documented, both intentional — but they
are visually interchangeable in a chart, and the default restore parks the
state forever while `restart_timers=True` restarts the deadline from zero.
This is the constraint that collides with **R11-04** (the `raise(delay=)`
handle leak): the only persistent deadline primitive is the leaking one.

## NEEDS-WRAPPER

| ID | Merged from | Constraint |
|---|---|---|
| R11-W-1 | `W-10-01` | Catalogue deadlines realised as `raise(delay=)` must declare a **stable `send_id`** — #213 keys `scheduled_sends` by it, and `cancel`/`rearm` address it. An auto-generated id leaves a restored deadline unaddressable. |
| R11-W-2 | `OBS-BUILTIN-SHADOW` | **Never register a user action whose name collides with a built-in** (`raise`, `send`, …). A collision silently disarms the built-in: `beats=0`, `last_error=None`, no warning, no error — total and completely silent. Filter registrations through `xstate_statemachine.actions.is_builtin` and lint the catalogue. |
| R11-W-3 | `D11-security-6`, `R10-12` | **`SimulatedClock` does not fire restored `scheduled_sends`** (nor `after`). A 1000 ms `raise(delay=)` persists correctly as `remaining_ms: 1000.0`, but `clock.increment(2.0)` + a pump leaves the machine in `h.a`. Deadline properties must be verified against the real clock on this build; the real-clock property was verified 300/300. |

## SUPERSEDED-RULE

**R11-S-1** — `issues/verify-main-19cb1f1/206_delayed_selfsend_charged.py`
(PASS @ `19cb1f1` → FAIL ×5/5 @ `c78ce99`), plus record `A`
(`attack_a_superseded_206`). This is **our test encoding the #206 rule**,
which #212 deliberately reverses. Not a regression. Per `60-r11-regression.md`
this is the **single** stable PASS→FAIL delta across the 163-check gate and
the 527-script sweep — the whole round is otherwise regression-free.
→ **Action: retire this script from the gate**, or it becomes one permanent,
meaningless blocking FAIL.

## HARNESS-ERROR

**R11-H-1** — the four parallel-sweep FAILs (`167_rollback_reinvoke_spin.py`
and neighbours) that pass 5/5 serially, and the stale `107`/`154`/`158`
probes reaching into `i._priority_queue`, whose elements have been
`(event, bool)` tuples since round-8 `061d619`. Both pre-date this round;
recorded so they are not re-counted.

## OUR-CONTRACT-DEFECTs (carried, re-verified at `c78ce99`)

None of these are library behaviour; all are fixable in our catalogue JSON.
Both blockers re-reproduced **fresh this round on both action kinds**.

| ID | Sev | Status at `c78ce99` |
|---|---|---|
| **C-04** | **Blocker** | **STILL PRESENT, open six rounds.** `B16.elevation.elevated` omits `LOGOUT` / `IDLE_DEADLINE` / `ABSOLUTE_DEADLINE`. Re-run: `["session.auth.revoked","session.elevation.elevated"], still_elevated: true` for all three kill events. A dead session stays elevated and can be re-elevated. Refuted as a library defect in round 10 (`REVOKE`, listed in both regions, clears correctly — engine dispatch is sound). Fix: hoist the four revocation events onto the root. Merges `C-04b` (re-elevation unaudited) and `C-04c` (post-revoke `STEP_UP_OK`) as the same missing-handler root. |
| **C-07b** | **Blocker** | **STILL PRESENT, open six rounds.** Re-run, both kinds: denied `RELEASE` → `status='error'`, `UnhandledEventError`; the subsequently authorised `RELEASE` returns `ok=True` but `final=['kill_switch.engaged']`, `bricked: true`. Documented opt-in policy (`onUnhandled: 'error'` + #170: a guard-denied event is unhandled). The round-6 Amendment-6 removal **still has not landed in the JSON**. Fix in config alone: an ordered unguarded `RELEASE` fall-through arm. |
| CD-B8 | High | `B8.sl.attaching` retries with no chart-level bound; parks with a live position, no stop-loss, `raise_critical_alert=0`, `stranded=[['position_protection.sl.attaching','att']]`. B6 and B10 bound their equivalents; B8 does not. Config fix: cap `attach_attempts`. |
| K10 | High | Idempotency: the mandated R6-03 rollback+onDone storm places `place_order` **128× (async) / 91× (def)** on B1 and `submit_child` **208× / 126×** on B5 before the chain cut. Library-correct (rollback ⇒ re-enter ⇒ re-invoke; #207 makes the strand observable). **An idempotency key on every order-placing service is mandatory.** |
| C-06 | High | `B19.stale_lockout` handles `RECONNECTED` only; `OPERATOR_RESOLVED` is deferred, so on a venue that never reconnects cleanly the only exit is a process restart. |
| CD-01 | High | Carried from `battle-f28719c` unchanged; nothing at `c78ce99` affects it. |
| K11 | Medium | **No timers declared in any chart**: all 20 catalogue machines have zero `after` transitions and zero `raise(delay=)` actions (`after=[] delayed_sends=[]`, every driver snapshot reads `v=3:sched=0`). Every deadline is a host-side timer an action stamps. #213 exists precisely to make deadlines restart-safe and **we cannot use it until the deadlines move into the charts** — which in turn exposes us to R11-04. |

## Library-verified passes (no defect; recorded to prevent re-litigation)

`K1`–`K6` (#216 clean on B1–B5; #212 reversal on a real B5 refill cycle, 40
beats / 21 laps with live invokes; #213 `scheduled_sends` 4000.0 ms + `send_id`
round-trip; #214 strict-on-restore for `pending_events`; #207 plateau
`maxIterations+2` on B18/B19 with `on_invocation_stranded`,
`has_dormant_invocations`, `pending_invocations()` all answering; #204 no-arm
on a state exited within its entry macrostep), `LD-01` (round-9 def-lane leak
**CLOSED** by #204, 4/4 cells, def lane now 52/52), `OBS-216` (0 unknown
top-level keys across B6–B10; positive control raises), `OBS-212`, `OBS-213`,
`CV78-L0` (zero new library findings on B16–B20), `B`–`F`
(v3 round-trip honours remaining delay over 60 trials; forged `engine:true`
record with a mismatched `after`-id does **not** fire; 200 machines × 1 ms
heartbeat clean; livelock fuzzer 60 configs), `i1-delayed-raise-pingpong-212`,
`p1_v3_roundtrip` 300/300.

Two of these deserve emphasis as **genuine hardening that held under attack**:
the v3 gate refuses every unflagged forged record (every R11-01 control row),
and #204 closed a real cross-engine leak.

---

# Constraint deltas for the CandleViewer register

**New constraints this round:** CV-C50 … CV-C62 (defined inline above).

**The unresolvable tension.** R11-04 says *do not use `raise(delay=)` for
periodic work* (unbounded handle leak, +753 MB / 90 s). R11-DC-2 + K11 say
*deadlines must be `raise(delay=)`* because `after` is not persisted and our
charts currently carry no timers at all. **The wrapper cannot satisfy both.**
Until R11-04 is fixed upstream, the only safe posture is:

- deadlines that must survive restart → `raise(delay=)` with a stable
  `send_id` (R11-W-1), **bounded interpreter lifetime**, and monitoring of
  `len(i._timer_handles.get(i.id, []))`;
- everything periodic and non-persistent → `after:`;
- **no** high-frequency `raise(delay=)` heartbeat under any circumstances.

**Effect on the row-8 ADOPT** (`59-r10-final-readiness-verdict.md`). The
round-10 fixes are real and Phase 3 need not stop, but the ADOPT **must not be
carried forward unamended**. Three items are new-at-this-commit and block an
unqualified carry-forward:

1. **R11-01 (Blocker)** — a security *regression*, not a pre-existing gap.
   Gated by CV-C52 + CV-C53; both are cheap and must land before any restore
   path ships.
2. **R11-05 (High)** — voids `maxIterations` as a liveness bound. Gated by
   CV-C50 + CV-C55.
3. **R11-04 (High)** and **R11-06 (Medium)** — a new unbounded memory leak and
   a new silent `start()` hang, both created by this round's changes.

Recommended posture: **ADOPT-WITH-CONDITIONS**, conditions = CV-C50 … CV-C62
implemented and linted, plus the two open OUR-CONTRACT blockers (C-04, C-07b)
finally landed in the catalogue JSON after six rounds.

# What to send upstream

In priority order: **R11-01** (Blocker, one-line premise error with a clean
fix), **R11-04** (one-line owner fix), **R11-02** (compose the two round-10
fixes), **R11-05** (time-aware floor), **R11-06** (bound the gate), **R11-07**
(recurse the existing key list), then R11-08 … R11-12 and the `#210` plateau
doc contradiction.
