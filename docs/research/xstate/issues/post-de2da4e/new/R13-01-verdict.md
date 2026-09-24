# R13-01 — drain_pending() drops the async priority lane — VERDICT: CONFIRMED (High)

## Claim
`Interpreter.drain_pending()` (interpreter.py:1715) reads only `self._event_queue`,
never `self._priority_queue` (interpreter.py:374). Documented as "every
accepted-but-unprocessed event". Sync engine returns all of them.

## Refutation attempts — all failed
1. **"Restore-only / snapshot artefact"** — REFUTED. New probe
   `probes/v0.9.0/p8b_drain_live.py` reproduces with **no snapshot at all**:
   a live started interpreter, run loop parked in a slow action, two
   `send()` and two public `send_priority(wait=False)` calls.
   `pending_events` -> `['P1','P2','I1','I2']`; `await drain_pending()` ->
   `['I1','I2']`; LOST `['P1','P2']`, still sitting in the lane afterwards.
2. **"Private-attribute poking"** — REFUTED. p8b uses only public API:
   `start/send/send_priority/pending_events/drain_pending/stop`.
   `send_priority` is public (interpreter.py:1051).
3. **"Documented behaviour"** — REFUTED. Docstring (interpreter.py:1716),
   `docs/api/index.md:717`, `docs/_guide/interpreters.md:212`,
   `docs/_guide/snapshots.md:299` and `README.md:1632` all say *every* /
   *every pending* event. No doc anywhere mentions a lane exclusion. The
   sibling read-only view `pending_events` (base_interpreter.py:2334 ->
   `_snapshot_pending_events`, interpreter.py:1675) deliberately DOES include
   the lane (#107 comment: omitting it "lost the deadline ... with no trace"),
   so the two documented durability views contradict each other.
4. **"Harmless — events stay queued"** — REFUTED, and this makes it worse.
   `_teardown()` (interpreter.py:1635) executes `self._priority_queue.clear()`.
   The documented shutdown recipe `drain_pending()` then `stop()` therefore
   **permanently destroys** the lane contents. Not a visibility bug: data loss.
5. **"XState v5 / SCXML disagree"** — N/A. No upstream analogue; `drain_pending`
   is a library-local durability API, judged against its own stated contract.
6. **"Trust boundary"** — not crossed. Documented public API, documented use
   case (durable shutdown), correct usage, wrong result.
7. **Duplicate** — no. Distinct from #107/#214/#233 (all snapshot/restore
   paths, all fixed); those fixes are precisely what turned this into an
   *engine-divergent* bug (sync drains all four, async two).

## Blast radius
The priority lane carries fired `after` timers and invoke completions
(`_deliver_priority`, interpreter.py:2498) plus all `send_priority()` traffic —
i.e. deadline and completion work — exactly the events an OMS shutdown must not
drop.

## Severity: High (retained)
Silent, permanent loss of accepted work on the documented durable-shutdown path;
public API, default config, both `def` and `async def` logic irrelevant (engine-level).
Not Critical: a correct alternative exists and is already the recommended
Option B in `docs/_guide/snapshots.md`.

## Mitigation (unchanged)
Persist with `get_persisted_snapshot()` / `get_snapshot()` (these use
`_snapshot_pending_events` and include the lane), then `stop()`.
Never use `drain_pending()` on the async engine for durability.

## Suggested fix
`drain_pending()` should pop `_priority_queue` first, then the inbox —
matching `_snapshot_pending_events()` ordering and the sync engine.
