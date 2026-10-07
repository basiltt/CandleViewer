# Battle track: SEMANTICS @ `c78ce99`

**Library:** `_ref/xstate-statemachine` @ `c78ce99` (merge of #217; unreleased
0.8.1, `__version__` still reports 0.8.0 — keyed on the commit).
**Scope:** round-11 re-verification of the round-10 semantics defects, a full
re-run of the prior suite on **both service lanes**, plus new attacks aimed at
this round's two semantic reversals — **#212** (a delayed self-send is a
timer, not a chain; supersedes #206) and **#213/#214** (snapshot layout **v3**
with `scheduled_sends`, strict-on-restore, lane and provenance) — together
with **#215** (three-lane lap parity) and **#216** (unknown top-level keys).

**Scripts** (all standalone — stdlib + `xstate_statemachine` only, every
helper inlined, proven from neutral cwd `<home>`):
`battle-c78ce99/semantics/{p_persistence,c_concurrency,f_fuzz,s_semantics_sec,k_soak}.py`.
Repro under `repro/`, machine-readable results under `results/`.

Financial-OMS standard applied throughout: nothing is counted as a defect
without a standalone repro that reproduces on a clean interpreter, and every
service/action-bearing check runs with **both `def` and `async def`**.

---

## 1. Prior-defect table (round 10 → round 11)

| Prior | Title | R10 severity | **R11 status** | Evidence |
|---|---|---|---|---|
| **D10-semantics-1** (R9-01 / D9-semantics-1, widened) | A genuine engine completion or `after` event is **re-typed** by `_replace` into any other descriptor, defeating #195 / #203 | High | **STILL-PRESENT — unchanged** | Prior `s_semantics_sec::S2` re-run at `c78ce99` is unchanged; #212–#216 touch the chain budget, the snapshot layout and config validation, none of which is the `_replace` route. The remedy shape (bind the marker to `(type, src)` at mint time, or override `_replace` on the private subclasses to return the **public** class) is still unapplied. Not re-counted as a new defect this round. |
| **D10-semantics-2** (R9-13) | `strict` does not gate events restored from a snapshot's `pending_events` | Low | **FIXED (by #214) — with one half of the promise still missing** | The behavioural half is genuinely closed: `P4` shows a restored undeclared event is refused and dropped (`last_error = UnknownEventError`, machine stays in `L.a`) while a declared one restores and drives its transition, on **both kinds**. The **observability** half is not — see **D11-semantics-2**. |

### 1b. Prior-suite whole-run (round-10 scripts, both lanes, at `c78ce99`)

| Script | Result at `c78ce99` | Note |
|---|---|---|
| `battle-19cb1f1/semantics/p_persistence.py` | **4/4 PASS** (was 4/4) | P1 / P3 / P4 / P5 all still hold; P5's 300-machine property is clean |
| `battle-19cb1f1/semantics/c_concurrency.py` | **4/4 PASS** (was 4/4) | C1–C4 unchanged |
| `battle-19cb1f1/semantics/s_semantics_sec.py` | unchanged (`S2` still FAIL = D10-semantics-1) | the open `_replace` finding |

**No regression.** Every round-10 check that passed still passes.

> ⚠️ **A round-10 harness error, found and corrected this round.** The prior
> `C1` and `P4` claimed to exercise a "`raise(delay=1ms)` self-ping-pong" via
> `interp.send("P", delay=1)`. **`delay` is not a `send()` keyword** — it is a
> parameter of the built-in **`raise` action** (`actions.py:186-202`;
> `send()`'s only options are `wait` and `priority`, `_RESERVED_SEND_KWARGS`
> at `base_interpreter.py:2367`). So `delay=1` was swallowed into the event
> **payload** and those tests measured a **zero-delay** chain. That is why
> they reported "every machine trips at lap 12" and still do at `c78ce99`:
> they never tested the #206/#212 rule at all. Every delayed-send check in
> this round's scripts uses the real action form,
> `{"type": "raise", "params": {"event": "P", "delay": 1}}`. The #206 pins
> those two tests were read as confirming should be regarded as **untested**
> before this round, not as superseded.

### 1c. #206 → #212: SUPERSEDED, and the new rule verified

`repro/d11_sem_212_heartbeat.py` (exit 0 == the new rule holds), both kinds:

