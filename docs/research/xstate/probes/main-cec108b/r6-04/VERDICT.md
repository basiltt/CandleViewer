# R6-04 refutation — `send_threadsafe(internal=...)` — DOWNGRADE Blocker -> Low

Commit cec108b. Probes: `p4b.py`, `p4c.py`, `p4d.py` (this dir); originals reproduced first.

## Reproduced as claimed
`p4_forge_internal.py`: honest 5 accepted / 45 refused; `internal=True` 5000 accepted / 0 refused.
`p3_threadsafe.py` [1]: `internal=False` from an action -> 200 hits, budget 20 not tripped.

## Direction A ("True bypasses the bounded inbox") — not a privilege escalation
`p4b.py`: an action copies its `contextvars` context into a worker thread (the
path the docstring and `docs/api/index.md` both name) and calls `send_threadsafe("X")`
with **no flag**: 500 accepted, 0 refused, inbox bound 2 + RAISE. The bypass is a
property of *self-sends*, not of the flag — self-sends go to the internal queue,
which is unbounded by design (SCXML internal lane). `internal=True` only reproduces
what the classifier already grants; it confers nothing extra.

Nor is it unaccounted: `p4d.py` — 5000 forged `internal=True` sends land in the
internal queue, `_raise_depth` reaches 5000, and on release the chain budget trips
with a loud `ERROR ... Exceeded 1000 chained self-raised events`, plugin
`on_event_dropped(reason="chain_budget")`. "No diagnostic" is false.

## Direction B ("False dodges maxIterations") — documented, and harm-free
The docstring states `False` forces external accounting; `maxIterations` exists to
stop an action re-raising its own trigger *without yielding* (CHANGELOG rationale:
"starving the entire asyncio loop"). `p4c.py`: 400 self-retriggers via
`internal=False` with `max_iterations=20`; a 10 ms heartbeat still ran **62 times
in 1 s** (normal). External accounting routes each event back through the inbox and
the loop yields between them, so the starvation the budget guards against does not
occur. Opting out trades a chain cap for fair scheduling — the safe direction.

## Remaining, minor
`internal=True` from a foreign thread can grow the unbounded internal queue without
backpressure (5000 entries retained until the loop drains). Same exposure as any
genuine self-send; in-process caller, no trust boundary crossed. Doc nit: neither
the docstring nor the API table says self-sends are exempt from `max_queue_size` /
`OverflowPolicy`.

Not refuted outright (the doc gap is real), but the Blocker rationale — "fails open
in both directions, both reachable with no diagnostic" — does not survive: A is
reachable without the flag by the documented route and is loudly capped; B is
documented and demonstrably does not starve the loop.

**Verdict: DOWNGRADE to Low (documentation).**
Unrelated live issue seen in `p3_threadsafe.py` [3]: `_threadsafe_self_sends_in_flight`
leaks 5 after loop stop — track separately, not part of R6-04.
