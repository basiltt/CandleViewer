# R6-07 — adversarial refutation verdict

**Claim:** `machine_hash: None`/absent silently disables `from_snapshot()` drift
verification even under `verify_machine_hash=True`. Proposed: when
`version >= 1`, a missing `machine_hash` should raise `SnapshotCorruptError`.

**Verdict: DOWNGRADE High -> Low (robustness / defence-in-depth, not a
security control).**

## Reproduced

`probe_r6_gap_fields.py` re-runs clean at cec108b: `machine_hash -> None`
ACCEPTED, `machine_hash -> 'wrong'` -> `SnapshotDriftError`. The mechanism is
exactly `persistence.py:check_identity` — `if verify_hash and snap_hash is not
None:` keys the escape hatch on field presence, not on `snapshot["version"]`,
while `check_shape` never lists `machine_hash` as required. So the *factual*
core of the finding stands. `refutation/r607d.py` shows the one case with real
teeth: an id-preserving drift (a guard added to an existing transition) is
caught with the hash present and accepted silently with the hash dropped.

## Why the High severity does not survive

1. **The threat model is wrong; the hash is not an integrity control.** R6-07 is
   filed as security (fuzz "196/300 mutations silently accepted"). But
   `machine_hash` is an unkeyed structural fingerprint of the *machine*, not a
   MAC over the *payload*, and the library documents it as drift detection —
   "a guard was added, or a state was renamed since this snapshot was taken"
   (`docs/_guide/snapshots.md:259`), never as tamper resistance. Nothing in
   `snapshots.md`, `reliability.md` or `troubleshooting.md` claims snapshots may
   be read from an untrusted source.
2. **Against an attacker the proposed fix is worthless.** `refutation/r607.py`:
   - **B** — dropping `machine_hash` *and* setting `version: 0` is still
     accepted. `check_version` takes `snapshot.get("version", 0)` from the same
     attacker-controlled blob, so a version-keyed check is bypassed by editing
     one more key.
   - **C** — leaving `machine_hash` **correct** and rewriting `state_ids`,
     `configuration` and `context` restores a fully forged interpreter
     (`state_ids={'m.b'}`, `context={'pwned': True}`). The hash constrains the
     machine, never the state. An attacker who can edit the blob never needs to
     touch `machine_hash` at all.
   A control that an attacker bypasses by editing an adjacent key, and that is
   irrelevant to the highest-value forgery, cannot carry a High for
   "silently disables verification". Untrusted snapshots require a signature
   the library does not offer — that is a separate feature request, not this bug.
3. **The accidental-corruption case mostly fails loudly anyway.**
   `refutation/r607b.py`: with a real drift (state `b` renamed to `c`) and the
   hash dropped, restore raises `StateNotFoundError: Could not find state with
   ID 'm.b'` instead of `SnapshotDriftError`. Worse error, still refused. Only
   id-preserving drift (guard/action rename, delay change) restores silently.
4. **It is not documented-as-intended and not superseded.** The docstring says
   "Version-0 payloads carry neither field and are accepted unchecked", which
   *implies* v1+ carries both — so the v1-missing-hash path is genuinely an
   unconsidered gap rather than a stated contract. No closed issue covers it
   (#45 introduced the envelope; #110/#146 hardened `check_shape` and
   demonstrably did not add `machine_hash` to the required set). XState v5 has
   no analogue — `persistedSnapshot` carries no machine fingerprint at all — so
   there is no upstream agreement to cite either way.

## Residual, correctly scoped

Genuine and worth fixing at Low: a v1/v2 payload produced by this library always
contains `machine_hash` (`base_interpreter.py:1327`, unconditional), so a v>=1
snapshot lacking it is by construction not one this library wrote — the same
reasoning `check_shape` already applies to `status == "error"` with no `error`
message (#145). Adding `machine_hash` to `check_shape`'s required keys when
`version >= 1` is a two-line consistency fix that closes the
accidental-truncation path. It should be pitched as corruption detection, and
the docs should state plainly that snapshots must come from a trusted store.
