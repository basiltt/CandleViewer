# R6-02 adversarial refutation — verdict: DOWNGRADE Blocker → High

## Reproduction (cec108b, both re-run clean)

- `repro/f2_naked_verify_livelock.py` (async): 8.06 s, **3983 laps** (494/s),
  3983 `raise_critical_alert` side effects, `status="running"`,
  `error=None`, `last_transition_ok=True`, `on_event_dropped=[]`.
  Unbounded and **completely silent**.
- `repro/f9_sync_budget_signal.py` (sync): stops at 500 laps,
  `dropped=[('done.invoke.ver','chain_budget')]`, `Receipt.error=RunawayChainError`,
  `last_transition_ok=False`, configuration legal (1 leaf per region), still responsive.

Cause confirmed at `interpreter.py:1427`
`if self._raise_depth > limit and not is_system_event(event):` — a blanket
exemption. `sync_interpreter.py:770-828` (#94) takes the opposite, considered
line: a completion is spared **only at the moment of the trip**
(`spare = is_completion and not tripped`); once tripped "a further completion
IS the cycle (rollback -> re-arm -> done -> rollback ...) and must be dropped
or the drain never ends."

## Refutation attempts

1. **API misuse?** No. No mandatory config is missing; `maxIterations` is at
   its documented default and raising it changes nothing (the exemption is
   unconditional). The trigger — an `onDone` guard that never settles — is
   precisely the class of defect `maxIterations` is advertised to bound.
2. **Sync-engine-only artefact?** Inverted: sync is the *correct* side here.
   #120's inline rationale ("an engine completion … cannot self-feed; the sync
   engine spares these by construction; mirror that here") is factually false
   on cec108b for a two-state invoke cycle, and sync does not spare them.
3. **Duplicate of a closed issue?** No. #144 / R5-04 was the *sync* nested-invoke
   `onDone` livelock, fixed by the "chain ends only when nothing self-generated
   remains" rule — a different engine and a different mechanism (budget reset vs
   categorical exemption). The async exemption survived that fix untouched.
4. **XState v5 agrees?** No support found for exempting `done.invoke.*` from a
   runaway guard; v5's own protection is on the microstep/`always` loop, and it
   does not distinguish system events for that purpose.
5. **Documented?** *Partially — this is the only surviving mitigation.*
   `docs/_guide/getting-started.md:462` states "engine completions are never cut
   by it". The async behaviour therefore matches a written sentence. But that
   same sentence is falsified by the sync engine (f9 drops `done.invoke.ver`
   with reason `chain_budget`), and it is contradicted by
   `docs/_guide/core-concepts.md:639` "**Identical semantics on both engines** …
   not 'close enough' between engines; they are the same code path", and by
   `docs/api/index.md:1786`, which names "a cross-region `always` keeps re-arming
   an invoke" as a `RunawayChainError` cause. The docs are self-inconsistent;
   they do not license the async outcome, but they do show it is an intended
   (if wrongly premised) design choice rather than an oversight.

## Why not a Blocker

Re-running f2 past the cycle: the escape hatch still works
(`POSITION_FLAT` → receipt `changed=True`, `denied=False`, watchdog region
moves to `idle`), the loop is **not** starved (external sends and the other
region keep turning), the configuration stays legal, and no state is corrupted
or lost. The damage is unbounded CPU, unbounded service invocations and
unbounded spurious side effects (3983 critical alerts in 8 s) with zero
signal — serious, needs a fix before adoption, but recoverable from outside
and not a total-loss / data-corruption condition.

## Recommended fix

Mirror #94 on the async engine: spare a completion only at the moment of the
trip, and drop it thereafter — or, minimally, fire `on_event_dropped` /
set `RunawayChainError` on the exempted path so the livelock is observable
even if the completion is still delivered.
