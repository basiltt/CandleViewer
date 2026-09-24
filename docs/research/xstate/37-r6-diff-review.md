# Round-6 diff review — 3ed3099..cec108b (unreleased 0.8.1)

**Scope.** 75 files, ~6.5k lines: round-5 fixes #142–#162 + reopened
#118/#122/#125/#133/#134, PR #141 (hot path), PR #163 (90% coverage gate).
Library at `cec108b`, `__version__` still `0.8.0` — key on the commit.

**Method.** Source read of `base_interpreter.py`, `interpreter.py`,
`sync_interpreter.py`, `persistence.py`, `models.py`, `validation.py`,
`exceptions.py`, then executable probes under
`docs/research/xstate/probes/main-cec108b/`. Every finding below was
reproduced before it was counted.

**Headline.** The round-5 fixes largely land: legality is checked on both
sides, `"fail"` genuinely stops and is non-restorable, `RootTargetError`
is non-downgradable, `Receipt.denied` is correct, `_die` is idempotent.
Two **new blockers** arrive with #150/#157: the `internal=` parameter of
`send_threadsafe` is an unvalidated escape hatch that defeats *both*
guardrails it was introduced next to — the `maxIterations` chain budget
and the bounded-inbox `OverflowPolicy`. #149 also only half-solves the
blocking it claims to solve.

---

## Findings

| id | severity | area | one line |
|----|----------|------|----------|
| K-1 | **BLOCKER** | #157 / backpressure | `internal=True` from any thread bypasses the bounded inbox and `OverflowPolicy` entirely |
| K-2 | **BLOCKER** | #150 / chain budget | `internal=False` from inside an action dodges `maxIterations` entirely |
| K-3 | HIGH | #149 | the entering macrostep still freezes *this machine's* timers and events for the service's full duration |
| K-4 | MEDIUM | #149 | `max_workers=4` is hard-coded and unconfigurable; >4 concurrent plain services serialise region entry |
| K-5 | MEDIUM | #150 | `_threadsafe_self_sends_in_flight` leaks when `_deliver` never runs |
| K-6 | LOW | #149 | `stop()` leaves service threads running past the machine's death (`shutdown(wait=False)`) |
| K-7 | LOW | #142 | a root with zero child states is "legal"; `_active_leaf_present` is now dead-ish and disagrees |
| K-8 | INFO | #163 | the coverage gate is a floor, not a ratchet — `fail_under` can be edited down in one line |

Verified-good list at the end.

---

### K-1 (BLOCKER) — `internal=True` forges past `OverflowPolicy.RAISE` and the bounded inbox

`Interpreter.send_threadsafe(event, internal=True)` is documented as an
accounting hint for a plain `threading.Thread` that an action started. It
is not validated against anything: any caller on any thread may pass it.
Setting it routes the event to `self._internal_queue` — which is
**unbounded by design** — and skips the `_inbox_is_full()` / `RAISE`
check entirely (`interpreter.py` ~L1115–1140: the overflow test is
guarded by `not self_issued`).

Probe `p4_forge_internal.py` — inbox bounded at 2, `OverflowPolicy.RAISE`,
run loop held hostage by a stalled action:

```
inbox max=2, policy=RAISE, loop stalled
  honest send_threadsafe : accepted=5 refused=45
  internal=True          : accepted=5000 refused=0
```

`p12_growth.py` pushes 200,000 forged sends through the same shape with no
refusal at any point. The producer does not have to be malicious — an
ordinary worker thread following the docstring's own advice ("an action
that hands its own re-trigger to one must pass `internal=True`") acquires
an unbounded, unmetered write path into the interpreter. For an OMS this
is the difference between a bounded inbox that sheds load and a process
that grows until the box dies.

Two orthogonal defects here: (a) `internal=` is a trust boundary with no
check — the interpreter cannot tell a genuine action-spawned worker from
anything else, and `contextvars` inheritance was the *only* thing that
made the classification honest; (b) even a *genuine* self-send should be
bounded — "the internal queue is never bounded" is a safe assumption only
while self-sends are charged to `maxIterations`, and per K-2 they are not
reliably charged.

