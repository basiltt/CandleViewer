# Battle-test track: SEMANTICS — SCXML 1.0 / XState v5 conformance, deep

**Build under test.** `_ref/xstate-statemachine` @ `main`, commit
`5e07ba8842345a73ef8f830f0281de16370a7c74` (unreleased 0.8.1; `__version__`
still reports `0.8.0` — this build is identified **by commit, never by
version string**). `CHANGELOG.md` `[Unreleased] — targeting 0.8.1`, read in
full before writing a single case.

**Date:** 2026-09-18. **Python:** CPython 3.13.7. **OS:** Windows 11 Pro
10.0.26200. **Interpreter for every run below:**
`_ref/xstate-statemachine/.venv-main/Scripts/python` with
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the adopting
project's repository. GitHub was read-only throughout.

**Standard applied.** This library is a candidate to run an order-management
system handling real money. Every silent failure, nondeterminism or ordering
ambiguity is treated as a defect and reproduced with a standalone script, not
argued about.

---

## 0. Bottom line

**90 conformance cases, 172 case×engine runs, 165 PASS / 7 FAIL.** Four
distinct defects, none of them a Blocker for our adoption shape, two of them
High.

- **The core transition algorithm is genuinely good.** Transition selection,
  ancestor preemption, LCCA computation, internal-vs-external self-transitions
  with `reenter`, targetless transitions, history (shallow/deep, including
  across parallel), in-state guards, event-descriptor precedence and the
  entire action-ordering surface are **conformant on both engines**. Groups
  **H (40/40)** and **O (32/32)** are perfect; **S is 38/40** and **T is
  35/36**. This is materially better than the 37-probe baseline suggested,
  and the two engines agree on 88 of 90 cases.
- **Two High defects, both on the actor/invoke boundary.** **D-semantics-1**:
  an invoked child machine's `output` is **discarded** — the parent's
  `done.invoke.<id>` carries `child.context` instead
  (`interpreter.py:2078`, `sync_interpreter.py:1179`). **D-semantics-2**:
  `escalate` from an invoked child is **unroutable** — it is delivered as
  `xstate.error.actor.<runtime-actor-id>`, a type no parent config can name,
  so it reaches neither `onError` nor `"*"` and is silently lost. Both engines,
  both defects. For an OMS these are exactly the wrong two things to lose: a
  child's *result* and a child's *escalated failure*.
- **One Medium engine-parity defect.** **D-semantics-3**: `SyncInterpreter.tick()`
  delivers only **one** due `after` deadline per call when deadlines chain, so
  a polled sync machine falls one stage behind per poll. Async is correct.
- **One Low spec deviation, deterministic.** **D-semantics-4**: exit order
  across parallel regions is depth-major, not SCXML's reverse-document-order
  (region-major). Verified stable across five `PYTHONHASHSEED` values, so it
  is a deviation, not a nondeterminism.
- **One contract worth writing down, not a defect.** `invoke.input` does not
  merge into a child's declared context keys — by deliberate design
  (`base_interpreter.py:530`, the review-F11 context-injection guard). The
  supported form is a `context` factory of `{input}`. Our machine contracts
  must use that form; see CV-S01.

---

## 1. Method

### 1.1 What "conformance" means here

Each case states an **expected** value derived from a normative source cited
in the case itself — SCXML 1.0 (W3C REC 2015-09-01) section numbers, or
XState v5's documented behaviour where SCXML is silent (`reenter`, partial
event descriptors, `input`/`output`, `spawnChild`/`stopChild`). The case body
returns an **observed** value. PASS is `observed == expected`.

Cases are modelled on the shapes the SCXML IRP suite exercises (test 403
series for conflicting transitions and document order, 570 for parallel
`done.state`, 364/372 for entry/exit order, 387/388 for history) and on
XState v5's core transition tests, rather than being a line-by-line port —
the IRP suite is written in SCXML XML against a datamodel this library does
not implement, so a mechanical port would have measured the harness, not the
engine.

**Honesty note on expectations.** Two of my initial expectations were wrong
and were corrected *against the spec text, before* looking at whether the
library agreed:

- **S-06** originally asserted depth-major exit order. SCXML §3.13
  `exitStates` sorts `statesToExit` in **exitOrder = reverse document order**,
  which for `p, A, a1, B, b1` is `b1, B, a1, A, p` — region-major. The
  corrected expectation is what the case now asserts, and the library fails
  it. Had I not re-read the spec, this defect would have been recorded as a
  PASS.
