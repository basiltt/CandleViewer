# R6-05 adversarial refutation — `send_threadsafe` / OverflowPolicy.RAISE (cec108b)

**Verdict: DOWNGRADE High → Medium.** The headline claim ("the bound is
bypassed", "excess events silently never run") is **refuted**. A narrower,
real defect survives: under a busy loop the RAISE refusal is invisible to the
documented fire-and-forget producer.

## Original repro reproduces (as written)

`contracts/repro/threadsafe_bound_bypassed_when_loop_busy.py`, cec108b:

```
accepted        : 500
QueueOverflow   : 0   <-- expected ~497
actually ran    : 3
on_event_dropped: 0
```

## Corrected usage refutes the headline

`contracts/repro/r6_05_corrected_bound_holds.py` — same script, but it reads
the returned future (the channel the `send_threadsafe` docstring names for
loop-side refusals) and samples `_event_queue.qsize()`:

```
call-site accepted     : 500
call-site raised       : 0
FUTURE raised QOE      : 497   <-- refused on the loop
FUTURE ok (enqueued)   : 3
max observed qsize     : 0     (bound = 3)
actually ran           : 3
```

- **The bound is never exceeded.** Queue depth never passes 3 (observed max 0).
  The stale-`qsize()` call-site check is an *optimistic pre-check*; the
  authoritative check is `_enqueue()` inside `_deliver()`, on the loop, against
  a live depth. 497 of 500 are refused there with `QueueOverflowError`.
- **No silent acceptance-then-loss.** Every event is either enqueued and run
  (3) or explicitly refused with an exception object delivered on its future
  (497). Nothing is accepted and then dropped; there is no queue growth, no
  leak, no unbounded in-flight backlog.
- **`on_event_dropped` not firing is by design, not a miss.** For
  `OverflowPolicy.RAISE` the exception *is* the signal; the hook is reserved
  for `DROP_NEWEST`/`stopped` (interpreter.py `_enqueue`). Counting it as
  "silent loss" conflates two policies.
- **Behaviour is documented.** `send_threadsafe` docstring: *"Evaluated against
  the inbox depth visible from the caller's thread; a concurrent producer may
  still be refused on the loop, in which case the returned future carries the
  error."* The repro discards that future.
- **Pinned test is not mis-scoped as alleged.**
  `test_raise_policy_raises_at_call_site_when_full` tests exactly what #157
  claims (call-site raise when the caller can see fullness); the loop-side path
  is the pre-existing `_enqueue` contract.

## What survives (Medium)

#157's value proposition — "backpressure at the call site, not on a future the
fire-and-forget pattern never reads" — **inverts under load**. Whenever the
loop is busy (the only time backpressure matters) the call-site check sees a
stale depth, passes, and the refusal lands on precisely the future #157 says
producers do not read. Confirmed: a fire-and-forget producer gets **no call-site
raise, no `on_event_dropped`, and no log line** (RAISE's `_enqueue` branch logs
nothing, unlike `DROP_NEWEST`) — verified with `logging.DEBUG`: 0 matching
lines, and no asyncio "exception never retrieved" traceback.

Net effect: correct load-shedding with a **hidden shed rate**. An OMS producer
can lose 99% of its cross-thread sends while every call appears to succeed.

Severity Medium, not High: bounded queue holds, no corruption, no leak,
deterministic refusal, and the loss is retrievable via the returned future.

Suggested fix (library): log a warning in the RAISE branch of `_enqueue`, or
fire `on_event_dropped(..., "queue_full")` for loop-side RAISE refusals, so the
shed is observable without per-send `.result()`.
