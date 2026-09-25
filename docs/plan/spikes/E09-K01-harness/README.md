# E09-K01 spike harness

Throwaway prototype for the session/token-rotation/revocation model. **Not shippable** — see
`docs/plan/spikes/E09-K01-session-model.md` for the findings and
`docs/plan/27-adrs/ADR-0017-session-access-token-and-revocation-model.md` for the decision.

## What this is

An in-process, in-memory simulation of the `sessions` / `sessions_rotation` tables
(`21-database-schema.md` §3.1.4) and the opaque-handle revocation check, driven by a
fake/virtual clock (no `sleep`, no wall-clock dependency, no network). It measures:

- session-lookup / revocation-check latency (p50/p99) for an opaque-handle design,
- WS re-auth frame cadence under a chosen access-token TTL, simulated for a virtual hour,
- rotation-family revocation walk cost at 10k rows,
- rotated-token-reuse family-kill behaviour and the `auth.refresh_reuse_detected` event.

**Not run locally: no docker** — a real Postgres-backed measurement (`services/api` does not
exist yet; `INFRA-001` scaffolding and `E03` CI/CD land it) is out of scope for this spike per
its own "Out of scope" section (throwaway harness, not production code). The in-memory model
uses the same dict/adjacency-list shape the real `sessions`/`sessions_rotation` tables would
back with a B-tree/hash index, so the O(1)-lookup, O(depth)-walk cost characteristics carry
over; this is called out explicitly in the findings note rather than presented as a real DB
benchmark.

## Run it

```
uv run pytest docs/plan/spikes/E09-K01-harness/test_harness.py -q
```

No coverage gate applies (ticket "Test plan": harness-level only, archived not merged).
