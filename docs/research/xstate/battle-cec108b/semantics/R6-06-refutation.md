# R6-06 adversarial refutation — VERDICT: CONFIRMED (High)

Library @ cec108b (0.8.1 unreleased). Repro:
`battle-cec108b/semantics/repro/d6s1_entry_window_torn_snapshot.py`, run
unmodified, both engines:

```
--- SyncInterpreter / --- Interpreter (async)   (identical)
  live after settle : ['oms.filled'] ctx= {'filled_qty': 100}
  snapshot mid-entry: ACCEPTED
     persisted state : ['oms', 'oms.filled']  context: {'filled_qty': 0}
     restored        : ['oms.filled'] ctx= {'filled_qty': 0}
     >>> TORN: state says FILLED, context says 0 filled
```

Cause verified at source: `base_interpreter.py:1306`
`if self._step_in_flight() and not self._configuration_is_legal():`.
#142 correctly rewrote `_configuration_is_legal` (:1222) to exactly-one-leaf-
per-region, closing the *parallel* tear. But in the entry-action window the
configuration is already perfectly legal (new leaf active, one per region)
while the macrostep is still open and context is half-applied, so the
conjunction is false and the snapshot is accepted. Legality was never the
right predicate for this window; `_step_in_flight()` alone is.

## Refutation attempts — all fail
- **Documented?** The opposite. `docs/api/index.md:713` and `:1787`, plus
  `_guide/snapshots.md:134` and `_guide/troubleshooting.md:56`, all promise
  `SnapshotMidStepError` when `get_persisted_snapshot()` is called
  "while a macrostep is in flight (e.g. **from inside an action**)".
  Observed behaviour contradicts the published contract.
- **API misuse?** No. No optional config is missing; the call is the exact
  case the docs name. Reproduces on *both* engines, so not a sync-engine
  artefact. Not superseded semantics — #102/#142 both post-date it.
- **Duplicate of a closed issue?** No. #102 closed the *no-leaf* window;
  #142/#143 closed the *parallel torn-region* window. Neither covers a
  legal-configuration-but-open-macrostep window. `tests/test_round5_findings.py`
  §#142/#143 pins only the parallel case.
- **XState v5 agrees?** No. In XState v5 `context` is updated by `assign`
  during the transition and the new `snapshot` object is published only once
  the macrostep completes; `actor.getPersistedSnapshot()` can never observe a
  leaf paired with a context that the same step has not finished writing.
  A torn (state, context) pair is not reachable there.

## Wider than claimed
Additional probe (`/tmp/p1.py`, same pattern): the **exit**-action window is
also ACCEPTED, not only entry. So the guard is inert for every action window
in a non-parallel machine, not just entry.

## Caveat on the proposed fix
"Refuse on `_step_in_flight()` alone for `_seen is None`" is the right
predicate, but it collides with a *documented remedy*: `on_transition` hooks
are listed as the safe place to snapshot, and a probe shows
`interpreter._step_in_flight()` is **True** inside `on_transition`. The fix
must either move the hook outside the in-flight window or exempt it, else a
documented-safe call site starts raising.

Severity retained **High**: silent, deterministic, both engines, persists a
financially wrong (filled/zero-qty) blob that restores clean with
`last_transition_ok=True`, `last_error=None`.
