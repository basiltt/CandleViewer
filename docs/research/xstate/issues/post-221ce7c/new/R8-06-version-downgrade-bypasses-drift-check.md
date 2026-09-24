# R8-06 — "#185 drift check is bypassable by version downgrade"

**Verdict: DOWNGRADE high → low** (security framing REFUTED; narrow robustness residue CONFIRMED)

Repro: `repro/persistence/r3_version_downgrade.py` (+ `r3b_equal_power.py`), both engines,
lib @ 6db65d8, default `verify_machine_hash=True`.

## Observed (both engines, reproduced verbatim)

snap hash `2a2bc6df958c1f67`, drifted machine hash `cb4e3010d02f7b77`, same id `acct`:

| payload | result |
|---|---|
| control (intact) | **REFUSED** `SnapshotDriftError` ✅ |
| `version=0` + hash removed | ACCEPTED → `JUMP` reaches `acct.c` |
| `version` key removed + hash removed | ACCEPTED → `JUMP` reaches `acct.c` |
| `version=0` + `hash=None` | ACCEPTED → `JUMP` reaches `acct.c` |

(The claim's own transcript shows async staying at `acct.a`; that is an artefact of not
awaiting. With `await asyncio.sleep(0.2)` async also reaches `acct.c`. The mechanism is
real on both engines — this correction strengthens the factual claim.)

Cause is as stated: `persistence.py:320-329` — `versioned = bool(version)`, and
`check_version` defaults a missing `version` to `0`.

## Why the security claim is refuted

`machine.structure_hash` is a **public, unkeyed, deterministic** SHA-256 prefix of the
machine definition (`persistence.py:120-126`). It is a checksum, not a MAC. `r3b_equal_power.py`:

```
structure_hash is public/unkeyed: cb4e3010d02f7b77
forged hash, version intact: ACCEPTED states=['acct.a']
```

An attacker who can edit the blob simply sets `machine_hash` to the **target** machine's
hash and leaves `version: 2` intact — accepted, no downgrade needed. The downgrade path
confers **zero** additional capability on the threat model the claim invokes ("the same
attacker-controlled JSON object edited by the same hand"). Against that hand the control
was never a barrier, before or after #185. So "the bypass survives verbatim" is true but
vacuous: there is nothing to bypass. Rating this *high* imports an integrity guarantee the
library never offered — `check_identity`'s docstring and the `SnapshotDriftError` message
both frame it as *"structure changed since this snapshot was taken… migrate the snapshot"*,
i.e. deploy-skew detection.

Note the adjacent #186 check does bite an inconsistent edit
(`state_ids=['acct.c']` → `SnapshotCorruptError`), but that is a coherence check, not auth.

## Why a residue survives (and why it is low)

#185's own rationale is **non-adversarial**: *"lost in transit (a JSON round-trip that drops
nulls, a column default, a lossy migration)"*. The fair question is whether such a transport
also loses `version`. It plausibly can — the mechanism that strips an optional/null key
strips both, and a numeric column defaulting to `0` yields exactly `version=0`. In that case
the pre-#185 silent-accept returns for the very scenario #185 was written to close. That is a
genuine, narrow gap — but:

- It requires a **correlated** loss of two independent keys, where #185 addressed loss of one.
- The unchecked-`v0` path is a **deliberate back-compat contract**: genuine 0.7.x snapshots
  carry neither `version` nor `machine_hash` and must still restore. Any tightening
  (e.g. refusing v0 under `verify_hash=True`) breaks every legacy payload — the constraint
  #185 explicitly preserved, and the reason the discriminator has to live *somewhere* in the
  same payload. There is no in-band field that a lossy transport cannot equally lose;
  a real fix must be out-of-band (caller passes the expected hash / pins
  `minimum_version`), which is an API addition, not a bug fix.
- A documented explicit opt-out (`verify_machine_hash=False`) already exists for the
  known-compatible case.

## Recommendation (enhancement, not defect)

Optional `from_snapshot(..., expected_machine_hash=...)` or `minimum_version=1`, so callers
whose store never holds 0.7.x blobs can refuse the downgraded shape out-of-band. Worth a
docstring note on `check_identity` that the v0 path is unchecked **by design** and that
`structure_hash` is a checksum, not an authentication tag — the current #185 comment's
security-flavoured tone ("the bypass") invites exactly the over-reading this finding made.