| Shape | beats @1.0 s | still beating | chain drops | `last_error` |
|---|---|---|---|---|
| `after: 1` ping-pong | 66 / 65 | ✅ | 0 | `None` |
| `raise(delay=1)` ping-pong | **66 / 65** | ✅ | 0 | `None` |
| `raise(delay=50)` ping-pong | 17 | ✅ | 0 | `None` |
| `raise(delay=0)` (zero) ping-pong | 12 | ❌ (correct) | 1 | `RunawayChainError` |

The delayed raise is now **beat-for-beat identical to `after` at the same
period** (`S3`: `after_vs_raise_delay_beat_gap = 0` on *both* kinds), and the
zero-delay cycle still trips. **#206's rule is SUPERSEDED, not failed**, and
the new #212 rule is verified positively (liveness, not merely "no
exception").

---

## 2. New attacks on this round's machinery

| ID | Attack | Result |
|---|---|---|
| `P1` | **v3 round-trip property**: 300 random machines with an **armed `raise(delay=)`** self-send at a random remaining delay, snapshotted mid-flight on a **`SimulatedClock`**, restored on a fresh clock | **PASS** — 300/300. Every snapshot is `version: 3` and carries exactly one `scheduled_sends` record; `remaining_ms` matches the true remaining delay to **1e-6 ms**; `send_id` survives; on restore the timer does **not** fire at `remaining − 0.001 ms` and **does** fire at `remaining + 0.001 ms`. #213's central claim holds exactly |
| `P3` | 🎯 **The question this round**: a **forged v2-shaped record** minting an engine event — `done` / `error` / `after`, at v2 vs v3, flagged vs unflagged | **FAIL → D11-semantics-1** — a forged `after` record that is correctly **refused at v3** is **trusted at v2** and fires a 24-hour timer instantly. `done` / `error` forgeries do not reach a terminal on this chart (their `onDone` is guarded by a live invoke), so the blast radius demonstrated is `after` |
| `P4` | **#214 restore-strict matrix**: declared vs undeclared user records under `strict`, both kinds | **PASS behaviourally, FAIL on observability → D11-semantics-2** — the undeclared event is refused (`last_error = UnknownEventError`) and dropped; the declared one restores and drives its transition. But `on_invalid_event` fires **0** times, not once |
| `C1` | **200 machines** (100 `def` + 100 `async def`) × **1 ms `raise(delay=)` ping-pong for 10 s** — CPU bounded by the clock, no `RunawayChainError` | **PASS** — 100/100 per kind **still beating** at the end, **0** runaway errors, **0** `chain_budget` drops, and the work is **clock-bounded**: ~1,230 beats over 10.01 s = **122.9 beats/s** (`def`) / 119.1 (`async def`) per machine. A chain would be orders of magnitude higher. This is the scale evidence for #212 |
| `C2` | **MIXED** chain: one step arms a delayed raise **and** a zero-delay raise | **PASS** — trips on both kinds (`RunawayChainError`). The delay exemption does **not** launder the zero-delay half |
| `C3` | **#215 descent-settle wait** under **100 concurrent `start()`s** with `always` cycles, 5 s watchdog | **PASS** — no hang (0.01 s for all 100), **1 distinct configuration** per kind (`s.b`), both kinds |
| `C4` | **200 v3 snapshots carrying `scheduled_sends` restored CONCURRENTLY** | **PASS** — 100/100 snapshots per kind carry the record, and 100/100 restored machines re-arm and wake |
| `F1` | **Livelock fuzz with the NEW #212 oracle**: 500 configs × {`def`, `async def`} × {sync, async} over `always` / `raise0` / **`raise_delay`** / `after` / **`mixed`** / `invoke` cycles, 3 s watchdog. Oracle: a cycle self-fed only by a delay ≥1 ms is **legal periodic work** (must NOT trip **and** must still be beating); a zero-delay cycle **must** trip | **PASS** (see §2b) — perfect separation, 0 hangs |
| `S1` | **#216 config-key fuzzer**: 17 realistic misspellings of behavioural keys, at **top level** and at **nested state level** | **Top level PASS** — 17/17 warned, **17/17 with a did-you-mean hint**, 0 silent, and `strict_config=True` raised `InvalidConfigError` on all 17. **Nested level → D11-semantics-3** — 17/17 silently dropped, *including* under `strict_config=True` |
| `S2` | **`strict_config` bypass**: the `x-` escape, and whether a payload can select its own level of checking | **PASS** — an `x-actionErrorPolicy` key is accepted **and inert** (the policy stays `continue`); config-level `"strictConfig": true` refuses; and a config **cannot** turn an explicit `strict_config=True` back **off** — `"strictConfig": false` in the payload does not override the argument |
| `S3` | **#212 rule matrix**: `raise(delay=)` at 1 ms / 50 ms / zero / **cancelled by id**, against the `after` rule it now mirrors | **PASS** — periodic shapes live and never trip; zero trips; a **cancelled** delayed self-send feeds nothing and correctly parks without tripping (1 beat). **`after_vs_raise_delay_beat_gap = 0`** on both kinds |
| `S4` | **Determinism**: 50 identical runs (transition trace + drops) on **both engines** and **both kinds**, plus **50 `scheduled_sends` restore** traces | **PASS** — **1 distinct trace** in all four lanes, including the restore lane |

