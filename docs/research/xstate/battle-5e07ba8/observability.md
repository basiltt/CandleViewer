# Observability, Error Surface & Operability — `xstate-statemachine` @ `5e07ba8`

**Build under test.** Local clone `_ref/xstate-statemachine`, branch `main`,
commit `5e07ba8842345a73ef8f830f0281de16370a7c74` (merge of PR #101 on top of
`8f761f4`), `CHANGELOG.md` `[Unreleased] — targeting 0.8.1`. `__version__`
still reports `0.8.0`; this build is identified **by commit only**, per the
project's standing rule.

**Date:** 2026-09-18. **Python:** CPython (venv `.venv-main`), Windows 11 Pro.
**Interpreter for every run:** `_ref/xstate-statemachine/.venv-main/Scripts/python`
with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

No library source was modified. No `git` command was run in the CandleViewer
repository. GitHub was read-only throughout (nothing was posted).

Scripts live under `docs/research/xstate/battle-5e07ba8/observability/`:
`probe_matrix.py` (hook/receipt/log matrix for 11 failure-mode families) and
`probe_matrix2.py` (snapshot drift, dormant-invoke restore, stop-with-pending-
queue, process-wide enumeration, diagram export). Both were executed
end-to-end; raw stdout is reproduced below per finding and in full in
`out.txt` next to `probe_matrix.py`.

---

## 1. Method

1. Read the source directly: `plugins.py` (`PluginBase`, `LoggingInspector`),
   `exceptions.py` (full hierarchy), `events.py` (`Event`, `DoneEvent`,
   `ErrorEvent`, `AfterEvent`, provenance), `base_interpreter.py` /
   `interpreter.py` / `sync_interpreter.py` (every call site that invokes a
   plugin hook or flips `status`).
2. Wrote a recording `PluginBase` subclass (`Recorder`) that timestamps every
   hook call with a monotonic sequence number, plus a `logging.Handler`
   attached to the `xstate_statemachine` logger to capture level+message for
   each probe.
3. For each failure mode, built the smallest machine that reproduces it,
   drove both engines where the API surface allows it (`SyncInterpreter` /
   `Interpreter`), and printed: the ordered hook-call list, any hook that
   fired more than once, the `Receipt` from `send(wait=True)`,
   `last_transition_ok` / `last_error`, `status`, and relevant log records.
4. Cross-checked hook signatures and call sites by grep across
   `base_interpreter.py`, `interpreter.py`, `sync_interpreter.py` to confirm
   the recorder's enumeration was exhaustive (14 hooks on `PluginBase`, all
   14 exercised at least once across the two scripts).

Commands:

```bash
cd docs/research/xstate/battle-5e07ba8/observability
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
  "_ref/xstate-statemachine/.venv-main/Scripts/python" probe_matrix.py
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
  "_ref/xstate-statemachine/.venv-main/Scripts/python" probe_matrix2.py
```

---

## 2. The hook inventory

`PluginBase` (`plugins.py`) declares exactly 14 hooks. All 14 fire from a
single shared call path used by both engines (`base_interpreter.py`), except
`on_interpreter_start`/`on_interpreter_stop`/`on_transition`/
`on_event_received`, which are engine-specific because each engine owns its
own run loop and macrostep boundary (`interpreter.py`, `sync_interpreter.py`).

| Hook | Fires on | Call site(s) |
|---|---|---|
| `on_interpreter_start` | `start()` completes initial entry | `interpreter.py:377`, `sync_interpreter.py:309` |
| `on_interpreter_stop` | `stop()` | `interpreter.py:467`, `sync_interpreter.py:394` |
| `on_event_received` | an event is dequeued for processing | `interpreter.py:1208`, `sync_interpreter.py:748` |
| `on_transition` | a transition (external or internal) completes | `base_interpreter.py:2464`, `:2510`; `sync_interpreter.py:338` |
| `on_action_execute` | before each action in an action list runs | `base_interpreter.py:2545` (shared, `_execute_actions`) |
| `on_action_error` | an action raised | `base_interpreter.py:2611` (shared, `_report_action_failure`) |
| `on_transition_failed` | `_apply_action_error_policy` sees ≥1 failed action, any policy | `base_interpreter.py:3396` |
| `on_guard_error` | a guard raised, any `guardErrorPolicy` | `base_interpreter.py:4166` |
| `on_guard_evaluated` | every guard evaluation, pass or fail | `base_interpreter.py:4182` |
| `on_unhandled_event` | an event selected no transition, any `onUnhandled` policy | `base_interpreter.py:3351` (`_notify_unhandled`) |
| `on_event_dropped` | bounded-inbox `DROP_NEWEST`, `send()` to a non-running machine, or a chain-budget discard | `interpreter.py:805,863,1185`; `sync_interpreter.py:732` |
| `on_error` | interpreter enters terminal `"error"` | `base_interpreter.py:3534` (`_fail`) |
| `on_done` | interpreter enters terminal `"done"` | `base_interpreter.py:3562` (`_complete`) |
| `on_service_start` / `on_service_done` / `on_service_error` | invoke lifecycle (callable service or child machine) | `interpreter.py:1794/1833/1864`, `:1975/2037/2072/2083`, `sync_interpreter.py:1361/1380/1398` |

