# R8-02 adversarial refutation — plain `def` service (lib @ 6db65d8)

## Reproduced (all three legs, both spellings)
| repro | async def | def |
|---|---|---|
| `concurrency/r2c_def_service_blocks_loop.py` | PING answered 0.001 s (pool 1 & 4) | **not answered**, latency 1.003 s, still in `r2c.hold` (pool 1 **and** 4) |
| `contracts/repro/cv_6db_01_def_invoke_not_cancelled.py` | PASS `after_cancel=m.cancelled`, `cursor=0` | **FAIL** `after_cancel=m.done`, `cursor=4242` |
| `contracts/kc_inline_svc.py` (A: `always` roll-forward; B: `actionErrorPolicy:"rollback"`) | PASS both, `service_calls=[]` | **FAIL** both, `service_calls=["submit_child"]` |

## Mechanism — the claim's wording is wrong, the effect is real
`interpreter.py:2811-2836` (`_invoke_plain_service_inline`) runs the callable on
`loop.run_in_executor(_get_service_executor(), ...)` — **not** on the loop thread (#149
moved it off). What stalls the machine is `interpreter.py:1571-1577`: the run loop does
`if self._inline_service_futures: await self._await_inline_services()` **before**
`_next_event()`, the only inbox drain. So the loop thread is free (other interpreters keep
running — confirmed) but *this* machine processes no inbox event until the service returns.
The "inline on the loop thread / blocks all event processing" framing is therefore false as
stated and non-reproducible as a process-wide stall; the per-machine starvation is real.

## Documented?
**Leg 1 is documented.** `docs/_guide/production-characteristics.md:93` (#174): "A plain-`def`
service blocks its own machine's timers for its whole duration … the macrostep that entered
the invoking state *awaits its result* before it completes … Other machines on the loop are
unaffected. If a timer has to interrupt a long service, make the service a coroutine."
That is the exact mechanism, with the prescribed fix. Leg 1 alone cannot be a blocker.

**Legs 2 and 3 are not documented.** The note is framed entirely around `after` timers. A
reader is not told that (a) `CANCEL` sent while a `def` service runs cannot pre-empt it — the
`done.invoke` lands first via the priority lane and drives the machine to `m.done`, so the
service is effectively **uncancellable** and its `onDone` writes context (`cursor=4242`) in a
state the user believed exited; and (b) a `def` invoke is **already executed** when the
arming step is undone. `_apply_action_error_policy`/`_discard_raised_since`
(`base_interpreter.py:4118-4141`) can withdraw raised events and restore context, and for an
`async def` service the *arming* of the task is what gets unwound — but the `def` call has
already run on the executor at entry, before the `always` chain and before the rollback
epilogue. Same chart, same policy, opposite side effects depending only on `def` vs `async def`.
The nearest doc statement ("cannot un-send a `sendTo` — that effect has left the machine")
covers a *committed* effect, not one the sibling spelling never commits.

## API misuse / XState v5 / duplicate?
- Not misuse: `MachineLogic(services={...})` accepts a plain callable as a first-class spelling;
  no strict mode, `strict=True` included, rejects or warns on it.
- XState v5 has no `def`/`async` service distinction (all actor logic is async) and no rollback
  policy, so it neither sanctions nor contradicts legs 2–3. Case A (enter → `always` exit) in
  XState starts and then stops the actor, i.e. the side effect happens — so **case A is
  arguably correct for `def` and the divergence is that `async def` never calls it at all**.
  Case B has no XState analogue.
- Not a duplicate: #116/#149/#173/#174 all address ordering, loop blocking and pool size. None
  claims cancellation or rollback semantics for plain services.

## Verdict
**DOWNGRADE to high.** Leg 1 (the stated blocker mechanism) is mis-stated and documented with
a one-word workaround (`async def`). Legs 2–3 survive: on both engines a `def` service is
uncancellable and its invoke is not unwound by a rollback, silently diverging from the
identical `async def` chart, with no documentation. Adoption impact is contained by a
mechanical rule — **never spell a service `def`; use `async def` + `asyncio.to_thread`** —
which we should encode as a lint/contract gate rather than treat as a ship-stopper.