---

## 3. Defects

### D11-semantics-1 — `"version": 2` in the payload mints a trusted engine event; the attacker chooses the version (**High**)

**Repro:** `repro/d11_sem_1_v2_upcast_mints_after.py` — exit 1 == reproduced.
Deterministic, reproduces on **both** service kinds.

```
v3_unflagged/plain : state=['t.a']            last_error=UnknownEventError  MINTED=False
v2_same_record/plain: state=['t.margin_called'] last_error=None             MINTED=True
v3_unflagged/async : state=['t.a']            last_error=UnknownEventError  MINTED=False
v2_same_record/async: state=['t.margin_called'] last_error=None             MINTED=True
```

The **identical record** — `{"type": "after.86400000.t.a", "kind": "after"}`,
no `engine` flag — is **refused at v3** and **trusted at v2**. A 24-hour
margin-call timer fires immediately, on a `strict: true` machine, with
`last_error = None`.

**Root cause.** #214's upcast (`persistence.py:436-447`) reasons: *"A v2
writer had exactly ONE minter of `done` / `error` / `after` records — the
engine itself… So a v2 record of those kinds IS an engine completion and is
upcast as one."* That inference is sound about **genuine** v2 payloads and
unsound about **hostile** ones, because **`version` is a field of the payload
being judged**. `upcast()` is reached from `from_snapshot` after
`check_version`, and nothing binds the declared version to any evidence that
the blob is actually of that vintage. The forger writes `"version": 2` and
`setdefault("engine", True)` does the minting for them.

This is precisely the property #203 was written to establish — *"a hand-built
event or a forged snapshot record fired a 60-second timer instantly"* — and
#214 re-opened it through a door #203 never guarded: not by weakening the v3
gate (which `P3` confirms is intact: `after_v3_unflagged` and
`done_v3_unflagged` are both refused) but by adding a **version-selected
bypass** around it.

**Severity High, not Blocker.** The library is explicit that a snapshot is
trusted input and that a party controlling the blob already owns `state_ids`
and `context` (`base_interpreter.py:1677-1690`, `events.py:418-420`). Against
an attacker with *full* blob control this changes little. It is High because
(a) it silently **reverses** a property the same release advertises as
closed, (b) it is reachable by a party with only *partial* influence — anyone
who can inject or replay a **legacy-looking** payload, e.g. a migration
pipeline or an archived-snapshot store, without touching `state_ids`, and
(c) `minimum_version=3` is the only defence and it is **off by default**
(`minimum_version: int = 0`).

**`file:line`:** `src/xstate_statemachine/persistence.py:436-447`
(the v2→v3 `setdefault("engine", True)` block); reached from
`base_interpreter.py:1802` (`check_minimum_version`, default `0`) and
`events.py:421` (`trusted = record.get("engine") is True`).

**Remedy shape.** Do not let the payload's own `version` grant trust. Either
(i) require `minimum_version=3` for any machine that has `after` / `invoke`
(make the floor opt-**out**, not opt-in), or (ii) upcast a v2 completion to a
**non-firing** record — restore the deadline without the engine flag, so a
persisted timer is re-armed by the engine rather than delivered as an already
-fired completion, or (iii) gate the upcast on an out-of-band vintage signal
the payload cannot write.

