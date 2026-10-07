# R10-03 adversarial refutation — DOWNGRADE to Medium

Tree: main @ 19cb1f1. All runs from neutral cwd <home>, stdlib-only repros.

## Reproduced (claim stands on the facts)
- `p2_delayed_selfsend_heartbeat.py`: async, `maxIterations=8`, 30 ms self re-arming
  heartbeat -> `n=9`, `on_event_dropped(reason="chain_budget")`, `last_error =
  RunawayChainError`. Identical for `def` and `async def`.
  Sync `tick()` lane: 29 beats, no cut. External traffic (Q3): 47 beats, no cut.
- `p3_delayed_selfsend_scope.py`: 30 / 100 / 250 ms all cut at 5 laps — not time-aware.
- Cause confirmed at interpreter.py:2213-2247 (`self_armed` -> `_chain_owed_sends` +
  `_armed_this_step`) and 1816-1836 (chain-clear test false while a debt is owed).
- New probe `r10_03_refute_after_vs_raise.py`, polled to convergence (15 s, 2 s
  no-new-beat plateau): still `n=9`. **Not the R9-03 early-sampling artefact.**

## What refutes the severity, not the behaviour
1. **Declared, not undeclared.** CHANGELOG [Unreleased] #206 states the change in
   terms: a `raise(delay=)` to self "is now a debt of the arming step ... its firing
   is charged as engine work ... trips at the same lap as the zero-delay `raise`
   cycle (±1)", and names the sync lane's divergence as by construction.
   `docs/_guide/json-config.md:110` already scopes `maxIterations` to "unbroken chains
   of self-`raise` / self-`send()`" — a heartbeat with no external traffic is exactly
   that chain, and #206 only removed `delay` as an escape hatch from it.
2. **The documented heartbeat idiom is unaffected.** `docs/_guide/delayed-transitions.md`
   (§ polling loop, 532-611) teaches `after` for pollers/heartbeats. Measured:
   `after` ping-pong at the same 30 ms and `maxIterations=8` runs **185 / 183 beats
   in 6 s with zero drops**, both kinds, while the `raise(delay=)` spelling dies at 9.
   No doc anywhere presents self-`raise(delay=)` as a heartbeat; `raise_` appears only
   as a zero-delay internal event. So this is a non-idiomatic spelling with a
   documented, working alternative — API misuse in the weak sense.
3. **Fail-loud, not silent.** Machine stays `running`; `RunawayChainError` on
   `last_error` / receipt, `on_event_dropped("chain_budget")`, WARNING log. A
   production chart cannot lose beats undetected.
4. **Any external traffic clears it** (Q3, 47 beats) — an OMS heartbeat that also
   receives order/tick traffic never reaches the budget.

## What survives (why not REFUTED)
The chain-clear test is genuinely not time-aware: 250 ms and 1 ms are charged
identically, so wall-clock separation — the one signal that distinguishes a poller
from a runaway — is discarded. `docs/_guide/production-characteristics.md:95` says the
budget bounds microsteps, "not wall-clock duration; a budget is not a deadline", which
reads as reassurance that slow work is safe; under #206 a *slow self-send* is not.
Real defect: a doc/behaviour gap plus a missing time-separation escape, on a
non-idiomatic but plausible spelling. Not High (declared + documented alternative +
loud failure + not silent, not data-affecting).

## Recommended constraint (supersedes any "avoid #206" note)
CV: heartbeats and pollers MUST be spelled with `after`, never a self
`raise(delay=)` / `send_to(self, delay=)`. Lint the charts for it.