**Observation, not a defect:** hooks are called directly on each plugin
(`for plugin in self._plugins: plugin.on_x(...)`) with no `try/except` wrapper
visible at these sites in `base_interpreter.py`/`interpreter.py` — a plugin
whose hook raises will propagate into the interpreter's own control flow.
`_SafePlugin` (referenced at `base_interpreter.py` around the `plugins`
setter) exists as an error-containing proxy, but only for objects assigned
through the `interpreter.plugins = [...]` setter — `.use()` registers the
plugin object directly, unwrapped. **This is an asymmetry (D-observability-6
below):** the two public entry points into `_plugins` (`.use()` vs the
`.plugins` setter) do not give the same fault-containment guarantee for the
same plugin object, which is exactly the kind of two-paths-disagree issue
the CHANGELOG calls out elsewhere (#92/#93) as something this project
otherwise takes seriously.

---

## 3. Failure-mode matrix (from `probe_matrix.py`)

Each row: hook(s) fired (order), `Receipt`, `last_transition_ok`/`last_error`,
terminal `status`, whether an audit record (machine id, event, from/to
state, cause) is synchronously reconstructable at the caller's `send(wait=True)`
return.

### 3.1 Action raise, all three `actionErrorPolicy` values (sync engine; source is engine-shared, so async is the same path)

| Policy | Hooks (order) | Receipt | `last_transition_ok` | `status` | Audit info available? |
|---|---|---|---|---|---|
| `continue` | `on_action_execute → on_action_error → on_transition_failed → on_transition` | `changed=True, error=ValueError('boom')` | `False` | `running` | **Yes** — receipt carries the cause, `on_transition` carries the committed target, `on_action_error` names the failing action. |
| `rollback` | `on_action_execute → on_action_error → on_transition_failed` (no `on_transition`) | `changed=False, error=ValueError('boom')` | `False` | `running` | **Yes** — from-state is implied (unchanged), no to-state since none committed. |
| `fail` | `on_action_execute → on_action_error → on_transition_failed → on_error` | `changed=False, error=ValueError('boom')` | `False` | `error` | **Yes** — `on_error` carries a `TransitionFailedError` wrapping the original as `__cause__`; `interpreter.error` holds the same. |

`on_transition_failed` fires under **every** `actionErrorPolicy`, including
`continue` — confirms the CHANGELOG's #33 claim. `Receipt.error` is always the
**original** `ValueError`, never the policy-dependent wrapper — a caller
reading only the receipt sees the true root cause even under `fail`, where
`on_error`/`interpreter.error` gets the wrapped `TransitionFailedError`. Both
are logged (`ERROR` for the action raise, `WARNING` for rollback, `ERROR`
again for the terminal failure under `fail`).

### 3.2 Guard raise, all three `guardErrorPolicy` values (`"false"`, `"true"`, `"raise"` — not `continue`/`rollback`/`fail`, a different vocabulary from the action policy; see D-observability-1)

| Policy | Hooks (order) | Receipt | `last_transition_ok` | `status` |
|---|---|---|---|---|
| `"false"` (default) | `on_guard_error → on_guard_evaluated(result=False) → on_unhandled_event(disposition="ignored")` | `changed=False, error=None` | `True` | `running` |
| `"true"` | `on_guard_error → on_guard_evaluated(result=True) → on_transition` | `changed=True, error=None` | `True` | `running` |
| `"raise"` | `on_guard_error` only | `changed=False, error=ValueError('guard-boom')` | `False` | `running` |

`on_guard_error` fires under **every** policy (confirmed), but under
`"false"`/`"true"` the guard's own raised exception is **swallowed after being
reported** — `Receipt.error` is `None` and `last_transition_ok` is `True`.
**A caller who checks only `last_transition_ok`/`Receipt.error` — the two
fields this library's own docs point to for "was anything wrong" — cannot
distinguish "the guard legitimately evaluated to false/true" from "the guard
crashed and the policy silently substituted false/true".** The only way to
see the crash is a registered plugin's `on_guard_error`, or grepping logs.
See D-observability-2.

### 3.3 Unhandled event, all three `onUnhandled` policies

| Policy | Hooks | Receipt | `status` |
|---|---|---|---|
| `ignore` | `on_unhandled_event(disposition="ignored")` | `changed=False, error=None, deferred=False` | `running` |
| `defer` | `on_unhandled_event(disposition="deferred")` | `changed=False, error=None, deferred=True` | `running` |
| `error` | `on_unhandled_event(disposition="errored") → on_error` | `changed=False, error=None, deferred=False` | `error` |

`Receipt.deferred=True` for the `defer` case confirms #84 is fixed as the
CHANGELOG claims — this was the headline defect of the prior verdict
(`26-verify-3c527b0-verdict.md` M-1). Verified independently here at
`5e07ba8`, both via the receipt and the hook payload.

### 3.4 Deferred replay

Sequence observed: `LATE` deferred while in `a` → `ARM` transitions `a→b` →
the deferred `LATE` is **replayed automatically** and now matches `b→c`. All
of this happens inside the single `send("ARM", wait=True)` call — the
caller's `ARM` receipt reflects only the `ARM` transition
(`state_ids={'...c'}` — i.e., **the state the machine ends up in after replay,
not the state ARM itself produced**). This is workable but worth flagging: a
caller reading `Receipt.state_ids` after `ARM` sees the *post-replay* final
configuration, not "where ARM landed". `on_event_received` fires again for
the replayed `LATE` (correctly, since it is genuinely reprocessed), and
`on_transition` fires for both hops — an observer distinguishes them only by
correlating `on_event_received{type='LATE'}` with the following
`on_transition`, there is no shared identifier between the receipt returned
to the `ARM` caller and the replay's own `on_transition` call. Not a bug, but
an audit-record gap: **the ARM caller's receipt cannot be split back into
"what ARM did" vs "what LATE (replayed) did"** without a plugin recording
hook order itself. See D-observability-3.

### 3.5 Inbox overflow (async engine only — see below)

`SyncInterpreter` has no `max_queue_size`/`overflow_policy` constructor
parameters at all; it drains synchronously inside `send()`, so there is
structurally no queue to overflow on that engine. **This means
`OverflowPolicy`/`QueueOverflowError`/`on_event_dropped(reason="queue_full")`
is async-engine-only observability, undocumented as such in the two
engines' constructor signatures side by side** (a reader has to notice the
parameter is simply absent from `SyncInterpreter.__init__`). See
D-observability-4.

