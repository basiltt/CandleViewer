# 62 — Round-11 diff review: `19cb1f1..c78ce99` (round-10 fixes #212–#216)

**Scope.** 15 files, ~1.3k lines. Library clone @ `c78ce99` (unreleased 0.8.1;
`__version__` still `0.8.0` — key on the commit). All src/ and tests/ changes
read. Every finding below was reproduced from neutral cwd `<home>`
with a STANDALONE probe (stdlib + `xstate_statemachine` only) under
`probes/main-c78ce99/`. Both action kinds (`def` / `async def`) exercised
wherever an action or service is the subject; both engines wherever parity is
the point.

**Verdict in one line.** The round-10 work is a real net improvement — #213
closes a genuine wedge, #215's lap parity holds, #216 is a correct and
complete top-level check — but the round introduces **one high-severity
security regression (P-1, the v2-downgrade laundering path)** and **one
semantic hole large enough to void the `maxIterations` contract (P-2,
sub-millisecond delay)**, plus a new `start()` stall shape (P-4). The row-8
ADOPT of `59-r10-final-readiness-verdict.md` should not be carried forward
unamended; see § Constraint deltas.

## Probe index

| Probe | Subject | File |
|---|---|---|
| P-1 repro | #214 v2-downgrade forging | `p3_214_v2_upcast_forge.py` |
| P-2 repro | #212 chain-budget escape | `p1_212_escape.py` |
| P-3 repro | #214 `scheduled_sends` bypasses `strict`; forged lane | `p5_214_strict_lane.py` |
| P-4 repro | #215 `_descent_done` stall; seed standing | `p6_215_descent_wait.py` |
| P-5 repro | #213 snapshot v3 round trip / forged records | `p4_213_snapshot_v3.py` |
| P-6 repro | #216 `KNOWN_MACHINE_KEYS` scope | `p7_216_known_keys.py` |
| P-7 repro | sync/async #212 parity, version error text | `p8_sync_parity_version.py` |

---

## P-1 — **CRITICAL.** #214's v2 upcaster launders forged completion records: a snapshot can fire an `after` deadline and an `onDone` it never earned

**Where.** `persistence.py::upcast`, the new `if version < 3` block.

**The claim being made.** The code comment argues: *"A v2 writer had exactly
ONE minter of `done`/`error`/`after` records — the engine itself; the public
NamedTuples could not reach `pending_events` except through it. So a v2 record
of those kinds IS an engine completion."*

**Why it is wrong.** `version` is a plain, unauthenticated field of the *same
payload* the record lives in. The whole point of #195/#203 — and of the trust
model #205 wrote down — is that a hand-authored record must **not** mint an
engine event. #214 hands the payload a one-line opt-out: set `"version": 2`.
`check_version` happily accepts it (2 ≤ `SNAPSHOT_VERSION`), and `upcast` then
stamps `engine: true` on every `done`/`error`/`after` record in it. The
attacker does not need a v2 writer; they write a v3 blob and edit one integer.

**Reproduction** (`p3_214_v2_upcast_forge.py`, neutral cwd). A `vault` machine
whose `locked` state has a **10-minute** `after` deadline, and a `pay` machine
whose `charging` state invokes a service that never completes:

```
baseline version: 3 states: ['vault.locked']
  after  v3 forged (control)      -> states=['vault.locked'] actions=0 TIMER_FIRED=False
  after  v2-DOWNGRADED forged     -> states=['vault.open']   actions=2 TIMER_FIRED=True
  done   v3 forged (control)      -> states=['pay.charging'] actions=0 ONDONE_FIRED=False
  done   v2-DOWNGRADED forged     -> states=['pay.paid']     actions=2 ONDONE_FIRED=True
```

The v3 control is refused exactly as #203 promises. The **same bytes with
`version` changed from `3` to `2`** fire a 600-second timer instantly and
drive an `onDone` for a service that is still running — with an
attacker-chosen `data` payload (`{"amount": 999999}`) delivered to the
transition's actions. This is precisely the #195/#203 defect, reopened.

