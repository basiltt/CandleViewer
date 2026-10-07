---
r9: R9-05
severity: Medium
verified: true
build: f28719c
relates_to: [185, 186, 198]
labels: [documentation, enhancement, severity/medium, persistence]
repro: new/repro/R9-05_snapshots_are_unauthenticated.py
---

# Snapshots are unauthenticated: a consistent `configuration`/`state_ids` forgery relocates the machine, and a `version: 0` downgrade bypasses the #185 drift check

**Severity (ours):** Medium (design constraint / documentation ask, not a code defect)
**Build:** `main` @ `f28719c` (merge of PR #202, unreleased 0.8.1; `__version__` still reports `0.8.0` — keyed on the commit)
**Environment:** CPython 3.13.7, Windows 11, fresh venv
**Relates to:** #185, #186, #198 — narrower than claimed: those closed the *shape*-integrity holes, not authenticity, and a caller who reads the docstrings that way may over-trust the result.

---

## Summary

Filing this as a **documentation and API-affordance request, not a bug report.** Our own first pass had it as High; refutation moved it down, and we want that read up front.

Two observations, both reproducible, both documented as intended:

1. **A consistent forgery relocates the machine.** `state_ids` outranks `configuration` when the two are forged *together and consistently*. A mutation matrix against a restored blob mutates it nine ways; eight are refused (#186/#198 working), and the ninth — an internally-consistent `state_ids: ["m.b"]` + matching `configuration` — relocates the machine.
2. **A `version: 0` or absent-`version` downgrade bypasses the #185 drift check.** Three downgrade forms (`version=0` + hash removed, version key absent + hash removed, `version=0` + `hash=None`) all restore into a **drifted** machine and accept an event (`JUMP`) the honest machine never declared, while the intact control correctly raises `SnapshotDriftError`.

## Why we are not calling this a defect

- `check_identity`'s own docstring (`src/xstate_statemachine/persistence.py:306-337`) states plainly: *"Version-0 payloads (no `version` key) carry neither field and are accepted unchecked — they cannot be drift-checked, which is precisely why the fields exist."* The bypass is documented, not accidental.
- #186/#198 are **shape-integrity** checks (configuration/state_ids agreement), not authenticity checks, and they do their job: eight of nine mutations refused in our matrix.
- **XState v5's `createActor({snapshot: ...})` likewise trusts a persisted snapshot with no signature or authentication step** — restoring is documented as a trust operation on the caller's own persisted state, not a defence against a tampered one. SCXML specifies no persistence model at all. There is no divergence from a comparable implementation to cite.
- Exploitation presupposes write access to the snapshot store, i.e. trusted input, by construction.

So there is no correct-usage fix *inside* the library, and we are not asking for one.

## What we would find genuinely useful

Two small API affordances that would let a wrapper express its own trust policy without re-implementing restore:

- **`minimum_version=` on `Interpreter.from_snapshot()`** — so a caller can refuse `version < 1` declaratively instead of pre-parsing the blob.
- **`expected_machine_hash=`** — so the caller supplies the hash rather than trusting the one inside the payload it is validating.

And one docstring correction that would have saved us a round: note that `structure_hash` / `machine_hash` is a **checksum, not an authentication tag** — it detects accident (a stale or corrupted blob), not an adversary who controls the whole payload including the hash field. That distinction is currently easy to misread as offering more safety than it does.

## Minimal reproduction

`R9-05_snapshots_are_unauthenticated.py` (attached; stdlib + `xstate_statemachine` only, run from a neutral cwd). Two standalone demonstrations inlined from the round-9 evidence scripts (`r2_readside_matrix.py`, `r3_version_downgrade.py`): (1) a consistent `state_ids`/`configuration` forgery relocates the restored machine; (2) three version-downgrade forms all restore into a structurally drifted machine and then accept `JUMP`, an event the honest machine never declared. Exits 1 while the documented-as-intended behaviour is present.

## Observed (fresh run)

```
1. consistent forgery -> ACCEPTED, leaves = ['m.b']
2. version absent + hash removed -> ACCEPTED into DRIFTED machine, after JUMP = ['m.c']
2. version=0 + hash removed -> ACCEPTED into DRIFTED machine, after JUMP = ['m.c']
2. version=0 + hash=None -> ACCEPTED into DRIFTED machine, after JUMP = ['m.c']

VERDICT: DOCUMENTED BEHAVIOUR STILL PRESENT
```
Exit code: 1.

## Expected

Per the library's own contract (`persistence.py:306-337`, quoted above) this is the documented behaviour, not a violation — restated here only to make the affordance ask concrete: with `minimum_version=1` a caller could get `SnapshotVersionError` instead of a silent accept-into-drift, and with `expected_machine_hash=` a caller-supplied hash would not need the payload's own (attacker-controlled) `machine_hash` field to agree with itself.

## Root cause

`src/xstate_statemachine/persistence.py:344-352`: `versioned = bool(version)` and the function early-returns (no check) when a v0 (absent or zero) payload carries no `machine_hash` — so *omitting* the version is strictly more powerful for an attacker than supplying one, because supplying a wrong hash on a versioned payload is refused while supplying no version at all is not checked. `src/xstate_statemachine/events.py:405-412` documents the parallel trust boundary on the event side: provenance is restored exactly as persisted, and a caller who can write arbitrary snapshot records already controls `state_ids` and `context` outright, "so this is the correct trust boundary" (library's own words).

## Impact

**General:** any caller that persists snapshots to a store an attacker (or a buggy migration) can write to should not rely on `from_snapshot()` alone to catch a forged or downgraded payload — the checks that exist (#185/#186/#198) are shape/version-conditioned, not cryptographic.

**Order-management:** a control-plane snapshot store is exactly this shape of trusted-but-not-verified input. A version-0 downgrade or a consistent-forgery restore could silently relocate an order-management machine to an unintended state (e.g. a kill-switch machine restored into a "cleared" leaf) if the persistence layer is ever exposed to less-trusted writers than assumed.

## Proposed fix

Not a change to default behaviour — an optional, additive envelope:

1. Add `minimum_version: int = 0` to `Interpreter.from_snapshot()` (and the `SyncInterpreter` equivalent); raise `SnapshotVersionError` when the declared version is below it.
2. Add `expected_machine_hash: Optional[str] = None`; when supplied, compare against it instead of (or in addition to) the payload's own `machine_hash`, so the caller does not have to trust an attacker-controlled field to validate itself.
3. Correct the `structure_hash` / `machine_hash` docstrings to say explicitly: *checksum against accidental drift, not an authentication tag against a party who controls the whole payload.*

We ourselves close this fully today with an HMAC envelope around the snapshot and a `version < 1` refusal in our own wrapper before `from_snapshot()` ever sees the payload — the ask above is ergonomics, so a wrapper does not have to re-implement `check_identity` from scratch to add that policy.

## Acceptance criteria

- `test_from_snapshot_minimum_version_rejects_v0` / `_v1_when_min_is_2` — parametrised over `Interpreter` and `SyncInterpreter`; asserts `SnapshotVersionError` when `minimum_version` exceeds the declared version.
- `test_from_snapshot_expected_machine_hash_overrides_payload` — a payload whose own `machine_hash` is forged to match a drifted machine is still refused when `expected_machine_hash` (the honest one) is supplied and disagrees.
- `test_check_identity_docstring_accuracy` (doc test / lint, not behavioural) — ensures the `structure_hash` docstring contains the word "checksum" and does not read as an authentication guarantee (guards the wording regression this issue flags).
- No existing test's default (no `minimum_version`, no `expected_machine_hash`) behaviour changes — both new parameters are additive and opt-in.

## Related

#185, #186, #198 — narrower than claimed: those three land the shape/version integrity checks correctly (we re-verified 8/9 mutation cells refused and the intact control still raising `SnapshotDriftError`), but none of them, individually or together, constitutes an authenticity check — the ninth mutation cell and all three downgrade forms above are the gap the "narrower than claimed" framing points at.

## Our containment, for context

We HMAC-tag control-plane snapshots and refuse `version < 1` in our own envelope before `from_snapshot()` ever sees the payload. That fully closes it on our side. We mention it so the priority is read correctly — this is an ergonomics and docs item for us, not a blocker.

## Verification

- Date: 2026-09-22
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `f28719c` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- cwd used: `<home>` (neutral, outside both repos)
- Exit codes: `R9-05_snapshots_are_unauthenticated.py` → **1** (both demonstrations reproduce fresh: consistent forgery accepted/relocated; all 3/3 version-downgrade forms accepted into a drifted machine)
