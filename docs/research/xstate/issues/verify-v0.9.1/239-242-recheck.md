# Independent recheck: #239-#242 (v0.9.1 @ 801eacd)

Env: fresh standalone repros (stdlib + xstate_statemachine only), run from
neutral cwd `C:/Users/basil`, against
`.venv-main` (source checkout = tag v0.9.1 payload, HEAD 801eacd is a
docs-only merge commit ahead of the fix commit 5c3b25b / tag 45bb7f3).
`tests/test_round13_findings.py` (24/24 pass, both engines where relevant).

## #239 | FIXED | drain_pending() now drains priority lane + inbox, priority-first, and fails wait=True receipts on drained events
Standalone repro: parked run loop mid-action, queued one inbox event and
one `send_priority()` event. `drain_pending()` returned both
(`['P1','I1']`, priority first), `pending_events` was empty afterward.
Confirms the fix note in the source and matches
`TestDrainPendingCoversPriorityLane` in the pinned test file. No false
positive found (old code would have returned `[]`/lost the priority item;
new code returns the correct set/order).

## #240 | FIXED | on_interpreter_start fires exactly once on every restore path, tagged resume vs boot
Standalone repro covered: fresh boot (`start:boot`), sync restore via
`from_snapshot(...plugins=[p])`, and async restore with
`restart_services=True`. All three produced the documented
`start:boot`/`start:resume` sequence with a trailing single `stop`, and
`interpreter.restored_from_snapshot` correctly reported `True`/`False`.
No double-fire observed.

## #241 | FIXED | malformed chain_trips / last_chain_error raise SnapshotCorruptError, not raw ValueError/TypeError
Standalone repro exercised 8 cases: `chain_trips` as non-numeric string
("NaN"), list, dict, negative int, and `bool` (explicitly rejected per
docstring even though `bool` is an `int` subclass) — all 5 raised
`SnapshotCorruptError` as required. Numeric string `"3"` was correctly
*accepted* and coerced to `int` (sanity check against over-rejection).
`last_chain_error` as list/dict also raised `SnapshotCorruptError`. No
stale-script false negative: every malformed-shape case in the CHANGELOG
description was reproduced and correctly rejected.

## #242 | FIXED | docs (not code): snapshots.md documents the chain-latch trust boundary
This is a documentation issue, not a code fix — verified textually.
`docs/_guide/snapshots.md` line 254 states the "Trust boundary (#205,
#242)" paragraph verbatim: restored `chain_trips`/`last_chain_error` are
accepted with no integrity check beyond `machine_hash`, and a party who
can write the blob can manufacture or suppress a chain-trip alert. Line
135 also cross-references the restart-safe guard recommendation
(`chain_trips > 0`) in the same sentence as the latch's type change, as
the CHANGELOG entry claims. No code repro applicable/needed.

## Summary
All four (#239, #240, #241, #242) are genuinely closed in v0.9.1 (801eacd).
No false positives (over-claimed fixes) or false negatives (stale-script
misses) found in this independent recheck.