**Wrapper mitigation (available today, and effective):** always call
`from_snapshot(..., minimum_version=3)`. This must become a **hard constraint**
on the adoption wrapper — it is the whole defence.

### D11-semantics-2 — #214's `on_invalid_event` on restore is structurally unreachable (**Low**)

**Repro:** `repro/d11_sem_2_restore_invalid_hook.py` — exit 1 == reproduced,
both kinds.

```
{'last_error': 'UnknownEventError', 'event_dropped': True,
 'on_invalid_event_calls': 0}
```

The CHANGELOG says a refused restored event is *"reported
(`on_invalid_event`, `last_error`) and the event dropped"*. Two of the three
hold. The hook does not, and **cannot**: `_admit_restored` reports through
`_report_invalid_event`, which iterates `self._plugins`
(`base_interpreter.py:1304-1306`), but `from_snapshot` **constructs** the
interpreter at `base_interpreter.py:1822` and runs the entire restore —
including every `_admit_restored` call — before returning. There is no
`plugins=` parameter on `from_snapshot`, so the earliest a caller can attach
a plugin is `.use()` on the **returned** object, by which time the refusal
has already happened.

The task's requirement was "`on_invalid_event` on restore **exactly once**";
the observed value is **exactly zero**, for every kind and every machine.

**Severity Low** — `last_error` *is* set, so a caller who polls it after
`from_snapshot` can still detect dropped traffic; the loss is the push-based
half. It is worth recording because a plugin-based audit trail (which is the
natural OMS shape) will silently miss restore-time drops.

**`file:line`:** `src/xstate_statemachine/base_interpreter.py:1822`
(construction after which restore runs to completion) vs
`base_interpreter.py:1211-1232` (`_admit_restored` → `_report_invalid_event`).

**Remedy shape.** Add `plugins=` to `from_snapshot` and register before the
restore loop; or defer refusal reporting to `start()`, replaying the
accumulated refusals through the hooks once plugins can exist.

### D11-semantics-3 — #216 validates only the TOP level; a misspelled key inside a state is silently dropped, even under `strict_config=True` (**Medium**)

**Repro:** `repro/d11_sem_3_nested_keys_silent.py`; `S1`'s nested matrix.

`S1` at top level is a clean pass — **17/17** misspellings warned, **17/17**
with a did-you-mean hint, **17/17** refused under `strict_config=True`. One
nesting level down, **17/17 are silently accepted**, *including* under
`strict_config=True`:

```
typo_onn/default/plain       : entry_fired=1  state=['n.a']   # GO did nothing
typo_onn/strict_config/plain : entry_fired=1  state=['n.a']   # still nothing
   (identical on the async kind)
```

A state written `{"entry": "mark", "onn": {"GO": "b"}}` builds without a
warning and simply **never transitions**. This is the exact failure mode
#216 exists to prevent — *"a misspelled policy key was silently dropped and
the policy reverted to its permissive default"* — one level down, and
arguably worse: a dropped `on` / `entry` / `invoke` / `after` removes
**behaviour**, not just a policy default, and the machine is then wrong in a
way no test of the config can see.

**Root cause.** `validate_top_level_keys(config, strict_config=...)` is
called once, on the root dict (`validation.py:314-359`); `KNOWN_MACHINE_KEYS`
(`validation.py:279-311`) mixes machine-level and state-level names but is
never applied to `StateNode` construction, which reads only the keys it
knows and ignores the rest.

**Severity Medium** — build-time, deterministic, and caught by any test that
exercises the transition; but `strict_config=True` is precisely the switch a
careful adopter turns on to be told about typos, and it answers "clean" here.
The promise is narrower than it reads.

**`file:line`:** `src/xstate_statemachine/validation.py:314`
(`validate_top_level_keys`, root only); call site `factory.py:307-310`;
unchecked consumer `models.py:1544-1601` (`StateNode` / `MachineNode`
`config.get(...)` reads).

**Remedy shape.** Walk the tree: apply the same unknown-key check with a
state-level key set at every `states` node, with the same
warn/`strict_config`-raise disposition. The did-you-mean machinery is
already written.