*Ask:* refuse `internal=True` unless the calling thread can prove
provenance (a token minted by the action's context and passed explicitly),
or at minimum apply a separate hard cap to the internal queue with a typed
overflow.

**Repro:** `probes/main-cec108b/p4_forge_internal.py`, `p12_growth.py`

---

### K-2 (BLOCKER) — `internal=False` from inside an action dodges `maxIterations`

The same parameter fails open in the other direction. #150's whole point
is that an action re-triggering itself via a worker thread must be charged
to the chain budget. But `internal=False` forces external accounting
**even when the call is made directly on the loop thread from inside one
of this interpreter's own actions** — the case `_issued_from_own_action()`
detects perfectly well and is then told to ignore.

Probe `p3_threadsafe.py` case [1], `maxIterations: 20`:

```
[1] internal=False from action: hits=200 status=running err=None
    -> budget maxIterations=20; dodged
```

200 self-triggered macrosteps, no `RunawayChainError`, machine still
`running`. The budget is the library's only runaway protection; a single
keyword on a call site inside user code disables it silently and with no
diagnostic. Compare the honest path (`p13_budget.py`): a plain thread
passing `internal=True` trips correctly at 21 hits, and the default
(`internal=None`) from a plain thread runs 300 uncharged — the last is
documented, but it means the *safe* default is the unbounded one.

`internal=False` should be honoured only when the classifier would not
already have said "self"; forcing external when the call is demonstrably
from our own action is an unsound downgrade of a safety limit.

**Repro:** `probes/main-cec108b/p3_threadsafe.py` (case 1),
`p13_budget.py`

---

### K-3 (HIGH) — #149 keeps the *loop* turning but still freezes the *machine*

The changelog says a plain-`def` service no longer blocks "every timer,
actor and inbound send". Only the first clause is true. `run_in_executor`
does free the loop thread, but `_await_inline_services()` is awaited
**inside the entering macrostep**, before `_next_event` looks at any
queue — deliberately, to preserve #116's ordering. So unrelated asyncio
tasks run, and the machine itself does not.

Probe `p6_service_blocking.py`, parallel machine: region `work` invokes a
0.5 s plain service, region `ui` has an independent `after: 100ms` and an
`on: PING`:

```
[A] events handled during a 0.5s plain service: [('PING', 0.064), ('after.100.x.ui.idle', 0.506)]
```

A 100 ms deadline in a *completely independent region* fired at 506 ms —
five times late. (`p5_service_executor.py` case [2] shows 37 loop turns in
the same window, which is what makes this easy to mistake for fixed.)

#116's ordering guarantee and non-blocking service execution are in
genuine tension, and the resolution chosen keeps the blocking where it
hurts an OMS most: a risk-check region's watchdog cannot fire while an
unrelated pricing service runs. At minimum the *documentation* needs to
say that the machine's own event processing is still suspended for the
service's duration; the honest fix is an opt-out of #116 ordering for
services declared long-running.

**Repro:** `probes/main-cec108b/p6_service_blocking.py`

---

### K-4 (MEDIUM) — the default pool is 4 workers, hard-coded, with a latency cliff

`_get_service_executor()` creates `ThreadPoolExecutor(max_workers=4)`.
The number appears nowhere in the public surface: `Interpreter.__init__`
accepts a whole `service_executor` or nothing. A machine with more than
four concurrently-invoking plain services serialises in waves, and because
of K-3 each wave blocks the entering macrostep.

`p7_sat.py`, N parallel regions each invoking the same 0.2 s plain
service:

```
n=1:  0.22s    n=2:  0.22s    n=4:  0.22s
n=5:  0.41s    n=8:  0.41s    n=12: 0.62s
```

A clean step function at multiples of 4. Confirmed `max_workers=4` via
`p5_service_executor.py` case [1] (`peak_parallel=4`). This is a
reasonable default but a surprising one to discover in production; it
deserves a `service_pool_size=` argument and a line in the docstring
stating the concurrency limit. Note the workaround is available today
(pass your own executor) — which is why this is MEDIUM, not HIGH.

**Repro:** `probes/main-cec108b/p7_sat.py`, `p5_service_executor.py`

---

### K-5 (MEDIUM) — in-flight self-send counter leaks when `_deliver` never runs

`send_threadsafe` increments `_threadsafe_self_sends_in_flight` on the
calling thread and decrements it inside the `_deliver` coroutine handed to
`run_coroutine_threadsafe`. If that coroutine never runs — loop stopped,
machine torn down between the increment and the hop — the counter stays
up for ever.

`p3_threadsafe.py` case [3]:

```
[3] in-flight counter after loop stop: 5 (expected 0)
```

The counter is read at `interpreter.py:1513` as a condition for resetting
`_raise_depth`. A permanently non-zero value means the chain budget can
never reset, so a long-lived machine accumulates `_raise_depth` across
unrelated traffic and eventually trips `RunawayChainError` on legitimate
work. I could not drive that to a trip within the time budget
(`p10_counter_leak.py`: 60 external sends after seeding the leak still
left `raise_depth=0`, because external events do not increment it), so the
consequence is *latent* rather than demonstrated — but the invariant
"increment on thread A, decrement on loop B" has no compensating path and
the leak itself reproduces deterministically. Decrement in a
`finally`/done-callback on the returned future instead.

**Repro:** `probes/main-cec108b/p3_threadsafe.py` (case 3),
`p10_counter_leak.py`

---

### K-6 (LOW) — service threads outlive the machine

`_teardown()` calls `self._service_executor.shutdown(wait=False)` for the
owned pool. `p5_service_executor.py` case [3]: `stop()` returns in 0.00 s
with a 0.6 s service mid-flight, the `xsm-svc-sd_0` thread is still alive
afterwards, and the service **runs to completion** with its result
discarded. That is the documented and probably correct choice (user code
cannot be interrupted), but two consequences are undocumented: a service
with side effects still commits them after `stop()` returned, and a
process cannot exit promptly while one runs. Worth an explicit note next
to `stop()` — for an order-placement service "stop() returned" must not be
read as "nothing further will happen".

**Repro:** `probes/main-cec108b/p5_service_executor.py` (case 3)

---

### K-7 (LOW) — root-with-no-states is "legal"; two legality predicates coexist

`_configuration_is_legal()`'s recursion treats any node with empty
`states` as atomic and therefore legal. For `create_machine({"id": "ro",
"states": {}})` the configuration `{ro}` — the root alone, no leaf —
returns `True` (`p1_legality.py`: `root_only_legal: True`). The old
`_active_leaf_present()` explicitly excludes `self.machine` and would
return `False` for the same configuration. Both predicates survive in
`base_interpreter.py`; the new one is used at every #142/#143 site and the
old one still exists. A degenerate machine is an edge case, but two
disagreeing definitions of the same invariant in one file is exactly the
shape that reopened #142 in the first place. Collapse to one, and make the
root-with-no-leaf case explicitly illegal.

**Repro:** `probes/main-cec108b/p1_legality.py`

---

### K-8 (INFO) — coverage gate

PR #163 moves the threshold into `[tool.coverage.report] fail_under = 90`
so local `pytest --cov` and CI agree — a genuine improvement over the
CI-only `--cov-fail-under=86`. It remains a floor a contributor can lower
in one line with no second signal; the comment ("Ratchet up, never down")
is the only enforcement. Not a defect, just: the gate is honour-system.

---

## Verified good (probed, no finding)

- **`_configuration_is_legal`, read side.** A torn parallel region and a
  two-leaves-in-one-compound configuration are both refused with
  `SnapshotCorruptError` on restore. Final states and history children are
  handled correctly (history nodes never enter `active`, so they do not
  break the exactly-one-child test). `p1_legality.py`
- **`"fail"` → stopped.** `status="stopped"`, `current_state_ids` empty,
  `.error` is a real `TransitionFailedError` with the original exception
  on `__cause__`. Restart raises `InvalidConfigError`; the snapshot
  round-trips as `stopped` with the message preserved and restores to a
  `RestoredError` that also refuses `start()`. `p2_fail_stop.py`
- **Parent `onError` on both engines.** Async: parent reaches
  `par.failed` with `error.platform.k`. Sync: same, after `tick()` —
  parity holds, though the sync path needs a `tick()`/`send()` to pump,
  which is worth knowing. `p11_parity.py`, `p11b.py`
- **`RootTargetError`** is `InvalidConfigError` → `XStateMachineError` and
  is raised under `strict_targets` both `True` and `False`. `p9_misc.py`
- **`Receipt.denied`** is `True` for guard-denied, `False` for an
  undeclared event — the distinction #153 asked for. `p9_misc.py`
- **`_die` idempotency.** Double `cancel()` and cancel-before-first-turn
  both yield exactly `status="error"`, `is_running=False`, a typed
  `RuntimeError`. `p9_misc.py`
- **Caller-supplied executor** is not shut down by `stop()`. `p9_misc.py`
- **Plain service raising in its thread** reaches `onError` as
  `error.platform.<id>` carrying the original `RuntimeError`.
  `p5_service_executor.py`
- **Chain-budget trip is observable**: `last_transition_ok=False` and
  `last_error=RunawayChainError` after a genuine `internal=True` trip.
  `p13b.py`
- **PR #141 geometry memo** (`TransitionDefinition._geometry`) is shared
  across interpreters of the same machine object, but stores only
  immutable tree facts (LCCA + entry path) keyed on `id(target)`, and
  returns a fresh `list` copy so callers cannot corrupt it. Two
  interpreters on one machine behaved identically. `p8_geom.py`
- **`persistence.check_shape`** now types `version`, `status`, `history`,
  `actors`, `system`, `pending_events`/`deferred` records, and refuses
  `status="error"` with no recorded error. Read of the diff; no hole found.
- **No deleted tests.** `--diff-filter=D` is empty. The four modified
  assertions in `test_strict.py` / `test_v080_edge_paths.py` /
  `test_core_algorithm.py` are honest updates to the #145 contract
  (`error` → `stopped`, leaf → empty set), not weakenings. No new
  `xfail`/`skip` outside the pre-existing CLI tool-availability skips.

## Out-of-diff observation

A `parallel` root whose every region has reached a `final` leaf reports
`status="running"`, not `done` (`p8_geom.py` case [3]). I did not confirm
whether this predates `3ed3099`, so it is not counted as a round-6
regression — but it is worth a dedicated check before adoption, since
"all regions complete" is the natural terminal condition for a
multi-leg order workflow.

## Verdict delta

K-1 and K-2 are adoption blockers of the same kind the earlier rounds
found: a guardrail with an unauthenticated bypass. They are cheap to fix
(validate or drop the `internal=` override) and do not touch the
algorithm. K-3 is a correctness-of-documentation problem that becomes a
correctness problem the moment anyone relies on a watchdog timer in a
sibling region. Everything else on the round-5 list that I could probe
holds up.