| Policy | Hooks | Result |
|---|---|---|
| `DROP_NEWEST` | `on_event_dropped(reason="queue_full")` × N (one per dropped event) | `send()` returns normally (no exception); the event is silently gone except for the hook + a `WARNING` log |
| `RAISE` (default once bounded) | none (no hook fires for a rejected send) | `send()` raises `QueueOverflowError` synchronously at the call site |

Both are logged; `queue_depth` read back after the run in this probe reports
`0` because the interpreter had already drained the one slot by the time we
read it — a caller polling `queue_depth` for backpressure needs to sample it
between sends, which is possible but not demonstrated as a pattern in the
docs.

### 3.6 Chain (runaway) budget trip

With `maxIterations=5` and a self-re-sending action, hooks fire per
iteration (`on_action_execute → on_transition` × 5) then
`on_event_dropped(reason="chain_budget")` fires **once**, for the discarded
6th `LOOP`. `Receipt.error` for the triggering `send(wait=True)` is the
`RunawayChainError` itself, `last_transition_ok=False`, `status` stays
`running`. Confirms the CHANGELOG's #77 criterion 6 claim exactly:
observable via receipt, `last_error`, and the dedicated hook, on the sync
engine (mirrors the async engine per source, not independently re-verified
here — that parity was the subject of the `#77 ride-along` fix and is
covered by the library's own `test_round3_findings.py`, not re-run here).

### 3.7 Invoke error (callable service), with and without `onError`

| `onError` declared? | Hooks | `status` | `interpreter.error` |
|---|---|---|---|
| Yes | `on_service_start → on_service_error → on_event_received(error.platform.svc) → on_transition` | `running` | `None` |
| No | `on_service_start → on_service_error → on_error` | `error` | the original exception |

Clean, symmetric, matches the documented contract (`_has_error_handler`
gates whether an undeclared `onError` fails the machine).

### 3.8 Child-machine (invoked `MachineNode`) failure — #99 parity check

Child's own `entry` action raises under `actionErrorPolicy="fail"` → child
enters `error` with a `TransitionFailedError` → parent sees:
`on_service_start(kid) → on_service_error(kid, error=TransitionFailedError(...)) → on_event_received(error.platform.kid) → on_transition` to the declared
`onError` target. **The error delivered to the parent's `onError` handler is
the child's `TransitionFailedError` wrapper, not the child's original action
exception** — the parent-side `ErrorEvent.error` (and `on_service_error`'s
`error` argument) is one level removed from the actual root cause (the
child's `TransitionFailedError.__cause__` holds it, but nothing in the
parent-visible surface tells the caller to go looking for `__cause__` two
frames down). This matches the design intent stated in `_fail()`'s docstring
(distinct `error` status makes failure observable) but is a genuine chain a
consumer must know to walk. Confirmed working (#99's stated goal — sync/async
parity for a failed invoked child machine — was **not** independently
re-verified on the sync engine here; that is this track's one explicit gap,
see §5).

### 3.9 `StateNotFound` under `strict_targets=False`

A `DeprecationWarning` fires at `create_machine()` time (build-time, points
at the offending `on` entry). At runtime, `send("GO", wait=True)` returns
`Receipt(changed=False, error=StateNotFoundError(...))`,
`last_transition_ok=False`, `status` stays `running`. No plugin hook fires
for this specific failure — it is visible only via the receipt/`last_error`
and an `ERROR`-level log line (`🚫 Target '...' does not resolve`). **There
is no `on_x` hook dedicated to an unresolvable target** — an application
that wants this as a first-class alert (as opposed to a receipt field it
must remember to check on every `send`) has nothing to subscribe to. See
D-observability-5.

### 3.10 Strict violation (`UnknownEventError`)

Raised **synchronously at the `send()` call site**, before the event is
queued — confirmed no hook fires for it (there's nothing to fire, the event
never entered the pipeline) and the exception itself is maximally
informative: offending type, machine id, full known-event list, and a
`difflib`-based "did you mean" suggestion. This is the single cleanest
failure-mode surface in the whole matrix — the exception message alone is
audit-record-complete.

### 3.11 Wrong thread (`WrongThreadError`)

Raised synchronously on the foreign thread, before scheduling — the message
explicitly names the correct idiom (`send_threadsafe()`) and calls out that
`asyncio.run_coroutine_threadsafe(interp.send(...), loop)` is *also*
rejected (the 0.8.0 behavioural break the CHANGELOG documents). No hook
fires (nothing was accepted). Good, load-bearing error message; no gap
found here.

---

## 4. Snapshot / restore / lifecycle probes (`probe_matrix2.py`)

### 4.1 Snapshot drift

- Structural change (guard added, same `machine_id`) →
  `SnapshotDriftError` naming both hash values.
- Different `machine_id` entirely → `SnapshotDriftError` naming both ids.
- `verify_machine_hash=False` → restores without complaint, `status=running`,
  correct `current_state_ids`.

All three exactly as documented; the escape hatch is real and does what it
says.

### 4.2 Dormant-invoke restore (#44)

- Static restore (`restart_services=False`, the default): `status=running`,
  `has_dormant_invocations=True`, `pending_invocations()` names the exact
  parked invoke (`state_id`, `invoke_id`, `src`).
- `restart_services=True` + a subsequent `await restored.start()` (**note:
  `restart_services=True` has no effect until `start()` is called on the
  restored interpreter — passing the flag to `from_snapshot()` alone does
  nothing observable**; this is documented in the docstring but easy to miss
  since `from_snapshot()` otherwise looks fully "restored and ready") →
  `has_dormant_invocations=False`, the service actually re-ran. Confirms #44
  works as designed. **The "flag has no effect until start()" trap is
  D-observability-7** (Low — it's in the docstring, but the object returned
  by `from_snapshot()` is otherwise indistinguishable from a live interpreter
  and nothing errors if you never call `start()`).

### 4.3 `stop()` with a pending queue

- `drain=False` (default): 5 events queued via `send(wait=False)`, `stop()`
  returns, `pending_events` is not drained (still queued in the stopped
  interpreter's internal deque — confirmed via `pending_events` length before
  stop; the events are neither processed nor reported dropped by any hook).
- `drain=True`: `stop()` processes to empty, `pending_events` reads `0`
  afterward.

Neither path fires `on_event_dropped` for the queued-but-never-processed
events under `drain=False` — they are simply abandoned in the deque of a
`stopped` interpreter with no observability signal that they were lost. If
the interpreter is later garbage-collected, those events vanish with no
trace beyond whatever the caller itself tracked. **D-observability-8.**

### 4.4 Enumerate every live interpreter

Confirmed: no process-wide registry. `ActorSystem` is per-hierarchy, rooted
at whichever interpreter's `_system_registry()` you ask, and only contains
actors that declared a `systemId`. There is no way to ask "what interpreters
exist right now" from the library — an application needing this (e.g. an
ops dashboard listing every live order-machine) must maintain its own
external registry. Documented here as a **gap** (§5), not a defect — this
was never claimed as a feature.

