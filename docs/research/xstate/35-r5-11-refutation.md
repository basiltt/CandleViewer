# R5-11 refutation — Receipt cannot distinguish no-op / guard-denied / unhandled-errored

Library: `main` @ 3ed3099 (unreleased 0.8.1). Repros: `triage-r5/t3_receipts.py` (as filed),
`triage-r5/t3b_refute.py`, `triage-r5/t3c_four.py` (added).

## Verdict: DOWNGRADE High -> Low

## What reproduces
`onUnhandled:"error"` + unknown event, async `send(wait=True)`:
`Receipt(changed=False, error=None, deferred=False)`. Confirmed.
Guard-denied event under the same policy: byte-identical receipt. Confirmed.
`interpreter.last_error` is `None` on both. Confirmed.

## What does not survive

**1. "Terminal and silent at the call site" / "surfaces one event late" — REFUTED.**
`_handle_unhandled_event` calls `_fail()` *inside* the macrostep, before the receipt
future resolves. At the awaiting call site, in the same expression:
`status == "error"` and `interpreter.error == UnhandledEventError(...)`.
A benign no-op leaves `status == "running"`. The discriminator is present at the
instant the receipt is read — nothing is deferred to a later send, and a caller
gating on `(receipt, status)` cannot act on a "clean receipt" in this path.

**2. "A guard that RAISED is absorbed under both policies" — REFUTED (API misuse).**
`guardErrorPolicy` is documented (`docs/api/index.md:63`) as *what a raising guard
is treated as*: `"false"` / `"true"` / `"raise"`. The prior artefact exercised only
`"false"` and `"true"` — the two values whose entire contract is to substitute a
result — and read the substitution as absorption. Under `"raise"`, the correct
setting for an OMS control path, the receipt carries the exception:
`changed=False, error=RuntimeError('guardboom')`, `last_transition_ok=False`,
`last_error` set. The cited battle result is a configuration artefact, not a defect.

**3. "#84 closes exactly one of the four cases" — REFUTED.**
Four-way matrix (`t3c_four.py`), receipt + `status` + `on_unhandled_event` hook:

| case | changed | error | deferred | status | hook disposition |
|---|---|---|---|---|---|
| real no-op (`ignore`) | F | None | F | running | `ignored` |
| guard-denied (`ignore`) | F | None | F | running | `ignored` |
| unhandled (`error`) | F | None | F | **error** | `errored` |
| deferred (`defer`) | F | None | **T** | running | `deferred` |

Three of four are separable without leaving the call site. The library also ships
`on_unhandled_event(..., disposition)` as the out-of-band correlated hook the
finding asserts "the library does not currently expose".

**4. `last_error is None` — documented, not a defect.** Its docstring scopes it to
per-step failures *reportable without a receipt* and gates it on
`last_transition_ok`. `UnhandledEventError` is surfaced via `status`/`.error`.
Coarse API surface; not a lost failure.

## Residue (the Low)
Real no-op and guard-denied are indistinguishable — identical receipt, identical
status, identical hook disposition (`ignored` / `errored` respectively, but the
*same* value within a given policy). This matches XState v5, where a transition
whose guard is false is by definition an unselected transition and the event is
unhandled; there is no upstream discriminator either. Impact is bounded because
the caller knows which event it sent and therefore whether a guard was in play.
Catalogue rule CV-C06 (§1.3b) already mandates treating `changed=False, error=None`
as inconclusive, so no shipped machine gates on it.

## Reason for severity
The High rested on silence at the call site, one-event-late surfacing, and guard
errors being absorbed. All three fail on re-run. What remains is a two-way
observability gap that is upstream-aligned and already covered by an existing
project rule: **Low**.
