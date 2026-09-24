# R10-C3 — Adversarial refutation: B19 `stale_lockout` has no operator escape hatch

**Library:** `19cb1f1` (unreleased 0.8.1; `__version__` still `0.8.0`).
**Verdict: DOWNGRADE High → Medium.** The failing symptom reproduces exactly;
the *stated cause* ("clearable only by an event the operator cannot produce")
is factually wrong. A real but smaller contract defect survives.

## Reproduction (standalone, neutral cwd `C:/Users/basil`, both lanes)

`r10c3/r10c3_repro.py` and `r10c3/p2.py` — stdlib + `xstate_statemachine`
only, inline helpers, polled to convergence (5 stable samples / 20 ms,
≤3 s budget), run for `async def` **and** plain `def` services.

| Probe | async | def |
|---|---|---|
| ladder reaches `stale_lockout` (3 failures, 4 fetches) | yes | yes |
| `OPERATOR_RESOLVED` in `stale_lockout` | `deferred=1`, state unchanged | identical |
| `RECONNECTED` + venue up | → `reconciliation.idle`, `reset_failures` ran, `consecutive_failures=0` | identical |
| `RECONNECTED` + venue still down | → `backing_off` (retry ladder) | identical |
| 8× `OPERATOR_RESOLVED` presses | `deferred` 1→8, never drains | identical |

Convergence-polled, so **not** the R9-03 sampled-before-convergence pattern.
The engine is behaving correctly throughout: `onUnhandled:"defer"` on an
undeclared event in the active state is exactly the configured policy.

## Refutation attempts

- **API misuse?** No. `strict:true` accepts `OPERATOR_RESOLVED` only because
  `divergent` declares it; deferral in `stale_lockout` is the declared policy.
- **XState v5 / SCXML disagreement?** None. SCXML §3.13 external-queue
  deferral and XState v5 unhandled-event semantics both give this result.
  Correctly classed OUR-CONTRACT-DEFECT, not a library defect.
- **Measurement artefact?** No — polled to convergence, stable, both lanes.
- **Duplicate of a closed issue?** No; it is a catalogue defect, not a
  library issue.
- **Documented?** Yes — and this is where the finding breaks. Catalogue
  §B19.7 **INV-B19-b** reads: *"`stale_lockout` locks the account for new
  orders and is cleared only by `OPERATOR_RESOLVED`."* The shipped
  `B19.machine.json` declares only `RECONNECTED`. So the contract and its
  own normative invariant disagree.

## Why the severity is wrong

The finding's cause claim is **"clearable only by an event the operator
cannot produce."** Measured: `RECONNECTED` is an ordinary external event.
Nothing in the engine, the contract, or the interpreter restricts its
source — an operator console can send it exactly as it sends
`OPERATOR_RESOLVED`. The probe drives `RECONNECTED` from the same call site
and the lockout clears cleanly in both lanes, with `reset_failures` applied.
**A critical account-locked state is therefore not unescapable.** The
High rating rested on an unescapable-lockout reading that does not hold.

## What genuinely survives (Medium)

1. **Contract/invariant mismatch.** INV-B19-b names `OPERATOR_RESOLVED`;
   the JSON implements `RECONNECTED`. One of the two must change — this is
   a real, fixable catalogue defect, and conformance tooling keyed on
   INV-B19-b will keep failing until it is.
2. **Semantic conflation.** `RECONNECTED` is a *connectivity* signal. Using
   it as the operator acknowledgement for an account lockout means an
   automatic reconnect can silently clear a critical, paged state with no
   operator in the loop and no distinct audit record — an OMS controls
   concern, but a smaller one than "no escape".
3. **Escape is conditional on the venue.** With the venue still down,
   `RECONNECTED` lands in `backing_off` and the ladder returns to lockout;
   there is no unconditional operator acknowledgement arm.
4. **Deferred events never drain** (1→8 across presses, still 8 after the
   escape to `idle`, since `idle` does not declare `OPERATOR_RESOLVED`).
   Unbounded growth under repeated operator pressing — track separately.

## Recommended fix (unchanged in substance, lower priority)

Add to `stale_lockout.on`:
`"OPERATOR_RESOLVED": {"target": "#reconciliation.idle", "actions":
["reset_failures", "audit_lockout_cleared"]}` — which restores INV-B19-b,
separates the operator acknowledgement from the connectivity signal, and
stops the deferral accumulation on the pressed event.

**Verdict: DOWNGRADE to Medium.** Symptom CONFIRMED; stated cause REFUTED
(`RECONNECTED` is operator-producible and does clear the lockout); residual
defect is contract/invariant divergence plus audit conflation.
