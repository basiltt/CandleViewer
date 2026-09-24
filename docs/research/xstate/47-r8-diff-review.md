# 47 — Round-8 diff review: `221ce7c..6db65d8`

**Scope.** Full read of the 16-file diff (~2k lines) between `main@221ce7c`
and `main@6db65d8` (merge of #191, "0.8.1 round-7"; `__version__` still
reports `0.8.0` — key on the commit). Source files reviewed in full:
`interpreter.py` (+237), `base_interpreter.py` (+72), `models.py`,
`persistence.py`, `sync_interpreter.py`, `validation.py`, `exceptions.py`,
`__init__.py`. Tests reviewed: `test_round7_findings.py` (new, 37 tests),
`test_round6_findings.py`, `test_round5_findings.py`, `test_strict.py`.

**Environment.** `_ref/xstate-statemachine` @ `6db65d8`, venv
`.venv-main`, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. Baseline comparisons
run against a `git archive` of `221ce7c` extracted to a scratch tree.
`tests/test_round7_findings.py`: **37 passed** in 6.0 s. No `xfail`, no
`skip`, no `pytest.mark` suppressions anywhere in the new or edited tests.

**Probes.** `docs/research/xstate/probes/main-6db65d8/` —
`m1_…` … `m11_…`, one file per numbered question. Every service- or
action-related probe runs both `def` and `async def` spellings, per the
financial-OMS standard.

---

## Verdict