**No new defect was found in #212, #213, #215, or in the top-level half of
#216.** Every attack aimed at those landed clean, several at 5–20× the
volume of the round-10 checks.

### D11-semantics-4 — a `raise(delay=)` heartbeat leaks one timer handle **per beat**, unboundedly: the liveness #212 legalises has no reclamation (**High**)

**Repro:** `repro/d11_sem_4_timer_handle_leak.py` — exit 1 == reproduced,
both kinds. Found by the 90 s soak (**+753 MB RSS**, against round-10's
+1.2 MB) and isolated to the heartbeat alone, with no external traffic.

| Shape (10 s run) | beats | `_timer_handles` retained | **per beat** |
|---|---|---|---|
| `after: 10` ping-pong | 625 / 610 | **1** | 0.002 |
| `raise(delay=10)` ping-pong | 617 / 607 | **617 / 607** | **1.0** |

Growth is strictly linear and never reclaimed:

```
t= 5s beats= 376 timer_handles= 376   rss +0.50 MB
t=10s beats= 689 timer_handles= 689   rss +1.04 MB
t=15s beats=1001 timer_handles=1001   rss +1.54 MB
t=20s beats=1309 timer_handles=1309   rss +2.04 MB
t=25s beats=1618 timer_handles=1618   rss +2.54 MB
```

