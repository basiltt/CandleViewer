# R11-05 — "#212's timer exemption keys on delay truthiness, not time" — REFUTED

Target: main @ c78ce99. Probes (standalone, neutral cwd <home>, both `def` and `async def` lanes):
- `probes/main-c78ce99/p1_212_escape.py` (reporter's)
- `probes/main-c78ce99/r11_05_after_parity.py` (new — control against `after`)
- `probes/main-c78ce99/r11_05_responsive.py` (new — livelock test, polled to convergence)

## Observations reproduce

Reporter's numbers reproduce exactly (maxIterations=10): mixed delayed+zero-delay `delay=1` → 133 beats err=None; `delay=0.0001` → 10539 beats, ~21k/s; pure `raise(delay=0.0001)` → 6701 beats; control `raise(delay=0)` → trips at 12 with `RunawayChainError`. Identical in shape on the `async def` lane.

## Why it is not a defect

**1. The control refutes the novelty claim.** `after` — the shape that has *always* been exempt, long before #212 — behaves identically on the same chart:

| shape | delay=1 | delay=0.0001 |
|---|---|---|
| `after:` + zero-delay raise per period | 131 beats, 129/s | 10247 beats, 20485/s |
| `raise(delay=)` + zero-delay raise | 133 beats, 131/s | 10539 beats, 21075/s |
| pure `after:` ping-pong | 68 beats, 67/s | 8235 beats, 16467/s |
| pure `raise(delay=)` ping-pong | 68 beats, 68/s | 6701 beats, 13365/s |

Both lanes, both action kinds. #212 did not open an escape; it made `raise(delay=)` *equal to* `after`, which `maxIterations` has never bounded and was never intended to. Both sub-claims — (1) "one delayed hop resets the chain every period" and (2) "below ~0.01 ms the bound is the loop turn rate" — are true of `after:0.0001` on every prior commit too. Nothing regressed; the finding is a property of clock-driven periodic processes, not of the #212 rule.

**2. It is documented, including the new rule.** `production-characteristics.md` §2: "a **delayed** self-send (`raise` with `delay`) is a timer with exactly the standing of `after` … a self-paced `raise(delay=)` heartbeat or poller is a periodic process the budget never counts, **whatever its period**. `maxIterations` bounds work the machine feeds itself *within* a step." The same section already documents the clock floor ("on Windows the default timer resolution is ~15.6 ms"), which is exactly consequence (2). The behaviour is the specified behaviour, stated in the terms the reporter uses.

**3. It agrees with XState v5 / SCXML.** SCXML §6.2: `<send delay=>` goes to the *external* queue via the scheduler; only `<raise>` (undelayed) is internal-queue work, and it is the internal queue that the microstep loop bounds. XState v5 likewise routes `raise({delay})` through the scheduler as a delayed event and applies no microstep limit to it. A delay of 0.0001 ms does not change its category in any of the three.

**4. API misuse.** `delay` is milliseconds; `0.0001` is 100 ns, below every platform clock floor. Asking for a 100 ns period and receiving "as fast as the loop turns" is the correct answer, not a liveness failure.

**5. Not a liveness failure — no starvation.** `r11_05_responsive.py`: with the machine spinning at ~15k beats/s on `delay=0.0001`, an external `send("PING")` is served at 16.5 ms (`def`) / 15.3 ms (`async def`) and the machine reaches `final` — versus 15.9 / 15.3 ms for the quiescent `delay=1` chart. Latency is the Windows timer floor and is *unchanged* by the spin rate. The loop is not wedged; this is a busy periodic process, the same thing a `while True: await asyncio.sleep(0)` task is. `maxIterations` is a *chain* budget, not a CPU quota, and was never the "only engine-level liveness bound" against a process the user explicitly asked to run at clock rate.

**6. No trust boundary crossed (R10-01 pattern).** The period is authored in the chart by the chart's author. There is no input path by which untrusted data selects a 0.0001 ms delay.

## Verdict

**REFUTED.** Severity High → none. Optional doc nit only: §2's clock-floor bullet could add "a delay below the platform clock floor fires on the next loop turn" — the fact is already implied by the ~15.6 ms sentence.