- **T-02 / T-17** initially failed because *my* `assign` action dicts were
  malformed (the built-in requires params nested under `params`, per #32).
  That is a harness bug, not a library defect; both now pass. I mention it
  because the library's build-time validator caught the sibling cases
  (A-06/A-08 `InvalidConfigError: missing required param(s)`) and that
  validator is a real quality signal.

### 1.2 Dual-engine execution

`conf_harness.py` runs **the same case body twice** — once on `Interpreter`
(async) and once on `SyncInterpreter` — behind a `Rig` that hides the engine
difference (`rig.boot`, `rig.send`, `rig.ids`, `rig.sleep` pumps the sync
timer lane via `tick()`). A divergence therefore shows up as one row reading
`PASS | FAIL`, which is how D-semantics-3 was found. Cases that are
inherently async-only (async services, real-timer actor delivery) declare
`engines=("async",)` and are reported as `n/a` on sync rather than silently
skipped.

### 1.3 Files

| Path (under `docs/research/xstate/battle-5e07ba8/semantics/`) | Contents |
|---|---|
| `conf_harness.py` | Dual-engine harness: `@case(id, title, spec, expected)`, `Rig`, JSON results writer |
| `c1_selection.py` | **S-01…S-20** — selection, preemption, document order, LCCA, `reenter` |
| `c2_eventless_done.py` | **T-01…T-18** — eventless/`always`, transients, `after:0`, `done.state`, final output |
| `c3_history_instate.py` | **H-01…H-20** — shallow/deep history incl. parallel, `stateIn`, descriptor precedence |
| `c4_actors.py` | **A-01…A-16** — invoke as machine, input/output, onError chains, `sendTo`+delay+`cancel`, spawn/`stopChild`, `sendParent` |
| `c5_ordering.py` | **O-01…O-16** — action ordering, `assign` ordering, targetless vs exit/entry, `raise` queue semantics |
| `run_all_groups.py` | Runs all five groups in one process → `results/all.json` |
| `results/*.json` | Per-group and combined machine-readable results |
| `repro/d1_sync_after0_chain.py`, `repro/d1d_realistic.py` | D-semantics-3 minimal + realistic repro |
| `repro/d2_statein_suffix.py`, `repro/d2b.py` | `stateIn` name-resolution probe (→ D-semantics-5) |
| `repro/d3_child_output.py` | D-semantics-1 minimal repro |
| `repro/d4_invoke_input.py` | `invoke.input` contract probe (not a defect) |
| `repro/d5_sendto_unresolved.py` | D-semantics-6 minimal repro |
| `repro/d6_escalate_route.py` | D-semantics-2 minimal repro |
| `repro/d7_exit_order.py` | D-semantics-4 determinism check across 5 hash seeds |

### 1.4 Exact commands

```bash
PY="<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python"
cd <workspace>/CandleViewer/docs/research/xstate/battle-5e07ba8/semantics

# whole matrix (172 case x engine runs)
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" run_all_groups.py

# individual groups
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" c1_selection.py        # 38/40
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" c2_eventless_done.py   # 35/36
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" c3_history_instate.py  # 40/40
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" c4_actors.py           # 20/24
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" c5_ordering.py         # 32/32

# defect repros
cd repro
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" d3_child_output.py      # D-semantics-1
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" d6_escalate_route.py    # D-semantics-2
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" d1d_realistic.py        # D-semantics-3
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" d7_exit_order.py        # D-semantics-4
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" d2b.py                  # D-semantics-5
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" d5_sendto_unresolved.py # D-semantics-6
```

---

## 2. Results summary

| Group | Area | Cases | Runs | PASS | FAIL |
|---|---|---:|---:|---:|---:|
| **S** | Transition selection, preemption, document order, LCCA, `reenter` | 20 | 40 | 38 | 2 |
| **T** | Eventless/`always`, transients, `after:0`, `done.state`, final output | 18 | 36 | 35 | 1 |
| **H** | History (shallow/deep/parallel), `stateIn`, descriptor precedence | 20 | 40 | **40** | 0 |
| **A** | Actors: invoke/machine, input/output, onError chains, `sendTo`/`cancel`, spawn | 16 | 24 | 20 | 4 |
| **O** | Action ordering, `assign` ordering, targetless vs exit/entry, `raise` | 16 | 32 | **32** | 0 |
| **Total** | | **90** | **172** | **165** | **7** |

**Engine agreement: 88 / 90 cases.** The two disagreements are T-07 (sync
only, D-semantics-3) and the async-only rows, which are `n/a` rather than a
disagreement.

---

## 3. Conformance matrix

Legend: **P** = PASS, **F** = FAIL, **–** = not applicable to that engine.

### 3.1 Group S — transition selection, preemption, LCCA

| # | Case | Spec | async | sync |
|---|---|---|:-:|:-:|
| S-01 | Parallel regions: both take their own transition on one event | SCXML 3.13 `selectTransitions` | P | P |
| S-02 | Ancestor preemption: child transition wins over ancestor | SCXML 3.13 (innermost enabled) | P | P |
| S-03 | Document order among two enabled transitions on one state | SCXML 3.13 | P | P |
| S-04 | Guard fallthrough: first enabled branch in document order | SCXML 3.13 | P | P |
| S-05 | Conflicting cross-region transitions: document-order-first wins | SCXML 3.13 `removeConflictingTransitions` | P | P |
| **S-06** | **Exit order across parallel regions = reverse document order** | **SCXML 3.13 `exitStates` exitOrder** | **F** | **F** |
| S-07 | LCCA: sibling↔sibling exits/enters only up to the LCCA | SCXML 3.13 `getTransitionDomain` | P | P |
| S-08 | LCCA across parallel: in-region target does not re-enter sibling region | SCXML 3.13 | P | P |
| S-09 | Targetless transition: actions run, no exit/entry | SCXML 3.13 | P | P |
| S-10 | Self-transition default (no `reenter`) is internal | XState v5 / SCXML `type='internal'` | P | P |
| S-11 | `reenter:true` is external: exit → action → entry | XState v5 / SCXML 3.13 | P | P |
| S-12 | v4 `internal:false` ≡ v5 `reenter:true` | `models.py:539` alias | P | P |
| S-13 | Compound `reenter:true` re-enters via `initial`, not last child | SCXML 3.13 | P | P |
| S-14 | Transition to a descendant enters only the missing links | SCXML 3.13 | P | P |
| S-15 | Transition to a proper ancestor exits and re-enters it | SCXML 3.13 | P | P |
| S-16 | Exit inner→outer, entry outer→inner | SCXML 3.9 | P | P |
| S-17 | Order: exit actions → transition actions → entry actions | SCXML 3.13 | P | P |
| S-18 | Unknown event: no transition, no actions | SCXML 3.13 | P | P |
| S-19 | Disabled inner transition does not shadow an enabled ancestor | SCXML 3.13 | P | P |
| S-20 | Transition actions receive the triggering event's payload | SCXML 3.13 | P | P |

### 3.2 Group T — eventless, transients, `after:0`, done/final

| # | Case | Spec | async | sync |
|---|---|---|:-:|:-:|
| T-01 | Eventless chain a→b→c settles in one macrostep | SCXML 3.13 | P | P |
| T-02 | Eventless guard re-evaluated after each microstep | SCXML 3.13 | P | P |
| T-03 | Eventless fires in the same macrostep as the event transition | SCXML 3.13 | P | P |
| T-04 | Transient state's entry/exit run though never observable | SCXML 3.8/3.9 | P | P |
| T-05 | Eventless with false guard does not fire | SCXML 3.13 | P | P |
| T-06 | `after:0` is a delayed event, not `always` | XState v5 | P | P |
| **T-07** | **`after:0` chain of three settles without further input** | **XState v5 / SCXML 6.2 delay=0** | **P** | **F** |
| T-08 | Exiting a state cancels its pending `after` | SCXML 6.2.2 | P | P |
| T-09 | `done.state.<compound>` on final child triggers `onDone` | SCXML 3.7 | P | P |
| T-10 | `done.state.<parallel>` only when **every** region is final | SCXML 3.7 | P | P |
| T-11 | `done.state` payload carries the final state's `output` | SCXML 3.7 `<donedata>` | P | P |
| T-12 | Top-level final ⇒ status `done` + machine `output` | SCXML 3.7 | P | P |
| T-13 | Final state's `output` becomes machine output when none declared | XState v5 | P | P |
| T-14 | A done machine accepts no further transitions | SCXML 3.7 | P | P |
| T-15 | Parallel `onDone` never fires if a region has no final state | SCXML 3.7 | P | P |
| T-16 | Nested done bubbles: inner final → outer final → outer `onDone` | SCXML 3.7 | P | P |
| T-17 | `always` on an ancestor is evaluated for the active leaf | SCXML 3.13 | P | P |
| T-18 | Unconditional eventless self-loop is bounded, not a hang | SCXML 3.13 note / `maxIterations` | P | P |

### 3.3 Group H — history, in-state guards, descriptors

| # | Case | Spec | async | sync |
|---|---|---|:-:|:-:|
| H-01 | Shallow history restores the last active immediate child | SCXML 3.10 | P | P |
| H-02 | Shallow history does **not** restore grandchildren | SCXML 3.10 | P | P |
| H-03 | Deep history restores the full nested configuration | SCXML 3.10 | P | P |
| H-04 | Unrecorded history takes its default target | SCXML 3.10 | P | P |
| H-05 | Unrecorded history with no default uses parent's `initial` | XState v5 | P | P |
| H-06 | **Deep history across a parallel state restores every region's leaf** | SCXML 3.10 | P | P |
| H-07 | Shallow history on a parallel restores regions to their initials | SCXML 3.10 | P | P |
| H-08 | Second re-entry reflects the newer history snapshot | SCXML 3.10 | P | P |
| H-09 | History pseudo-state is never in the active configuration | SCXML 3.10 | P | P |
| H-10 | `stateIn` satisfied for an active leaf | SCXML 5.9.2 `In()` | P | P |
| H-11 | `stateIn` false for an inactive sibling leaf | SCXML 5.9.2 | P | P |
| H-12 | `stateIn` satisfied by an ancestor of an active leaf | SCXML 5.9.2 | P | P |
| H-13 | `stateIn` does not match a same-named node on another branch | SCXML 5.9.2 (identity) | P | P |
| H-14 | Exact descriptor beats `prefix.*` | XState v5 | P | P |
| H-15 | Longer partial beats shorter partial | XState v5 | P | P |
| H-16 | Bare `*` is last resort | XState v5 | P | P |
| H-17 | `mouse.*` matches bare `mouse` | XState v5 | P | P |
| H-18 | `mouse.*` does **not** match `mousedown` (segment boundary) | XState v5 | P | P |
| H-19 | Deeper state's `*` outranks shallower state's exact match | SCXML 3.13 (depth first) | P | P |
| H-20 | Failed guard on exact descriptor falls through to `*` | XState v5 | P | P |

### 3.4 Group A — actors, invoke, error propagation

| # | Case | Spec | async | sync |
|---|---|---|:-:|:-:|
| A-01 | invoke `src` as machine → `done.invoke.<id>` on child's final | SCXML 6.4.4 | P | P |
| **A-02** | **Child machine `output` delivered as `done.invoke` data** | **SCXML 6.4.4 / XState v5** | **F** | **F** |
| A-03 | `input` reaches child via `context` factory; plain dict ⇒ `context["input"]` | XState v5 + `base_interpreter.py:530` | P | P |
| A-04 | Failing invoked **callable** → `ErrorEvent` at `onError` | SCXML 6.4 / #80 | P | P |
| A-05 | Failing invoked **child machine** → parent's `onError` | SCXML 6.4 / #99 | P | P |
| **A-06** | **onError chain: grandchild fails → child escalates → grandparent catches** | **SCXML 5.10/6.4** | **F** | **F** |
| A-07 | Exiting the invoking state cancels a running invocation | SCXML 6.4.1 | P | – |
| A-08 | `sendTo` with `delay`+`id` delivered to the addressed child | SCXML 6.2 | P | – |
| A-09 | `cancel` with matching `sendId` prevents the delayed send | SCXML 6.3 | P | – |
| A-10 | `cancel` with non-matching `sendId` leaves the send intact | SCXML 6.3 | P | – |
| A-11 | `spawnChild` in `entry` creates an addressable actor | XState v5 | P | – |
| A-12 | `stopChild` on exit stops the spawned actor | XState v5 / SCXML 6.4.1 | P | – |
| A-13 | `sendParent` from an invoked child reaches the parent | SCXML 6.2 | P | – |
| A-14 | `done.invoke` does not match a user's `"*"` handler | #79 / XState v5 | P | P |
| A-15 | Unhandled invoked-service failure is observable, not swallowed | SCXML 5.10 | P | P |
| A-16 | Invocation starts **after** the owning state's entry actions | SCXML 6.4.1 | P | – |

### 3.5 Group O — action ordering

| # | Case | Spec | async | sync |
|---|---|---|:-:|:-:|
| O-01 | Transition actions run in declaration order | SCXML 3.13 | P | P |
| O-02 | `assign` ordering: later action sees earlier assignment | SCXML 4.3 | P | P |
| O-03 | Entry action sees context written by the transition's actions | SCXML 3.13 | P | P |
| O-04 | Exit action precedes transition actions; its write is visible | SCXML 3.13 | P | P |
| O-05 | Targetless transition runs no exit and no entry | SCXML 3.13 | P | P |
| O-06 | Targetless transition on an **ancestor** does not exit the leaf | SCXML 3.13 | P | P |
| O-07 | Nested entry actions run outermost-first | SCXML 3.9 | P | P |
| O-08 | Across an eventless hop: xA, t1, eB, xB, t2, eC | SCXML 3.13 | P | P |
| O-09 | Parallel fan-out: both regions' actions, each exactly once | SCXML 3.13 | P | P |
| O-10 | Shared-ancestor transition fires once, not once per region | SCXML 3.13 | P | P |
| O-11 | Shared-ancestor guard evaluated once (side effects not multiplied) | SCXML 5.9 / `base_interpreter.py:3671` | P | P |
| O-12 | `raise` is queued internally, taken in the next microstep | SCXML 3.13 / 4.5 | P | P |
| O-13 | Two `raise`d events processed in raise order (FIFO) | SCXML 3.13 | P | P |
| O-14 | Internal queue drained before the next external event | SCXML 3.13 | P | P |
| O-15 | Entry actions run before the state's `always` is evaluated | SCXML 3.13 | P | P |
| O-16 | Root `entry` then initial state's `entry` at `start()` | SCXML 3.2/3.9 | P | P |

---

## 4. Defects

### D-semantics-1 — **High** — An invoked child machine's `output` is discarded; `done.invoke` carries its raw context instead

**Case:** A-02 (both engines). **Repro:** `repro/d3_child_output.py`.

SCXML §6.4.4 and XState v5 both specify that a finished invoked session's
*output* (its `<donedata>` / machine `output`) is the payload of
`done.invoke.<invokeid>`. The library instead hands the parent
`child.context`.

```
child standalone status/output: done {'code': 7}      <- child resolves output correctly
parent state : ['m.ok']
done event   : {'type': 'done.invoke.kid', 'data': {}}  <- output LOST; empty context
VERDICT      : DEFECT - child output lost
```

The child's own `output` machinery works (`_resolve_output`, T-11/T-12/T-13
all pass, and the standalone line above reads `{'code': 7}`). The defect is
purely at the hand-off.