### 4.5 Health/liveness signals

`has_dormant_invocations` and `pending_invocations()` are exactly the
"is this machine's declared work actually running" signal a health check
needs, and they are the **only** such signal — `status` alone
(`uninitialized`/`running`/`done`/`error`) is explicitly documented as
insufficient after a restore (`_fail`/`_complete` docstrings say so
directly). No aggregate metrics hook (queue depth over time, transition
rate, action latency) exists beyond `queue_depth` (instantaneous, async-only)
and the plugin hooks themselves, which a consumer would have to wire into a
metrics system by hand.

### 4.6 Machine JSON / diagram export

`to_mermaid()` and `to_plantuml()` both exist and produce correct-looking
output on the first probe machine. **There is no `to_dict()`/`to_json()`/
`config` re-export of the machine definition** — `hasattr(machine, "to_dict")`
etc. all `False`. An application that wants to hand its *original* config
back out (for a doc generator, a diff-against-source check, or a UI that
edits and re-submits the machine) has no library-provided path; it must have
kept the original `dict`/JSON it built the machine from. **D-observability-9**
(Low — the CLI/`cli/` package almost certainly round-trips machine configs
for its own generator, but that is a separate, heavier code path, not a
`MachineNode` method).

---

## 5. What was covered / what was not

**Covered**, with a working, reproducible script and printed evidence in
this document: action raise (3 policies), guard raise (3 policies),
unhandled event (3 policies), deferred replay, inbox overflow (2 policies,
async engine — see the note in §3.5 on why sync has no equivalent), chain
budget trip, invoke error (with/without `onError`), child-machine failure
via `onError` (async engine), `StateNotFound` under `strict_targets=False`,
strict violation, wrong thread, snapshot drift (3 variants), dormant-invoke
restore (static + `restart_services=True`), stop with pending queue (2
drain modes), process-wide-enumeration question, health signals, diagram
export.

