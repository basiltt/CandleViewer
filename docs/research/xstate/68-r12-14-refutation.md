# R12-14 refutation — B18 kill switch bricked by one guard-denied RELEASE

Commit `de2da4e`. Verdict: **CONFIRMED — Blocker, OUR-CONTRACT-DEFECT** (not a library defect).

## Re-run evidence (this pass, neutral cwd `<home>`, stdlib + library only)

- `battle-de2da4e/contracts/repro/de_c07b_killswitch_bricked.py` → exit 0,
  `bricked: true` on **both** `async def` and `def` services.
  Denied `RELEASE` → `status='error'`,
  `UnhandledEventError("Event 'RELEASE' is not handled in any active state
  ['kill_switch.engaged'] and the machine's onUnhandled policy is 'error'.")`.
  The subsequent **authorised** `RELEASE` is accepted by `send()` (no exception)
  but is dropped ("Interpreter is error; dropping event") — final states stay
  `['kill_switch.engaged']`.
- `contracts/f9_c04_c07b.py` → 6/6 PASS: config-only patch makes the denial
  non-fatal (`status='running'`, stays `engaged`), the authorised `RELEASE`
  then lands `kill_switch.clear`, `chain_trips=0`.
- `contracts/fC_sharp.py` → 13/13 PASS, incl. B18 async/sync parity.

## Refutation attempts

| Line of attack | Result |
|---|---|
| **Documented?** | Yes — and that is *why* it is ours. `onUnhandled: "error"` is an explicit opt-in fatal policy, and CHANGELOG #153 states a guard-denied event with no selectable arm is reported through `on_unhandled_event` (disposition `"guard_denied"`, `Receipt.denied=True`). The library behaves exactly as specified. Library defect: **REFUTED**. |
| **API misuse / our config?** | Confirmed cause: `engaged.on.RELEASE` has exactly one guarded arm, so a denial selects nothing, and root `onUnhandled:"error"` escalates that to fatal. The other four control charts use `defer`. Our catalogue JSON, ours to fix. |
| **XState v5 / SCXML agrees?** | Both treat a guard-denied event as simply *not taken* (no error, no state change). Neither has a fatal-on-unhandled mode — `onUnhandled:"error"` is this library's extension, chosen by us. So the upstream semantics do not endorse our configuration; they argue *against* it. |
| **Duplicate?** | Yes, deliberately: merges `C-07b`, `CV-C07b`, `CD-03` (and earlier `F6`, `CV-19-C07b`, `CD-02`). Single tracked item, **open seven rounds**. |
| **Measurement artefact?** | No. Reproduced fresh, both service spellings, both engines, polled to convergence, neutral cwd, exit 0. |
| **Trust boundary?** | Not crossed — no `from_snapshot`, no in-process trust assumption. This is ordinary event delivery. |

## Severity

Stays **Blocker for adoption of B18 on the order path**: a single wrong button
press permanently wedges the kill switch in the trading-blocked state, and no
authorised release can clear it. Not a library Blocker — no change to the
library board (no filed library Blocker survives this round).

## Fix (unchanged, config-only, Amendment-6, still unlanded)

On `B18.machine.json`: root `onUnhandled: "defer"`, plus an ordered **unguarded
`RELEASE` fall-through** arm on `engaged` that audits the denial as a no-op
(the B17/B20 shape). Proven by `f9_c04_c07b.py` on `de2da4e`. Tracked as
`E50-T43`, P0.