**Root cause.** Both engines build the `DoneEvent` from `child.context` and
never consult `child.output`:

- `src/xstate_statemachine/interpreter.py:2075-2079`
  ```python
  done_event = DoneEvent(
      type=f"done.invoke.{invocation.id}",
      data=child.context,          # <- should be child.output, falling back to context
      src=invocation.id,
  )
  ```
- `src/xstate_statemachine/sync_interpreter.py:1177-1181` — identical shape.

The comment at `interpreter.py:2074` (`"onDone carries the child's final
context, as before"`) shows this is a deliberate 0.7.x carry-over, but it
predates the `output` feature that T-12/T-13 pin, and the two are now
inconsistent: a machine's `output` is honoured when it is the *root* and
ignored when it is a *child*.

**Why it is High for us.** A child machine is the natural unit for "price this
order", "settle this fill". `output` is the documented way to return a
*computed result* distinct from working state. Silently substituting the
child's whole context means (a) the result is missing, and (b) the child's
entire internal context — potentially including credentials or unreduced
intermediate state — is injected into the parent's event payload. Both halves
are wrong for an OMS.

**Not a Blocker** only because a workaround exists and is cheap: have the
child write its result into a well-known context key and read *that* on
`onDone`. See CV-S02.

---

### D-semantics-2 — **High** — `escalate` from an invoked child is unroutable: it reaches neither `onError` nor `"*"`, and is silently lost

