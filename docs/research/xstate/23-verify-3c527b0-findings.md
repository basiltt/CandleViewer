# 23 — Re-test of the 13 `5327ba6` findings on `main@3c527b0`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `3c527b0` (merge of PR #83, `fix/0.8.1-remaining-issues`). CHANGELOG
`[Unreleased] — targeting 0.8.1`; **`__version__` still reports `0.8.0`**, so
this build is identified **by commit**, here and everywhere downstream.

**Date:** 2026-09-18. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro 10.0.26200.
**Interpreter:** `_ref/xstate-statemachine/.venv-main/Scripts/python`, env
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

**Baseline:** `22-verify-main-verdict.md` §2.2 (13 findings on `5327ba6`).
**Diff under review:** `5327ba6..3c527b0` — 18 files, +1023/−357. One functional
commit, `2459c82`: **`ErrorEvent` (#80)**, **provenance-based system events
(#79)**, **one task per invoked child (#43)**. Source files touched:
`events.py` (+92), `base_interpreter.py`, `interpreter.py` (+337/−…),
`models.py`, `sync_interpreter.py`, `plugins.py`, `validation.py` (−50),
`__init__.py`; plus the new `tests/test_actor_perf.py` (+460).

No library source was modified. No `git` command was run in the CandleViewer
repository. GitHub was not written to.

---

## 0. Bottom line

**Twelve of thirteen findings are unchanged. One is obsolete, as predicted.**

- **M-1 — the finding that gates our order path — is STILL-PRESENT**, and was
  re-tested harder than any other item (§2). PR #83 rewrote the very function
  that parks the event (`_handle_unhandled_event`, for #79) and reworked the
  interpreter around it (#43), and the receipt gap survived both untouched.
  `Receipt` is still `('state_ids', 'changed', 'error')` — no field was added
  to carry the defer disposition.
- **M-5 is OBSOLETE in the way the CHANGELOG says, and partly better than that.**
  The build-time reserved-namespace warning was withdrawn *and* the runtime rule
  it disagreed with was replaced: system status is now decided by **provenance**
  (`events.is_system_event`), not by name. The case-variant trap (`DONE.review`
  vs `done.review`) is gone because *neither* is exempt any more. A genuine
  residual remains, but it is a different, smaller thing (§3).
- **No regressions.** Nothing that worked on `5327ba6` stopped working. The new
  `tests/test_actor_perf.py` is 9/9 green. The 500-way receipt test (probe A1)
  still passes, unaffected by #43's one-task redesign.
- **#43 changed actor teardown mechanics but not observable ordering** (§4).

---

## 1. Re-test table

| ID | Sev (was) | Status on `3c527b0` | Evidence / one-line |
|---|---|---|---|
| **M-1** | High | **STILL-PRESENT** | `probes/main-5327ba6/a2_confirm_deferred_receipt.py` → `changed=False, error=None, deferred_count=1`, then `OPEN` replays into `gate.filled`, `filled=1`. Receipt shape unchanged. See §2. |
| **F-1** | High | **STILL-PRESENT** | `f_tripped_sticky.py` → `INNER handled: 0 of 5 (expected 5)`. Identical to baseline. #83 touches `sync_interpreter.py` only for `ErrorEvent`/provenance plumbing. |
| **F-2** | High | **STILL-PRESENT** | `f_clock_kwargs.py` → `AssertionError: unexpected kwargs: ['owner', 'sync']`, raised from `base_interpreter.py:3451`. Shim untouched by #83. |
| **M-2** | Medium | **STILL-PRESENT** | `c14_async_no_send_budget.py` → sync stops at 1001 steps; async spins to 112 486 steps in 3 s and is still climbing, `status='running'`, `queue_depth=0`. |
| **M-3** (=F-4) | Medium | **STILL-PRESENT** | `g1b_alias_ambiguity_and_leak.py` → `fetchData` and `fetch_data` both registered to **different** callables, config requiring either still **BUILT**. Probe `gh_aliases_deprecation` G1 and G9 still FAIL. |
| **M-4** (=F-3) | Medium | **STILL-PRESENT** | `f_pollute.py`, `f_shared_logic.py`, G10 → registry grows `['store_user'] → ['storeUser','store_user'] → ['STOREUSER','storeUser','store_user']` across builds; second build raises `InvalidConfigError`. |
| **F-5** | Medium | **STILL-PRESENT** | `f_loader_dup.py` → `bound to: fetch_data`, silently, by iteration order. |
| **F-6** | Medium | **STILL-PRESENT** | `f_sticky_invoke.py` → `state: {'m.work'} (expected m.done)`. |
| **F-7** | Medium | **STILL-PRESENT** | `f_rollback_gap.py` → `state: {'m.b'} context n = 0 (rollback should restore 0)`. Checkpoint-skip predicate unchanged. |
| **M-5** (⊃F-8) | Low | **OBSOLETE** (premise removed) — **residual re-expressed, §3** | #79 landed: `is_system_event` is provenance-based; the build-time warning is withdrawn; `validation.py` −50 lines. Probe F5 now reports `no-warning` for every reserved `on` key **by design**. |
| **M-6** | Low | **STILL-PRESENT** | Probe D3 → `RuntimeError` before `start()`; D4 → `UnknownEventError` for unknown, `NO-RAISE` for known, on a stopped interpreter. Precedence unchanged. |
| **F-9** | Low | **STILL-PRESENT** | `f_chain.py` → `SYNC landed: {'m.s1000'}` vs `ASYNC landed: {'m.s1001'}`; probes C2b/C5/C9–C12 still cut at 1001. Cut still silent. |
| **F-10** | Low | **STILL-PRESENT** | `resolver.py:89` `_SIBLING_FALLBACKS_WARNED: Set[Tuple[str, str]] = set()` — still an unbounded module-global. |

**Tally: 12 STILL-PRESENT, 1 OBSOLETE, 0 FIXED-BY-83, 0 CHANGED, 0 new regressions.**

This is the expected shape: PR #83 implements three items that were
**deferred-by-design** in the `5327ba6` verdict (§5 item 10 of that document
named #80, #79's runtime half, and #43's task-collapse half as exactly the work
still outstanding). It was never scoped to fix F-1…F-10 or M-1…M-4, and it
did not.

---

## 2. M-1 in detail — the finding that gates the order path

M-1 was re-tested with more care than the rest because CV-C01 mandates
`onUnhandled: "defer"` and CV-C06 mandates `send(wait=True)` on the order path,
and M-1 is what those two produce together.

### 2.1 Why it was plausible that #83 moved it

PR #83 rewrote `_handle_unhandled_event` in `base_interpreter.py` — the exact
function containing the `defer` branch — replacing its name-based system-event
exemption with `if is_system_event(event) or not isinstance(event, Event)`.
It also reworked `interpreter.py` substantially for #43. Either could plausibly
have touched the receipt-resolution path.

### 2.2 What was actually run

`probes/main-5327ba6/a2_confirm_deferred_receipt.py`, unmodified:

```
receipt at defer time:
  changed = False
  error   = None
  states  = ['gate.closed']
  context = {'filled': 0}
  deferred_count = 1

after OPEN (replay):
  states  = ['gate.filled']
  context = {'filled': 1}
```

Plus a new four-variant probe, `probes/main-3c527b0/p3_m1_deep.py`:

```
V1 defer receipt:        {'changed': False, 'error': None, 'deferred': 1}
V2 Receipt fields:       ('state_ids', 'changed', 'error')
V3 true-negative receipt:{'changed': False, 'error': None, 'deferred': 0}
   => distinguishable only via deferred_count: 0 vs 0
V4 post-replay: same receipt object changed=False  state={'gate.filled'}  ctx={'filled': 1}
```

And the full 500-way adversarial receipt suite, `probes/main-5327ba6/a_receipts.py`:
**3/7 pass — identical to the `5327ba6` baseline.** A1 (500 concurrent
`wait=True` sends of one `Event` under rollback + defer + a bounded inbox) still
passes; A6 (200 priority sends of one instance) still passes; A2 still
reproduces M-1.

### 2.3 Findings

1. **STILL-PRESENT, unchanged in mechanism.** The defer branch records the
   disposition on `self._deferred_events`; the pending receipt learns nothing.
   The receipt still resolves from the end-of-macrostep configuration/context
   diff.
2. **`Receipt` gained no field.** Still `('state_ids', 'changed', 'error')`.
   There is no in-band way for a caller to learn the event was parked.
3. **The false negative is byte-identical to a true negative** (V1 vs V3): a
   deferred event and a genuinely handled action-less event both yield
   `changed=False, error=None`.
4. **`deferred_count` is NOT a usable discriminator from the call site.**
   This is the material update to the finding. The `5327ba6` verdict proposed a
   CV-C06 `deferred_count` clause as our mitigation. At the caller's `await`
   point **both** the deferred case and the true-negative case read
   `deferred_count == 0` (V3 line 3) — the probe's own `deferred_count = 1`
   in `a2` is read at a different observation point. A mitigation built on
   reading `deferred_count` after `await i.send(..., wait=True)` **does not
   work as specified** and must be re-derived before CV-C06 can rely on it.
5. **V4:** the receipt object is not updated on replay. A caller holding the
   receipt still sees `changed=False` after the event has driven its transition.

**Disposition:** keep the draft, keep `blocks_adoption: true`, keep the
severity at High. Flag item 4 to whoever writes the CV-C06 clause — the
mitigation named in `22-verify-main-verdict.md` §3 is not sound as written.

---

## 3. M-5 — obsolete premise, re-expressed residual

The `5327ba6` M-5 had three limbs. On `3c527b0`:

| Limb | Status |
|---|---|
| The build-time reserved-namespace warning is narrower than the runtime rule (misses `DONE.review`) | **OBSOLETE.** The warning is withdrawn (`validation.py` −50) and the runtime rule it disagreed with is gone. Probe F5: `no-warning` for every reserved `on` key, by design. |
| `strict` exempts reserved prefixes, so a typo'd `send("done.typo")` is accepted silently | **FIXED by #79.** Direct probe `probes/main-3c527b0/p1_strict_user_system.py`: `done.review`, `DONE.review`, `error.validation` now all raise `UnknownEventError` on a `strict` machine. |
| `SYSTEM_EVENT_PREFIXES` is importable but not extensible (`base_interpreter` holds an import-time copy) | **STILL TRUE, now harmless.** `base_interpreter.py:275` still binds `_SYSTEM_EVENT_PREFIXES`, but it is vestigial: the live checks call `is_system_event()`. Probe F1's `module_patched=True, base_interpreter_copy=False` is now a dead observation. |

**Also fixed, and material to us:** probe F6 previously showed `"*"` matching
only `ordinary`. It now reports
`matched_by_star: ['ordinary', 'error.validation', 'done.review']` — a
user-sent event named `error.*` / `done.*` is visible to `"*"` and trips
`onUnhandled`. **This retires the substantive half of CV-C15.**

**Residual worth stating (small, new shape).** `is_known_event` treats anything
matching `ENGINE_EVENT_SHAPES` as known, and those shapes are still matched by
**prefix**, not by structure. On a `strict` machine, `p1` shows `after.5` and
`xstate.foo` are still **ACCEPTED** while `done.review` is rejected. So a typo
in the `after.` or `xstate.` namespace remains silent under `strict`. That is
narrower than the original M-5 and narrower than CV-C15, but it is the bit
that survives.

**Draft action:** M-5 had no standalone draft in `issues/new-main/` (it was a
ride-along on #79). The ride-along comment for #79 must be rewritten: its
premise is now the opposite of what it said. Marked in
`issues/comments-main-5327ba6/79.md` as superseded.

---

## 4. #43's one-task design — teardown, ordering, and the receipt test

The instruction to check whether #43 changed actor teardown ordering,
done/error delivery order, or the 500-way receipt test. It did not, in any
observable way.

### 4.1 What changed mechanically

`interpreter.py` drops the per-child manager task that awaited `wait_done()`.
Completion is now pushed from the child's terminal listener. A new
`self._invoked_children: Dict[str, List[Interpreter]]` maps owning state id →
children, and `_cancel_state_tasks` stops them directly:

```python
for child in list(self._invoked_children.pop(state.id, [])):
    child._terminal_listeners = [
        fn for fn in child._terminal_listeners
        if getattr(fn, "__name__", "") != "_on_child_terminal"
    ]
    self._actors.pop(child.id, None)
    self._actor_sources.pop(child.id, None)
    if child.status == "running":
        await child.stop()
```

The listener is **detached before** `stop()`, so a child stopped by state exit
is "cancelled", not "done", and cannot fire `onDone` into a state just left.
That is the correct discrimination and it is implemented deliberately.

### 4.2 What was observed

`probes/main-3c527b0/p2_actor_lifecycle.py`:

```
child running before LEAVE: running
after LEAVE: state= {'p.gone'}  child= stopped  actors= []  LOG= []
tasks alive: 2
error path: state= {'p.bad'}  LOG= [('onError', 'ErrorEvent', 'ValueError')]
done path:  state= {'p.ok'}   LOG= [('onDone', 'DoneEvent')]
```

- **Teardown:** exiting the invoking state stops the child, clears it from
  `_actors`, and fires **no** `onDone`/`onError`. Correct, and the same
  observable behaviour as `5327ba6`.
- **Error delivery:** a failing service now delivers a real **`ErrorEvent`**
  carrying `event.error` (`ValueError`), not a `DoneEvent` with an exception in
  `data`. This is #80 working as advertised. Delivery *order* is unchanged —
  `onError` routes to `p.bad` exactly as before.
- **Done delivery:** `DoneEvent` → `p.ok`, unchanged.
- **Task count:** no leaked tasks after teardown.

`tests/test_actor_perf.py` (new, +460): **9 passed in 1.64 s** — the ≤51-tasks,
no-timer-callbacks and sub-2 ms-`onDone` claims are pinned by the library's own
suite.

### 4.3 The 500-way receipt test

`probes/main-5327ba6/a_receipts.py` re-run on `3c527b0`: **3/7, identical to
baseline.** A1's 500 concurrent `wait=True` sends of one `Event` object, under
`actionErrorPolicy: "rollback"` + `onUnhandled: "defer"` + a bounded inbox with
`RAISE`, all resolve; none hang. **#43 did not disturb receipt resolution.**

### 4.4 Other probe suites, for completeness

| Suite | `5327ba6` | `3c527b0` |
|---|---|---|
| `a_receipts` | 3/7 | **3/7** |
| `b_rollback_raise` | 6/7 | **6/7** |
| `b5_child_actor_rollback` | 1/1 | **1/1** |
| `c_sync_chain_budget` | 7/9 | **7/9** |
| `c2_raise_builtin_chain` | 1/5 | **1/5** |
| `gh_aliases_deprecation` | 12/15 | **12/15** |
| `def_threads_dormant_namespaces` | 5/13 | **5/13** (composition shifted: F6 now passes on merit, F5 now fails by design — see §3) |

Every `FAIL` above is a `DOCUMENT`-expectation probe or a known finding, not a
regression.

---

## 5. Draft updates applied

Every draft in `issues/new-main/` now carries `status:`,
`retested_on: main@3c527b0 (2026-09-18, after PR #83)`, and
`library_version: main@3c527b0`, plus a **Re-test on `main@3c527b0`** section
with refreshed Observed output and a note on why #83 did or did not reach it.

| Draft | `status:` | Action |
|---|---|---|
| `M-1-deferred-event-receipt-false-negative.md` | `still-present` | Kept; `blocks_adoption: true` retained; §2.4 caveat about `deferred_count` added |
| `F-1-sync-tripped-flag-starves-later-events.md` | `still-present` | Kept |
| `F-2-kwargs-clock-receives-unexpected-sync.md` | `still-present` | Kept |
| `M-2-async-action-self-send-unbounded.md` | `still-present` | Kept |
| `M-3-alias-ambiguity-guard-misses-documented-example.md` | `still-present` | Kept |
| `M-4-resolve-aliases-mutates-caller-registry.md` | `still-present` | Kept |
| `F-5-logic-modules-setdefault-order-dependent.md` | `still-present` | Kept |
| `F-6-done-invoke-dropped-after-trip.md` | `still-present` | Kept |

F-7, F-9, F-10, M-5 and M-6 had no standalone drafts (all ride-alongs on #27,
#77, #31, #79 and #78 respectively). F-7, F-9, F-10 and M-6 ride-alongs stand
as written. **The #79 ride-along (M-5) must be rewritten** — §3.

Nothing was filed, posted, commented or edited on GitHub.

---

## 6. Consequences for the verdict

1. **The gate decision does not move.** ADOPT WITH CONSTRAINTS, with the
   operative condition still ours (`E29-T10` linter + `tests/xstate_contract/`).
   High open count is unchanged at 4 (#31/LC-07, M-1, F-1, F-2).
2. **M-1 still blocks the order path**, and its proposed mitigation is now
   known to be unsound as specified (§2.3 item 4). That is the single most
   important line in this document.
3. **CV-C15 can be narrowed.** #79 makes a user event named `error.*`/`done.*`
   visible to `"*"`, trippable by `onUnhandled`, and rejected by `strict`. The
   case-insensitivity requirement on the `E50-T05` event-name gate is retired.
   The `after.` / `xstate.` namespaces still need the gate (§3 residual).
4. **The `Production Characteristics` task budget is now `children + 1`**, down
   from `2 × children`, and is pinned by the library's own tests. Capacity
   planning that used the old number can be revised.
5. **#80's `ErrorEvent` is a net ergonomics win** for our `onError` paths:
   branch on `isinstance(event, ErrorEvent)` / read `event.error`. Note
   `ErrorEvent.data` emits a `DeprecationWarning` and is removed in 0.9 — do
   not write new code against it.

---

## 7. Evidence index

| Artefact | What it holds |
|---|---|
| `probes/main-5327ba6/*.py` | The `5327ba6` probe corpus, re-run unmodified on `3c527b0` |
| `probes/main-3c527b0/p1_strict_user_system.py` | `strict` acceptance per event name under #79 provenance |
| `probes/main-3c527b0/p2_actor_lifecycle.py` | #43 teardown, `ErrorEvent`/`DoneEvent` delivery order, task count |
| `probes/main-3c527b0/p3_m1_deep.py` | M-1 four-variant deep re-test, incl. the `deferred_count` discriminator check |
| `issues/new-main/*.md` | The 8 drafts, front-matter and Observed refreshed |
| `22-verify-main-verdict.md` | The `5327ba6` baseline this document re-tests |
