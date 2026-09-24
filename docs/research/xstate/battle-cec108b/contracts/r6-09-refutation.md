# R6-09 adversarial refutation — plain-`def` service "freezes the inbox"

Library: `main` @ cec108b. All runs: `.venv-main` python, `PYTHONUTF8=1`.

## 1. Repro re-run, unmodified

`battle-cec108b/contracts/repro_cv_cec_01.py`:

```
async def  PING latency=0.001s receipt.state_ids=['p.working'] mark_ping=True  final=['p.working']
plain def  PING latency=0.350s receipt.state_ids=['p.done']    mark_ping=False final=['p.done']
```

The *observable* is real: with a plain `def` service, a `PING` declared on the
invoking state is evaluated against the post-completion configuration and lost.

## 2. What the repro's own framing gets wrong

The finding's stated cause asserts the CHANGELOG's claim that "timers, actors and
inbound sends no longer stall" is false. Three measurements say otherwise:

- **Loop turns** (`/tmp/r609.py`): a background `asyncio` ticker fires every
  ~55 ms straight through a 0.5 s plain service.
- **`send()` does not block** (`r609b`): `await i.send("PING")` without
  `wait=True` returns in 0.000 s. The 0.350 s in the repro is *only* because it
  passes `wait=True` — it is waiting for its own receipt, not for the inbox.
- **Child actors keep running** (`r609d`): a nested actor on a 100 ms `after`
  ladder alternates `c.a`/`c.b` seven times during the parent's 0.6 s plain
  service.

So the only thing deferred is **the invoking machine's own event dispatch** —
which is exactly the #116 parity contract, not a regression of it.

## 3. Documented?

`docs/api/index.md`, `service_executor` row, verbatim:

> The entering macrostep still *awaits* the result — so a plain service's
> `done.invoke` lands ahead of any event already in the inbox exactly as on the
> sync engine (#116) — but the event loop is free for the duration.

That sentence states the observed behaviour precisely: events already in the
inbox are processed *after* `done.invoke`. `docs/_guide/services.md` ("Sync vs
Async Services") also lists `async def` as the async engine's service type; a
plain `def` there is a parity accommodation, not the recommended shape.

## 4. Corrected usage

Documented shape, same blocking body (`/tmp/r609c.py`):

```python
async def corrected(i, c, e):
    return await asyncio.to_thread(blocking)
```

```
corrected: latency=0.001 receipt=['p.working'] trace=['ping']  final={'p.done'}
```

`PING` is handled in `working` as declared. The defect does not survive
correct usage.

## 5. XState v5

No analogue to cite in either direction: v5 has no "synchronous blocking actor"
— `fromPromise` / `fromCallback` are all loop-resident, so a user porting the
documented `async def` shape never meets this.

## 6. Residual (the part that is genuinely worth filing)

Two narrow doc/telemetry gaps, not a correctness bug:

- `docs/_guide/services.md`'s #116 parity note says completion lands "at the
  same point" on both engines but never warns that **events declared on the
  invoking state itself** will be evaluated post-completion. The warning exists
  only in the API reference's `service_executor` row.
- The invoking machine's own `after` timers fire late by the service duration
  (`after.100` observed at 0.528 s for a 0.5 s service, ~428 ms lateness) —
  consistent with the same ordering rule, but undocumented.

## Verdict

**DOWNGRADE to Low (documentation).** Reproduced, but documented at the exact
API surface, deliberate (#116), and removed by the documented `async def` /
`asyncio.to_thread` shape. The finding's cause claim — that actors, timers and
inbound sends still stall — is refuted by direct measurement.