**Case:** A-06 (both engines). **Repro:** `repro/d6_escalate_route.py`.

```
parent state     : ['m.run']          <- expected ['m.caught']
events seen by '*': []                 <- the parent's wildcard saw NOTHING
VERDICT          : DEFECT - escalate unroutable to onError
```

The parent declares `invoke: {id: "kid", src: ..., onError: "caught"}` **and**
a catch-all `on: {"*": {actions: ["spy"]}}`. The child runs
`escalate({error: "child failed"})`. Neither handler fires. The error
disappears.

**Root cause.** `src/xstate_statemachine/base_interpreter.py:2697-2701`:

```python
escalate_event = ErrorEvent(
    type=f"xstate.error.actor.{self.id}", error=err, src=self.id
)
if self.parent is not None:
    await self._deliver(self.parent, escalate_event, None, None)
```

Two independent problems compose into a total loss:

1. **`type` is unnameable.** `self.id` is the *runtime actor id*, which
   `interpreter.py:1552` builds as `f"{parent.id}:{explicit_id}"` (or
   `parent:key:uuid` when auto-generated). The event type is therefore
   `xstate.error.actor.m:kid`. No `on:` key in a static config can be written
   to match that, and it is not the `error.platform.<invokeid>` shape that the
   `invoke`'s `onError` is wired to.
