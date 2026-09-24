# Independent recheck: #198, #199, #200, #201 (main @ f28719c)

Full suite: `tests/test_round8_findings.py` -> 29 passed.
Targeted subset (198/199/200/201 classes only): 9 passed.

## #198 (persistence.py:216-249)
Versioned (`version>=1`) running snapshot now requires both `configuration`
and `state_ids` non-empty; v0 (no version key) still accepts `state_ids`-only.
Verified: emptied `state_ids`, dropped/emptied `configuration`, and outright
contradiction all raise `SnapshotCorruptError` on both engines; legacy v0
blob still restores. No false positive — logic reads exactly as claimed.

## #199 (interpreter.py:599-604, sync_interpreter.py:370-374)
In-flight flag (`_processing` / `_is_processing`) raised before
`on_interpreter_start` fires, cleared in `finally`. Verified a plugin
grabbing a snapshot inside the hook gets `SnapshotMidStepError` on both
`SyncInterpreter` and `Interpreter`, then a snapshot taken after `start()`
returns has non-empty `state_ids`.

## #200 (interpreter.py:2752-2779)
Ledger switched from bare counter to `_chain_owed_tasks: Set[Task]`,
discarded via `task.add_done_callback`, so it self-clears on ANY terminal
outcome including a bare `BaseException` neither `Exception` nor
`CancelledError`. Verified: (a) a service that raises a custom
`BaseException` subclass leaves `_chain_owed == 0` after settle for both
`def`/`async def`; (b) two concurrent invocations keep independent debts —
the fast one's completion doesn't zero the slow one's still-open debt.

## #201 (interpreter.py:648-660, 1643)
Initial-descent completions/raises are seeded (not charged as chain links)
by resetting `_raise_depth` to 0 and re-tagging the priority queue as
non-self-generated right after the initial macrostep settles, matching the
sync engine's "user standing" seed rule (#77). Verified ping-pong invoke
chains from the initial state hit the SAME lap count as previously
mismatched (off-by-one) case, for both limits tested (3, 20).
Documented asymmetry (sync engine doesn't re-arm a rolled-back invoke in
the same drain and raises `RuntimeError` instead of `RunawayChainError`)
is stated as a known non-parity, not silently swept — acceptable.

## Verdict
No stale/false-positive tests, no matrix cell skipped (both engines, both
service kinds exercised where relevant). All four fixes reproduce and
resolve as documented.
