# R11-05 — "#212's timer exemption keys on delay truthiness, so `raise(delay=0.0001)` escapes `maxIterations`" — REFUTED

Filed **High**. **Refuted outright; severity none.** Not filed upstream.

Behaviour reproduces exactly as reported: a `raise(delay=0.0001)` cycle runs at ~20k laps/s with no chain trip, on both `def` and `async def` lanes.

## Why it is not a defect — the control kills it

Plain `after:` at the same delays behaves **identically on the same charts**:

| spelling | beats | per second |
|---|---|---|
| `after: 0.0001` (mixed) | 10,247 | 20,485 |
| `raise(delay=0.0001)` (mixed) | 10,539 | 21,075 |
| `after: 0.0001` (pure ping-pong) | 8,235 | — |
| `raise(delay=0.0001)` (pure ping-pong) | 6,701 | — |

Both lanes. `after` has been exempt from `maxIterations` since long before #212, so **both sub-claims are true of `after:` on every prior commit** and nothing regressed. #212 opened no escape — it made `raise(delay=)` equal to `after`, which `maxIterations` never bounded by design.

1. **Documented.** `production-characteristics.md` §2 states it verbatim, including the new #212 rule ("a periodic process the budget never counts, whatever its period") and the ~15.6 ms clock-floor bullet.
2. **Conformant.** SCXML §6.2 and XState v5 both send delayed sends to the scheduler, outside the microstep / internal-queue bound.
3. **Not a liveness failure.** Polled to convergence: an external `send("PING")` during the ~15k beats/s spin is served in **16.5 ms (`def`) / 15.3 ms (`async`)** and the machine reaches final — the same latency as the quiescent `delay=1` chart, i.e. the Windows timer floor. No starvation.
4. **No trust boundary.** The period is chart-authored.
5. **API misuse, not an escape hatch.** `delay` is milliseconds, so `0.0001` is 100 ns.

## Carried forward

Not as a library finding. As **CV-C55**: no `delay` below 10 ms anywhere in the catalogue, either spelling — sub-millisecond values land under the platform clock floor regardless. Mentioned on the #212 thread only as an optional kindness (warn on a delay below clock granularity), explicitly not as a defect.

## Collateral question this settles

This was the leading candidate for "did #212 re-open a bounded-cycle class?" It did not. Together with the purpose-built collateral-unboundedness probe (no previously-bounded shape became unbounded, watchdogs on both lanes) and the 527-script sweep (one stable delta, and it is our own superseded #206 test), the answer to that round question is **no**.