2. **`src` is the child's id, not the invoke id.** `onError` transitions are
   selected in `_collect_eligible_transitions`
   (`base_interpreter.py:3740-3746`) by `event.src == inv.id` — here `inv.id`
   is `"kid"` but `event.src` is `"m:kid"`, so the match fails even if the
   type matched.

Because `ErrorEvent` is engine-minted it is flagged as a system event, so
`_matching_descriptors` (`base_interpreter.py:3629-3634`) returns exact
matches only — which is why the `"*"` handler does not catch it either. #79's
provenance rule is correct in itself; combined with an untargetable type it
means the event has *no* reachable handler.

**Why it is High.** `escalate` is the library's documented supervision
primitive — the way a child says "I cannot handle this, parent, you decide".
CHANGELOG #97 specifically hardened it (`escalate` mints an `ErrorEvent`) but
hardened the *payload shape* while leaving the *routing* broken. A supervision
tree that silently swallows escalations is worse than one without escalation
at all, because the config *looks* like it handles the case.

**Note on the fix boundary.** A-05 passes: a child machine that *fails*
(uncaught service error) does reach the parent's `onError` correctly, via
`interpreter.py:2064-2070`, which uses `error.platform.{invocation.id}` and
`src=invocation.id` — the correct shapes. `escalate` simply does not go
through that path. The fix is to route `escalate` from an invoked child
through the same completion path as a failure.

---

### D-semantics-3 — **Medium** — `SyncInterpreter.tick()` delivers only one due `after` deadline per call when deadlines chain

**Case:** T-07 (sync only; async PASSes). **Repro:**
`repro/d1_sync_after0_chain.py`, `repro/d1d_realistic.py`.

A chain of `after` transitions advances exactly one link per `tick()`, no
matter how much wall-clock time has elapsed:

```
t=0.25s  after tick #1: ['order.ack_timeout']   (all 3 deadlines due by t=0.15s)
t=0.50s  after tick #2: ['order.retry']
t=0.75s  after tick #3: ['order.escalated']
```

All three deadlines (50 ms each) were due before the first `tick()` at 250 ms.
A correct pump lands on `escalated` at tick #1. A caller polling every 250 ms
is **two stages behind** for 750 ms of real time.

