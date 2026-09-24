# R12-02 "v2 upcast mints engine provenance" — REFUTED

**Claim.** An attacker-controlled snapshot declaring `"version": 2` gets
`engine: true` / `_EngineAfter` / `_EngineDone` stamped by `persistence.upcast`
(`if version < 3:`), letting a hand-written `after.*` / `done.invoke.*` record
drive a transition that v3 correctly refuses. Proposed severity: Blocker.

**Reproduced.** Yes — `out_r12_02_equiv.txt` row A: a forged v2 blob fires the
600 s `after` immediately (`fired=1`, `vict.expired`) on BOTH engines, even
under `strict: True` + `onUnhandled: "error"`; row C (identical record at v3) is
inert. The mechanism is exactly as described.

**Why it is not a defect.**

1. **No privilege is gained.** Row B: a plain **v3** blob with *no* forged
   record, in which the attacker simply writes `configuration: ["vict.expired"]`
   and `context: {"fired": 1}`, reaches the *identical* observable outcome on
   both engines. `from_snapshot`'s docstring states this verbatim: *"A snapshot
   is TRUSTED INPUT: its `state_ids` / `configuration` and `context` are applied
   verbatim … `machine_hash` is a fingerprint of the machine's structure, not a
   MAC … a party who controls the whole blob can write a consistent one."* An
   adversary who can set `version` can equally set `configuration`. The v2
   upcast therefore reaches no state that was not already reachable.

2. **The proposed mitigation is inert, which proves the point.** Row B′:
   `minimum_version=3` refuses the forged v2 blob (row A′) but does nothing to
   the v3 verbatim write, which still lands in `vict.expired`. A "fix" that
   leaves the equivalent outcome fully available is evidence the boundary — not
   the upcast — is what is doing the work.

3. **The behaviour is documented and deliberate.** CHANGELOG #214 and the
   `upcast` comment state the rule: a v2 writer had exactly one minter of
   `done`/`error`/`after` records, so such a record *is* an engine completion;
   the alternative (demoting it to inert user traffic) silently drops genuine
   0.8.0-era `after` deadlines under #203's gate. This is a migration
   correctness choice about *trusted* legacy payloads.

4. **Same pattern as R10-01 / R11-01.** In-process Python + a trust boundary the
   docs draw explicitly, with the authentication step (HMAC / signed envelope)
   named as the caller's job.

**Verdict: REFUTED** (trust boundary not crossed; documented; no escalation over
plain verbatim restore). Merged sources D11-fuzz-1, D11-semantics-1, R11-01 fall
with it. Residual, non-defect: worth a note in adoption guidance that
`minimum_version=3` is hygiene, not a security control.