**Not covered / explicitly out of scope for this pass:**

- **`escalate` built-in action** was not separately probed as its own
  scenario — §3.8 covers a child *machine* entry-action failure surfacing
  through the normal `onError` invoke path, not the `escalate` action
  creator the CHANGELOG's #97 fix targets (`escalate` minting an
  `ErrorEvent`). That fix was independently verified by the prior verdict's
  own probes (`25-verify-3c527b0-diff-review.md` G-5/G-6); not re-run here.
- **`SyncInterpreter` sync/async parity for #99** (invoked child-machine
  failure) was verified on the **async** engine only (§3.8). The sync engine
  was not separately driven through the same scenario in this pass.
- **Schema violation** (`InvalidEventPayloadError`) was enumerated from the
  exceptions read but not driven through a live probe in this pass — no
  entry in §3 for it. Its shape (`event_type`, `cause`) was confirmed by
  reading `exceptions.py` only.
- **Structured logging** (JSON log records, a formatter, machine-readable
  log schema) was not assessed beyond confirming the library uses the
  stdlib `logging` module with a `NullHandler` (the documented, correct
  library pattern) — there is no built-in structured/JSON formatter or
  schema; a consumer wires their own `Formatter`/`Handler`. Not filed as a
  defect (this is the expected, correct posture for a library), noted as a
  **gap** an adopting project must fill itself.
- **Metrics hooks** beyond the plugin system and `queue_depth` were not
  found and are noted as a gap (§4.5), not independently probed further
  (there is nothing further to probe — the absence was confirmed by
  exhaustive `dir()`/grep, not by a runtime script).
