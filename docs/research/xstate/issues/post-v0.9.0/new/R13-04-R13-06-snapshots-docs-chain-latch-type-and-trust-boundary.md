---
id: R13-04-R13-06
title: "Docs: snapshots.md states the chain latch survives a restart before saying it changes type, and doesn't flag chain_trips/last_chain_error as attacker-controllable in a replayed blob"
labels: [documentation, persistence]
severity: Medium
repro_script: null
commit: "v0.9.0 (91bd979)"
---

## Summary

We've pinned and adopted 0.9.0 and these two rows are two of the few
remaining items between "adopt with constraints" and "nothing open" — not a
defect, filed for tracking/docs so the trust boundary is written where a
reader will find it. `docs/_guide/snapshots.md` already documents both
underlying facts (the latch survives a restart, and restored fields are
part of the documented trust boundary at #205) — the two asks below are
about ordering and completeness of that existing prose, not about new
behaviour.

## Environment

`xstate_statemachine` v0.9.0 (tag `v0.9.0` = `91bd979`).

## Current state

Two bullets in `docs/_guide/snapshots.md`:

`snapshots.md:133` (⚠️ Important Limitations):

> "**The chain-trip latch DOES cross a restart** (0.9.0, #226) — `chain_trips`
> and `last_chain_error` are snapshot fields. A restored machine reports the
> same count and a `RestoredError` carrying the message; `clear_chain_error()`
> is still the only thing that clears it. Before #226 both reset to `0` /
> `None` on restore."

`snapshots.md:252` (envelope field reference):

> "**`chain_trips`** / **`last_chain_error`** *(#226)* — the sticky
> chain-trip signal (#222). Restored verbatim; the error comes back as a
> `RestoredError`. Absent in blobs written before 0.9.0, which restore to
> `0` / `None`."

Neither bullet mentions that `last_chain_error`'s type changes across the
round-trip (a live chain trip carries whatever exception type tripped it;
a restored one is always a `RestoredError`, which subclasses
`XStateMachineError` directly and **not** `RunawayChainError` —
`exceptions.py:212`). Neither bullet mentions that `chain_trips` /
`last_chain_error` are restored **verbatim**, with no authentication beyond
`machine_hash` (which checksums the machine definition, not the payload —
`snapshots.md:249`), so a forged value in a replayed blob (`chain_trips`
inflated or zeroed, an invented `last_chain_error` message) is accepted and
surfaces on a supervisor-alerting path.

## Observed behaviour

A reader who follows `snapshots.md:133` top-to-bottom is told the latch
"crosses a restart" — i.e., a supervisor written against a live machine
keeps working — *before* being told (nowhere, currently) that the object's
type changed underneath it. A supervisor guarding on
`isinstance(i.last_chain_error, RunawayChainError)` (the natural pattern
against #222's live-machine hierarchy) is silently `False` against a
restored one, and the doc bullet that introduces the restart-survival
behaviour gives no warning of that.

Separately, nothing in either bullet tells an operator that these two
specific fields — unlike, say, `context`, which the docs already describe
as attacker-shaped input — feed a supervisor-alerting signal and are
trust-boundary input from a replayed blob: a forged `chain_trips=999999` (or
an invented `last_chain_error` message) restores cleanly and can manufacture
a "work was discarded" page, or a forged `chain_trips=0` can suppress a real
one, with `machine_hash` providing no protection against either because it
never covers snapshot data.

## Expected behaviour

## Requested change

1. In the `snapshots.md:133` bullet, state the type change *before* (or in
   the same sentence as) the restart-survival claim, so a reader hits the
   caveat before they hit the reassurance.
2. In the `snapshots.md:252` envelope-field bullet, add one sentence noting
   that `chain_trips` / `last_chain_error` are restored verbatim with no
   integrity check beyond the definition-level `machine_hash`, and that a
   forged value in a replayed blob can manufacture or suppress a
   chain-trip alert — the same trust boundary #205 already documents for
   `context` et al., just not yet spelled out for these two fields.

Suggested replacement text for `snapshots.md:133`:

> - **The chain-trip latch survives a restart, but changes type** (0.9.0,
>   #226) — `chain_trips` and `last_chain_error` are snapshot fields. A
>   restored machine reports the same count, and the error comes back as a
>   `RestoredError` — which subclasses `XStateMachineError` directly, **not**
>   `RunawayChainError` — so `isinstance(i.last_chain_error,
>   RunawayChainError)` is `True` against a live chain trip and silently
>   `False` against a restored one. Guard on `chain_trips > 0` instead of
>   an `isinstance` check if the code must work across a restart.
>   `clear_chain_error()` is still the only thing that clears it. Before
>   #226 both reset to `0` / `None` on restore.

Suggested replacement text for `snapshots.md:252`:

> - **`chain_trips`** / **`last_chain_error`** *(#226)* — the sticky
>   chain-trip signal (#222). Restored verbatim; the error comes back as a
>   `RestoredError`. Absent in blobs written before 0.9.0, which restore to
>   `0` / `None`. Like every other restored field, these are accepted
>   verbatim from the snapshot with no integrity check beyond the
>   definition-level `machine_hash` above — a party who can write the blob
>   can set `chain_trips` to any value and `last_chain_error` to any
>   message. If these fields feed a supervisor-alerting path, treat a
>   replayed blob as capable of manufacturing or suppressing that alert,
>   the same as any other restored field (#205).

## Root cause analysis

N/A — documentation-completeness ask, not a code defect. `snapshots.md:133`
and `:252` are accurate as far as they go; they simply state the
restart-survival fact without the type-change caveat that sits two
paragraphs away in the same file's own migration-note prose, and without
cross-referencing the general trust-boundary statement that already
protects every other restored field.

## Impact

A reader following only the ⚠️ Important Limitations bullet (the section
whose entire purpose is to warn about restore surprises) can walk away
believing a live-machine `isinstance` check against the chain-trip error
keeps working after a restart-from-restore, when it does not. And nothing
in the envelope-field reference currently tells an operator wiring
`chain_trips` / `last_chain_error` into an alerting path that a replayed
blob is untrusted input for those two fields specifically, even though the
general trust boundary (#205) already covers them by omission.

## Proposed fix

Apply the two replacement bullets above (or equivalent wording) to
`docs/_guide/snapshots.md:133` and `:252`.

## Acceptance criteria

- [ ] `snapshots.md:133`'s chain-trip-latch bullet states the
      `RestoredError`/`RunawayChainError` type change before or alongside
      the restart-survival claim, and recommends `chain_trips > 0` over an
      `isinstance` check for code that must work across a restart.
- [ ] `snapshots.md:252`'s envelope-field bullet states that `chain_trips` /
      `last_chain_error` are restored verbatim with no integrity check
      beyond `machine_hash`, and that a forged value in a replayed blob can
      manufacture or suppress a chain-trip alert.
- [ ] Neither edit changes any runtime behaviour — this is a documentation-
      only change.

## Related

`R13-07` (design-constraint, not a defect) — the underlying type-change
behaviour itself is defensible design (JSON cannot carry a type, and the
`error` field already sets this precedent); this issue is only about doc
ordering. `R13-06` (design-constraint, not a defect) — the underlying
verbatim-restore-of-forgeable-fields behaviour is the documented trust
boundary (#205) working as intended; this issue is only about spelling it
out for these two fields specifically. `R13-03` — a related but distinct,
genuine defect where a *malformed* (not merely forged) `chain_trips` /
`last_chain_error` escapes the snapshot validator's error-type contract.
