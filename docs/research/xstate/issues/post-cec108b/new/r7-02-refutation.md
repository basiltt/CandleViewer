# R7-02 adversarial refutation — VERDICT: CONFIRMED (Blocker)

Target: main @ 221ce7c. "External `send(priority=True)` is charged to the
chain budget and silently dropped as `chain_budget`."

## Reproduction
- `probes/main-221ce7c/p1_priority_lane_charged.py` (burst producer):
  `sent=3000 processed=1162 dropped=1838 reasons={'chain_budget'}`,
  `_raise_depth=0 tripped=False last_error=NoneType` afterwards.
- `p1b_priority_realistic_producer.py` (new, gentler: one send per
  0.1 ms from a separate task, 0.5 ms `await` inside the action):
  `sent=1500 processed=890 dropped=454 {'chain_budget'}` — 30% loss with
  no burst and no reentrancy trick.

## Refutation attempts (all fail)
1. **Documented?** No. `send()`'s docstring (interpreter.py:2255-2265)
   describes `priority=True` only as ordering + exemption from
   `max_queue_size`; nothing says these events are charged to the
   self-raise budget. The run loop's own architecture note
   (interpreter.py:1510-1516) states the opposite as the design
   intent: "`_raise_depth` counts only events this loop enqueued *while
   processing another event*, so external traffic of any volume is never
   throttled." No caveat in `docs/_guide/interpreters.md`,
   `docs/api/index.md`, `README.md`, or CHANGELOG.
2. **API misuse?** No. `priority=` is a public keyword (plus public
   `send_priority()`), called from the owning thread, fire-and-forget as
   documented. Control run `p1c_control_nonpriority.py` — identical
   volume/shape without `priority=True` — is `processed=3000 dropped=0`.
   So the loss is caused purely by opting into the documented
   "must not wait behind routine traffic" lane.
3. **Deliberate backpressure?** No: the lane is explicitly exempt from
   `max_queue_size`, and the drop reason is `chain_budget`, not
   overflow. The overflow policy (`on_event_dropped(queue_full)`) is the
   designed backpressure path; this one bypasses it.
4. **XState v5 parity?** v5 has no chain/iteration budget applied to
   external `actor.send()`; its microstep guard covers eventless/raised
   transitions only. No upstream precedent for cutting external sends.
5. **Duplicate of a closed issue?** #166/#167/#168 (round 6) are about
   *completions produced while processing* — self-generated work. They
   changed `_deliver_priority` to test `self._processing` (WHO → WHEN),
   which is what leaks onto the public external path at
   interpreter.py:811-812. Not covered by #122/#157.

## Root cause
`_deliver_priority` (interpreter.py:2287-2288) decides provenance by
*when* the event lands (`if self._processing: self._raise_depth += 1`),
while `send(..., priority=True)` routes straight there. Every other
enqueue path decides provenance by *who* issued it
(`_issued_from_own_action()`, lines 826/854/1206). Any producer faster
than the loop therefore has legitimate external events counted as
self-generated and cut at `max_iterations`.

## Aggravating: near-silent
On the drop path, once both lanes are empty `_raise_depth` and
`_chain_tripped` are reset (lines 1596-1599), so `last_error` reads
`None` and `last_transition_ok` is overwritten by the next successful
step. Loss is observable only via `on_event_dropped` — an opt-in plugin
hook. Under the financial-OMS standard this is silent loss on the
highest-criticality lane.

## Fix
In `_deliver_priority`, charge the budget only for self-generated
deliveries: pass an explicit `internal: bool` from the call site (timer /
completion paths → `True`), or gate on `_issued_from_own_action()`.
Public `send(priority=True)` must enqueue without touching
`_raise_depth`.
