# R7-01 adversarial refutation attempt — VERDICT: CONFIRMED (Blocker)

Library @ 221ce7c (unreleased 0.8.1). All numbers re-run this session.

## Reproduced
- `/tmp/lane.py` (lane instrumentation): plain `def` svc -> `{priority: 23, inbox: 0}`, `last_error=RunawayChainError`.
  `async def` svc -> `{priority: 0, inbox: 27409}`, `last_error=None`. Completion lane is decided purely by
  whether the service is a coroutine function.
- `fuzz/q1_async_invoke_runaway.py`: `maxIterations=20`, invoke ping-pong a<->b.
  sync=22 laps/RunawayChainError; async+`def`=22 laps/RunawayChainError; async+`async def`=**67351 laps in 5 s,
  last_error=None, ok=True** — budget never charged.
- `fuzz/q14_torn_repro.py`: async+`def` -> config stays `['m.a.a.a']` 0/10; async+`async def` -> **EMPTY config 10/10**,
  `ok=True`, `err=None`, `status=running`, still empty after +500 ms; snapshot correctly REFUSED (SnapshotMidStepError),
  i.e. the library itself classifies that state as corrupt while `send(wait=True)` reports success. Sync engine on the
  identical chart: `['m.a.a.a']` throughout.
- `/tmp/rb.py` (rollback ablation): plain svc_calls=23 + RunawayChainError; async svc_calls=2780, last_error=RuntimeError
  (the rollback re-arm loop is unbounded only on the async lane).

## Cause (code-level, supersedes prior theories)
Two publication paths for one logical event:
- plain: `_finish_plain_service` -> `_deliver_priority(done_event)` (interpreter.py:2690), charging `_raise_depth`
  when `_processing` (interpreter.py:2287-2288).
- `async def`: `_invoke_service_task` -> `await self.send(done_event)` (interpreter.py:2414); child-actor `onDone`
  likewise at :2882 — the public inbox, which never reaches `_deliver_priority` for any value of `_processing`.
Compounding: arriving `from_inbox`, the completion also satisfies the `from_inbox` disjunct at interpreter.py:1647
and resets `_settle_iterations`/`_settle_tripped` every lap, so the per-macrostep settle budget cannot trip either.
This refutes LD-03's `is_system_event` theory and the `_processing`-timing theory (D7-fuzz-1 / LD-04 / CV-221-01):
the lane counters show 0 priority deliveries for async regardless of timing.

## Refutation attempts — all fail
- **Documented?** No. CHANGELOG/[Unreleased] and docs describe the round-6 chain budget and `maxIterations` as engine-wide
  infinite-loop detection (docs/FEATURE_GAP_ANALYSIS.md:212/219); nothing states the budget applies only to
  non-coroutine services. No doc mentions the two lanes.
- **API misuse?** No. `async def` services are the library's own recommended form (#174); the failing charts are the
  same ones the library's round-6 tests use, only with `async def` substituted.
- **XState v5 agrees?** No. In XState, `done.invoke.*` / actor-done events are processed by the same microstep loop
  regardless of whether the actor logic is sync or async, and `maxIterations` guards that loop unconditionally. And no
  SCXML/XState-conformant interpreter ever exposes an empty configuration while `status === 'active'`; `q14` shows the
  sync engine here keeping a legal config on the identical chart, so this is also an internal engine-parity break.
- **Duplicate of a closed issue?** No. Round-6 fixes #166-#175 target this area but all three pinned tests declare
  `def svc(...)` (tests/test_round6_findings.py:124, 184, 486), so the suite is structurally blind to the async lane;
  only :235 uses `async def` and it asserts late-completion delivery, not budget charging.
- **Correct usage re-run:** switching the service back to plain `def` (the only "fix" available to a user) restores
  bounding — confirming the defect is the lane split, not the chart.

## Verdict
CONFIRMED — Blocker. Unbounded self-generated work (67k laps/5 s, no error) plus a silently torn/empty configuration
reported as a successful transition, on the library's recommended service style, invisible to its own test suite.
