# R10-C2 refutation — "B18 onUnhandled:'error' + sole guarded RELEASE bricks the kill switch"

**Verdict: REFUTED as a library finding. Stands, unchanged, as OUR catalogue Blocker C-07b (config defect).**

## Reproduced first (19cb1f1, neutral cwd C:/Users/basil)
`contracts/repro/r7_c07b_b18_release.py`, both lanes, both dispositions:

| CV | UNH | denied RELEASE | subsequent authorised RELEASE |
|---|---|---|---|
| async | error | status=error, `UnhandledEventError`, unhandled=('RELEASE','errored') | dropped, still `kill_switch.engaged` |
| def | error | same | dropped, still engaged |
| async | defer | status=running, deferred | releases -> `kill_switch.clear` |
| def | defer | same | releases -> `kill_switch.clear` |

So the observed behaviour is real and lane-symmetric. Not a measurement artefact: the
authorised press was polled past convergence in every cell and never lands under `error`.

## Why it is not a library defect
1. **Documented, opt-in, per-machine.** README error-policy table: `onUnhandled:"error"`
   "stops with `UnhandledEventError`"; the default is XState's ignore. The catalogue
   *chose* `error` on B18. CHANGELOG (0.8.1 block, #170 note) states explicitly that a
   denied event under `onUnhandled:"defer"` enters the defer buffer — i.e. a guard-denied
   event is by design an *unhandled* event and is then subject to the chosen policy.
2. **SCXML/XState agree on the premise.** SCXML §3.13 `selectTransitions` only selects a
   transition whose `cond` evaluates true; a false guard selects nothing, so the event is
   consumed with no transition. XState v5 is identical (guarded transition with no
   fallback -> event does nothing). Neither defines an "error on unhandled" disposition at
   all — that is this library's extra safety policy, and applying it to a state whose only
   arm is guarded is the caller's choice.
3. **API misuse, and it is fixable in config alone.** The SCXML/XState idiom is ordered
   arms with an unguarded last arm. With
   `"RELEASE": [{target: clear, guard: owner_and_elevated, actions:[audit]}, {actions:[audit_denied]}]`
   and `onUnhandled:"error"` retained, both lanes:
   - async: denied -> `running`, `ks.engaged`; authorised -> `running`, `ks.clear`
   - def:   denied -> `running`, `ks.engaged`; authorised -> `running`, `ks.clear`
   No library change, `error` policy kept, denial still auditable. (Also fixed by `defer`,
   but the fallback arm is the better fix: it audits the denial instead of replaying it.)

## Residue
The Amendment-6 removal still has not landed in the JSON (`ka_killswitch.async.json`
sha1 `3d0de943effd…` on 19cb1f1, same shape in all contracts dirs). C-07b therefore remains
an open **Blocker in our catalogue** — ours to fix, gating B18 on any runtime, gating no
library decision. Recommended catalogue fix: add the unguarded `RELEASE` fallback arm
(keep `onUnhandled:"error"`), not a switch to `defer`.
