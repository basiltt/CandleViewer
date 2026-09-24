# R6-03 adversarial refutation — VERDICT: CONFIRMED (Blocker)

Library cec108b. Repro `rollback_invoke_respawn_spin.py` reproduced verbatim:
2859 service invocations in 2.0 s, `state=['spin.starting']`, `status='running'`, indefinitely.

## Refutation attempts (all fail)

1. **Documented?** No. `docs/_guide/reliability.md` §1 states rollback = "configuration
   restored, context restored, machine running"; `actions.md` L636 says entered states'
   `invoke`s are "restored, timers re-armed". Nothing anywhere warns that a re-armed
   `invoke` whose `onDone` target keeps failing re-invokes without bound. No bound is
   documented for this shape.
2. **Contradicted by the library's own stated invariant.** CHANGELOG #94 (round 4):
   *"It is still counted, so a rollback→re-arm→done cycle remains bounded."* This is
   exactly that cycle and it is unbounded on the async engine. The claim is false for
   `Interpreter`.
3. **API misuse / missing mandatory config?** No. `maxIterations=5` measured: 7321
   invocations in 1 s — the budget has no effect. `onError`/guards are irrelevant (the
   service succeeds; the entry action raises). `rollback` is not exotic: it becomes the
   **1.0 default** (`reliability.md` L35).
4. **Sync engine / superseded semantics?** Sync is correct (2 invocations, quiescent),
   so this is also an **engine-parity break**, not an intended semantic.
5. **XState v5 agrees?** v5 has no `actionErrorPolicy`/rollback concept at all — an
   entry-action throw propagates to the actor's error handling and the actor errors out.
   There is no upstream precedent endorsing silent unbounded re-invocation.
6. **Duplicate of a closed issue?** Closest are #103/#144 (budget/livelock) and #94.
   All are sync-engine or self-generated-chain fixes; each lap here is a separate
   macrostep driven by a genuine `done.invoke.s`, so none of them apply — confirmed by
   the `maxIterations=5` measurement above.

## Policy/engine matrix (1 s, this run)

| policy | async invocations | sync |
|---|---|---|
| rollback | 7699 (running, `spin.starting`) | 2 (running) |
| continue | 1 (`spin.recording`) | 1 |
| fail | 1 then `stopped` | 2 then `stopped` |

## Honest mitigations (do not change severity)

- The event loop is **not** starved: a concurrent heartbeat kept ≤0.7 ms gaps, and
  `send("ABORT")` was accepted with 0.000 s latency and stopped the spin. So this is an
  unbounded *side-effect / CPU* spin, not a hang.
- It is observable via hooks: `on_transition_failed` fires every lap,
  `last_transition_ok=False`, `last_error` set. But there is no *bound* and no terminal
  state — an unattended process re-invokes the service for ever.

## Why Blocker stands

For a side-effecting service (order placement, payment capture) one user-visible event
produces ~1400 duplicate invocations per second, with the machine reporting `running`
and `error=None`, under the policy that becomes the 1.0 default, on the engine the
product uses, while the sync engine and the library's own #94 note say it is bounded.

Repro artefacts: `rollback_invoke_respawn_spin.py`, `r603_probe.py` (policy/engine
matrix, `maxIterations` probe), `r603_starve.py` (responsiveness/ABORT measurement).
