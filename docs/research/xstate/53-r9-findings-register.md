# Round-9 Findings Register — library `main` @ `f28719c`

Scope: triage + dedupe of every round-9 input (battle tracks, `52-r9-diff-review.md`
`N-*`, `50-r9-regression.md`), each re-run fresh against `f28719c` in the round-9
venv, classified against `src/`, and merged by root cause into canonical `R9-nn`.

Classification vocabulary: `LIBRARY-DEFECT` | `HARNESS-ERROR` | `DESIGN-CONSTRAINT`
| `OUR-CONTRACT-DEFECT` | `DUPLICATE`. Severity is the OMS (order-management)
severity, not the reporter's.

## 1. Canonical register

| ID | Sev | Class | Title | Merged inputs |
|----|-----|-------|-------|---------------|
| **R9-01** | **Blocker** | LIBRARY-DEFECT | Engine-completion provenance (#195) is forgeable by five independent vectors; each drives a real `onDone` under `strict` while the genuine service runs | D9-fuzz-1, D9-semantics-1, D9-concurrency-1, D9-persistence-1, N-3, N-4 |
| **R9-02** | High | LIBRARY-DEFECT | `after.*` matching tests the **public** `AfterEvent` class, so a hand-built one fires a 60 s timer instantly — the one event family #195's mint-and-check never reached | N-2 |
| **R9-03** | High | LIBRARY-DEFECT | `always` → `invoke` → `onDone` starves external priority traffic permanently on the `async def` lane | D9-fuzz-3 |
| **R9-04** | High | LIBRARY-DEFECT | A plain `def` service armed by a transition an `always` rolls **forward** is still submitted, contradicting #193; `SyncInterpreter` additionally leaks the rollback half | LD-01, CV-F28-01 |
| **R9-05** | High | DESIGN-CONSTRAINT (wrapper obligation) | Snapshots are unauthenticated: a *consistent* `configuration`/`state_ids` forgery relocates the machine, and a v0/absent-`version` downgrade bypasses the #185 drift check | D9-persistence-2, W-04 |
| **R9-06** | Medium | LIBRARY-DEFECT | A delayed self-`send` cycle is charged to no budget and is tagged *external* by #192, so it can never be shed — `maxIterations` inert | N-5 |
| **R9-07** | Medium | LIBRARY-DEFECT | `rollback` + `invoke.onDone` storm self-terminates below the default `maxIterations`, never reports `RunawayChainError`, and wedges the machine in the transient invoking state | CV-F28-02 |
| **R9-08** | Medium | LIBRARY-DEFECT | `await send(EV, wait=True)` resolves at an instant where `current_state_ids == []` with `last_transition_ok=True` | D9-fuzz-4 |
| **R9-09** | Medium | DOC-DEFECT | #201's "all three lanes agree at every limit tested" is false: sync runs exactly two laps more than async at every **odd** `maxIterations` on the `def` lane | D9-fuzz-2 |
| **R9-10** | Low | LIBRARY-DEFECT | The #192 priority-lane provenance tag **and the lane itself** are lost across a snapshot round-trip | D9-persistence-3, N-6 |
| **R9-11** | Low | LIBRARY-DEFECT | Call-site `QueueOverflowError` refusals fire no `on_event_dropped`; the hook under-counts the shed rate by ~99.8 % | D9-concurrency-2 |
| **R9-12** | Low | DESIGN-CONSTRAINT | `done.state.*` is an unreserved event namespace: a plain `Event` of that name drives a compound/parallel `onDone` exactly as a forged `DoneEvent` does | N-1 |
| **R9-13** | Low | DOC-CONTRACT-MISMATCH | `strict` does not gate events restored from `pending_events`, contradicting the documented restore contract | D9-semantics-2 |
| **R9-14** | Low | LIBRARY-DEFECT | #198 narrows v1 restore compatibility beyond the changelog: a `version: 1` running blob without `configuration` used to restore and is now refused | N-7 |
| **R9-15** | Low | LIBRARY-DEFECT | `SnapshotMidStepError` from an invoked child's entry action reports `child=False` | D9-fuzz-5 |
| **R9-16** | Low | LIBRARY-DEFECT | Unknown top-level config keys are accepted silently, downgrading policy to defaults | NW-unknown-keys |

Our-contract defects (catalogue JSON, not the engine) and closed/withdrawn items
are carried in §4 and §5.

## 2. Verdict summary

- Re-run: **every** finding above reproduced fresh at `f28719c` unless the row
  says otherwise. No round-9 input was demoted to `HARNESS-ERROR` on re-run
  except the two already self-declared as such (§5).
- **One blocker (R9-01)** and it is the same blocker the round-8 fix set claimed
  to close. Adoption gate stays shut on it.
- `50-r9-regression.md` reports **no true PASS→FAIL regression**; the single gate
  flip (`LC-42`, sub-millisecond latency assertion) re-ran 4/5 PASS and is
  classified `HARNESS-ERROR` (host load noise).

## 3. Canonical findings in detail

### R9-01 — engine-completion provenance is forgeable (Blocker, LIBRARY-DEFECT)

Merges **D9-fuzz-1**, **D9-semantics-1**, **D9-concurrency-1**,
**D9-persistence-1**, **N-3**, **N-4**. One root cause, five vectors; all six
inputs were filed separately because they were found by different tracks.

Root cause. `#195` replaced a by-name trust test with a by-type one:
`events.py:272 is_system_event` returns `True` for any instance of the private
`_EngineDone` / `_EngineError` / `_EngineAfter` (`events.py:558-588`), and
`events.py:414` trusts any persisted record whose `"engine"` key is `True`.
Neither is a secret and neither is bound to the invocation it describes:

1. **`_replace` re-typing.** Every ordinary `onDone`/`onError` handler is handed
   a genuine engine-minted event as its `event` argument — the documented way to
   consume a completion. `NamedTuple._replace` goes through `_make`, which
   preserves the subclass, so the handler can re-type a harmless `ping`
   completion into `done.invoke.fill` with an attacker payload. No private name
   needed.
2. **pickle / deepcopy round-trip** — the classes are importable, so they pickle
   as themselves (`events.py:558-562` explicitly sanctions this).
3. **`type(held_instance)(...)`** — a constructor reached off any held instance.
4. **The importable private name** `xstate_statemachine.events._EngineDone`.
5. **A hand-written snapshot record** carrying `"engine": true`, restored by the
   **public** `restore_event()` (`events.py:414` → `:429`).

Re-run at `f28719c`:

| repro | result |
|-------|--------|
| `battle-f28719c/fuzz/g7_forgery_repro.py` | exit 1 — **3 of 4 vectors succeed**: `_replace`, pickle, hand-written `engine:true` record; each lands `{'filled': 999999}` with the genuine service still running |
| `battle-f28719c/semantics/repro/d9_sem_1_replace_forgery.py` | exit 1 — `async` lane `state=['oms.settled'] booked=[('done.invoke.fill', {'qty': 999999})] last_error=None` |
| `battle-f28719c/concurrency/s6_restore_event_forgery_minimal.py` | exit 1 — forged `engine:true` record drove `onDone` past `strict` with `{'v': 'FORGED'}` |
| `battle-f28719c/persistence/s1_engine_forgery_roundtrip.py` | `VERDICT: FAIL` — forged record restores as `_EngineDone system=True`; genuine and forged records are **byte-identical** |
| `probes/main-f28719c/p7_engine_class_reachable.py` | exit 1 — `_replace`/deepcopy/pickle all keep `_EngineDone`; `real_b_invocations=0` |
| `probes/main-f28719c/p5_stale_completion_roundtrip.py` | exit 1 — a *genuine* persisted completion replayed against a freshly-armed invocation drives its `onDone` with `{'value': 'STALE'}`, `fetch_invocations=0` |

**N-3 is the sharpest sub-case and deserves its own remedy**: the gate is *only*
a provenance test. Even a completion the engine genuinely minted is accepted by
an invocation it does not belong to, because nothing binds the marker to the
`(type, src, invocation-instance)` triple.

Lane note (financial-OMS rule). Both service kinds run. The plain-`def` lane
reports "not reproduced" in `d9_sem_1_replace_forgery.py` only because the
`def` service blocks the run loop (the documented D8-concurrency-2 behaviour),
not because it is protected — the trust site is lane-independent.

Remedy shape. Bind the marker at mint time to the `(type, src)` pair plus a
per-invocation nonce and verify it at `is_system_event`; override `_replace` /
`__reduce__` on the private subclasses to degrade to the public class; and make
`restore_event`'s trust contingent on a snapshot-scoped secret rather than a
plaintext boolean. Note the changelog's justification for the snapshot door —
"a record writer already controls `state_ids` outright" — is no longer sound,
because `#198` in this same release now refuses forged `configuration` payloads
(see R9-05), which makes the event channel strictly the weaker door.

### R9-02 — `after.*` is matched on the public class (High, LIBRARY-DEFECT)

From **N-2**. Kept **separate from R9-01**: this is not a forged *private*
subclass, it is a match site that never consults provenance at all.
`base_interpreter.py:4523` selects `after` transitions with a bare
`isinstance(event, AfterEvent)` — the **public** class. So a hand-built
`AfterEvent("after.60000.m.work", None, None)` fires a 60-second timer
instantly on both engines.

Discriminating control written for this triage,
`battle-f28719c/r9triage/t1_plain_event_control.py`:

```
after/AfterEvent       ['m.expired']      <- transitioned
after/plainEvent       ['m.work']         <- no effect
after/plainStr         ['m.work']         <- no effect
```

The public class is genuinely *privileged* over a plain `Event` of the same
name, so this is a real provenance bypass, not the open-namespace effect of
R9-12. `probes/main-f28719c/p15_strict_refusal_coverage.py` confirms the shape:
with `strict` **on** the forged `AfterEvent` is refused, but with `strict` off
— the shipped default — it `TRANSITIONED` on both engines. OMS impact: any
component that can hand the interpreter an event can fast-forward a timeout.

### R9-03 — `always` → `invoke` → `onDone` starves external priority traffic (High, LIBRARY-DEFECT)

From **D9-fuzz-3**; R8-04 was only half-fixed. Re-run of
`battle-6db65d8/fuzz/r18_ext_starvation_repro.py` at `f28719c`:

| lane | applied | end queues | status |
|------|---------|-----------|--------|
| `async def` | **126 / 500 (25.2 %)** | inbox 499, priority 374 | `running`, `last_error=None`, no drop hook |
| `async def`, no-`always` ablation | 500 / 500 | drained | clean |
| `async def`, no-`invoke` ablation | 500 / 500 | drained | `RunawayChainError` |
| `plain def` | 500 / 500 | drained | now passes |

Both ablations remain necessary, so the shape is exactly `always` + `invoke` +
`onDone`. The self-generated re-entry cycle is serviced ahead of the external
priority queue on the coroutine-completion path, and the backlog never drains.
Silent: no error, no drop hook, `status=running`.

### R9-04 — a rolled-forward `def` invoke is still submitted (High, LIBRARY-DEFECT)

Merges **LD-01** and **CV-F28-01** (same root cause, different reporters).
CHANGELOG `#193` claims a `def` service armed by a transition that is rolled
back **or rolled forward** is never submitted. Re-run of
`battle-f28719c/contracts/repro/ld01_always_rollforward.py` — 3 of 6 lanes leak:

```
ok   case A | async service | async engine | calls=[]
LEAK case A | def   service | async engine | calls=['submit_child']
LEAK case A | def   service | sync  engine | calls=['submit_child']
ok   case B | async service | async engine | calls=[]
ok   case B | def   service | async engine | calls=[]
LEAK case B | def   service | sync  engine | calls=['submit_child']
```

Case A is roll-forward (`always` leaves the invoking state in the same
macrostep), case B is rollback. So the roll-forward half holds only for
`async def`, and `SyncInterpreter` additionally still leaks the rollback half
that `#193` fixed on the async engine. `always_rollforward_def_invoke.py`
independently reports `ok` for `async` and exit 1 for `def`.

In every leaking row the configuration and context are correct and the orphaned
`onDone` is correctly discarded per SCXML §6.4.2 — **only the side effect
escapes**, from a state the machine never settled in. For an OMS that side
effect is an exchange order placement, which is why this is High rather than
Low despite being invisible in the state.

### R9-05 — snapshots are unauthenticated (High, DESIGN-CONSTRAINT / wrapper obligation)

Merges **D9-persistence-2** and **W-04**. Classified `DESIGN-CONSTRAINT`, not
`LIBRARY-DEFECT`: `#198`/`#186` are documented *internal-consistency* rules, not
authentication, and the library never claimed otherwise. It is High for us
anyway because the control plane (kill switch, elevation) is snapshotted.

Re-run `battle-f28719c/persistence/r2_readside_matrix.py` §2 — eight of nine
mutations are correctly refused, and the ninth is the one that matters:

```
contradict(m.b only)     CORRUPT
state_ids emptied        CORRUPT
state_ids forged m.b     ACCEPT   ['m.b']  <- RELOCATED, forged key won
```

A forgery in which `configuration` and `state_ids` **agree on a lie** is
indistinguishable from an honest payload (`W-04` shows the same on the real B18
kill switch: a version-2 blob edited so both fields read `kill_switch.clear` is
accepted and restores to `clear`).

Re-run `r3_version_downgrade.py` — all three downgrade forms still bypass the
`#185` drift check entirely:

```
CONTROL intact                       -> SnapshotDriftError (correct)
version=0 + hash removed             ACCEPTED into DRIFTED machine: ['m.a'] -> JUMP -> ['m.c']
version key removed + hash removed   ACCEPTED into DRIFTED machine
version=0 + hash=None                ACCEPTED into DRIFTED machine
```

`persistence.py:344-352` computes `versioned = bool(version)` and early-returns
when a v0 payload carries no `machine_hash`, so *omitting* the version is
strictly more powerful than supplying one. Wrapper obligation: HMAC-tag every
persisted control-plane snapshot and reject `version < 1` outright.

### R9-06 — a delayed self-`send` cycle can never be shed (Medium, LIBRARY-DEFECT)

From **N-5**. `probes/main-f28719c/p3_delayed_selfsend_unbounded.py` re-run:
`laps(exits)=659` in 10 s, `raise_depth=0`, `chain_tripped=False`,
`status=running`. The cycle is charged to no budget, and `#192` now explicitly
tags it *external*, which means the shed site — which by design only cuts
self-generated items — can never cut it. `maxIterations` is inert against this
shape. Medium rather than High: it burns a core and wedges progress but does
not corrupt state or fire a side effect twice.

### R9-07 — `rollback` + `onDone` storm self-terminates and wedges (Medium, LIBRARY-DEFECT)

From **CV-F28-02**. `battle-f28719c/contracts/repro/rollback_ondone_silent_wedge.py`
re-run, exit 1 on both lanes: at the shipped default `maxIterations=1000` the
storm self-terminates after a non-deterministic 190-252 laps, so the runaway
detector never fires; `last_error` is the entry action's own `RuntimeError`, the
caller's receipt is clean, and the interpreter is left `status=running` parked in
the transient invoking state (`configuration_2s_later: ['r6.starting']`,
`wedged_in_transient: true`) with no service in flight and no `onDone` that can
ever arrive. At `maxIterations` 10/50 `RunawayChainError` is raised correctly —
so the diagnostic exists but is unreachable at the default.

Related but distinct, and **not** merged: `F1` (`rollback` + `invoke.onDone`
re-arms a side-effecting service once per lap, 1003 calls) is the documented
SCXML re-entry contract and is carried in §4 as a wrapper obligation.

### R9-08 — `send(wait=True)` resolves at a torn instant (Medium, LIBRARY-DEFECT)

From **D9-fuzz-4**. `battle-6db65d8/fuzz/r3_empty_repro.py` re-run verbatim at
`f28719c`: **13/15 laps** on the async-engine + `async def` lane resolve with
`current_state_ids == []`, `ok=True`, `err=None`, `status=running` (was 11/15 at
the previous commit — the window has widened, though the count is noisy). The
plain-`def` lane is 0/15 and the sync engine is clean.

`get_snapshot()` correctly refuses in the same window with
`SnapshotMidStepError`, and it heals (`+500ms ids=['m.a.c']`), so the
persistence boundary is sound. The defect is that the *caller's success signal*
fires inside the window: a wrapper that reads `current_state_ids` off a
successful receipt sees an empty configuration.

### R9-09 — #201's three-lane parity claim is false (Medium, DOC-DEFECT)

From **D9-fuzz-2**. `battle-f28719c/fuzz/g2_lap_parity.py` (sweep 1-10, 15, 20,
25 × 2 shapes × 2 service kinds × 2 engines) reports 33 mismatches; the
`def`-service ones form a clean pattern: on `rollback_ondone` the sync engine
runs **exactly two laps more** than async at every **odd** `maxIterations`
(1, 3, 5, … 25) and agrees at every even one. Corroborated independently by
`battle-6db65d8/fuzz/r11_livelock_matrix.py` (7 mismatches, all plain-`def`).

Classified `DOC-DEFECT`, not `LIBRARY-DEFECT`: both lanes still trip
`RunawayChainError`, so the bound is real and safety is not affected. What is
wrong is the changelog sentence claiming all three lanes agree at every limit
tested. An off-by-two in lap accounting between the sync drain and the async
engine.

### R9-10 — the priority lane does not survive a snapshot (Low, LIBRARY-DEFECT)

Merges **D9-persistence-3** and **N-6**.
`probes/main-f28719c/p12_priority_provenance_roundtrip.py` re-run:

```
lane before:       [('LANE', True)]
persisted pending: ['LANE', 'INBOX']
lane after restore: []
inbox after restore: ['LANE', 'INBOX']
```

Both the lane *and* the `#192` provenance tag are lost: an external
`send(priority=True)` that was pending at snapshot time restores as ordinary
inbox traffic. `interpreter.py:1488 _snapshot_pending_events` flattens with
`[ev for ev, _ in self._priority_queue] + inbox`, discarding the flag, and
`_enqueue_restored` → `_put_inbox` puts every restored record on the inbox lane.

Note the round-trip is not *only* lossy in the safe direction: because
provenance is lost, a restored item that was self-generated comes back tagged
external and becomes unsheddable — the same mechanism as R9-06.
`battle-f28719c/persistence/s2_lane_provenance_roundtrip.py` part B (chain
budget across a round-trip) re-ran **PASS**, so the charge site itself is intact.

### R9-11 — call-site queue-full refusals fire no hook (Low, LIBRARY-DEFECT)

From **D9-concurrency-2**; unchanged in mechanism from D8-concurrency-5 and
D7-concurrency-3. `battle-f28719c/concurrency/r9_observability_matrix.py --only=qf`
re-run: `result FAIL`, `callsite_refusals 78105`, `loopside_refusals 169`,
`queue_full_hooks 169`, `callsite_hooked false`. The optimistic `qsize()` guard
in `send_threadsafe` raises `QueueOverflowError` before anything is queued and
never reaches the loop-side hook at `interpreter.py:1136-1137`. A supervisor
watching `on_event_dropped` under-counts the true shed rate by ~99.8 %.

### R9-12 — `done.state.*` is an unreserved namespace (Low, DESIGN-CONSTRAINT)

From **N-1**, reported as High. **Downgraded to Low on re-run** — this is the
one round-9 severity the triage moves, and the reason is the discriminating
control the original report did not run.
`probes/main-f28719c/p1_forged_done_state.py` shows a hand-built
`DoneEvent("done.state.m.p", ...)` driving a parallel `onDone` on both engines,
and concludes `#195` "does not cover `done.state.*`". But
`battle-f28719c/r9triage/t1_plain_event_control.py` shows:

```
done/DoneEvent         ['m.finished']
done/plainEvent        ['m.finished']   <- a PLAIN Event does exactly the same
done/plainStr          ['m.finished']   <- so does the bare string
```

`base_interpreter.py:4517-4520` matches `current.on_done` by **name only** —
it never consults the event's type or provenance. So the `DoneEvent` class is
not privileged here at all; `done.state.*` is simply an open event namespace
that any caller can send by string. There is nothing for `#195` to "cover": the
same result is reachable with `send("done.state.m.p")`. Contrast R9-02, where
the public `AfterEvent` class *is* privileged over a plain `Event` of the same
name and the finding stands at High.

Remains a real constraint — the engine should reserve the `done.` / `error.` /
`after.` prefixes against user `send()` — but it is an open door, not a broken
lock, and our wrapper already refuses reserved prefixes at the boundary.

### R9-13 — `strict` does not gate restored `pending_events` (Low, DOC-CONTRACT-MISMATCH)

From **D9-semantics-2**. `events.py:403-414` documents that a record *without*
`"engine": true` restores as "user traffic, subject to `strict` / `onUnhandled`".
`onUnhandled` is honoured; `strict` is not. Matrix from
`battle-f28719c/semantics/p_persistence.py::P2`: `strict/bare_done` →
`status=running err=None recv=['done.invoke.q']`; `strict/plain_undeclared` →
`status=running err=None recv=['BOGUS']`; both `onUnhandled` rows correctly
raise `UnhandledEventError`. `_check_strict` runs at the `send()` call site
(`interpreter.py:907`) while the restore path re-enqueues through
`_enqueue_restored` → `_put_inbox`, bypassing it. Low because a caller who can
write `pending_events` already controls `state_ids` and `context` outright —
the trust boundary the library itself draws — and `onUnhandled: "error"` catches
it. The defect is that the documented sentence over-promises.

### R9-14 — #198 narrows v1 restore compatibility (Low, LIBRARY-DEFECT)

From **N-7**. `probes/main-f28719c/p6_v1_blob_from_0_8_0.py` re-run:
`A: v1 + both fields -> restored ['m.a']`; `B: v1 + state_ids only -> REFUSED`.
A `version: 1` running blob written by 0.8.0 without `configuration` used to
restore and is now refused with "the writer always records it, so the field was
dropped" — which is untrue of the 0.8.0 writer. The changelog migration note
names only the v0 shape. Either the note or the check needs to widen; as
shipped this is an undocumented breaking change for anyone resuming a 0.8.0
snapshot store.

### R9-15 — mid-step refusal misreports `child` (Low, LIBRARY-DEFECT)

From **D9-fuzz-5**. `battle-6db65d8/fuzz/r14_observability.py` §C:
`{'root': None, 'child': 'REFUSED child=False'}` on both service kinds. The
`child` flag is not propagated when the `SnapshotMidStepError` originates inside
an invoked child's entry action. Diagnostic quality only — the refusal itself is
correct.

### R9-16 — unknown top-level config keys accepted silently (Low, LIBRARY-DEFECT)

From **NW-unknown-keys**. Bad *values* for known keys raise `InvalidConfigError`
cleanly, but a misspelled *key* (`onUnhandledd`, `spawnBlockingTimeoutMs`)
leaves the default policy in place with no diagnostic
(`g3_policy.py P2_typo_keys`). Reclassified from the reporter's
`NEEDS-WRAPPER` to `LIBRARY-DEFECT`: silently downgrading a declared safety
policy to a default is an engine defect, even though an allowlist pass in our
loader is the mitigation we will ship.

## 4. Not library defects — carried elsewhere

### 4.1 `OUR-CONTRACT-DEFECT` (our catalogue JSON, `docs/plan/28-statechart-catalogue.md`)

| ID | Sev | Title |
|----|-----|-------|
| C-04 | **Blocker** | B16 elevation outlives `LOGOUT`/`IDLE_DEADLINE`/`ABSOLUTE_DEADLINE` and is acquirable after revocation — ends at `["auth.revoked","elevation.elevated"]` in both lanes |
| C-07b | **Blocker** | B18 `onUnhandled:"error"` turns a guard-denied `RELEASE` into `UnhandledEventError` and a dead kill switch |
| C-06 | High | B19 `stale_lockout` listens only for `RECONNECTED`; `OPERATOR_RESOLVED` is deferred and the account stays locked |
| CD-01 | High | Kill switch deferrable: B6/B9 declare no cancel handler, so under `onUnhandled=defer` the kill is held for the full in-flight service duration (1.49 s vs 1 ms) |
| CD-02 | Medium | B18 `RELEASE` undeclared on the kill chain's intermediate states → halt under `onUnhandled=error` |
| OUR-B14-d | Medium | "buffer is BOUNDED" is prose-only; no `maxBuffer` in `B14.machine.json` |
| OUR-B11-d | Medium | B11 defer-flap: a second `STREAM_UNHEALTHY` in `degraded` flaps `recording↔degraded` or is never recorded |
| C-05 | Low | B16 `STEP_UP_OK` while already elevated writes no audit record |
| C-01 | Low | Missing action/guard/service implementations are still not a build error |
| C-07 | Low | Catalogue promises halted states that do not exist in B16-B20 |

Two blockers here, both ours, both fixable in JSON without the library. Note
C-07b and CD-01 share a shape (no handler on an invoking/blocked state) and
C-07b's fix also lands the section-5.2 pre-emption result.

### 4.2 Wrapper obligations (documented engine contracts, not defects)

- **F1** — `rollback` + `invoke.onDone` re-arms a side-effecting service once per
  lap until `maxIterations` sheds it (1003 calls at default, 28 at 25, identical
  on both kinds). SCXML re-entry semantics. Obligation: no fallible entry action
  on an `invoke.onDone` target; make placement idempotent on a client order id.
- **F2** — a chain trip never reaches `on_error` or `interpreter.error`; it is
  visible only via `last_error` and `on_event_dropped`. Obligation:
  `CvErrorHooks` must subscribe to `on_event_dropped` and read `last_error` off
  the send receipt.
- **F3** — `last_error` is cleared once settled on the `async def` lane but
  retained on `def`. Obligation: sample per step, off the receipt, never
  asynchronously.
- **CV-6DB-01** (round-7 blocker, **withdrawn**) — a plain-`def` service not
  cancelled on state exit is the documented `#193` contract. Converts to an
  our-contract design rule: any state that both invokes and carries an escape
  transition must use `async def` (B12 buffering, B12 stepping, B13 subscribing).

## 5. `HARNESS-ERROR` and closed

- **F4** — `send(wait=True)` resolves at end-of-macrostep, not after an
  `async def` chain settles; three flaky B3 FAILs vanished once `SETTLE` widened
  0.03 → 0.05. Our harness, self-declared.
- **harness-timeout-false-hang** — 2-6 s `wait_for` timeouts under `tracemalloc`
  load produced false "D-soak-1 hang" lines; not reproducible at 15 s.
- **LC-42** (`50-r9-regression.md`) — the only gate PASS→FAIL flip; 4/5 PASS
  standalone on a sub-millisecond latency assertion. Host load noise.
- **priority-provenance-rerun** — `#192` shed-by-provenance holds: 0 drops of
  3000 priority sends. The harness's `always`-cycle collision with the
  pre-existing round-7 1000-microstep settle cap reproduces identically pre- and
  post-round-8, so it is not a regression. `PASS-with-note`.
- **scope-note** — the full brief (300-machine property fuzz, 10 k/s
  concurrency, 12-min soak) is not achievable in the 20-minute bound; round 9
  scoped to a regression re-run plus targeted probes. Recorded, not a finding.
- **CV-221-01 / CV-221-02** — closed by round-8 `#179`/`#200`/`#201`; re-verified
  still closed.
- Passing verifications retained for the record: **DRIVE-1**, **DRIVE-2**,
  **DRIVE-3**, **PROV-195** (holds on the real B18 machine — the forgery in
  R9-01 needs a *held genuine instance* or snapshot write, which `m5_sharp.py`
  check C does not have), **PROV-198**, **SNAP**, **SYNC**.

## 6. Adoption gate

Shut, on **R9-01** alone. It is the same blocker round 8 claimed to close, and
the fix moved the door rather than shutting it: `#195` made the *class* private
but left five ways to obtain or mint one, and `#198` — by hardening the snapshot
door in the same release — made the event channel the weaker of the two. Nothing
in `R9-02` … `R9-16` blocks on its own; R9-02 and R9-04 are the next two to fix
and both are narrow, single-site changes.