**The #205 knobs do not close it** (`/tmp` variant of the same probe, results
reproduced below). Only a floor at the *current* version helps, and that
floor is undocumented as a security control and breaks every genuine v2
payload the library still claims to upcast:

```
  defaults                           -> FORGE_WORKED=True
  minimum_version=1                  -> FORGE_WORKED=True
  minimum_version=3                  -> BLOCKED SnapshotVersionError
  expected_machine_hash (correct)    -> FORGE_WORKED=True
```

`expected_machine_hash` is useless here by construction: the forgery does not
touch the machine's structure, so the correct fingerprint still matches.

**Severity.** For a financial OMS this is the worst shape in the round: a
persisted order can be made to take its `onDone`/timeout branch on restore,
with a chosen payload, by flipping one integer in a blob that already had to
be treated as trusted-but-corruptible. The library's own trust boundary
(`from_snapshot` docstring) says `state_ids`/`context` are applied verbatim —
true, and a forged `context` is a *data* lie. Minting an engine *completion*
is different in kind: it makes the machine take a transition the chart says
only the engine may take, which is what #203 existed to prevent.

**Recommended fix.** Do not infer provenance from a self-declared version.
Either (a) drop the upcast entirely and document that a 0.8.0-era persisted
deadline is demoted on restore (the #203 behaviour — a known, loud,
fail-closed loss), or (b) gate the upcast behind an explicit caller opt-in
(`from_snapshot(trust_legacy_completions=True)`), so the *caller* — who knows
whether the blob came from their own 0.8.0 writer — makes the trust decision,
not the payload.

**CV constraint.** New: **CV-C49** — never call `from_snapshot` without
`minimum_version=SNAPSHOT_VERSION` *and* an out-of-band HMAC over the JSON.
This supersedes the softer "authenticate outside" advice; with #214 in place,
authentication outside is now load-bearing rather than belt-and-braces.

---

## P-2 — **HIGH.** #212's exemption is keyed on delay *truthiness*, not on time: `raise(delay=0.0001)` escapes `maxIterations` at ~20,000 laps/s

**Where.** `interpreter.py::_deliver` — `if not delay:` selects the charged
zero-delay branch; anything truthy takes the timer branch, which since #212
no longer counts as `_armed_this_step`.

**The reversal itself is defensible.** #206's rule was time-blind in the other
direction and did kill legitimate pollers; I agree with the direction. The
defect is the *boundary*. `delay` is milliseconds as a float. `0.0001` ms is
100 nanoseconds — it is not a "period", it is a syntactic dodge that buys a
chain reset. The clock cannot enforce any floor at that scale; the arming
returns immediately and the firing lands on the very next loop turn.

**Reproduction** (`p1_212_escape.py`, `maxIterations=10`, both action kinds):

```
--- action kind: beat ---
  A mixed delayed+zero-delay (delay=1)       beats=   129 err=None rate=128.2/s
  A mixed (delay=0.0001)                     beats= 11817 err=None rate=23629.8/s
  B pure raise(delay=1)                      beats=    64 err=None rate=63.1/s
  B pure raise(delay=0.0001)                 beats=  7892 err=None rate=15782.2/s
  B pure raise(delay=0) [control]            beats=    12 err=RunawayChainError rate=23.9/s
--- action kind: abeat ---   (identical shape; async def)
  A mixed (delay=0.0001)                     beats=  9837 err=None rate=19671.2/s
  B pure raise(delay=0) [control]            beats=    12 err=RunawayChainError rate=23.7/s
```

Two distinct answers to the brief's questions:

1. **"Can a chart combine `raise(delay=1)` with zero-delay work to escape
   `maxIterations` entirely?"** — **Yes** (row A, `delay=1`). State `A` arms a
   delayed self-raise; `B` does a *genuine zero-delay* `raise`. Every period
   therefore contains real same-step chain work, but the delayed arming resets
   the chain each period, so the zero-delay link never accumulates past 1. It
   ran 129 laps in 1 s with `maxIterations=10`, no error, indefinitely. The
   changelog's framing ("`maxIterations` bounds work the machine feeds itself
   *within* a step") is honoured to the letter and useless in practice: any
   runaway can be made periodic by inserting one delayed hop.

