# R9-05 adversarial refutation — snapshot authentication

Re-ran on f28719c:
- `battle-f28719c/persistence/r2_readside_matrix.py` part 2: 8/9 mutations refused; `state_ids forged m.b` -> ACCEPT `['m.b']` (relocated).
- `r3_version_downgrade.py`: 3/3 downgrade forms (version=0, version key removed, version=0 + hash=None) ACCEPTED into the drifted machine, `['m.a']` -> JUMP -> `['m.c']`; control intact -> SnapshotDriftError.

Refutation checks:
- **Documented?** Yes for the downgrade half: `persistence.check_identity` docstring states v0 payloads "are accepted unchecked -- by design"; #185 is explicitly keyed on the *declared* version. Behaviour is intended, not a defect.
- **API misuse?** No library API offers snapshot authentication; there is no correct usage that closes it. Remedy is wrapper-side only.
- **XState/SCXML?** XState v5 `createActor({snapshot})` likewise treats persisted snapshots as trusted input; SCXML has no persistence/authentication model. No divergence.
- **Internal-consistency rules (#186/#198)** are integrity-of-shape, never authenticity — confirmed by the forged-`state_ids` cell that is internally consistent and accepted.

Conclusion: real and reproducible, but a design constraint with a trusted-input precondition (attacker must already write the snapshot store). Severity reduced to **medium**; wrapper obligation unchanged: HMAC-tag control-plane snapshots and reject `version < 1` before calling restore.
