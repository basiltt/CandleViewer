# Refuted before filing — R12-02: forged `"version": 2` blob gets `engine: true` from `upcast`

**NOT POSTED. Never will be. Retained as method evidence.**

**Filed severity:** Blocker. **Verdict after independent refutation: REFUTED — no defect.** Build: `main` @ `de2da4e`.

## The claim

`persistence.upcast` stamps `engine: true` on `done` / `error` / `after` records when it lifts a `"version": 2` blob to v3. So an attacker who can write a snapshot need only *downgrade the version field* and hand-write a completion record; `upcast` mints it as engine-provenanced, and it drives an `after` / `onDone` transition that a v3 blob would have been refused for. Proposed mitigation: `minimum_version=3`.

## Reproduction

**Reproduced exactly**, both engines, both action kinds, from a neutral cwd. The forged v2 record is stamped `engine: true` and drives the transition. The mechanism is real.

## Why it is refuted anyway

**The control kills it.** A plain **v3** blob — no forged record, no version trick — that simply writes `configuration` and `context` verbatim reaches the **identical observable outcome**. `from_snapshot` documents the snapshot as **trusted input applied verbatim**, with `machine_hash` explicitly described as *"a fingerprint, not a MAC"*. An attacker who can author snapshot bytes does not need to forge an event to reach a state; they can write the state.

**The proposed mitigation proves the point rather than fixing anything.** `minimum_version=3` refuses the v2 forgery and leaves the equivalent v3 verbatim write completely untouched. A mitigation that closes the exotic path and not the trivial one is a mitigation aimed at the wrong layer — which is the cleanest possible demonstration that **the trust boundary, not `upcast`, is load-bearing.**

**The behaviour is deliberate and documented.** Per #214, a v2 writer had exactly one minter for these records; demoting them on upcast would **silently drop genuine 0.8.0-era `after` deadlines** under #203's provenance gate — a real data-loss regression traded for no security gain.

**Upstream comparison:** XState v5 restores persisted snapshots verbatim as well and offers no cryptographic event provenance.

**Precedent:** identical to the accepted pattern in R10-01 and R11-01.

## What falls with it

Merged sources **D11-fuzz-1**, **D11-semantics-1** and **R11-01** all rest on this mechanism and **fall with it**.

## Residual — not a defect

One documentation note, carried to the #214 thread: **`minimum_version=3` is hygiene, not a security control.** We keep it at every restore site because it is free and it fences a path we do not need, but we have stopped describing it as a defence. The boundary is the MAC we apply to the journal at rest.

## Method note

This is the **fourth** Blocker filed against engine-event provenance across four rounds, and the fourth to die on the same control. The control is now a **triage precondition** in our gate: *any finding whose threat model requires blob-write must first be tested against "what does the same writer achieve with `state_ids` / `context` alone?"* If the answer is "the same thing", the row is hardening, not a defect.

Drafting this as a Blocker and then refuting it internally cost about an hour. Posting it would have cost a maintainer the same hour plus the credibility of the three legitimate findings alongside it. **That trade is the entire argument for the refutation step.**