2. **"Is the CPU bounded by the clock — is a 0 ms delay a timer or a chain?"**
   — `delay=0` is falsy and correctly stays a **chain** (control row trips at
   12 laps with `RunawayChainError`, both kinds). But **any** positive value,
   however small, is a **timer**. At `0.0001` the effective bound is the event
   loop's turn rate, not the clock: ~16k–24k laps/s, uncharged, forever. So
   the answer to "is #206's original defect (unbounded 1 ms ping-pong burning
   CPU) now simply accepted" is: yes at 1 ms (~64 laps/s — genuinely bounded by
   the OS timer floor, and defensible), and **no, it is far worse than
   accepted below ~0.01 ms**, where there is no clock bound at all.

**Recommended fix.** Charge the timer exemption only above a stated floor
(the OS timer resolution is the natural one: sub-`1 ms` delays behave as
zero-delay for budget purposes), or clamp `delay` to a minimum of 1 ms as the
sync engine's `SimulatedClock` semantics already imply. Either makes the rule
time-*aware* rather than truthiness-aware, which is what #212 set out to do.

**Sync/async agreement** (`p8_sync_parity_version.py`): both engines apply the
reversal, and both let a 1 ms ping-pong run past the limit — the sync engine
beat 201 times over 200 virtual ms at `maxIterations=6`, the async engine 53
times in 0.8 s. Parity holds; the rule they agree on is the problem.

**Delayed `sendTo` to a child** is unaffected either way: the exemption keys
on `actor is self`, so a child send was never charged and still is not. No
regression, but worth stating — a parent can drive a child at any rate with no
budget at all, as before.

**CV constraint.** New: **CV-C50** — no chart may use a `raise`/`send` delay
below 1 ms. Lint the contracts for `"delay"` values in `(0, 1)`; treat any as
a build failure, because `maxIterations` provides no protection there.

---

## P-3 — **MEDIUM.** #214 applies `strict` to `pending_events` only; `scheduled_sends` is an unchecked second door, and the refusal is not visible to the restoring caller

**Where.** `base_interpreter.py::from_snapshot` — `_admit_restored` is called
in the `pending_events` loop; the `scheduled_sends` loop two lines above
copies records verbatim, and `_rearm_restored_self_sends` delivers them
through `_deliver` with no check at all.

**Reproduction** (`p5_214_strict_lane.py`, machine with `"strict": true`):

```
a) last_error BEFORE start(): UnknownEventError
   last_transition_ok: False
   on_invalid_event seen at restore time: []
   after start(): states = ['strictm.a']
b) scheduled_sends BOGUS under strict: err = None invalid hook = []
   known WAKE via scheduled_sends -> ['strictm.b']
c) persisted [P inbox, Q forged-priority] -> processed ['Q', 'P']
```

Three separate observations:

- **(a) The `pending_events` half works, but the report is unreachable.**
  `last_error` / `last_transition_ok` are set correctly *before* `start()`, and
  the event is dropped. However `on_invalid_event` fires inside
  `from_snapshot`, **before any plugin can be attached** — `.use(plug)` is
  necessarily called on the returned instance. So the hook never reaches a
  real subscriber on the restore path; only the `last_error` attribute does,
  and only if the caller thinks to read it before `start()`. The changelog's
  "a refusal is reported (`on_invalid_event`, `last_error`)" is half true. The
  library's own pin (`test_restore_applies_strict_to_restored_events`)
  constructs `_Invalid()` and calls `r.use(plug)` but **never asserts on
  `plug`** — it asserts `last_error` only, so the pin does not notice.

