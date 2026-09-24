# R5-01 adversarial triage — CONFIRMED (Blocker)

Commit 3ed3099 (unreleased 0.8.1). Claim: `_active_leaf_present()`
(`base_interpreter.py:1112`) is an ANY-leaf test, consumed at :1156 as the
sole legality conjunct of the #102 `SnapshotMidStepError` guard. SCXML
legality is exactly one active leaf PER REGION, so the guard is vacuous for
(a) parallel machines mid-step in one region and (b) the entry-action window.

## Refutation attempts, all failed

1. **Documented behaviour?** No — the opposite. `docs/_guide/snapshots.md:134`
   states `get_persisted_snapshot()` *raises* `SnapshotMidStepError`
   "mid-macrostep (while a transition's actions are still running)". That is
   exactly the window that silently succeeds here. The docstring at :1129
   repeats the promise. The observed behaviour contradicts the library's own
   published contract.
2. **API misuse / mandatory config?** No. Repro `x1_observer_task.py` reaches
   the tear from a plain `asyncio` monitoring task — no plugin hook, no
   snapshot-from-inside-an-action, no re-entrancy. There is **no public
   settled/idle predicate** (`grep` for `is_settled|settled|quiesced|is_idle|
   is_busy` in `src/` → nothing), so a concurrent checkpointer has no way to
   avoid the window other than the guard that is broken. The mandatory policy
   block (28-statechart-catalogue §1.3b) has no bearing on snapshot legality.
   `d3b_partial_parallel.py` uses `get_snapshot()` from `on_action_execute`,
   a public `PluginBase` hook.
3. **Superseded snapshot semantics / sync engine only?** No.
   `d5s1_entry_action_torn_snapshot.py` shows BOTH engines ACCEPT
   `state_ids=['oms.filled']` with `ctx filled_qty=0` vs live `100`.
   `x1` reproduces on the async engine; `t1_snapshot.py::A` gives
   `A_refused=false`.
4. **XState v5 agrees?** No. v5 `getPersistedSnapshot()` is only reachable at
   a macrostep boundary — the actor's step is not re-entrant from a caller and
   there is no half-applied entry window to observe. And even taken on its own
   terms the library's persisted blob is self-inconsistent: `state_ids` says
   one thing, `context` another.
5. **Duplicate of a closed issue?** It is the *incomplete fix* of #102 (a
   Round-4 Blocker, closed). #102's repro was a no-leaf-anywhere flat machine;
   the fix's predicate only covers that shape. Not a duplicate — a regression
   of the same class through the fix's own hole.

## Reproductions (all re-run at 3ed3099)

| repro | result |
|---|---|
| `triage-r5/t1_snapshot.py::A` | `A_refused=false`, snapshot taken from an entry action of `par.A.a2` |
| `battle-3ed3099/persistence/d3b_partial_parallel.py` | whole `exchange` region absent from `configuration`; restore raises nothing, `status=running`, `error=None`, `has_dormant_invocations=False`; `FILL`/`DONE` silently deferred; `filled=0` vs 3 uninterrupted |
| `battle-3ed3099/semantics/repro/d5s1_entry_action_torn_snapshot.py` | sync AND async: `ACCEPTED state_ids=['oms.filled'] ctx filled_qty=0` (live 100); `last_transition_ok=True`, `last_error=None` |
| `triage-r5/r5-01/x1_observer_task.py` (new, no in-action call) | `ACCEPTED`, ctx `booked=False` persisted while live settles to `True`; restore `running`, permanently `booked=False` |
| `triage-r5/r5-01/x2_documented_safe_points.py` (control) | after `send(wait=True)` the snapshot is correct — the bug is confined to the window the guard claims to cover, so it is a guard defect, not a general snapshot defect |

## Mechanism

`_active_leaf_present()` returns `any(not node.states or node.is_final ...)`
over the whole active set. In a parallel machine every sibling region
contributes leaves, so the disjunction is True while the stepping region is
between its exit and entry sets. The same conjunct is True once the entry set
has been applied but before entry actions have finished mutating context, so
`state_ids` reflects the new configuration and `context` reflects the old one.
`_await_settled_for_snapshot()` (:1088) shares the predicate, so the child-actor
path is holed identically.

Correct predicate: for every active compound state, exactly one child active;
for every active parallel state, every region active and each region resolving
to exactly one leaf — plus a separate "entry actions drained" condition, which
leaf-counting cannot express at all.

## Verdict

**CONFIRMED — Blocker.** Severity unchanged from R5-01's original rating and
matching #102's own. Silent, typed-error-free persistence of a blob whose
configuration and context disagree, restoring a machine that reports itself
healthy while a whole parallel region (its invokes, `after` timers and event
handlers) is gone. In the OMS target this is an order that can never fill or
cancel, with no exception, no log line and no `error`. Not detectable by the
caller: the only advertised detector is the broken guard, and there is no
public settled predicate to substitute for it.
