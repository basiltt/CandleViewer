# R7-04 adversarial refutation — "External traffic renews the per-macrostep settle budget; invoke cycle never drains its inbox"

**Verdict: REFUTED.** Both repros reproduce, but the causal claim is wrong on
three independent axes, and the designed-and-documented remedy removes the
wedge entirely.

Library: `_ref/xstate-statemachine` @ `221ce7c` (unreleased 0.8.1).

## Claim under test

> `interpreter.py:1646-1652` (`if not is_system_event(event) or from_inbox:
> self._settle_iterations = 0`) hands a fresh settle budget to a
> self-generated cycle. "Each invoke-cycle lap costs a service round-trip, so
> burning `maxIterations` laps per inbox event exceeds the cost of one inbound
> `send_threadsafe`; arrival rate permanently exceeds drain rate."

## Reproduction (both confirmed)

- `probes/main-221ce7c/p4_external_event_renews_budget.py`:
  `noise=False laps=10 BOUNDED at ~20`, `noise=True laps=1010 BUDGET RENEWED`.
- `battle-221ce7c/concurrency/q7b_minimal_invoke_cycle_unresponsive.py`:
  10/10 wedged, `final_inbox_backlog 19834`, `laps_burned 70400`, `result FAIL`.

The *observations* stand. The *diagnosis* does not.

## A1 — `laps_per_event` is flat across a 1000x budget sweep

`adversarial/r7-04/a1_budget_scaling.py`, same shape/traffic, only
`maxIterations` varied:

| maxIterations | sent | laps | laps/event | final backlog | wedged |
|---|---|---|---|---|---|
| 1 | 10800 | 32424 | 3.00 | 0 | 0/6 |
| 5 | 10800 | 41807 | 3.87 | 4835 | 6/6 |
| 50 | 10800 | 35683 | 3.30 | 10115 | 6/6 |
| 1000 | 10800 | 35202 | 3.26 | 10776 | 6/6 |

The claim requires laps/event to scale with the renewed budget ("burning
`maxIterations` laps per inbox event"). It is **flat at ~3.3 while the budget
grows 1000x**, and `maxIterations=1000` is indistinguishable from `50`. The
budget is not the throttle being defeated, because the budget was never the
binding constraint: the cycle burns ~3 laps per event regardless.

## A2 — the claimant's own control refutes the mechanism

In q7b's published JSON, the `always_cycle` control burned **317,210 laps**
(4.5x the invoke shape's 70,400) under the same external drip and finished with
`final_inbox_backlog 0`, `machines_not_answering_in_5s 0`. Budget renewal
applies identically to both shapes. More renewed laps, zero starvation. The
variable that separates wedge from no-wedge is not the budget.

## A3 — cause isolation: it is the documented plain-service macrostep await

`adversarial/r7-04/a2_cause_isolation.py`, identical cycle, budget and traffic,
varying only *how the service is written*:

| variant | laps | final backlog | wedged |
|---|---|---|---|
| A plain `def`, `sleep(1ms)`, pool=2 | 35355 | 10117 | 6/6 |
| B plain `def`, no sleep, pool=2 | 70447 | 9427 | 6/6 |
| C plain `def`, `sleep(1ms)`, pool=32 | 35787 | 10107 | 6/6 |
| D `async def`, `await sleep(1ms)` | 2652 | **0** | **0/6** |
| E `async def`, no sleep | 54520 | **0** | **0/6** |

Settle-budget renewal is bit-identical in all five. D and E do not wedge — E at
54,520 laps, *more* self-generated work than the wedging variant A. B removes
service latency entirely and still wedges, killing the claim's own cost
argument ("each lap costs a service round-trip"). C gives 16x the workers and
changes nothing, so it is not pool starvation either.

The discriminating variable is `def` vs `async def`, i.e. the documented rule
that a non-coroutine `invoke` is *awaited by the entering macrostep*:

- `docs/_guide/production-characteristics.md:95` — "**A plain-`def` service
  blocks its own machine's timers for its whole duration** (#174) ... the
  macrostep that entered the invoking state *awaits its result* before it
  completes (that is what puts `done.invoke` ahead of the inbox, #116/#149) ...
  If a timer has to interrupt a long service, make the service a coroutine
  (`async def`)."
- `docs/api/index.md:694-695` (`service_executor` / `service_pool_size`) — "The
  entering macrostep still *awaits* the result ... so a plain service's
  `done.invoke` lands ahead of any event already in the inbox."

`done.invoke` landing ahead of the inbox is the *specified* ordering (#116). A
cycle built from plain services therefore re-enters ahead of the inbox on every
lap by design. That is the wedge, and the documented fix (`async def`) clears it
— variants D/E, 0/6 wedged, backlog 0.

## A4 — p4's "BUDGET RENEWED" is the documented contract, restated as a bug

p4 reports `noise=True laps=1010` over 100 external sends at
`maxIterations=20` — ~10 laps per external event, i.e. **bounded by the budget
on every macrostep**, with the total growing *linearly* in external events.
That is precisely the per-macrostep semantics shipped as #166/#151 and
documented:

- `CHANGELOG.md` [Unreleased] — the settle budget "is now per macrostep on the
  instance, reset only when an external event begins its step — the sync
  engine's #103/#151 rule".
- `docs/_guide/json-config.md:110` — "Counted per **chain** — it resets whenever
  a step generates nothing — so a batch of any size of independent user events
  is always processed in full on both engines."
- `docs/_guide/production-characteristics.md:95` — "What the `maxIterations`
  settle budget bounds is the *number of microsteps* a macrostep may take, not
  its wall-clock duration; a budget is not a deadline."

A per-*macrostep* budget that did **not** reset per macrostep would be a
per-lifetime budget, and would cap the total microsteps a long-lived machine may
ever take — the #151 defect that was deliberately fixed. p4 labels
"budget is per macrostep" as "budget renewed by external traffic". `laps=1010`
is not divergence; it is 100 macrosteps of ≤20 microsteps each.

Note also that both repros show `chain_tripped=False` / the cycle is sustained
by engine completions, which `docs/_guide/json-config.md:110` states are
categorically exempt: "Engine completions (`done.invoke`, `error.platform`) are
never discarded." The budget is not the governing mechanism for this shape at all.

## Correct usage, re-run

Per `production-characteristics.md:95`, a service that must not block its own
machine's macrostep is written `async def`. Applying that to the claimant's own
shape (variants D/E) yields `machines_not_answering_in_5s 0` and
`final_inbox_backlog 0`. The reported failure mode does not survive documented
correct usage.

## Residual

There is a real, narrower, already-documented property: a machine whose invoke
cycle re-arms itself via a **plain-`def`** service will service its own
completions ahead of its inbox indefinitely, so its inbox starves. It is the
direct consequence of the specified #116 ordering plus a self-feeding
configuration the user authored. It is bounded to that shape, does not depend on
`maxIterations`, has a documented remedy, and is not the "external traffic
renews the budget" defect claimed. Merging L-4 and D7-concurrency-1 under the
budget-renewal cause is a misattribution.

## Files

- `a1_budget_scaling.py` — budget sweep (A1)
- `a2_cause_isolation.py` — service-shape isolation (A3)
