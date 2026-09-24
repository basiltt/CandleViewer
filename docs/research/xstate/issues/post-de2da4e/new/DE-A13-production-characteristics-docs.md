---
id: DE-A13
title: "Docs: two production facts not yet written down — the ensure_future escape hatch's real precondition, and chain_trips' process-locality"
labels: [documentation, docs, persistence, severity/low]
severity: Low
repro_script: null
commit: de2da4e
verified: true
---

## Summary

This is from our "make it perfect" list after twelve rounds of adoption
review: the library is adopted and running, and these are the few items
left between *adopt with constraints* and *nothing open*.

Two facts about production behaviour that we had to derive ourselves are
not stated in the docs. Both are small additions to pages that already
exist and already cover the surrounding material well.

**We want to correct our own earlier framing.** We had drafted this as
"three undocumented facts", including the `from_snapshot` trust boundary.
On checking the tree at `de2da4e`, that one **is** documented, and
thoroughly — `docs/_guide/snapshots.md:247` states plainly that
`machine_hash` is "a **checksum against accidental drift, not an
authentication tag** (#205)", explains that anyone with the config can
compute it, and gives the `minimum_version=1` +
`expected_machine_hash=` recipe; `docs/api/index.md:726` repeats the
trust-boundary framing in the API table. We were wrong; that item is
withdrawn, and we're noting the withdrawal rather than quietly dropping it.

## Current state

### 1. The `ensure_future` escape hatch's precondition is unstated

`docs/_guide/interpreters.md:519` documents the idiom as unconditionally
safe:

```python
fut = asyncio.ensure_future(i.send("GO", wait=True))  # fine: awaited elsewhere
```

and `CHANGELOG.md:28` says "The receipt can still be handed out
(`asyncio.ensure_future(i.send(..., wait=True))`) and awaited later; only
the in-step await is refused."

Neither statement carries the actual precondition. Because
`_ACTIVE_ACTION_OWNER` is a `ContextVar` and `ensure_future` copies the
current context, the spawned task inherits the owner for its whole life —
so the idiom works only when the spawning action **returns without
awaiting again**. Add one `await` after the `ensure_future` line and the
same code raises `ReentrantWaitError`. We've filed the behaviour itself
separately (see Related); this item is only about the docs, and it stands
regardless of how the code question is resolved — if the guard is
narrowed, the docs should say so; if it stays, the precondition needs
stating.

### 2. `chain_trips` / `last_chain_error` are process-local

`#222`'s sticky-supervision API is well documented as a *live* signal:
`docs/_guide/production-characteristics.md:97`, `docs/_guide/plugins.md:335`
and `docs/api/index.md:743` all describe the latch, the monotonic counter,
and why `last_error` is the wrong thing to poll. All correct.

What no page says is that neither field is a snapshot key. A process that
trips the guard, is snapshotted, and restarts comes back reporting
`chain_trips == 0` and `last_chain_error is None`. The docs are strong on
"don't poll `last_error`, poll the latch" and silent on "the latch does
not cross a restart" — which is the boundary a supervisor is most likely
to be watching across.

Note the contrast the docs already draw well for timers:
`snapshots.md:132` is explicit that "Timers are NOT resumed by default"
and names the opt-in. The same one-sentence treatment for the chain-trip
latch is all that's missing.

## Requested change

1. **`docs/_guide/interpreters.md`**, at the `ensure_future` example
   (~line 519): state the precondition next to the "fine: awaited
   elsewhere" comment — that the spawning action must return without
   further awaiting, because the task inherits the action's context — and
   give `contextvars.Context().run(...)` as the shape for a helper that
   outlives its action and must talk back to the machine. Mirror the same
   caveat in the `#219` CHANGELOG entry.

2. **`docs/_guide/snapshots.md`**, in the "what a snapshot does not carry"
   list that already covers services and timers: one bullet — the
   chain-trip latch and counter are runtime-only; a restore resets them to
   `0` / `None`; capture them before `get_persisted_snapshot()` if your
   supervisor needs them to survive a restart. A cross-reference from
   `production-characteristics.md:97` would close the loop.

## Acceptance criteria

- `interpreters.md`'s `ensure_future` example carries the precondition
  inline (not in a footnote), and shows the fresh-context alternative for
  a long-lived helper.
- The `#219` CHANGELOG entry's escape-hatch sentence is qualified to
  match, so a reader upgrading from the changelog alone gets the same
  information.
- `snapshots.md` states that `chain_trips` / `last_chain_error` are not
  snapshot fields and reset on restore, in the same list that documents
  dormant services and timers.
- `production-characteristics.md`'s §2 chain-trip paragraph links to it.

## Verification

Every claim in this issue was checked against the tree at `de2da4e`:

- `docs/_guide/interpreters.md:519` — the `ensure_future` example and its
  "fine: awaited elsewhere" comment, with no precondition stated. Confirmed
  present.
- `CHANGELOG.md:28` — the escape-hatch sentence, quoted verbatim above.
  Confirmed present.
- `docs/_guide/snapshots.md:247` — the `machine_hash` trust-boundary
  paragraph, which is why fact 1 of our earlier draft is **withdrawn**.
  Confirmed present.
- `docs/_guide/snapshots.md:131-132` — the dormant-services and
  dormant-timers bullets, i.e. the list the new chain-trip bullet belongs
  in. Confirmed present; neither mentions `chain_trips`.
- `docs/_guide/production-characteristics.md:97`,
  `docs/_guide/plugins.md:335`, `docs/api/index.md:743` — all three
  document the live latch; a full-tree grep for `chain_trips` across
  `docs/` returns no statement about snapshot behaviour.
- The process-locality itself is demonstrated by the repro on our
  chain-trip-latch issue (see Related), which shows `(2,
  'RunawayChainError')` live and `(0, None)` after restore on both
  engines, with neither key present in the v3 envelope.

## Related

- Our `ensure_future` / `ReentrantWaitError` issue this round — the code
  question behind doc item 1; **noted on `#219` in an earlier round and
  promoted to its own issue for tracking**.
- Our chain-trip-latch-persistence issue this round — the behaviour behind
  doc item 2; **noted on `#222` in an earlier round and promoted to its own
  issue for tracking**. If that one is fixed by persisting the latch, this
  doc bullet becomes "restored as of 0.8.x" instead.
- `#205` — the trust-boundary thread whose documentation we confirmed
  complete.
- Our adoption audit (#26).