- **(b) `scheduled_sends` bypasses `strict` entirely.** A `BOGUS` event the
  machine has never declared, smuggled in as a scheduled send, produces no
  error, no hook, and is delivered. A *known* event delivered the same way
  drives a real transition (`strictm.a` → `strictm.b`). So #214's stated
  invariant — "restored user events pass the same `strict` check a `send()`
  does" — does not hold for the field #213 added in the same commit. The two
  fixes were not composed.

- **(c) A forged `lane: "priority"` promotes plain user traffic.** Persisted
  order was `[P (inbox), Q (lane-tagged)]`; processed order was `['Q', 'P']`.
  `lane` is caller-writable like everything else in the blob, and
  `_enqueue_restored` honours it with no provenance check. Lower severity than
  P-1 (this reorders user events; it does not mint engine events), but it is
  a new payload-controlled ordering primitive that did not exist at `19cb1f1`.

**Recommended fix.** Route `_rearm_restored_self_sends` through
`_admit_restored`; and either fire `on_invalid_event` lazily on `start()` or
document that the restore-path refusal is observable on `last_error` only.

---

## P-4 — **MEDIUM.** #215's `_descent_done` gate creates a new `start()` stall: an entry action that awaits its own receipt blocks for the full timeout

**Where.** `interpreter.py::_run_event_loop` — `await self._descent_done.wait()`
before the main `while`, set only at the end of `start()`'s try-body (and in
`finally`).

**The brief asked: can `start()` now hang on a non-terminating descent?** Two
answers, from `p6_215_descent_wait.py` (25 s watchdog; a timeout would itself
be the result):

```
a) always-cycle in descent  : start() returned, n=13, err=RunawayChainError
b) entry awaits own receipt : start() returned, n=0, states=['dead.x']
c) seed standing lap counts : descent-seeded chain=8 laps, external-seeded=3 laps (limit=6)
```

- **(a) The `always` self-cycle is correctly bounded.** A machine whose
  initial configuration cycles `x ⇄ y` via `always` at `maxIterations=12`
  returns from `start()` with `RunawayChainError` after 13 entries. The
  settle budget covers the descent; no hang. Good.

- **(b) A real new stall shape.** An `async def` entry action that does
  `await i.send("GO", wait=True)` cannot be satisfied: the receipt resolves
  only when the run loop processes `GO`, and the run loop is parked on
  `_descent_done`, which only the completion of that same entry action can
  set. This is a genuine cycle. It is *not* unbounded here only because the
  probe wrapped the await in `asyncio.wait_for(..., 3.0)`; measured directly:

  ```
  start() took 3.01s  n=-1 states=['dead.x'] err=None
    after settle: ['dead.y']
  ```

  With no timeout in the user's action, `start()` never returns. Confirmed
  causal by re-running the identical chart on a subclass that opens the gate
  before spawning the loop (pre-#215 behaviour, library source untouched):

  ```
  gate pre-opened: start() took 0.00s n=1 states=['dead.y']
  ```

  So this is a **regression introduced by #215**, not a pre-existing shape.
  It is silent: `last_error` is `None`, the machine is `running`, and the
  configuration is legal — indistinguishable from a slow entry action. The
  #207 `on_invocation_stranded` machinery does not cover it (no invoke is
  involved). Awaiting one's own receipt from an entry action is admittedly
  unusual, but "await a helper that happens to await a receipt" is not, and
  the failure mode is an unbounded hang inside `start()`.

- **(c) Seed standing is more permissive, as designed — quantify it.** At
  `maxIterations=6`, a `raise` chain seeded by the initial descent ran **8**
  laps; the identical chain seeded by an external `KICK` ran **3**. That is
  the intended #215/#77 parity (the sync drain gives the descent's raises
  seed standing), and it is the *sync* number the async engine was brought to
  — not a weakening invented in round 10. But it is worth pinning explicitly:
  a descent-seeded cycle gets roughly `limit + 2` laps against an
  external-seeded cycle's `limit / 2`. Any budget sizing done against the
  external number under-provisions the descent case by ~2.7×.