One **blocker** (M-1) and one **major** (M-2), both in the new
chain-budget machinery; both are regressions introduced by this diff and
both are invisible to the 37 new tests. The remaining seven questions in
the brief came back clean or with documented-but-acceptable behaviour
(M-3 … M-7). The round-7 fixes themselves (#179, #181, #183–#190) do what
the CHANGELOG says they do — verified individually.

| ID | Sev | Area | Status |
|----|-----|------|--------|
| M-1 | **Blocker** | #180 provenance-by-WHO | Reproduced; regression vs `221ce7c` |
| M-2 | **Major** | #179 `_chain_owed` | Reproduced; unbounded counter leak |
| M-3 | Minor | #179 `_chain_owed` settle is not identity-matched | Reasoned; latent |
| M-4 | Minor | #181 `children_timeout` is aggregate, not per child | Reproduced; doc gap |
| M-5 | Info | #181 late `sendTo` to a not-yet-registered child | Clean — does not drop |
| M-6 | Info | #182/#187 in-flight flag vs plugin hooks | Clean — parity both engines |
| M-7 | Info | #183/#184 child mid-step wait | Clean — bounded at 0.5 s |
| M-8 | Info | #185/#186 persistence | Clean — as specified |
| M-9 | Info | #190 strict/wildcard split | Clean — dispatch unchanged |

---

## M-1 (BLOCKER) — `send(priority=True)` from inside an action is never charged: `maxIterations` is unbounded on the priority lane

**File.** `src/xstate_statemachine/interpreter.py` — `send()` (line ~862)
and `_deliver_priority()` (line ~2342).

**What changed.** Before this diff, `_deliver_priority` charged by
*timing*:

```python
if self._processing:
    self._raise_depth += 1
```

#180 replaced that with provenance-by-WHO:

```python
def _deliver_priority(self, event, *, engine_completion: bool = False):
    if engine_completion:
        if self._chain_owed:
            self._chain_owed -= 1
        self._raise_depth += 1
```

and the public `send(..., priority=True)` path calls it with the default
`engine_completion=False`:

```python
if priority:
    if not self._refuse_if_not_running(event_obj):
        self._deliver_priority(event_obj)      # never charged
```

**Why this is wrong.** "Who issued it" is not the same question as "did it
come from outside the machine". The premise in the docstring — *"The public
priority lane is external traffic"* — is false for a send issued **from an
action running on this interpreter's own loop**. Both other lanes handle
that case explicitly: the default lane and the BLOCK lane each test
`self._issued_from_own_action()` and route to the internal queue with
`self._raise_depth += 1` (lines ~877 and ~905). The priority branch is
checked *first* and has no such test, so `priority=True` is a complete
bypass of the chain budget for self-feeding code.

This is exactly the failure #90 fixed on the default lane
("`async def act(i,...): await i.send(...)` spun unbounded while the sync
engine stopped at the limit") — reintroduced on the priority lane.

**Reproduction.** `probes/main-6db65d8/m1_priority_self_send_uncharged.py`
— a two-state ping-pong whose action re-sends `PING`, `maxIterations: 50`,
capped at 20 000 laps so the probe terminates:

```
# @ 6db65d8
asyncdef=False priority=True laps=20000 (cap 20000) elapsed=2.98s err=NoneType
asyncdef=True  priority=True laps=20000 (cap 20000) elapsed=3.16s err=NoneType

# @ 221ce7c (same probe, same venv)
asyncdef=False priority=True laps=51 (cap 20000) elapsed=6.28s err=RunawayChainError
asyncdef=True  priority=True laps=51 (cap 20000) elapsed=6.41s err=RunawayChainError
```

Uncapped, the probe never terminates and `stop()` cannot complete: the
interpreter is a live-locked loop with `last_error is None`, `status ==
"running"`, and no `on_event_dropped` hook. The same machine on the default
lane still trips correctly at 51 laps with `RunawayChainError`, so the two
lanes now disagree about whether an identical machine is runaway.

Severity is blocker for an OMS: `priority=True` is precisely what an
order-router self-send uses to jump a backlog, and the failure mode is a
silent hot loop with no observable signal — not a shed event, not a
`last_error`, not a plugin hook.

**Why the 37 tests miss it.** `TestExternalPrioritySendNeverCharged`
(test file line ~415) is the #180 pin. Its producer loop is
`i.send("TICK", priority=priority)` issued from `main()` — the *caller's*
task, outside any action. That is the case #180 was about and it is
correctly pinned. The self-send-from-action case, which #90 had already
established as charged work on every other lane, has no pin at all on the
priority lane.

**Suggested fix (library-side; not applied — source is read-only here).**
Decide provenance the way the other two lanes already do, rather than by
the lane:

```python
if priority:
    if self._issued_from_own_action() and not self._refuse_if_not_running(event_obj):
        self._raise_depth += 1
        self._internal_queue.append(event_obj)
        return receipt if receipt is not None else _completed()
    if not self._refuse_if_not_running(event_obj):
        self._deliver_priority(event_obj)
```

(Or, minimally, pass `engine_completion=self._issued_from_own_action()`.)
Note the internal-queue route also restores SCXML `raise` ordering for a
self-send, matching #36. #180's actual requirement — an *external*
producer whose send lands mid-macrostep is not charged — is preserved,
because `_issued_from_own_action()` is false for it.

**Adoption impact.** Any catalogue machine that self-sends with
`priority=True` from an action loses `maxIterations` entirely. Until fixed,
treat `priority=True` as forbidden inside actions and use the default lane
(which routes internally and is charged) — a rule worth adding to
`20-adoption-gate.md`.

---

## M-2 (MAJOR) — `_chain_owed` leaks permanently when a coroutine service dies of a `BaseException`

**File.** `src/xstate_statemachine/interpreter.py` — `_owe_completion()`
(line ~2658), `_invoke_service_task()` (line ~2470).

**The claimed invariant** (docstring of `_owe_completion`):

> Every coroutine service task ends in exactly one of: a `done.invoke` /
> `error.platform` published through `_publish_completion` (which settles
> the debt as it charges), or cancellation because the owning state was
> exited (settled here without a completion). So the count can never leak.

**The gap.** `_invoke_service_task` catches `asyncio.CancelledError` (re-
raised) and `Exception`. A `BaseException` that is neither — `SystemExit`,
`KeyboardInterrupt`, a `BaseException` subclass from a third-party
cancellation/timeout library, `GeneratorExit` — propagates out of the
wrapper. The task then finishes **not cancelled** and **without publishing
a completion**, so neither settlement path runs: `_settle_if_cancelled`
tests `t.cancelled()` and does nothing, and `_publish_completion` was never
reached. `_chain_owed` is decremented in exactly two places, both of which
are skipped.

**Reproduction.**
`probes/main-6db65d8/m2_chain_owed_leak_baseexception.py` — arm/disarm a
state whose `async def` service raises a bare `BaseException`, five laps:

```
lap 0: owed=1 depth=0 state={'p.off'}
lap 1: owed=2 depth=0 state={'p.off'}
lap 2: owed=3 depth=0 state={'p.off'}
lap 3: owed=4 depth=0 state={'p.off'}
lap 4: owed=5 depth=0 state={'p.off'}
```

Monotonic growth, one per lap, with the machine sitting idle in `off`
between laps.

**Consequence.** `_chain_owed` is never *read* as a magnitude — the loop
compares `self._chain_owed == owed_before` (line ~1730) — so a leak does
not by itself trip the budget. The damage is the opposite one: once the
counter is permanently non-zero it is still *decremented by every
subsequent engine completion* (M-3), which converts the leak into
mis-accounting on unrelated chains rather than into a false trip. The
counter also never resets except with the chain (`_raise_depth = 0` paths
do **not** clear `_chain_owed`), and there is no upper bound on it, so a
long-lived process that repeatedly enters such a state grows it without
limit. It is an `int`, so this is accounting corruption, not memory
exhaustion.

Note the *benign* neighbouring case is genuinely handled: a service that
simply **never completes** holds `owed == 1` for as long as the state is
active and settles on `stop()` via cancellation —
`m3_chain_owed_never_completing.py`:

```
after ARM:      owed= 1 depth= 0
after 10 PING:  owed= 1 depth= 0
after stop:     owed= 0
```

That is the designed behaviour and it does not block the ten unrelated
`PING`s. The leak is specific to the `BaseException` exit.

**Suggested fix.** Settle the debt from the task's done-callback on *any*
terminal outcome that did not publish, rather than on `cancelled()` alone
— e.g. track a per-task "published" flag and decrement in the callback if
it is still unset; or add `except BaseException: self._report_service_failure(...)`
(re-raising after) so every exit publishes.

---

## M-3 (MINOR) — the `_chain_owed` settle is a bare counter, not matched to the debt that armed it

**File.** `interpreter.py` `_deliver_priority` (line ~2384).

Every `engine_completion=True` delivery decrements `_chain_owed` if it is
non-zero — including completions that **never registered a debt**. Three
sources publish with `engine_completion=True` but are explicitly *not*
counted by `_owe_completion`:

1. a due `after` timer (`_deliver_priority(fired, engine_completion=True)`,
   line ~2450);
2. an invoked **child actor's** terminal — deliberately excluded, per the
   comment at line ~2633 ("a child's terminal may legitimately never come
   … so it cannot be a debt");
3. a plain `def` service's inline `done.invoke` (`_invoke_plain_service_inline`
   → `_publish_completion`), which is awaited in-step and never owes.

Any of these arriving while a genuine coroutine-service debt is
outstanding cancels that debt one-for-one. The step that armed the
coroutine service then sees `_chain_owed == owed_before` and executes the
"raised nothing, armed nothing, owes nothing" reset — the exact reset the
#179 design says must *not* fire under an outstanding debt.

**Status: latent, not reproduced as a user-visible failure.** I probed the
obvious shape — a parallel chart with a never-completing coroutine service
in one region, a 5 ms `after` self-loop in another, and 400 one-deep user
raises in a third (`m4`/`p4`) — and the machine behaved correctly
(400/400 raises delivered, zero drops, `owed` back to 0). The invoke-cycle
budget is also still correct with and without a fast timer beside it
(`m10_invoke_cycle_bounded.py`):

```
timer=False asyncdef=False service_laps=52 err=RunawayChainError
timer=True  asyncdef=False service_laps=51 err=RunawayChainError
timer=False asyncdef=True  service_laps=52 err=RunawayChainError
timer=True  asyncdef=True  service_laps=51 err=RunawayChainError
```

so a false *trip* is not reachable this way. The realistic consequence is
the mirror image — a chain the budget should have held open is closed one
link early by an unrelated timer, i.e. a runaway that takes longer to trip
— which I could not force into a failing assertion within the time bound.
Recorded as a design smell to fix alongside M-2, since the same
"match the settlement to the debt" change closes both.

---

## M-4 (MINOR) — `children_timeout` is an aggregate deadline, not a per-child bound; the docstring implies otherwise

**File.** `interpreter.py` `_await_actor_bringups()` (line ~2733).

The implementation computes one `deadline = time.monotonic() + timeout`
before the loop and reuses it across every `asyncio.wait` round, so the
bound is on the **total** bring-up phase. The parameter docstring on
`start()` reads "how long `start()` waits for the initial configuration's
invoked child actors to finish their own bring-up", which a reader
naturally takes per child.

In practice bring-ups are awaited concurrently in one `asyncio.wait`, so
for a single round the two readings coincide —
`m5_children_timeout_aggregate.py`, 4 children × 0.5 s entry,
`children_timeout=0.6`:

```
4 children each 0.5s entry, children_timeout=0.6: start() took 0.504s
```

The distinction bites only when `_actor_bringups` is refilled by a second
round (a child that itself invokes children during its bring-up): the
second round inherits the *remaining* budget, not a fresh one. That is
arguably the right semantic for a `start()` bound, but it is not what the
docstring says, and with the default 2 s a deep actor tree can have its
inner rounds given near-zero budget and log the #181 WARNING spuriously.

**Recommendation.** Documentation fix, plus — for adoption — always pass
`children_timeout=` explicitly rather than relying on
`DEFAULT_CHILDREN_TIMEOUT`, and size it for the whole tree.

Also note the `return` on timeout (replacing a re-queue) is correct and
well-commented: it is what keeps a timed-out `start()` from turning into an
unbounded *first send*. Good fix.

---

## M-5 (INFO) — a `sendTo` to a child that is still starting is **not** dropped

The brief's concern — after a `children_timeout` expiry, does a `sendTo`
in the meantime drop silently or defer? — is clean.
`m4_children_timeout_sendto.py`: parent with a child whose entry action
sleeps 1.0 s, `start(children_timeout=0.3)`, then `sendTo("kid","POKE")`
immediately after `start()` returns:

```
start() returned in 0.303s (timeout=0.3); actors=['par:kid']
after wait: actors=['par:kid'] kid.got=1
drops=[]
```

The child is **registered in `_actors` before its entry actions run**, so
`_resolve_actor_target` resolves, the event is queued on the child's own
inbox, and it is applied when the child's bring-up finishes (`got == 1`).
No `unresolved_target` drop. The #181 WARNING is about the bring-up not
being *finished*, not about the child being unaddressable — worth stating
explicitly, because the WARNING's wording ("start() returns with them in
progress") invites the opposite assumption.

---

## M-6 (INFO) — in-flight flag over `start()` and hooks: no legitimate snapshot newly refused

The brief asks whether any hook where a snapshot was previously legitimate
is now refused (plugin persistence hooks). Answer: no regression, and the
two engines agree. `m6_hook_snapshot_refusal.py` takes a
`get_persisted_snapshot()` from three hooks during `start()`:

```
async engine hook snapshots: {'on_interpreter_start': 'ok', 'on_action_execute': 'REFUSED', 'on_transition': 'ok'}
sync  engine hook snapshots: {'on_interpreter_start': 'ok', 'on_action_execute': 'REFUSED', 'on_transition': 'ok'}
```

`on_action_execute` is inside the refusal window by design (#187) and is
refused identically on both engines — the refusal is the *fix*, since a
snapshot taken there is torn by construction. `on_transition` — the hook
the docs recommend for persistence — remains accepted, on both engines,
including for the synthetic init transition #124 emits. `_processing` is
cleared in a `finally` (line ~646) so a raising entry action cannot leave
the flag stuck; I confirmed by inspection that the `except` branch also
sets `status = "stopped"` before re-raising, so no path leaves a running
interpreter permanently un-snapshottable.

---

## M-7 (INFO) — child mid-step: the wait cannot hang on a livelocked child

`_await_settled_for_snapshot` is bounded at its default `timeout_s=0.5`
and is only entered when the child's `_step_thread_ident` is a *different*
thread; a same-thread child is refused instantly. So the pathological case
the brief asks about — a livelocked child — costs 0.5 s once, not a hang.
`m7_child_midstep_wait.py`, a sync child actor grinding for 5 s on its own
pump thread while the parent snapshots:

```
child pump ident: <bound method ...>
refused after 0.502s child=True
elapsed total 0.502
```

The parent gets `SnapshotMidStepError(child=True)` rather than the torn
blob the old code returned — the #183/#184 fix works as specified.

Two small notes. (a) The 0.5 s bound is hard-coded at the single call site
in `base_interpreter.py` (line ~1421) with no way to pass a budget
through from `get_persisted_snapshot()`; for an OMS taking snapshots on a
hot path, 0.5 s of blocked wall clock per pathological child is worth
knowing about and worth a parameter. (b) `_step_thread_ident` is set
inside `_runner_recording` **on the child thread**, i.e. after
`Thread.start()` returns — so a parent that snapshots in the microseconds
before the child's first instruction reads `None` and refuses instead of
waiting. Refusing is the safe direction, so this is a note, not a finding.

---

## M-8 (INFO) — persistence #185 / #186 behave as specified

`m8_persistence_185_186.py`, parallel chart, `version: 2` blob:

```
version 2 hash? True
state_ids ['p.r1.b', 'p.r2.c']
configuration ['p', 'p.r1', 'p.r1.b', 'p.r2', 'p.r2.c']
roundtrip ok -> {'p.r1.b', 'p.r2.c'}
null hash refused: SnapshotDriftError
no configuration key: accepted -> {'p.r2.c', 'p.r1.b'}
```

- #185: `machine_hash: null` on a `version: 2` payload is now
  `SnapshotDriftError`, not a silent bypass. Correct, and the bypass is
  keyed on the declared version as the CHANGELOG says.
- #186: `configuration` and `state_ids` must agree when both are present;
  an **absent** `configuration` key is still accepted and reconstructed
  from `state_ids`. That is the right compatibility choice (v0/v1 writers)
  but it does mean an attacker/corruption that *removes* the key rather
  than emptying it takes the lenient path. Not a finding — the hash check
  covers structural drift and the field is inside the hashed payload — but
  worth recording.

---

## M-9 (INFO) — #190 strict/wildcard split: declaration vs dispatch, dispatch unchanged

`m9_strict_wildcard.py`, chart with `"GO"` and a `"*"` handler:

```
sync strict send('GO')   -> accepted, state={'p.a'}
sync strict send('TYPO') -> UnknownEventError
sync strict send('*')    -> UnknownEventError
sync non-strict send('TYPO') -> ok (wildcard dispatch preserved)
```

Exactly the specified split: under `strict` the wildcard no longer makes
every name known (so a typo'd event is rejected rather than swallowed by
the catch-all), while with `strict` off the wildcard still catches
undeclared events — dispatch is untouched. The validator's `raise` check
correctly opts back in with `wildcard_matches=True` (`validation.py` line
~245). One extra behaviour I verified and did not find documented: the
literal string `"*"` sent as an event *name* under `strict` is now itself
rejected, because of the added `and event_type != "*"` clause. That is
almost certainly intended, but it is a behaviour change not in the
CHANGELOG (see M-10).

---

## M-10 — behaviour changes not in the CHANGELOG

Reviewed the whole diff for silent changes. Only minor ones:

1. **`SnapshotMidStepError` gained public attributes** `machine_id` and
   `child`. The CHANGELOG describes the `child=True` *behaviour* but not
   that `machine_id` is now introspectable on the exception. Additive;
   worth a note since it is public API.
2. **`is_known_event("*")` is now `False`** under the declaration
   question (M-9). Not mentioned.
3. **A `version >= 1` blob with a *missing* `machine_hash` key** (not just
   `null`) is refused under `verify_hash`. The CHANGELOG says "missing or
   `null`", so this is covered — noted only because the pre-fix behaviour
   silently accepted it and a stored-blob migration will now hard-fail.

## M-11 — deleted / weakened tests

No test was deleted and none was weakened in a way that hides a
regression. Three edits, all defensible:

- `test_round6_findings.py::TestAsyncRollbackRearmCycleBounded` — the old
  single-spelling body was replaced by a `for kind in KINDS` subTest loop
  covering `def` and `async def`. This is the #179 retrofit and it is a
  strict strengthening.
- The same file's engine-parity assertion changed from
  `assertEqual(laps["a"], laps["s"])` to
  `assertLessEqual(abs(laps["a"] - laps["s"]), 1)`. A genuine loosening,
  by one lap. Justified by the #120 "spare exactly one pending completion
  at the trip" rule, which makes an exact match unachievable across
  engines; my own `m10` probe shows the same ±1 (51 vs 52). Acceptable,
  but it is the one place where a future one-lap accounting drift would
  now pass silently.
- `TestThreadsafeLoopSideRefusalObservable` — rewritten from a racy
  `run_coroutine_threadsafe` fan-out to a deterministic "fill the inbox
  behind a slow step, then call `_enqueue_from_thread` directly" shape.
  This is a de-flake, and it tests the same loop-side refusal path.

No `xfail`, no `skip`, no `pytest.mark` suppression in any reviewed test
file. `tests/test_round7_findings.py` confirmed to parametrise over both
service spellings and to run both engines where parity is the claim, as
the CHANGELOG states.

---

## Recommendation for the adoption gate

- **M-1 is a gate blocker.** Either it is fixed upstream, or
  `20-adoption-gate.md` gains a hard rule: *never* call
  `send(..., priority=True)` from inside an action — the default lane
  already delivers self-sends ahead of external traffic via the internal
  queue (#36) and is the correct mechanism.
- **M-2** should be fixed with M-1; on its own it is not reachable without
  a `BaseException`-raising service, which an OMS should not have, but the
  invariant the code documents is false and the next change that reads
  `_chain_owed` as a magnitude will inherit the bug.
- Everything else in the round-7 batch reproduces as advertised. The
  #179 single-lane refactor is the right architecture and it genuinely
  closes the `def`/`async def` budget asymmetry — `m10` shows both
  spellings tripping at the same lap count, which was the whole point.