Direct instrumentation (`repro/d1c.py` output) confirms a due timer is left
sitting in the heap after `tick()` returns:

```
ids after 1 tick: ['m.b']
clock pending timers: 1   next_due<=now: True     <- due, unfired, tick() already returned
```

**Root cause.** `src/xstate_statemachine/sync_interpreter.py:638-644`:

```python
while self._event_queue or self._internal_queue:   # line 638 - loop CONDITION
    self._pump_timers()                            # line 644 - pump INSIDE the body
```

Entering `b` arms `b`'s `after` timer. The event that caused the entry has
already been consumed, so both queues are empty, the `while` condition fails,
and the loop exits **before** the body's `_pump_timers()` can observe the
newly-armed, immediately-due deadline. `tick()`
(`sync_interpreter.py:1268-1277`) pumps once up front and then calls
`_process_event_queue()`, so it inherits the same one-shot behaviour.

`SimulatedClock` is **not** affected — `_advance_to` re-reads the heap between
timers (`clock.py:291-300`), so `clock.increment(1)` correctly lands on
`m.d`. Only the `RealClock` + `tick()` lane is wrong, which is precisely the
production lane for a sync deployment.

**Severity Medium, not High, for us** only because CV-C03 already restricts us
to the async engine. For anyone on `SyncInterpreter` with chained timeouts —
a retry/escalation ladder is the canonical shape — this is a High.

---

### D-semantics-4 — **Low** — Exit order across parallel regions is depth-major, not SCXML's reverse document order

**Case:** S-06 (both engines). **Repro:** `repro/d7_exit_order.py`.

For document order `p, A, a1, B, b1`, SCXML §3.13 `exitStates` sorts
`statesToExit` in **exitOrder = reverse document order**: `b1, B, a1, A, p`.
Observed: `b1, a1, B, A, p` — all leaves, then all regions.

**Verified deterministic.** Because `_compute_states_to_exit`
(`base_interpreter.py:3825`) returns a `Set`, the obvious worry is
hash-ordering nondeterminism. It is not:

```
PYTHONHASHSEED=0      -> ["xb1", "xa1", "xB", "xA", "xp", "eX"]
PYTHONHASHSEED=1      -> ["xb1", "xa1", "xB", "xA", "xp", "eX"]
PYTHONHASHSEED=42     -> ["xb1", "xa1", "xB", "xA", "xp", "eX"]
PYTHONHASHSEED=12345  -> ["xb1", "xa1", "xB", "xA", "xp", "eX"]
PYTHONHASHSEED=99999  -> ["xb1", "xa1", "xB", "xA", "xp", "eX"]
distinct orders observed: 1 -> DETERMINISTIC
```

The set is sorted by depth before execution, so the result is stable across
processes. This downgrades the finding from "nondeterministic ordering"
(which would be a Blocker under our standard) to "a documented, stable
deviation from the spec's ordering".

**Impact.** Only observable when exit actions in *different* parallel regions
at *different* depths have ordering dependencies on each other — e.g. region A's
region-level exit releasing a lock that region B's leaf-level exit needs.
Within a single region, relative order is correct (inner before outer, S-16
passes). Our B1–B20 contracts do not currently have such a cross-region
exit dependency; CV-S03 records the constraint that they must not acquire one.

---

### D-semantics-5 — **Low** — `stateIn` resolves an ambiguous bare state name by suffix match instead of rejecting it

**Repro:** `repro/d2b.py`. Not a matrix FAIL — H-10…H-13 all pass, because
fully-qualified and relative-path spellings behave correctly.

`_is_state_in` (`base_interpreter.py:4218-4222`) accepts a node when
`node.id == target or node.id.endswith("." + target)`. With two states named
`work` on different branches:

```
fully-qualified inactive branch (want False)   target='#m.p.A.left.work'   fired=False   ok
fully-qualified active branch   (want True)    target='#m.p.A.right.work'  fired=True    ok
relative path of the INACTIVE branch (want False) target='left.work'       fired=False   ok
relative path of the ACTIVE branch   (want True)  target='right.work'      fired=True    ok
ambiguous bare leaf name (2 states named 'work')  target='work'            fired=True    <- silent
```

The suffix rule is *sound* whenever the spelling is unambiguous, which is why
H-13 passes. But `stateIn: "work"` in a machine with two `work` states
resolves to whichever is active and reports nothing. SCXML §5.9.2 `In()`
takes a state **id**, which is unique by construction. The library already
escalates the analogous actor-target ambiguity to `logger.error` and drops
the event (`base_interpreter.py:1859-1868`); `stateIn` should do the same
rather than guess.

**Low** because the correct spelling is available and we can mandate it —
CV-S04.

---

### D-semantics-6 — **Low** — `sendTo` with an unresolvable target drops the event with no observable signal

**Repro:** `repro/d5_sendto_unresolved.py`. Not a matrix FAIL — A-08/A-09/A-10
pass once the target is a real actor. Found while debugging my own A-08,
which is itself the point: the engine gave me no signal that my target was
wrong.