**Recommended fix.** Bound the gate: `await asyncio.wait_for(self._descent_done.wait(), <descent timeout>)`, or set `_descent_done` before running entry
actions and use a re-entrancy flag (the sync engine's actual mechanism) rather
than a wait, which is what the #215 comment says it is mirroring.

**CV constraint.** New: **CV-C51** — no entry/exit action may `await` a
receipt (`send(..., wait=True)`) on its own interpreter. Lint for it.

---

## P-5 — **LOW/INFO.** #213 is correct and closes the wedge; three sharp edges in the new field

**Where.** `base_interpreter.py::_persist_scheduled_sends` /
`_rearm_restored_self_sends`; `persistence.py::check_shape`.

`p4_213_snapshot_v3.py`:

```
SNAPSHOT_VERSION = 3
a) scheduled_sends: [{'kind': 'event', 'type': 'WAKE', 'payload': {},
                      'remaining_ms': 197.13, 'send_id': 'w'}]
   right after start(): ['park.waiting']
   after 0.45s: ['park.done_'] n = 1
   control (field stripped): ['park.waiting']
c) armed=1 after cancel=[]
d) remaining -1e9         -> ACCEPTED, states=['park.done_']
d) remaining 1e18         -> ACCEPTED, states=['park.waiting']
d) remaining 'abc'        -> ValueError: could not convert string to float: 'abc'
d) forged engine after    -> ACCEPTED, states=['park.waiting']
d2) hash is structural only: True
e) sync scheduled_sends: [... 'remaining_ms': 299.77 ...]
```

**The fix works and the counterfactual is exact.** A 300 ms self-raise
snapshotted at 100 ms records `remaining_ms ≈ 197`, re-arms on `start()`, and
the restored machine reaches `done_` at ~0.45 s. With the field stripped, the
same blob parks in `waiting` for ever — the pre-#213 wedge, reproduced as the
control. Cancelled sends leave no record (`after cancel=[]`). The sync engine
persists the same shape. The remaining delay is computed as
`(deadline - self.clock.now()) * 1000` on **whichever clock the interpreter
holds**, so a `SimulatedClock` snapshot records virtual milliseconds and a
`RealClock` restore consumes them as real ones — correct within each clock,
silently wrong across a clock swap. Worth stating in the guide; not a defect.

Three edges:

1. **`remaining_ms` is unvalidated.** `check_shape` was extended to require
   `scheduled_sends` be a list of dicts (`persistence.py` line ~274) and
   nothing more. A negative remaining (`-1e9`) is clamped by
   `max(delay_ms, 0.001)` and fires immediately — so a forged record can
   **pull a deadline forward to now**. A huge one (`1e18`) is accepted and
   arms a timer ~31 billion years out; on a real `asyncio` loop that is a
   `call_later` with an enormous delay, silently. A non-numeric one escapes as
   a bare `ValueError` from `float()` rather than the `SnapshotCorruptError`
   that #110/#146/#198 established as the contract for every other malformed
   field — the one place in the round where the typed-error discipline slips.
2. **`machine_hash` does not cover it** (confirmed: `d2 ... True`). Correct by
   design — it is a *structure* hash — but it means nothing in the snapshot
   detects tampering with `scheduled_sends`. Combined with edge 1 and P-3(b),
   `scheduled_sends` is the least-checked field in the payload.
3. **No double-arm, and ordering is right.** A restored machine does **not**
   re-run entry actions (static restore), so the record is the only arming;
   `start()` re-arms after the descent, and the probe shows the state still in
   `waiting` immediately after `start()` returns. No interaction with #215's
   gate was observed.

**Forward-compat message is good** (`p8`): a v4 payload gives *"Snapshot
version 4 is newer than the supported version 3. Upgrade xstate-statemachine
to restore it."*, and `minimum_version` failures carry `.minimum`. Actionable.

---

## P-6 — **LOW.** #216 is complete and correct *at the top level*; the same defect one level down is untouched

**Where.** `validation.py::KNOWN_MACHINE_KEYS` / `validate_top_level_keys`,
called once from `factory.py::create_machine`.

`p7_216_known_keys.py`:

```
KNOWN_MACHINE_KEYS: 26
a) parser keys NOT in KNOWN_MACHINE_KEYS: []
   full-key machine under strict_config=True: OK []
b) 'history' in known: True
   nested typos under strict_config=True -> ACCEPTED SILENTLY | warnings: []
c) config strictConfig=true, no kwarg   -> RAISED
c) config false, kwarg True             -> RAISED
c) config true, kwarg False             -> warned: 1
c) neither (default)                    -> warned: 1
d) nested typos, default mode -> warnings: (none)
```

- **Completeness holds.** I enumerated every key the parser actually reads at
  the root — `_NODE_KEYS` (the twelve `StateNode` keys) plus every
  `config.get(...)` in `MachineNode.__init__` — and built a machine carrying
  all 25 simultaneously under `strict_config=True`. It builds clean with zero
  warnings. No false positive, which is the dangerous direction: a false
  positive would make `strict_config=True` refuse a valid machine. I also
  scanned the bundled corpus — **152 machines** across `tests/` and
  `examples/` — for top-level keys outside the set: **zero hits**. Adopting
  `strict_config=True` project-wide costs nothing.
- **Precedence is right in both directions**: kwarg `None` reads the config's
  `strictConfig`; an explicit kwarg overrides it either way, including
  `strict_config=False` *downgrading* a config that asked for strict. That
  last one is arguably wrong — a config's own safety request overridden by the
  call site — but it is what the docstring says.
- **The gap: nested states.** A state carrying `entryy` and
  `actionErrorPolicyy` is accepted *silently* even under `strict_config=True`
  — no error, no warning. The motivating harm of #216, a misspelled safety
  policy silently reverting to its permissive default, applies identically to
  nested keys the parser drops: `_prefetch_node_keys` discards unknown state
  keys by exactly the same mechanism. The changelog and `json-config.md` both
  say "top-level", so this is scoped honestly rather than mis-stated — but a
  user reading "unknown config keys are caught" will not expect `entryy` on a
  state to pass. The one-line list is in place; extending the walk is
  mechanical.

---

## P-7 — **INFO.** Rewritten round-9 pins: what changed, and whether any bound was weakened

The brief's most important housekeeping question.
`tests/test_round9_findings.py` is the only test file modified (186 lines);
`test_round10_findings.py` is new (608 lines, 15 tests). Full suite for both
files: **36 passed**, no xfail, no skip, no deletion of unrelated pins.

Exactly one class was rewritten: `TestDelayedSelfSendIsCharged` →
`TestDelayedSelfSendIsATimer`. The rewrite is a *direction* reversal, so the
assertions necessarily inverted. Bound for bound:

| Old pin | New pin | Weakened? |
|---|---|---|
| `test_delayed_selfsend_cycle_trips`: asserts `RunawayChainError`, a `chain_budget` drop, and `n < 3*20` | `test_raise_delay_heartbeat_survives_max_iterations`: asserts `n > floor`, `err is None`, no drop — at three periods (30/100/250 ms), both action kinds | Reversed by design (#212). The new direction is pinned at three periods and both kinds — broader coverage than the single case it replaced. |
| `test_delayed_matches_immediate_selfraise_lap_count`: `abs(delayed - immediate) <= 1` **and** `delayed < 3*20` | **deleted**; replaced by `test_raise_delay_matches_after_idiom`: `abs(r - a) < max(6, a // 3)` | **Yes — the one real loss.** The old pin carried an *upper bound on laps* (`delayed < 60`). The replacement compares `raise(delay=)` against the `after` idiom with a tolerance that **scales with the observed value** (`a // 3`), so it asserts only that two unbounded quantities are within ~33% of each other. Nothing anywhere in the new file asserts any upper bound on a delayed cycle's lap count — exactly the property P-2 exploits. |
| — | `test_zero_delay_raise_cycle_still_trips` (new): the trip at `maxIterations` for the zero-delay case, both kinds | Net addition; the budget's real target stays pinned. |
| `test_sync_engine_timer_paced_cycle_is_a_periodic_process` | same assertions, config swapped to `_raise_cfg(1, 20)` | Unchanged in substance. The comment explaining *why* the sync engine treats it as periodic was cut from five lines to two — documentation loss only. |

So **one bound was weakened**: the absolute lap ceiling on a delayed
self-send cycle. That is precisely the guarantee P-2 shows is now absent in
practice. The rewrite is honest about the reversal; it is silent about having
given up the only upper bound the class contained.
`test_after_heartbeat_unaffected` (`drops == []`, `n > 20`) is new and
tightens the `after` side.

No round-6/7/8 pins were touched. The #216 tests correctly assert the
*silent* pre-fix behaviour as the contrast case (`m.action_error_policy ==
"continue"` for a dropped `actionErrorPolicyy`). One pin is weaker than it
looks: `test_restore_applies_strict_to_restored_events` constructs an
`_Invalid()` plugin and calls `r.use(plug)` but never asserts on it, so it
cannot notice P-3(a) — the hook fires before any plugin can be attached.

**Undocumented behaviour found.** (i) `scheduled_sends` is not checked against
`strict` (P-3b), though the snapshot guide says restored user events are;
(ii) `on_invalid_event` on the restore path fires before a plugin can be
attached (P-3a), though the changelog says the refusal is reported there;
(iii) `remaining_ms` accepts negatives and pulls a deadline forward (P-5.1);
(iv) the sub-millisecond delay boundary (P-2) is nowhere stated —
`json-config.md` says a delayed self-send is a timer "of any period", which is
literally true and operationally a trap.

---

## Constraint deltas for the CandleViewer register

Carry CV-C01..C48 forward unchanged. Add:

- **CV-C49 (from P-1, blocking).** `from_snapshot` is called only with
  `minimum_version=SNAPSHOT_VERSION` **and** an out-of-band HMAC verified over
  the JSON before the call. Rationale: #214 makes a self-declared
  `version: 2` sufficient to mint engine completions.
- **CV-C50 (from P-2, blocking).** No chart may specify a `raise`/`send`
  delay in the open interval `(0, 1)` ms. Add a lint over
  `battle-*/contracts/*.machine.json`.
- **CV-C51 (from P-4).** No entry/exit action may await a receipt on its own
  interpreter (`send(..., wait=True)`); `start()` will not return.
- **CV-C52 (from P-3b / P-5.1).** Treat `scheduled_sends` as untrusted:
  validate `remaining_ms` is a finite non-negative number under a sane
  ceiling, and re-check each record's `type` against the machine's known
  events, before handing a blob to `from_snapshot`.
- **CV-C53 (from P-6).** Build every chart with `strict_config=True`.
  Verified zero-cost against the 152-machine bundled corpus. Nested-state
  typos remain uncovered — keep the existing schema check on the contract
  JSON.

### Effect on the row-8 ADOPT

`59-r10-final-readiness-verdict.md` recorded ADOPT with Phase-3 cleared. P-1
is a **new** critical that did not exist at `19cb1f1`, and its only complete
mitigation (`minimum_version=SNAPSHOT_VERSION`) is caller-side discipline, not
a library property. My reading: **ADOPT stands, conditional on CV-C49 and
CV-C50 landing as enforced lints before any persisted-state path ships.**
Neither is expensive; both are absolute. P-4 is a correctness annoyance that
CV-C51 fully covers. P-3, P-5 and P-6 are documentation and
defence-in-depth, not gates.

### What I would send upstream

P-1 first and alone — it reopens #195/#203 and the fix is small (remove the
inference, or make it an explicit caller opt-in). P-2 second, with the
`0.0001` numbers, framed as "the #212 boundary should be time-based, not
truthiness-based". P-3b and P-4 third as a pair — both are "two round-10
fixes were not composed". P-5.1 and P-6 as polish.
