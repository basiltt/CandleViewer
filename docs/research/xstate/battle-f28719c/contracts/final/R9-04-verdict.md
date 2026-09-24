# R9-04 — adversarial refutation result: CONFIRMED (high)

Repro re-run @ f28719c, fresh venv:

- `ld01_always_rollforward.py` -> exit 1, **3/6 lanes leak** (case A def/async-engine,
  case A def/sync-engine, case B def/sync-engine). `async def` clean on both cases.
- `always_rollforward_def_invoke.py` -> `CV_SVC_STYLE=async` exit 0 (`doomed_submitted=0`);
  `CV_SVC_STYLE=def` exit 1 (`doomed_submitted=1`).
- Configuration/context correct in every leaking row; only the side effect escapes.

## Refutation attempts, all failed

1. **Documented?** The opposite is documented. `docs/_guide/production-characteristics.md`
   §2 (line 97) ends: "Where the async engine *does* now match the coroutine lane: a `def`
   service armed by a transition that is then rolled back ... **or rolled forward (an
   `always` out of the state before it stabilises) is never submitted to the pool**."
   Case A def/async-engine is exactly that sentence, and it leaks. The §2 "cannot be
   cancelled by an event" contract covers *events*, not `always`, so it does not absorb
   the roll-forward path.
2. **API misuse?** No. `invoke` + `always` on one state is legal SCXML; guard is a pure
   `lambda: True`; strict/strictTargets/rollback all on; no timing race (settled 6x30ms,
   and the async lane is clean under identical timing).
3. **SCXML agreement?** SCXML §6.4 is on the reporter's side: `statesToInvoke` is drained
   and `invoke` started **only after the macrostep completes** (i.e. after eventless/
   `always` settling), and `exitStates` removes the state from `statesToInvoke`. A
   transient state left by `always` in the same macrostep must never start its invocation.
   Since #196 made `always` a settle-pass transition, the invoking state is on a path that
   never reaches the cancelling epilogue.
4. **Duplicate/closed?** No — it is the *residual* of #193, whose rollback half does hold
   on the async engine (case B def/async clean). The library is internally inconsistent:
   `tests/test_round8_findings.py::test_always_rollforward_matches_sync` pins the leaking
   behaviour ("both engines arm and complete the plain service inside the step ... parity
   is the contract") while CHANGELOG #193 and the docs promise the opposite. Both currently
   pass, so the green suite does not cover the claim it makes.
5. **Correct usage re-run?** `async def` is the only spelling that honours the claim — a
   workaround, not a refutation, because the published claim explicitly covers `def`.

## Residual scoping note (does not change severity)

The doc sentence is scoped to "the async engine", so the two `SyncInterpreter` rows
(case A and the case-B rollback leak) are the weaker half — the sync engine awaits the
service inline, and §2 argues that is the documented plain-`def` shape. The load-bearing
row is **case A, `def` service, async engine**: a published fix claim that is false on the
engine it names, with a real side effect (child-order submission) issued from a state the
machine never settled in.
