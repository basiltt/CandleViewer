# R5-08 adversarial refutation — DOWNGRADE High -> Low

Library: _ref/xstate-statemachine @ 3ed3099 (unreleased 0.8.1).
Probes: `r5_08.py` (A–E) + contextvar/mechanism probe.

## Reproduced
`p2_gate_and_inline.py` j4c: 60 iterations, `j4c_threadsafe_budgeted=false`.
Re-run with the **mandatory six-key policy block** applied (probe A):
`A_count=60, A_budgeted=false, A_drops=[]`. Not API misuse — the behaviour
is real and survives correct configuration.

## But the stated mechanism is wrong
R5-08 claims the cause is "threads get a fresh, empty context, so
`_ACTIVE_ACTION_OWNER.get()` is None". Measured:

- in an `asyncio.to_thread` worker spawned from the action, the contextvar
  **is** visible (`owner_visible_in_to_thread_worker=[true,true]`) — the
  context is copied — and the send is **still unbudgeted**
  (`E_to_thread_count=60`).
- `Interpreter.send_threadsafe()` never calls `_issued_from_own_action()` at
  all (`send_threadsafe_consults_gate=false`); it routes straight to
  `_enqueue()`.

So the gate is not "blind to threads because of contextvars"; `send_threadsafe`
is simply outside the gate by construction. A "thread-identity fallback" would
not fix it, and would not have been needed for `to_thread`.

## Refutation evidence
1. **Not starvation.** Probe C: with the thread self-feed running 40 deep,
   all 5 concurrent external `OTHER` events were delivered and interleaved
   (`C_other_delivered=5`). Unlike a true runaway chain this does not wedge
   the loop or strand the configuration; it is unbounded *work*, not a
   liveness failure.
2. **Both proposed remedies regress #105.** Probe B implements the scenario
   #105 exists to protect: a genuine external producer thread sending 30
   events while a slow action holds the step. Today all 30 land
   (`B_external_thread_delivered=30`, no `chain_budget` drops). "Count
   `send_threadsafe` against the chain while `_processing`" would charge
   exactly these to `maxIterations=10` and drop 20 — reintroducing the
   dropped-external-traffic bug. A thread-identity fallback cannot separate
   a worker-pool thread owned by the producer from one spawned by an action.
3. **No documented promise is broken.** `docs/_guide/json-config.md` scopes
   `maxIterations` to "eventless microsteps, and unbroken chains of
   self-`raise` / self-`send()`". A send arriving from a foreign thread over
   `run_coroutine_threadsafe` is not an unbroken self-send chain. Every
   `send_threadsafe` doc/example (`interpreters.md` §Sending from Another
   Thread, `examples/async/features/send_threadsafe/`) frames it as an
   *external producer* path; none shows an action spawning a thread that
   sends the same event back. The "documented escape hatch" framing in R5-08
   is not supported by the docs.
4. **XState v5 / SCXML agree.** SCXML's macrostep guard covers the internal
   queue and NULL (eventless) transitions only; external-queue events are
   never budgeted (W3C SCXML §D `mainEventLoop`). XState v5's loop protection
   is likewise on `_internalQueue`/`always`; `actorRef.send()` from outside
   is unbounded. A worker thread posting back is an external-queue send in
   both models.
5. **Not a duplicate** of a closed issue: #105/#90 cover the asyncio-task
   side, which probes j4/j4b/j4d confirm is correctly budgeted (21/1/21).

## Residual (why not REFUTED)
There is a genuine, guard-free unbounded self-feed shape:
`action -> spawn worker -> send_threadsafe(same event)`. It has no budget, no
`chain_budget` drop, and no diagnostic; `max_queue_size` + `DROP_NEWEST` did
not engage at this rate (`D_count=200, D_queue_full_drops=0`) because the
loop keeps up. That is a missing-hardening / docs gap, not a correctness
defect, and no obvious fix exists that does not regress #105.

## Verdict
**DOWNGRADE to Low.** Behaviour reproduced; causal claim falsified;
starvation claim falsified; "documented escape hatch" claim unsupported;
XState/SCXML agree that cross-boundary sends are not budgeted; the proposed
fixes regress the issue this gate was built for. Worth a documentation note
("`send_threadsafe` is external traffic and is never charged to
`maxIterations`; do not build action->thread->self-send loops") rather than an
engine change.
