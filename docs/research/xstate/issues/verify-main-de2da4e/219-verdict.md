# Independent recheck: #219 (ReentrantWaitError on own-interpreter in-step wait)

## Method
Standalone repros, neutral cwd, both engines.

## Sync engine
`i.send('GO', wait=True)` called from inside `A`'s own entry action while `A` is
processing raises `ReentrantWaitError` immediately (verified via direct repro with
DEBUG logging showing the raise happens synchronously, machine settles at `A.x`
having never advanced — correct: the send is refused outright on the sync engine,
matching the documented "sync engine refuses the same shape for parity" behaviour).

Also checked cross-interpreter shape (B's action calls `A.send(wait=True)` where A
is a *different* interpreter, not B's own) — this is NOT reentrant and must not be
refused; confirmed no exception raised in that shape (own-interpreter identity
check, not "any wait from inside any action", is correctly scoped).

## Async engine
- In-step `await i.send('GO', wait=True)` from `A`'s own entry action: raises
  `ReentrantWaitError` immediately, as documented.
- Deferred shape: `r = i.send('GO', wait=True)` (not awaited in-step), stored, then
  awaited from OUTSIDE after `start()` returns: resolves normally with the correct
  `Receipt(state_ids=frozenset({'A.y'}), changed=True, ...)` — the "hand the receipt
  out and await it later" escape hatch documented in the changelog and code comments
  works exactly as claimed, not merely theoretically.

## Verdict
**219 | VERIFIED FIX — no defect | in-step self-wait raises `ReentrantWaitError` on
both engines (sync refuses outright, async guards the future); the receipt-handed-
out-and-awaited-later escape hatch resolves correctly; cross-interpreter waits are
correctly excluded from the guard.**