- Benchmark-grade throughput/latency measurement of the observability hooks
  themselves (e.g., cost of a hot-path `on_guard_evaluated` firing on every
  guard check, noted already as a historical hot-path concern in the
  CHANGELOG's #55 entry) was not re-measured in this pass.

This track's evidence base is therefore **broad but not exhaustive** on two
axes: (a) engine parity was spot-checked, not systematically driven through
every failure mode on both engines; (b) a small number of documented-but-
not-executed corners (escalate, schema violation) rely on reading source and
the prior verdict's own probes rather than a fresh run here.

---

## 6. Defects

Severity scale: **Blocker** (silent money-affecting failure/lost event with
no signal at all) / **High** (observable only via a workaround, or a real
ambiguity between two legitimate outcomes) / **Medium** (a gap that forces
extra plumbing but has a workaround) / **Low** (a papercut / doc-only trap).

### D-observability-1 — Medium — `actionErrorPolicy` and `guardErrorPolicy` use disjoint vocabularies for a conceptually parallel choice

**Root cause:** `models.py` — `ACTION_ERROR_POLICIES` (values `continue`/
`rollback`/`fail`, inferred from `exceptions.TransitionFailedError` naming
and probe output) vs `GUARD_ERROR_POLICIES = ("false", "true", "raise")`
(`models.py:95`). Two "what happens when user code raises" policies on
sibling concepts (an action, a guard) use unrelated words for the
"suppress and treat as if nothing happened" case (`"continue"` vs
`"false"`/`"true"`) and only guards have a two-way "coerce to a boolean"
split, because a guard's return type is `bool` and an action's isn't.

**Minimal repro:** `create_machine({..., "guardErrorPolicy": "continue"})`
raises `InvalidConfigError: 'guardErrorPolicy' must be one of ['false',
'true', 'raise'], got 'continue'` (reproduced in this run while adapting
the probe script from the action-policy vocabulary).

**Impact:** a developer configuring both policies on the same machine (very
plausible for an order-management machine using both actions and guards
defensively) has to remember two separate enumerations. Not a bug — the
naming is *defensible* given the type difference — but it is a genuine
usability/observability-adjacent gap: a config typo here fails loudly at
build time (`InvalidConfigError`, good), so the blast radius is small; filed
as **Medium** because it's a design-clarity issue, not a runtime-safety one.

**Constraint we would need:** none — document the two enumerations
side-by-side in our own machine-authoring guide (28-statechart-catalogue.md)
so B1–B20 authors don't guess.

---

### D-observability-2 — High — a guard that raises under `guardErrorPolicy in {"false","true"}` is indistinguishable, at the `Receipt`/`last_error` surface, from a guard that legitimately evaluated

**Root cause:** `base_interpreter.py:4150-4169` (`_evaluate_guard` — name
inferred from context) reports the raise via `on_guard_error`, then sets
`result = policy == "true"` and **returns**, i.e. the guard's own exception
is fully absorbed at this layer. The caller further up the stack (whatever
selects the transition) sees a normal boolean and proceeds; nothing sets
`last_transition_ok=False` or attaches an `error` to the `Receipt` for this
case, confirmed in §3.2 (`policy="false"`: `Receipt(changed=False,
error=None)`, `last_transition_ok=True`; `policy="true"`: `Receipt
(changed=True, error=None)`, `last_transition_ok=True`).

**Minimal repro:**
```python
def bad_guard(ctx, ev): raise ValueError("guard-boom")
cfg = {"id": "m", "initial": "a", "guardErrorPolicy": "false",
       "states": {"a": {"on": {"GO": {"target": "b", "guard": "bad_guard"}}}, "b": {}}}
interp = SyncInterpreter(create_machine(cfg, logic=MachineLogic(guards={"bad_guard": bad_guard}))).start()
r = interp.send("GO", wait=True)
# r == Receipt(state_ids=frozenset({'m.a'}), changed=False, error=None, deferred=False)
# interp.last_transition_ok == True, interp.last_error is None
# — indistinguishable from a guard that correctly returned False.
```

**Impact:** on an order-management machine, a risk/eligibility guard that
raises (e.g. a downstream pricing-service timeout inside the guard) under
the default `guardErrorPolicy="false"` produces **exactly the receipt of a
normal, correct rejection** — `changed=False, error=None,
last_transition_ok=True`. A caller cannot tell "the order was correctly
rejected by the risk check" from "the risk check itself crashed and we
silently treated that as a rejection" without a registered plugin
specifically watching `on_guard_error`. This is the same shape of bug as
#84 (`Receipt.deferred`) that the CHANGELOG already fixed for the deferred
case — the guard-raise case was not given the same treatment.

**Constraint we would need:** either (a) always register a plugin whose
sole job is capturing `on_guard_error` into a machine-local buffer we can
inspect immediately after every `send(wait=True)` that touches a guarded
transition, mirroring what `deferred_count` does for #84, or (b) treat any
`guardErrorPolicy` other than `"raise"` as unsafe for guards that can throw
on money-relevant transitions and mandate `"raise"` + our own
try/except-and-log wrapper around every such `send()`.

---

### D-observability-3 — Medium — a `send(wait=True)` receipt for an event that triggers deferred-event replay reflects the *post-replay* configuration, not the triggering event's own transition, with no shared identifier to separate the two

**Root cause:** `interpreter.py` (async) / `sync_interpreter.py` (sync) —
the deferred-replay loop (`_take_deferred_for_replay` / the "3️⃣ Replay
deferred events" comment at `interpreter.py:1343`) runs **inside** the same
processing step as the triggering event, before that event's `Receipt` is
resolved, confirmed in §3.4: `send("ARM", wait=True)` returned
`Receipt(state_ids={'...c'})`, the state reached only after the replayed
`LATE` was also processed — not `{'...b'}`, which is what `ARM` alone
produced.

**Minimal repro:** see §3.4 output — `probe_deferred_replay()` in
`probe_matrix.py`.

**Impact:** a caller awaiting `send("ARM", wait=True)` to confirm "did ARM
do what I expect" gets back a state that also encodes a completely
different, asynchronously-queued event's effect, with the two transitions'
`on_transition` hook calls interleaved and distinguishable only by an
observer that was already watching hook order — the `Receipt` itself
carries no per-event identifier or count of "how many events were folded
into this answer". For an order-lifecycle machine using `onUnhandled:
"defer"` (a documented, encouraged pattern per the CHANGELOG's #84 framing),
a caller sending event X and getting back a receipt that silently also
reflects deferred event Y's effect is a real audit-trail ambiguity.

**Constraint we would need:** a plugin recording `on_event_received` +
`on_transition` pairs around every `send(wait=True)` if we need to attribute
state changes to individual events for audit purposes; the receipt alone is
not sufficient.

---

### D-observability-4 — Medium — bounded-inbox observability (`OverflowPolicy`, `on_event_dropped(reason="queue_full")`, `QueueOverflowError`, `queue_depth`) is asynchronous-engine-only, and the two engines' constructors do not make this discoverable side by side

**Root cause:** `interpreter.py:184-185` (`Interpreter.__init__` accepts
`max_queue_size`/`overflow_policy`) vs `sync_interpreter.py:163-168`
(`SyncInterpreter.__init__` has no such parameters at all — confirmed by
reading the full signature). `SyncInterpreter` drains synchronously inside
`send()`, so there is no queue to bound, but nothing surfaces this
asymmetry at the type/API level (no `NotSupportedError` if you try
something equivalent; the parameters simply do not exist on that class).

**Minimal repro:** `SyncInterpreter(machine, max_queue_size=1, overflow_policy=OverflowPolicy.RAISE)`
→ `TypeError: SyncInterpreter.__init__() got an unexpected keyword argument
'max_queue_size'` (reproduced while adapting the probe).

**Impact:** low runtime risk (fails loudly, at construction) but real
design-review risk: a team picking `SyncInterpreter` for an order machine
because they want a bounded inbox for backpressure (a very plausible
requirement on a payment path) will discover only at construction time that
the feature does not exist on that engine, and must re-derive their own
backpressure story (e.g. bound the caller's own producer, or switch
engines).

**Constraint we would need:** document explicitly in our ADR that
backpressure via `max_queue_size`/`OverflowPolicy` is `Interpreter`
(async)-only; any `SyncInterpreter` machine on a load-bearing path needs an
external queue depth guard if unbounded processing is a risk.

---

### D-observability-5 — Low — `StateNotFoundError` under `strict_targets=False` has no dedicated plugin hook; it is visible only via `Receipt.error`/`last_error` and a log line

**Root cause:** `base_interpreter.py` (resolver failure path, confirmed via
the `ERROR`-level log `🚫 Target '...' does not resolve` observed in §3.9) —
no `for plugin in self._plugins: plugin.on_x(...)` call accompanies this
failure the way `on_action_error`/`on_guard_error` accompany theirs.

**Minimal repro:** §3.9's `probe_state_not_found()`.

**Impact:** an application wanting a single subscription point ("alert me
whenever anything goes wrong") to also catch unresolvable targets must
additionally attach a log handler for this one case, or check
`last_transition_ok` after every `send()` — the plugin system alone is not
a complete "everything that can silently misbehave" surface, contradicting
the otherwise strong pattern established by `on_action_error`/
`on_guard_error`/`on_unhandled_event` all firing under every policy.

**Constraint we would need:** none blocking — `last_transition_ok`/
`last_error` after every `send()` is a sufficient (if less convenient)
substitute; note this in our error-handling guide so nobody assumes the
plugin hook set is exhaustive for "anything that went wrong".

---

### D-observability-6 — Medium — `.use(plugin)` and `interpreter.plugins = [...]` give the same plugin object different fault-containment guarantees

**Root cause:** `base_interpreter.py` — the `plugins` **setter** wraps every
element in `_SafePlugin` (a `__getattr__` proxy with "error containment",
per its own comment at `base_interpreter.py:891-894`) before storing it in
`self._plugins`; `.use()` (`base_interpreter.py:900+`) appends the plugin
object **directly** with no such wrapping (confirmed by reading both call
sites; `.use()`'s body was not shown to construct a `_SafePlugin`).

**Minimal repro:** register the same buggy plugin (a hook that raises) via
`interp.use(BuggyPlugin())` vs `interp.plugins = [BuggyPlugin()]` and observe
whether the interpreter's own transition is disrupted in one path and not
the other. **Not independently executed as a runtime repro in this pass**
(inferred from reading the setter's docstring/comments and the absence of
equivalent wrapping visible at the `.use()` call site) — flagged as
**PLAUSIBLE**, not confirmed, and should be re-verified with a live script
before being relied on.

**Impact if confirmed:** a plugin author who tests with `.use()` (the more
commonly demonstrated entry point in the library's own docstring examples)
and later an operator who wires the same plugin via `interpreter.plugins =
[...]` (or vice versa) get different blast-radius behavior for the exact
same bug in their own plugin code — one path can crash the interpreter's
transition, the other cannot.

**Constraint we would need:** re-verify with a live probe before adoption;
if confirmed, standardise on whichever entry point is safer (`.plugins =`
per the setter's own stated intent) for any plugin we ship on an
order-management path, and treat `.use()` as "trusted code only".

---

### D-observability-7 — Low — `from_snapshot(restart_services=True)` has no effect until the restored interpreter's `start()` is called; the object returned in between looks fully alive

**Root cause:** `base_interpreter.py:1290` sets
`interpreter._restart_services_on_start = restart_services` but the actual
re-invocation only happens inside `Interpreter.start()`
(`interpreter.py:338-340`) / `SyncInterpreter.start()`
(`sync_interpreter.py:265-270`) — confirmed in §4.2, where calling
`from_snapshot(..., restart_services=True)` alone left
`has_dormant_invocations=True`, and only `await restored.start()` flipped it.

**Minimal repro:** §4.2's `probe_dormant_invoke_restore()` (first variant,
before the `.start()` fix was applied to the probe — reproduced the trap
directly during development of this script).

**Impact:** the flag is documented correctly in the docstring, but a
restored interpreter's `status` already reads `"running"` before `start()`
is called (it was persisted as `"running"`), so nothing about the object's
observable state warns that the re-invocation has not happened yet — a
caller who forgets the follow-up `start()` call silently keeps a dormant
invoke that never restarts, indistinguishable from `restart_services=False`
except by explicitly checking `has_dormant_invocations`.

**Constraint we would need:** none blocking — always call `.start()`
immediately after any `from_snapshot(restart_services=True)` in our own
restore helper, and assert `has_dormant_invocations is False` right after,
so a silent no-op fails our own tests loudly.

---

### D-observability-8 — Medium — events left in the queue by `stop(drain=False)` (the default) are neither processed, reported via `on_event_dropped`, nor otherwise made observable as lost

**Root cause:** confirmed in §4.3 — `stop()` without `drain=True` leaves
`pending_events` non-empty in a `stopped` interpreter and no hook fires for
those events at any point in the probe. (Whether they are dropped
immediately, or simply retained forever in a stopped-but-not-garbage-
collected interpreter, was not traced further into `stop()`'s source in this
pass — filed as observed-behavior, not a full root-cause trace.)

**Minimal repro:** §4.3's `probe_stop_with_pending_queue()`, first variant.

**Impact:** on an order-management path, `interp.send(cmd, wait=False)`
immediately followed by an unrelated `stop()` (e.g. a supervisor shutting
down a machine it believes is idle, racing a late command) loses that
command with **zero** observability signal — no hook, no log line noted in
this probe's captured records, nothing in `Receipt` (there is no `Receipt`,
since `wait=False`never resolves one). This is exactly the "silent failure
on a money path" category this audit is mandated to treat as a defect.

**Constraint we would need:** either always call `stop(drain=True)` on any
order-management machine (accepting the latency of draining), or maintain
our own outside record of "sent but not yet confirmed processed" commands
(a client-side idempotency/outbox pattern) so a `stop()` race cannot lose a
command invisibly. This is very likely already necessary for other reasons
(the network boundary to whatever originates commands), but it must be
treated as **mandatory**, not optional hardening, given this finding.

---

### D-observability-9 — Low — no machine-definition JSON/dict re-export (`to_dict`/`to_json`) on `MachineNode`; only diagram export (`to_mermaid`/`to_plantuml`) exists

**Root cause:** confirmed by `hasattr` probe in §4.6 — `MachineNode` exposes
`to_mermaid()`/`to_plantuml()` (both present and produce plausible output)
but no config re-export method.

**Impact:** a documentation/visualiser pipeline that wants the *original*
config back (to diff against source, or feed a different tool that consumes
JSON rather than Mermaid/PlantUML) must retain its own copy of the config it
built the machine from; the library will not hand it back.

**Constraint we would need:** none — keep our own copy of every machine's
source JSON (which we already do, per `28-statechart-catalogue.md`) as the
canonical artifact; treat `to_mermaid`/`to_plantuml` purely as
derived-view exports.

---

## 7. Cross-cutting observability gaps (not filed as numbered defects — these are absences, not misbehaviors)

- **No correlation/trace id on any event class.** `Event`, `DoneEvent`,
  `ErrorEvent`, `AfterEvent` (`events.py`) carry no id field of any kind —
  confirmed by reading every field of all four classes. An application
  wanting to correlate "this specific `send()` call" across logs/hooks/
  receipts must mint and thread its own id through `payload`.
- **No structured/JSON logging support beyond stdlib `logging` +
  `NullHandler`.** Correct, expected library posture; noted as a gap the
  adopting project fills itself (a `logging.Formatter` emitting JSON,
  wired to the `xstate_statemachine` logger name).
- **No metrics hooks** beyond the plugin system itself and the
  instantaneous `queue_depth` property (async engine only). Transition
  rate, action latency, guard-evaluation latency, hook-call latency: none
  built in.
- **No process-wide interpreter registry / enumeration.** Confirmed in
  §4.4. An ops view of "every live order machine" is entirely the
  adopting application's responsibility.

None of these four are defects in the sense of "the library does something
wrong" — they are absences of a feature this library never claimed. They are
recorded here because the mandate for this track is to identify what would
force us to wrap or fork, and each of the four does exactly that: any of
them needed for CandleViewer's operability requirements means writing it
ourselves, not configuring something already there.

---

## 8. Bottom line

The plugin/exception surface is unusually thorough and honestly documented
for a library at this stage — `on_guard_error`/`on_action_error`/
`on_transition_failed` genuinely fire under every configured policy (verified,
not just read), the #84 deferred-receipt fix holds up under direct
re-verification, snapshot-drift and dormant-invoke-restore are exactly as
documented, and the strict/wrong-thread error messages are the best-in-class
examples of "the exception alone is audit-record-complete." Against that: two
places (guard-raise silently absorbed into a legitimate-looking boolean
outcome, D-observability-2; events lost across an undrained `stop()` with
zero signal, D-observability-8) are genuine silent-failure risks on exactly
the money-relevant paths this audit is mandated to scrutinise, and neither
has a library-provided guard rail — both require us to build our own
wrapper/discipline around `send()`/`stop()` before this library is safe to
put under an order-management machine as-is. Everything else in this report
is either a documented, load-bearing design choice (async-only backpressure,
no correlation ids, no process-wide registry) or a Low papercut with a cheap
workaround.