```
receipt           : Receipt(state_ids=frozenset({'m.s'}), changed=False, error=None, deferred=False)
last_transition_ok: True
last_error        : None
status            : running
VERDICT           : silent drop
```

`base_interpreter.py:2656-2662` logs a `logger.warning` and returns. The
receipt is indistinguishable from a correct no-op, `last_transition_ok` stays
`True`, `last_error` stays `None`, and no `on_event_dropped` plugin hook
fires — even though the library added exactly that hook for the runaway-chain
path (#77 criterion 6).

This is the same class of defect as G-1/M-1 in `26-verify-3c527b0-verdict.md`
(a receipt that cannot distinguish "nothing to do" from "something was lost"),
on a different code path. **Low** on its own — a typo'd actor id is usually
caught in development — but it compounds D-semantics-2: both failures on the
actor-messaging path are silent, so a supervision tree can be wholly
non-functional while every health signal reads green.

---

## 5. Constraints we would need

If the library is adopted for the machine contracts in
`docs/plan/28-statechart-catalogue.md` (B1–B20), these constraints follow
from the findings above. They are additive to the CV-C0x constraints in
`26-verify-3c527b0-verdict.md`.

| ID | Constraint | Driven by |
|---|---|---|
| **CV-S01** | A child machine that must be parameterised by its parent declares `context` as a **factory of `{input}`**. Never rely on `invoke.input` merging into declared context keys — it does not, by design. | A-03 contract probe |
| **CV-S02** | A child machine returns its result through an agreed **context key** (e.g. `context["result"]`), read by the parent's `onDone`. Do **not** use a child machine's `output` until D-semantics-1 is fixed; it is silently discarded. Add a CI assertion that fails if any B1–B20 child machine declares a top-level `output`. | D-semantics-1 |
| **CV-S03** | Do **not** use `escalate` for supervision. A child signals failure by **failing** (letting a service error propagate) or by an explicit `sendParent` of a named event the parent declares. Ban `{"type": "escalate"}` in B1–B20 by the same CI check. | D-semantics-2 |
| **CV-S04** | Every `stateIn` guard uses a **fully-qualified** `#machine.path.to.state` id. Never a bare leaf name. Lint for it. | D-semantics-5 |
| **CV-S05** | Exit actions in **different** parallel regions must not have ordering dependencies on one another. Region-internal ordering is safe and spec-correct; cross-region exit ordering is depth-major, not document order. | D-semantics-4 |
| **CV-S06** | Every `sendTo` target must be an **explicitly `id`-ed or `systemId`-ed** actor, and the adoption shim must assert the target resolves before the send — the engine will not tell us if it does not. | D-semantics-6 |
| **CV-S07** | CV-C03 (async engine only) is **reaffirmed on semantic grounds**, not just performance ones: `SyncInterpreter` is one `tick()` behind per link on chained `after` deadlines, which is the shape of every timeout-ladder contract in B1–B20. | D-semantics-3 |

---

## 6. Coverage — what was and was not tested

A clean track must say what it did not look at. This one is not clean, but the
same obligation applies to the 165 PASSes.

### 6.1 Covered, with evidence

- **Transition selection** — per-region selection, ancestor preemption,
  document order on one state, guard fallthrough, conflicting cross-region
  transitions and preemption, disabled-inner-vs-enabled-ancestor (S-01…S-05,
  S-19).
- **LCCA / transition domain** — sibling↔sibling, cross-region, to-descendant,
  to-ancestor, and self-transition domains; exit/entry set correctness for
  each (S-07, S-08, S-14, S-15).
- **Internal vs external transitions** — `reenter` present/absent, the v4
  `internal:false` alias, compound `reenter` re-entering via `initial`,
  targetless at leaf and at ancestor depth (S-09…S-13, O-05, O-06).
- **Eventless transitions** — chains, guard re-evaluation after each
  microstep, interaction with evented microsteps, transient entry/exit,
  ancestor-declared `always`, and boundedness of a non-terminating loop
  (T-01…T-05, T-17, T-18).
- **`after:0` and timers** — `after:0` as a delayed event rather than
  `always`, a three-link `after:0` chain, cancellation on state exit (T-06,
  T-07, T-08).
- **`done.state` / final / output** — compound done, parallel all-final done,
  the not-all-final and no-final-at-all negatives, `<donedata>` payload,
  top-level final ⇒ machine done + output, final-state output as machine
  output, nested done bubbling, post-done inertness (T-09…T-16).
- **History** — shallow and deep, the shallow-does-not-restore-grandchildren
  negative, deep **across parallel** (both regions' leaves), shallow on a
  parallel, default target, no-default fallback, re-snapshot on second exit,
  pseudo-state never in the configuration (H-01…H-09).
- **In-state guards** — active leaf, inactive sibling negative, ancestor
  satisfaction, and the same-name-different-branch negative (H-10…H-13), plus
  the ambiguity probe in `repro/d2b.py`.
- **Event descriptors** — exact > longer-partial > shorter-partial > `*`,
  segment-boundary matching, bare-segment matching, depth-outranks-specificity,
  guard fallthrough across descriptor classes (H-14…H-20).
- **Actors** — invoke-as-machine done, input contract, failing callable,
  failing child machine, escalation chain, cancellation on exit, `sendTo` with
  delay+id, `cancel` matching and non-matching, `spawnChild`, `stopChild`,
  `sendParent`, system-event/`"*"` isolation, unhandled-failure observability,
  invoke-after-entry ordering (A-01…A-16).
- **Action ordering** — declaration order, `assign` ordering and visibility,
  exit→transition→entry sequencing and context visibility across it,
  targetless ordering, nested entry order, microstep non-interleaving across
  an eventless hop, parallel fan-out exactly-once, shared-ancestor
  exactly-once, guard memoisation, `raise` queue placement, internal FIFO,
  internal-before-external (O-01…O-16).

### 6.2 **Not** covered — explicitly out of scope for this track

- **Persistence / snapshot round-trips of any of the above.** Layout v2,
  `Receipt.deferred`, provenance survival and `has_dormant_invocations` are
  the subject of `26-verify-3c527b0-verdict.md` G-2/G-3 and were not re-tested
  here. In particular I did **not** test whether history state, pending
  `after` deadlines, or invoked-child identity survive a snapshot — that is a
  real gap and a natural next track.
- **Concurrency and interleaving.** Every case is single-threaded and
  quiescent between sends. `send_threadsafe`, concurrent `wait=True`
  receipts, and cross-thread actor messaging are covered by the
  performance/concurrency track, not this one.
- **`actionErrorPolicy` interaction with ordering.** All cases run under the
  default `"continue"`. Whether `rollback` correctly un-does a *partially
  executed* exit/entry sequence — and in what order — is untested and is a
  meaningful risk area given #27's scope.
- **The runaway-chain budget as a semantic boundary.** T-18 only asserts that
  an unconditional eventless loop terminates. The exact cut point, the
  `RunawayChainError` surface and engine parity on deep chains are #77's
  territory and were re-verified in the round-3 work, not here.
- **`SimulatedClock` as the primary timing lane.** I used it only to isolate
  D-semantics-3. A conformance pass driven entirely by virtual time would be
  more deterministic than the real-clock `sleep()`s used in T-06…T-08 and
  A-08…A-10, and would be a strict improvement to this harness.
- **SCXML features the library does not implement**, and which are therefore
  neither PASS nor FAIL: the `<datamodel>`/`<data>` element and ECMAScript
  expression evaluation, `<foreach>`, `<script>`, event I/O processors and
  `<send type=>` external targets, `error.communication`, and `<invoke>` with
  `autoforward`. Their absence is a documented design choice (the library is
  XState-shaped, not SCXML-shaped), not a conformance failure — but it means
  "SCXML conformance" here should be read as "conformance to SCXML's
  *algorithm* for the feature set XState defines", which is what every case
  above actually asserts.
- **`deep` history interaction with `reenter` self-transitions**, and history
  targeted from *inside* the remembered subtree. Both are plausible edge cases
  I did not get to.

### 6.3 Confidence

The 165 PASSes are load-bearing: they are positive *and* negative assertions
(every "X must happen" case has a sibling "Y must not happen" case where one
was meaningful), and they agree across two independently written engines,
which is a strong signal that the shared algorithm in `base_interpreter.py`
is right rather than that both are wrong in the same way. The core statechart
engine is, on this evidence, the strongest part of this library.

The four defects cluster tightly: **three of the four** (D-semantics-1, -2,
-6) are on the **actor/invoke/messaging boundary**, and all three are
**silent**. That is a consistent story — the state-machine core is mature and
the actor layer around it is not — and it is the story our adoption decision
should be based on.

---

## 7. Suggested issue filings

Should the Post agent file these, the two High items are worth separate
issues; the Lows can ride along.

1. **`done.invoke` should carry the child machine's `output`, not its
   context** — D-semantics-1, `interpreter.py:2078`,
   `sync_interpreter.py:1179`. Repro attached. Note the inconsistency with
   the root-machine `output` path that already works.
2. **`escalate` from an invoked child reaches no handler** — D-semantics-2,
   `base_interpreter.py:2697-2701`. Note that the correct shapes already
   exist a few lines away at `interpreter.py:2064-2070`, and that #97
   hardened the payload while leaving routing broken.
3. **`SyncInterpreter.tick()` fires one due deadline per call on chained
   `after`** — D-semantics-3, `sync_interpreter.py:638` vs `:644`. Note
   `SimulatedClock` is unaffected, so existing tests would not catch it.
4. **Ride-alongs:** exit order across parallel regions vs SCXML exitOrder
   (D-semantics-4, deterministic, arguably WONTFIX-with-a-doc-note); `stateIn`
   ambiguous-name silent resolution (D-semantics-5); `sendTo` unresolvable
   target silent drop (D-semantics-6 — suggest reusing the existing
   `on_event_dropped` hook).

All references to the adopting project are by the neutral phrases used
throughout this document; no project name or label appears in any artefact
intended for upstream.
