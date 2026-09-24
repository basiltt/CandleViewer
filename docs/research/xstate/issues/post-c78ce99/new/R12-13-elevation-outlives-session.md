# R12-13 — B16 elevation outlives the session (CONFIRMED, Blocker, OUR-CONTRACT-DEFECT)

Library: xstate-statemachine @ de2da4e (unreleased 0.8.1).
Repro: `repro/R12-13_elevation_outlives_session.py` — standalone (stdlib +
xstate_statemachine), run from neutral cwd `C:/Users/basil`, exit 0, both
engines (Interpreter / SyncInterpreter) and both action kinds (`def`,
`async def`), polled to convergence (5 x 10 ms per event).

## Result

| config | kill event | terminal states | still elevated |
|---|---|---|---|
| catalogue | REVOKE | auth.revoked + elevation.normal → **re-elevated by a later STEP_UP_OK** | yes |
| catalogue | LOGOUT / IDLE_DEADLINE / ABSOLUTE_DEADLINE | auth.revoked + **elevation.elevated** | yes |
| fixed (root hoist → final `elevation.dead`) | LOGOUT / IDLE_DEADLINE / ABSOLUTE_DEADLINE | auth.revoked + elevation.dead | no |
| fixed | REVOKE | auth.revoked + elevation.normal → re-elevated | **still yes** |

catalogue-fails 12/12 lanes; fixed-fails 3/12 (all REVOKE).

## Refutation checks — all fail to refute

- **Documented / API misuse?** No. Engine dispatch is correct: an event with no
  handler in a parallel region leaves that region untouched; `onUnhandled:
  defer` swallows it silently. Our catalogue chose both.
- **XState v5 / SCXML agree?** Yes — they agree *with the library*. SCXML
  microstep selection picks enabled transitions per parallel region
  independently; a region with no matching transition does not move. So the
  library behaviour is spec-correct and the defect is ours.
- **Duplicate?** Same root as C-04 / CV-C04 / CD-02 (and absorbs C-04b
  re-elevation, C-04c post-revoke STEP_UP_OK). R12-13 is the merged entry.
- **Measurement artefact?** No — deterministic across 24 lanes, two engines,
  no clock/timer involvement.
- **Trust boundary?** Not crossed. No `from_snapshot` input, no in-process
  Python injection; a plain sequence of ordinary events.

## Correction to the prescribed fix

The stated fix ("hoist the four revocation events to the B16 root targeting a
final `elevation.dead`, plus `audit_step_up` on the re-enter arm") is
**necessary but incomplete**: the existing `elevated.on.REVOKE →
elevation.normal` handler is deeper than the root and wins, so REVOKE lands in
`normal`, which still accepts `STEP_UP_OK` and re-elevates a dead session.
Landing C-04 must also **delete the region-level `REVOKE` handler in
`elevated`** (and add no `STEP_UP_OK` arm in `dead`, which `type: final`
already guarantees).

## Verdict

**CONFIRMED — Blocker, OUR-CONTRACT-DEFECT** (not a library defect; refuted as
such in round 10 and again here). Blocks B16 from the order path.
