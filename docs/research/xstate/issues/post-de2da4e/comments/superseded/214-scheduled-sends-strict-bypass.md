# Comment draft — note on #214: `strict` is bypassed on restored `scheduled_sends`

**NOT POSTED. Draft.** Severity on our board: **Low** (parity / observability gap). Against `main` @ `de2da4e`.

This is the narrow residue of a security claim we investigated and **refuted ourselves** this round; the refutation matters as much as the residue, so both are below.

## The residue (the actual report)

`_rearm_restored_self_sends` calls `restore_event()` and `_arm_restored_self_send` directly, **without going through `_admit_restored`**. The consequence is a straightforward inconsistency in what `strict=True` promises:

| restored records | `strict=True` enforced? | refusal observable? |
|---|---|---|
| `pending_events` | **yes** (#214) | yes — `last_error` is set |
| `scheduled_sends` | **no** — silently admitted | no — `last_error` stays `None` |

So a chart upgrade that *undeclares* an event yields a **silent delivery** from the `scheduled_sends` lane where the `pending_events` lane would refuse it and record why. A live `raise(delay=)` is strict-checked at arm time, so an undeclared event reaches `scheduled_sends` only via a chart change or a hand-written blob — but a chart change is the ordinary case, not an exotic one.

Looks like a one-line fix: route `_rearm_restored_self_sends` through `_admit_restored`, as the `pending_events` path already does.

## What we refuted, and why we are saying so

We initially drafted this as a **Blocker**: "a forged `scheduled_sends` record mints an engine-only event (`done.invoke.*`, `after.*`) with an attacker-chosen payload, because the `engine` provenance flag is never consulted on this path."

**That claim is wrong, and we killed it with our own control before filing.** The `engine` flag **is** consulted here — `restore_event` → `_restore(..., trusted=record.get("engine") is True)` runs on the `scheduled_sends` path exactly as on the `pending_events` path. Measured, both `def` and `async def`, polled to convergence:

| record appended to `scheduled_sends` | delivered as | payload |
|---|---|---|
| control (untouched v3 blob) | — (inert) | — |
| `{"type": "done.invoke.job", "data": {"filled": 999999}}` | **public `Event`**, `is_system_event=False` | **`e.data == {}`** — the payload never arrives |
| same **+ `"kind": "done", "engine": true`** | `_EngineDone` | `{'filled': 999999}` |
| same forgery in `pending_events` | **public `Event`**, `is_system_event=False` | — |

Only *adding* `"engine": true` mints an engine event, and that is identically reachable through `pending_events` (#195) — the path that ships with the explicit comment that a caller who can write arbitrary snapshot records already controls `state_ids` and `context` outright. `from_snapshot`'s docstring (#205) states the snapshot is trusted input and `machine_hash` is a fingerprint, **not a MAC**. A party who can append to `scheduled_sends` can equally write `configuration: ["fg.expired"]` and `context: {"filled": 999999}` directly, with no event at all.

**So there is no escalation, and the trust boundary the docs draw is the correct one.** We authenticate snapshots at the storage boundary on our side, which is where the docstring says the responsibility lives.

We are including the refuted version because this is the **fourth** provenance Blocker we have drafted and then killed on the same control across four rounds, and the pattern is worth naming for anyone else auditing this library: **any finding whose threat model requires blob-write must first be tested against "what does the same writer achieve with `state_ids` / `context` alone?" If the answer is "the same thing", it is hardening, not a defect.**

## One related documentation request

`minimum_version=3` is sometimes read as a security control. It is not, and this round demonstrated why: it refuses a forged `"version": 2` blob while leaving an **equivalent v3 verbatim write** untouched — both reach the same observable state. That is a clean demonstration that the **trust boundary**, not `upcast`, is load-bearing. One sentence in the adoption docs saying `minimum_version=3` is hygiene rather than a defence would prevent an integrator from mistaking it for one.
