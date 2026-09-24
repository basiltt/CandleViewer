# Battle track: SEMANTICS @ `6db65d8`

**Library:** `_ref/xstate-statemachine` @ `6db65d8` (merge of #191; unreleased
0.8.1, `__version__` still reports 0.8.0 — keyed on the commit).
**Scope:** round-8 re-verification of every round-7 semantics defect, re-run of
the whole prior suite **on the coroutine lane that was structurally blind**,
plus new attacks aimed at this round's machinery (`_publish_completion` /
`_chain_owed` / `children_timeout` / in-flight-over-`start()` / blob integrity
/ strict+wildcard / receipt matrix).
**Scripts:** `battle-6db65d8/semantics/{n1..n6,s1..s5}` (prior, re-run),
`{n7,n8,n9,na,nb,nc}*.py` (new), `asyncify.py` (lane transform),
repro under `repro/`, machine-readable results under `results/`.

Financial-OMS standard applied throughout: nothing is counted as a defect
without a standalone repro that reproduces on a clean interpreter, and every
service-bearing check is run with **both `def` and `async def`** services.

---

## 1. Prior-defect table (round 7 → round 8)

### 1a. Method

Two passes over the prior suite:

1. **Unmodified** — every script in `battle-221ce7c/semantics/` run as-is.
2. **Coroutine lane** — every script re-run under `asyncify.py`, which patches
   `MachineLogic.__init__` so that every plain-`def` *service* becomes an
   `async def` wrapper around the original. This is the lane R7-01 lived in and
   the lane the round-6 pins could not see.

### 1b. Round-7 canonical defects

| Prior | Title | R7 severity | **R8 status** | Evidence |
|---|---|---|---|---|
| **R7-01** | `async def` completions bypass the charged lane; cycles unbounded, one variant settles EMPTY | Blocker | **FIXED** | `n7::A4`, `n9::C1`. 500 cycle configs × {def, async def} × both engines: `def_vs_asyncdef_lap_mismatch = 0`, `unbounded_laps = 0`, `silent_runaways = 0`. `A4` cycle trips `RunawayChainError` on both kinds with identical lap counts. |
| **R7-02** | External `send(priority=True)` charged to the chain budget; ~61% silently dropped | Blocker | **CHANGED — still present in a narrow band** | `n7::A2` FAIL → **D8-semantics-1**. Loss is now ~1.6% (not 61%), only when `maxIterations ≤ 10`, and is now *observable*. Root cause moved from the charge site to the shed site. |
| **R7-03** | `await start()` hangs unboundedly on a slow invoked child | Blocker | **FIXED** | `n7::A3`: 50 slow children, `start(children_timeout=0.3)` returns in **0.31 s**, `status == "running"`, one WARNING, all 50 children register afterwards. `nb::E4`: exactly one warning per `start()`, 3/3. |
| **R7-04** | External traffic renews the per-macrostep settle budget mid-chain | High | **FIXED** | `s2::S2-01` PASS on both lanes — the `or from_inbox` disjunct is gone; the chain still trips under 16 concurrent external senders. |
| **R7-05** | Async `start()` never sets the in-flight flag; #169 refusal inert during initial entry | High | **FIXED** | `n8::B1` — snapshots from `on_action_execute` / `on_transition` / `on_event_received` **during the initial descent** and during a **child's entry action**, both engines × both action kinds: refused-or-legal, **0 torn, 0 untyped**. |
| **R7-06** | `machine_hash` null/removed silently disables drift verification | High | **FIXED** | `n8::B3` — 12-cell matrix {v0,v1,v2} × {null, absent, wrong, intact}. No versioned blob with a missing/null/wrong hash restores. |
| **R7-07** | Root snapshot harvests a child's half-applied context | High | **FIXED** | `s4::S4-06` PASS on both lanes; `n8::B1` covers the child-entry-action window directly. |
| **R7-08** | `_await_settled_for_snapshot` spins `time.sleep` on the loop thread | High | **FIXED** | `s4::S4-06` PASS; `n8::B1` child snapshots complete without burning the wait. |
| **R7-09** | Contradictory `configuration` outranks `state_ids` on restore | Medium | **FIXED** | `n8::B2` — 400-mutation fuzz, **0 silently accepted**, 0 untyped rejections; every disagreeing pair is `SnapshotCorruptError`. |
| **R7-10** | `get_persisted_snapshot()` from `on_action_execute` torn on async | Medium | **FIXED** | `n8::B1`, `s1::S1-01/S1-02` (300 random machines) PASS on both lanes. |
| **R7-11** | Sync `_deferred_this_step` never cleared on `wait=False` | Medium | **FIXED** | `n3::N3-02` PASS; per-step scope cleared unconditionally (`interpreter.py:586`). |
| **R7-12** | `onUnhandled:"error"` kill invisible to the sender | Medium | **FIXED** | `n8::B5` — `Receipt.error` is `UnhandledEventError` on both engines; no success-shaped receipt. |
| **R7-13** | `strict:true` defeated by a `"*"` handler | Medium | **FIXED** | `n8::B4` — 4-cell matrix; an undeclared name is refused **even with a wildcard present**, declared names still dispatch. |
| **R7-14** | Call-site `QueueOverflowError` refusals fire no `on_event_dropped` | Low | **FIXED (as designed)** | `nb::E2`, `s2::S2-04` — every refusal observable on exactly one side; loop-side refusals fire the hook exactly once. |
| **R7-15** | `last_error` set after the drop hooks / cleared by next success | Low | **DESIGN-CONSTRAINT** | Confirmed unchanged; `on_event_dropped` is the reliable channel. Recorded in §4. |
| **R7-16** | `DEFAULT_SERVICE_POOL_SIZE` absent from `__all__` | Low | **FIXED** | `s2::S2-03` — `exported_from_package_root: true`. |
| **R7-17/18/19** | Non-semantics-track (builder/validator/API-shape items) | Low | not re-triaged here | Out of this track's scope; owned by the API/validator tracks. |
| **R7-20** | Sync/async lap-count asymmetry in the plain-`def` path | Low | **FIXED** | `n9::C1` `sync_vs_async_engine_lap_mismatch = 0` over 500 configs; `na::D1` trip laps equal across engines and kinds. |

