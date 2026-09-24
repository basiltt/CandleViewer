# R11-01 — "v2 upcast mints engine provenance onto attacker records" — REFUTED

Behaviour reproduced exactly as reported (probes/main-c78ce99/p3_214_v2_upcast_forge.py,
neutral cwd C:/Users/basil): v3 forged `after`/`done` records inert; same blob with
`"version": 2` -> `vault.open` / `pay.paid`, TIMER_FIRED / ONDONE_FIRED True.
So the mechanism is real; the *finding* is not.

## Why it is not a defect

1. **No trust boundary is crossed (the R10-01 pattern).** `from_snapshot` takes
   trusted input *by contract* — stated in the docstring, `docs/api/index.md`
   (#205 paragraph), `docs/_guide/snapshots.md` and CHANGELOG #205:
   "`state_ids`/`configuration` and `context` are applied verbatim … the checks
   are not authentication; `machine_hash` is a fingerprint, not a MAC."
2. **The "privilege" grants nothing the payload did not already have.**
   Control probe: leaving `version` at 3 and rewriting `state_ids` to
   `["vault.open"]` restores directly into the target state — no forgery, no
   downgrade, strictly more power than minting one timer record. An attacker who
   can edit `version` can edit `configuration` and `context`.
3. **The documented mitigation works and is version-aware.**
   `from_snapshot(..., minimum_version=3)` -> `SnapshotVersionError` on the forged
   blob (verified). `expected_machine_hash` accepts it, exactly as documented —
   a fingerprint is not a MAC; authentication belongs outside the library.
4. `#214`'s upcast comment is about *library-written* v2 blobs, and is true of
   them. Nothing in #212's new timer rule changes this.

## Residual (Low, doc-only, not filed as a blocker)

`minimum_version` defaults to 0; the snapshot guide names `minimum_version=1` as
the anti-downgrade floor, written before v3 provenance existed. Suggest the guide
say **3** now, so the provenance flags cannot be re-derived by downgrade. Pure
hardening advice inside an already-trusted boundary.

**Verdict: REFUTED** (documented trust boundary + working mitigation; optional Low doc nit).