**Root cause.** The handle bookkeeping was written for `after` timers, which
are **owned by a state** and reclaimed when that state is exited —
`interpreter.py:2557`, `for handle in self._timer_handles.pop(state.id, [])`.
A delayed self-send is registered under **`self.id`**
(`interpreter.py:2354`, `self._timer_handles.setdefault(self.id, []).append(handle)`)
— the *machine*, which is never exited while running — and the entry is
**not removed when the timer fires**. `_fire` / `_cancel`
(`interpreter.py:2323-2387`) correctly clean up `_armed_self_sends` (#213)
and `_scheduled_sends`, and the repro confirms both stay at ~0; only
`_timer_handles` grows. The list is cleared solely at `stop()`
(`interpreter.py:1514-1517`).

**This is a direct consequence of #212**, and is why it did not exist
before. Under #206 a delayed ping-pong tripped at `maxIterations` and the
list stopped growing at ~12 entries. #212 deliberately removed that bound —
correctly, per the new rule — but the reclamation path that `after` has was
never added to the delayed-self-send path. The two shapes are now
semantically equivalent by design (`S3`:
`after_vs_raise_delay_beat_gap = 0`) and differ only here.

**Severity High.** The exact use case #212 was introduced to enable — *"a
self-paced heartbeat or poller"*, *"a `raise(delay=)` heartbeat of any period
runs indefinitely"* — is the use case that leaks, and it leaks in proportion
to uptime. A 50 ms heartbeat accrues ~20 handles/s, ~1.7 M/day per machine;
the soak's 200 machines reached **+753 MB in 90 seconds**. For a long-running
OMS process this is an availability defect, not a tidiness one. It is not a
Blocker only because it is trivially attributable, bounded by process
lifetime, and avoidable today by using `after` instead.

**`file:line`:** `src/xstate_statemachine/interpreter.py:2354`
(registration under `self.id`) and `interpreter.py:2323-2340` (`_fire`, which
settles the #213 debt but never discards the handle); contrast the correct
reclamation at `interpreter.py:2557`. The sync engine has the same shape at
`sync_interpreter.py:1198` vs `sync_interpreter.py:1488`.

**Remedy shape.** In `_fire` and `_cancel`, discard the handle from
`_timer_handles[self.id]` alongside the existing `_armed_self_sends.pop`
— the handle box is already captured in both closures. Equivalently, make
`_timer_handles[self.id]` a `set` and remove on fire.

**Wrapper mitigation:** prefer `after` over `raise(delay=)` for any
long-lived periodic work until this is fixed; the two are now semantically
identical, so this costs nothing.

### 2b. `F1` — the livelock fuzz, in full

**500 configs × {`def`, `async def`} × {sync, async} = 1,334 runs, 3 s
watchdog, 0 hangs, 0 findings.** The new #212 oracle separates the shapes
perfectly, with no cell ambiguous:

| Shape | runs | oracle | tripped | periodic & still beating |
|---|---|---|---|---|
| `always` | 168 | trip | **168** | — |
| `raise0` (zero-delay) | 168 | trip | **168** | — |
| `mixed` (delayed **+** zero in one step) | 166 | trip | **166** | — |
| `invoke` (completion cycle) | 166 | trip | **166** | — |
| `raise_delay` (≥1 ms) | 166 | **periodic** | **0** | **166** |
| `after` | 166 | **periodic** | **0** | **166** |

The two periodic rows are the round's headline: **0/166 cut** and
**166/166 still beating** at the end of the window — the liveness assertion,
not merely "no exception raised". `raise_delay` and `after` are now
indistinguishable, and `mixed` confirms the delay exemption cannot be used
to launder a zero-delay cycle.

### 2c. `K1` — soak (90 s, reduced; see §4)

200 machines (100 `def` + 100 `async def`), `raise(delay=)` heartbeats at
10–50 ms, a continuous external priority producer, and chaos v3
snapshot/restore every 2 s:

| Metric | Value |
|---|---|
| External sends issued | **787,400** |
| External actions fired | **787,400** |
| **External dropped** | **0** (no drops of any reason) |
| Heartbeats delivered | 456,717 |
| **Heartbeats still alive at the end** | **200 / 200** |
| Runaway errors | **0** |
| Chaos snapshots | 320, of which **256 carried `scheduled_sends`** |
| Chaos restores succeeded | **320 / 320**, 0 errors |
| CPU | 99.6% (one core, 200 machines) |
| **RSS growth** | **+753 MB** → **D11-semantics-4** |

Everything the soak was built to check passed. The RSS figure is the
finding, and it is not the soak's own doing: it reproduces with a **single**
machine and no external traffic (§ D11-semantics-4).

*(A first soak run reported 440/440 chaos errors; that was my harness
rebuilding the chaos machine without its `MachineLogic`, so every restore
raised `ImplementationMissingError`. Corrected, and the corrected run is the
one tabulated. Similarly `C2`'s first pass targeted the zero-delay `Z` back
at its own state — a self-target that never re-enters — and reported a false
"did not trip"; corrected to a genuine `a → b → a` cycle, it trips on both
kinds. Both notes are recorded in the scripts.)*

---

## 4. Not covered / reduced, with reasons

| Area | Status |
|---|---|
| **12-minute soak** | **Reduced to 90 s** (`k_soak.py`, `SOAK_SECONDS` env-overridable). The full 12 minutes does not fit this task's 20-minute wall-clock bound alongside the 1,334-run fuzz, the 300-machine persistence property and the dual-lane prior-suite re-run. The reduction is **not** masking anything this round: the one long-horizon risk it exists to catch — memory growth — was **caught at 90 s** and then reproduced in 25 s on one machine (D11-semantics-4). Recommend `SOAK_SECONDS=720` unattended once that fix lands, to confirm the leak is the *only* drift. |
| **`machine_hash` covers `scheduled_sends`** | **Not answered — and the question is mis-posed.** `structure_hash` is documented (`models.py:1808-1823`) as a fingerprint of the machine's *structure* — states, transitions, guard/action names, `after` delays — not of any runtime payload. `scheduled_sends` is runtime state, like `context` and `state_ids`, which the hash also does not cover. So "does the hash cover it" has the answer "no, by design"; the meaningful question is whether the *`delay` literal* in a `raise` action participates in the hash (so that editing the period invalidates old snapshots), and I did not test that. **Gap.** |
| **Forged `lane` field on restore** | **Not attacked.** `P4` covers restore-strict; the ordering consequence of a forged `"lane": "priority"` on an otherwise-legal record was not isolated. Low expected impact (a caller who writes records already controls `state_ids`), but it is an untested assertion in #214. **Gap.** |
| **Redaction** | Not re-attacked this round; untouched by #212–#216 and passing at `6db65d8`. Carried gap. |
| **`on_invalid_event` exactly-once on restore** | Answered, but negatively and structurally — see D11-semantics-2. The "exactly once" shape cannot be observed at all, so the *ordering* question behind it is moot until the hook is reachable. |
| **Receipt semantics** | Re-run only via the prior suite (unchanged, passing). No new receipt attacks; #212–#216 do not touch the receipt path. Carried gap. |
| **Thread-leak / sync-child reaping** | Still not directly instrumented (carried from rounds 9–10). `F1`'s sync lane (664 runs, 0 hangs) exercises it indirectly only. |
| **Sync-engine lane for `raise_delay` / `after` in `F1`** | Excluded by construction, recorded in the script: a timer-paced self-send on `SyncInterpreter` is driven by the caller's clock, so lap counts inside one `send()` are not comparable. The sync engine *is* covered for all four **trip**-shaped cycles. |

---

## 5. Verdict

**The two semantic reversals this round both land, and land cleanly.**

- **#212 is correct and is now verified positively.** A `raise(delay=)`
  heartbeat is beat-for-beat identical to an `after` of the same period
  (`after_vs_raise_delay_beat_gap = 0`, both kinds), survives 1,334 fuzz runs
  with **0/332** periodic cells cut and **332/332** still beating, and
  sustains 200 machines × 1 ms ping-pong for 10 s at a clock-bounded ~123
  beats/s each with **0** runaway errors. The zero-delay and **mixed** cycles
  still trip, so the exemption cannot be used to launder self-fed work.
  **#206 is SUPERSEDED, not failed.**
- **#213 is exact.** 300 random machines round-trip an armed delayed
  self-send through a `SimulatedClock` with `remaining_ms` correct to
  **1e-6 ms**, firing neither early nor late; 200 concurrent v3 restores all
  re-arm; the restore trace is deterministic over 50 runs.
- **#215 holds** under 100 concurrent descent-settling starts (one
  configuration, no hang), and **#216's top-level half is exemplary** —
  17/17 misspellings warned *with hints*, 17/17 refused under
  `strict_config`, and the payload cannot select its own checking level.

**Four findings, of which two are new failures of properties this round
introduced:**

| ID | Severity | One line |
|---|---|---|
| **D11-semantics-1** | **High** | `"version": 2` in the payload mints a trusted engine event — the same forged `after` record refused at v3 fires a 24 h timer at v2 |
| **D11-semantics-4** | **High** | A `raise(delay=)` heartbeat leaks one timer handle **per beat**, unboundedly — #212's liveness without #212's reclamation |
| **D11-semantics-3** | **Medium** | #216 validates only the top level; a misspelled key inside a state is silently dropped even under `strict_config=True` |
| **D11-semantics-2** | **Low** | #214's `on_invalid_event` on restore fires **zero** times; the hook is unreachable by construction |

The two High findings share a shape worth naming: **each is a correct new
rule whose supporting machinery was not extended with it.** #214 reasoned
correctly about *genuine* v2 payloads and forgot that `version` is
attacker-chosen; #212 reasoned correctly that a heartbeat should live for
ever and forgot that something must then reclaim its handles. Neither is a
flaw in the *semantics* the round chose — both semantics are right — and
both remedies are small and local (three lines in `_fire`/`_cancel`; a
version floor or a non-firing upcast).

**Gate impact (this track's input only): conditional pass, with two new
wrapper constraints and one lint rule.**

Nothing here blocks Phase-3, and the round-10 ADOPT of row 8 is not
disturbed — but three constraints must be added to the CV-C set:

1. **Always call `from_snapshot(..., minimum_version=3)`.** This is the
   entire defence against D11-semantics-1 and it is off by default.
2. **Use `after`, not `raise(delay=)`, for long-lived periodic work**, until
   D11-semantics-4 is fixed. They are now semantically identical, so the
   substitution is free.
3. **Lint nested config keys against the state-level key set** in the
   wrapper's own loader, since `strict_config=True` does not (D11-semantics-3).

The carried round-9/10 rule is unchanged and still required: *never re-type
an engine event with `_replace`; construct a fresh user `Event`* —
**D10-semantics-1 / R9-01 remains open** and untouched by this round.

Finally, one process note that matters more than its size: the round-10
`C1`/`P4` "delayed self-send" tests used `send(..., delay=1)`, which is not
an API — the value went into the event payload and the tests measured a
zero-delay chain. Those two cells should be treated as **never having tested
#206**, and any confidence attributed to them re-derived from this round's
`C1` / `S3` / `F1`, which use the real `raise`-action form.
