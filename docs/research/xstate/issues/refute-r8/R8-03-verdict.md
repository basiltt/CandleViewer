# R8-03 adversarial refutation — VERDICT: CONFIRMED (high)

Claim: `start(children_timeout=)` is a no-op against a non-yielding (plain `def`)
child entry action, suppresses its own WARNING, and is an aggregate not per-child bound.

## Re-run (commit 6db65d8, venv-main)
| repro | result |
|---|---|
| concurrency/r6b_children_timeout_def_noop.py | FAIL — `def`,1 child: 3.00s (15x bound 0.2), warning_logged=false; `def`,5 children: 15.0s (75x), no WARNING. `async def` rows bounded. |
| concurrency/r6_children_timeout_50_slow.py | FAIL — `def` 50 x 1s = 50.04s, no WARNING; `async def` bounded. |
| persistence/r5_children_timeout_def.py | FAIL — `def` 20x100ms = 2.02s at bounds 0.05 / 0.2 / 1.0 (identical to `None`), warn=0; all `async` rows bounded. |
| probes/m5_children_timeout_aggregate.py | 4 x 0.5s children, bound 0.6 -> 0.506s: bring-ups are serial, bound is aggregate. |

## Refutation attempts — all fail
- **Documented?** No. `docs/api/index.md:701` justifies the bound precisely by "a child's
  bring-up runs its entry actions — user code (#181)", and CHANGELOG only ever says
  "a slow child's *`async def`* entry action". Nowhere is it stated the bound holds only
  for coroutine entry actions. The doc promises "On timeout a WARNING is logged and
  `start()` returns" — neither happens for `def`.
- **API misuse / correct usage exists?** No. `service_executor` / `service_pool_size`
  (#149, #173) off-load plain **services** only (`interpreter.py:2813 run_in_executor`);
  there is no executor, no `to_thread`, and no documented knob for **actions**. Plain
  `def` actions are a first-class supported spelling (`@action` decorator, sync engine
  parity) — correct usage reproduces the failure.
- **XState v5 agrees?** No precedent: v5 has no `children_timeout` equivalent
  (`createActor().start()` is synchronous and offers no bring-up bound), so it cannot
  license a bound that silently does not bind.
- **Duplicate of a closed issue?** No. #181 is the *introducing* change; #149/#173 are
  the service-side analogue and explicitly scoped to services.
- **Covered by tests?** No — `tests/test_round7_findings.py:557
  test_start_returns_within_bringup_timeout` parametrises over KINDS but gives the `def`
  branch `time.sleep(0.05)` vs the `async` branch `asyncio.sleep(3.0)`: the `def` arm
  cannot fail. `test_bringup_timeout_is_observable` is `async def`-only. Both pass; the
  "both spellings" claim for this finding is hollow.

## Root cause (unchanged)
`interpreter.py:601` -> `_await_actor_bringups(timeout=)` at `:2753` uses
`asyncio.wait(pending, timeout=)`, which can only pre-empt at an await point. A bring-up
awaits `child_interpreter.start()` (`:2973`), whose `def` entry action runs to completion
on the loop thread. Bring-ups are awaited serially, hence exact N x D scaling. The WARNING
lives on the same timeout path, so observability is suppressed with the bound.

## Severity: high (retained)
An advertised safety bound silently fails for one of two supported action spellings,
with no diagnostic, scaling linearly in child count (50s observed at a 0.2s bound) and
blocking the whole event loop for that time.