### 1c. Prior-suite whole-run

| Suite | Unmodified (`def`) | Coroutine lane (`async def`) |
|---|---|---|
| `n1_persistence` | 6/6 PASS | 6/6 PASS |
| `n2_concurrency` | 7/7 PASS | 5/7 — 2 **transform artefacts**, §5 |
| `n3_semantics` | 7/7 PASS | 7/7 PASS |
| `n4_determinism` | 5/5 PASS | 4/5 — 1 **transform artefact**, §5 |
| `n5_fuzz_obs_sec` | 7/7 PASS | 7/7 PASS |
| `s1_persistence_hooks` | 2/2 PASS | 2/2 PASS |
| `s2_concurrency_obs` | 5/5 PASS | 4/5 — 1 **transform artefact**, §5 |
| `s3_fuzz_livelock` (520 configs × 2 engines) | 2/2 PASS | 2/2 PASS |
| `s4_semantics_det_sec` | 6/6 PASS | 6/6 PASS |
| **Total** | **47/47 PASS** | **43/47**, all 4 deltas explained as artefacts |

**Prior-suite verdict: no regressions on either lane.** All four coroutine-lane
deltas are attacks that assert *executor offloading* (`#149`: "a plain `def`
service runs off the loop", "the injected `service_executor` is used",
"`pool_size=8` beats `pool_size=1`", "the async trace equals the executor-backed
sync trace"). An `async def` service correctly runs **on** the loop and never
touches the executor, so those assertions are inapplicable after the transform,
not library failures. Verified by reading each failing detail block:
`ran_on_injected_executor: false`, `threads_seen: ["MainThread"]`,
`pool1 1.209 s vs pool8 1.211 s`.

---

## 2. New attacks

18 new attacks in 6 scripts. Reductions from the brief are in §5.

| ID | Target | Result |
|---|---|---|
| `A1` | `_chain_owed` leak: **100 concurrent never-completing** coroutine services + `stop()` | **PASS** — 100/100 armed, `stop()` in **0.05 s**, `owed_after_max ≤ 1`, 0 tasks left running |
| `A2` | **#180**: external `send(priority=True)` ×2000 during a self-generated chain, both kinds — 0 dropped required | **FAIL → D8-semantics-1** |
| `A3` | **#181**: `start(children_timeout=0.3)` with **50 slow children** | **PASS** — 0.31 s, running, warned, 50/50 register later |
| `A4` | **#179** debt accounting: a real cycle trips, 30 independent one-deep completions do **not** false-trip; parity across kinds | **PASS** |
| `B1` | Snapshot from **every hook** incl. **initial descent** and **child entry**, both engines × both action kinds | **PASS** — 0 torn, 0 untyped |
| `B2` | `configuration`/`state_ids` disagreement fuzz, **400 mutations** | **PASS** — 0 silently accepted |
| `B3` | `machine_hash` null/absent/wrong on **v0/v1/v2** blobs | **PASS** — 0 unverified restores |
| `B4` | **strict + wildcard** matrix (declared / undeclared / wildcard-only) | **PASS** |
| `B5` | **5-way receipt matrix** ok / denied / guard-crash / unhandled-kill, both engines, engine parity | **PASS** (discriminator includes the error *type*, §4) |
| `B6` | **Forge the engine-completion marker** from user code (`Event` subclass, `dataclasses.replace`, `internal=True`, captured `DoneEvent`) | **PASS** — 200 forged `done.invoke.*` sends left `_raise_depth`/`_chain_owed` unmoved; `engine_completion` is not on any public signature |
| `C1` | **Livelock fuzz: 500 configs × {def, async def} × {sync, async}**, 5 shapes, 28 s watchdog | **PASS** — 0 hangs, 0 silent runaways, 0 unbounded, **0 lap mismatches** across kinds *and* engines |
| `D1` | Determinism **50×** per lane × 3 lanes incl. **trip lap counts** | **PASS** — 1 distinct trace per lane; kinds and engines agree |
| `D2` | **Hash-seed sweep**: 5 `PYTHONHASHSEED` values, fresh subprocesses, 12 cycle configs × both kinds | **PASS** — 1 distinct output |
| `E1` | `chain_budget` hook on the **async-def lane** | **PASS** — both lanes trip *and* report |
| `E2` | `queue_full` loop-side + call-site observability | **PASS** |
| `E4` | `children_timeout` warning **exactly once** per `start()` | **PASS** — `[1, 1, 1]` |
| `NC` | **12-min soak**, 200 machines, **async def** services, 3 shapes incl. rollback+onDone and always→invoke, external priority producer, chaos snapshot/restore at quiescence | **PASS** — 169.4k events, **0/3.39M** external dropped, +8.8 MB RSS, §6 |

---

## 3. Defects

### D8-semantics-1 — an EXTERNAL `send(priority=True)` is still shed as `chain_budget` when a self-generated chain trips (**Medium**)

**Repro:** `repro/d8_s1_priority_shed.py` — exit 1 == reproduced. Deterministic,
**3/3 runs identical**.

```
{'kind': 'plain', 'external_sent': 2000, 'send_accepted_no_raise': 2000,
 'external_applied': 1992, 'external_LOST': 8,
 'chain_budget_drops_by_type': {'EXT': 8, 'done.invoke.pp.a': 1},
 'last_error': None, 'VERDICT': 'REPRODUCED'}
```

**Root cause — the fix was applied to the charge site, not the shed site.**
#180 made *charging* provenance-based, and that half is correct:
`_deliver_priority` (`interpreter.py:2375-2387`) increments `_raise_depth` only
`if engine_completion`. An external `send(priority=True)` is therefore never
charged — confirmed by `B6` (200 forged completions moved neither counter).

But the **shed** site never learned the same rule. At
`interpreter.py:1598-1623` the guard is:

```python
over = self._raise_depth > limit                       # :1598
if over and is_system_event(event) and not self._chain_tripped:
    ...                                                 # spare the first completion
elif over:
    ...
    plugin.on_event_dropped(self, event, "chain_budget")  # :1623
```

The predicate is `over` — a property of the *chain* — applied to whatever
`_next_event()` (`:1582`) happened to pull. The priority queue
(`_priority_queue`, appended at `:2388`) is a **single FIFO carrying engine
completions and external priority sends side by side**. So once a chain the
external sender had no part in goes over budget, the next external send sitting
in that FIFO is destroyed with reason `chain_budget`. Provenance is honoured
when the counter goes *up* and ignored when the axe comes *down*.

**Why it is Medium, not the Blocker R7-02 was:**

- *Magnitude collapsed.* Loss is now bounded by the trip window, not the whole
  run. Sweep over `maxIterations` (500 external sends each):

  | `maxIterations` | applied | lost |
  |---|---|---|
  | 5 | 480 | **20** |
  | 10 | 483 | **17** |
  | 20 | 500 | 0 |
  | 50 | 500 | 0 |
  | 100 | 500 | 0 |

  Only tight budgets (≤10) are affected; R7-02 lost ~61% at any budget.
- *It is now observable.* `on_event_dropped(..., "chain_budget")` fires for the
  dropped `EXT`, and a caller using `wait=True` gets a failed receipt
  (measured: 499 clean / **1 with error**, matching the loss). R7-02's loss was
  invisible. `last_error` remains `None` on the fire-and-forget path, so the
  hook or the receipt — not `last_error` — is the channel that must be wired.
- *The 12-min async soak lost zero external events* (§6) — at a realistic
  budget the band is not entered.

**Impact for an OMS:** a fire-and-forget external `send(priority=True)` on a
chart with a tight `maxIterations` can be discarded with no exception at the
call site. Mitigation is available today: use `wait=True` and check
`Receipt.error`, or subscribe `on_event_dropped`, or keep `maxIterations ≥ 20`.

**Fix direction:** the drop decision needs the same provenance bit the charge
decision already has — tag the queue entry at `_deliver_priority` and shed only
tagged (engine/self-raised) events at `:1600`, letting external traffic through
as the inbox lane already does post-#105.

---

**No other defects found.** 17 of the 18 new attacks pass, and the entire prior
suite passes on both lanes.

---

## 4. Not a defect — recorded

- **`Receipt` 4-tuple is not injective on its own.** `(denied, error is None,
  deferred, changed)` gives `(F,F,F,F)` for *both* a crashed guard and the
  `onUnhandled:"error"` kill. Adding the **error class** (`RuntimeError` vs
  `UnhandledEventError`) makes the 5-way matrix injective, and both carry a
  non-`None` error, so no observer receives a success-shaped receipt. R7-12 is
  genuinely closed; consumers must switch on the error *type*, not the tuple.
- **A wrong-arity guard is silently denied.** A guard spelled
  `(interpreter, ctx, event)` — the *action/service* signature — is never
  called and denies its transition. This is the documented default
  `guardErrorPolicy` ("a raising guard evaluates to `False`",
  `base_interpreter.py:4926-4934`) and **is** observable: `on_guard_error`
  fires with the `TypeError`. Easy to trip because guards take `(ctx, event)`
  while everything else takes `(interpreter, ctx, event)`. Wrapper guidance,
  not a library defect.
- **`last_error` is still set after the drop hooks and cleared by the next
  success** (R7-15). Unchanged, by design. Any drop accounting must use
  `on_event_dropped`.
- **`__dict__` is deliberately retained** on interpreters
  (`base_interpreter.py:464`), so ad-hoc attributes are accepted despite
  `__slots__`. By design; carried from round 7.

---

## 5. Reductions and caveats

| Brief item | Ran as | Why |
|---|---|---|
| Livelock fuzz ≥500 configs × both kinds × both engines | **500** configs × 2 kinds × 2 engines = 1,500 runs, 28 s watchdog | at the stated size; ~8 min, within the wall-clock bound |
| Persistence property ≥300 machines | **300** (`s1::S1-02`) + 400-mutation blob fuzz (`B2`) | at size |
| External priority at **10k/s** | **2000 sends as fast as the loop accepts** (`A2`), plus 20/sweep × 200 machines for 12 min in the soak (~4.8M) | a true 10 k/s rate limiter would spend the whole budget; the burst is strictly more adversarial per unit time |
| `_chain_owed` under 100 concurrent never-completing services | at size (`A1`) | — |
| `children_timeout` with 50 slow children | at size (`A3`) | — |
| Determinism 50× | at size (`D1`), 3 lanes | — |
| Hash-seed sweep | 5 seeds × 12 configs × 2 kinds | subprocess cost |
| 12-min soak, 200 machines, async services | at size (`nc_soak_async.py`) | — |
| RAISE loop-side refusals exactly-once | covered by `s2::S2-04` (re-run, both lanes) + `nb::E2` | not re-implemented |
| `start()` ordering vs #116 with `children_timeout` hit | `s4::S4-02` (both lanes) + `A3`/`E4` | — |
| Coroutine-lane re-run of prior scripts | via `asyncify.py` monkeypatch, not hand-rewritten | mechanical, uniform, and auditable; 4 known-inapplicable artefacts listed in §1c |

**Caveat on the transform:** `asyncify.py` wraps services only (not actions or
guards), and leaves `MachineNode` values (invoked child machines) alone. Attacks
that assert executor behaviour are inapplicable under it — see §1c.

---

## 6. Soak (12 min, 200 machines, **async def** services)

`nc_soak_async.py` — derived from `s5_soak.py` with (a) the `price` service
changed to `async def` (the #179 coroutine lane), (b) an **external priority
producer** issuing `send("FILL", priority=True)` per machine per sweep, and
(c) a per-machine `on_event_dropped` spy so external loss is counted by
reason **and event type**.

Smoke run (20 s / 40 machines / 5 ext per sweep) as a pre-check:

```
events 8080, snapshots 36, restores 36,
midstep_at_quiescence 0, restore_drift 0, inert_running 0,
typed_errors 0, untyped_errors 0, lost_fills 0,
ext_sent 40400, external_dropped_as_chain_budget 0,
drops_by_reason {"stopped:FILL": 35, "stopped:done.invoke.ai.work": 1},
rss_delta_mb 2.45, cpu_percent_avg 95.4, ok true
```

The only drops are `stopped:*` — events racing a deliberate chaos `stop()`,
which is correct refusal, not loss. **Zero external events shed as
`chain_budget`**, confirming D8-semantics-1 does not fire at a realistic
`maxIterations`.

**Full run — 720 s, 200 machines, 20 external sends per machine per sweep**
(`results/nc_soak_async.json`):

```
soak_seconds 720.0, machines 200, service_kind "async def (#179 coroutine lane)"
events        169,400      typed_errors           0
ext_sent    3,388,000      untyped_errors         0
snapshots       5,920      midstep_at_quiescence  0
restores        5,920      restore_drift          0
orders          6,120      inert_running          0
                           lost_fills             0
external_dropped_as_chain_budget  0
drops_by_reason  {"stopped:FILL": 200, "stopped:done.invoke.rb.work": 4}
rss_delta_mb 8.81   cpu_percent_avg 98.3   ok true
```

| Soak requirement | Result |
|---|---|
| CPU bounded | **PASS** — 98.3% of **one** core, flat; no runaway spin |
| Memory bounded | **PASS** — **+8.8 MB** RSS over 12 min across 200 machines and 6,120 constructed interpreters |
| 0 dropped external | **PASS** — **0 / 3,388,000** shed as `chain_budget`; the only 200 `stopped:FILL` drops are events racing a chaos `stop()`, i.e. correct refusal |
| No livelock | **PASS** — 169,400 `wait=True` sends all resolved; no watchdog, no hang |
| Snapshot integrity at quiescence | **PASS** — 5,920 snapshots, 5,920 restores, **0** mid-step refusals at quiescence, **0** drift, **0** inert-running zombies, **0** lost fills |
| Typed-error discipline | **PASS** — 0 typed *and* 0 untyped errors |

The rollback+onDone and always→invoke shapes — the two that were unbounded on
the coroutine lane in round 7 (R7-01) — ran 12 minutes under an async-`def`
service with zero runaways and zero `chain_budget` drops beyond the 4 completions
racing `stop()`. This is the strongest single piece of evidence that R7-01 is
structurally closed.

---

## 7. Verdict

**The round-7 fix set holds.** All three round-7 Blockers are closed, and the
one that mattered most — R7-01, the uncharged coroutine lane — is closed
*structurally*, not narrowly: across 1,500 fuzz runs the lap count at which a
machine trips is now **identical for `def` and `async def` and identical
between the two engines**, which is exactly the invariant #179 set out to
establish. The persistence hardening (#182–#186) survives a 400-mutation blob
fuzz, a 12-cell hash matrix, and hook snapshots from the initial descent and
from child entry actions on both engines. The provenance model resists direct
forgery (`B6`).

**One defect remains open on this track: D8-semantics-1 (Medium)** — #180's
provenance rule was applied to the charge site but not to the shed site, so
external priority sends queued behind a tripped chain are still discarded. It
is a ~1.6% loss confined to `maxIterations ≤ 10`, and unlike R7-02 it is
observable on the receipt and on `on_event_dropped`.

**Gate impact (this track's input only):** the semantics track no longer holds
a Blocker. D8-semantics-1 is a Medium that a wrapper can absorb today
(`wait=True` + `Receipt.error`, or an `on_event_dropped` subscription, or
`maxIterations ≥ 20`). This track's recommendation is **conditional pass**,
subject to the other tracks' findings and to the wrapper carrying the §4
guidance on guard arity and on `last_error` not being a drop channel.
