# Triage: `semantics.md` (battle-5e07ba8)

**Build:** `_ref/xstate-statemachine` @ `main` = `5e07ba8` (unreleased 0.8.1).
**Method:** each `D-semantics-n` repro re-run fresh in this pass with
`_ref/xstate-statemachine/.venv-main/Scripts/python`,
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`; root cause re-read against current
source at the cited line numbers; severity re-assessed for an OMS order path.

## Table

| ID | Re-run result | Root cause confirmed? | Classification | Severity (register) | Re-assessed severity | Reason |
|---|---|---|---|---|---|---|
| D-semantics-1 | Reproduced: `done event: {'type': 'done.invoke.kid', 'data': {}}` vs child's own `output` `{'code': 7}` | Yes — `interpreter.py:2075-2079` and `sync_interpreter.py:1177-1181` both build `DoneEvent.data` from `child.context`, never `child.output` | LIBRARY-DEFECT | High | **High (unchanged)** | Confirmed silent loss of a child's computed result plus context leakage into the parent event; both are wrong on an order path. Workaround (CV-S02: write result into a context key) is cheap, so not a Blocker. |
| D-semantics-2 | Reproduced: `events seen by '*': []`, parent stays `['m.run']` instead of `['m.caught']` | Yes — `base_interpreter.py:2697-2701` mints `type=f"xstate.error.actor.{self.id}"` with `self.id` the runtime actor id (`parent.id:explicit_id`), and `_collect_eligible_transitions` (`base_interpreter.py:3740-3746`, confirmed at `3744`: `if event.src == inv.id`) requires `event.src == inv.id`, which is the declared invoke id, not the runtime actor id — so neither the type nor the src match, and `_matching_descriptors` treats the engine-minted event as a system event so `"*"` doesn't catch it either | LIBRARY-DEFECT | High | **High (unchanged)** | Confirmed total, silent loss of the documented supervision primitive. A config with `onError` + `"*"` that "looks like" it handles the case handles nothing — this is the worst kind of silent failure for a supervision tree. CV-S03 (ban `escalate`, use failure-propagation or `sendParent`) is the correct adoption constraint. |
| D-semantics-3 | Reproduced: `sync after tick #1: ['m.b']` (only one link per tick) vs `async after 0.25s: ['m.d']` (all three links); realistic ladder repro shows tick #1 lands on `ack_timeout` not `escalated` despite all three deadlines already due | Yes — `sync_interpreter.py` `tick()`'s `while self._event_queue or self._internal_queue: ... self._pump_timers()` pumps timers only when queues are non-empty on the *next* loop iteration; a newly-armed, already-due timer from an entry action that runs after the queues empty is never observed before the loop exits. `SimulatedClock._advance_to` (`clock.py:291-300`) re-reads the heap between timers so is unaffected — confirms the defect is specific to `RealClock` + `SyncInterpreter.tick()` | LIBRARY-DEFECT | Medium | **Medium (unchanged)** | Confirmed engine-parity gap, real for anyone polling `SyncInterpreter` with a chained/retry-ladder `after` pattern (exactly an OMS retry/escalation shape). Held at Medium rather than High here specifically because CV-C03 already restricts this adoption to the async engine, per the cited constraint register — that mitigation is external to the library, not a reason the defect itself is minor. |
| D-semantics-4 | Reproduced: observed `["xb1","xa1","xB","xA","xp","eX"]` vs SCXML reverse-document-order `["xb1","xB","xa1","xA","xp","eX"]`; stable across 5 `PYTHONHASHSEED` values | Yes — `_compute_states_to_exit` (`base_interpreter.py:~3825`) sorts the exit set by depth (depth-major) rather than SCXML §3.13's reverse document order (region-major) | DESIGN-CONSTRAINT | Low | **Low (unchanged)** | Confirmed deterministic (not a nondeterminism, which would have been a Blocker under this register's own rule) and a documented deviation from SCXML rather than a bug in the library's own semantics — region-internal order is correct, only cross-region depth-vs-region ordering differs. Behaves consistently; adopters must simply avoid cross-region exit-ordering dependencies (CV-S05). Kept as a deviation to design around, not fixed as a bug, matching the source document's own framing ("arguably WONTFIX-with-a-doc-note"). |
| D-semantics-5 | Reproduced: bare `stateIn: "work"` with two same-named leaf states on different branches silently resolves to the active one (`fired=True`) instead of rejecting the ambiguous spelling; fully-qualified and relative-path spellings both behave correctly | Yes — `_is_state_in` (`base_interpreter.py:~4218-4222`) matches `node.id == target or node.id.endswith("." + target)`, which is unsound only for a bare, ambiguous leaf name; the library already has a stricter, safer precedent for the analogous actor-target ambiguity (`logger.error` + drop, `base_interpreter.py:1859-1868`) that `stateIn` does not follow | LIBRARY-DEFECT | Low | **Low (unchanged)** | Confirmed real but narrow: only bites when two states share a bare leaf name, which is a spelling choice fully within the adopter's control (CV-S04: mandate fully-qualified `stateIn` ids, lint for it). Not elevated because it degrades gracefully to "silently picks one branch" rather than corrupting unrelated state, and a lint rule fully closes it. |
| D-semantics-6 | Reproduced: `sendTo` to an unresolvable target returns `Receipt(changed=False, error=None, deferred=False)`, `last_transition_ok=True`, `last_error=None`, `status='running'` — indistinguishable from a correct no-op | Yes — `base_interpreter.py:2656-2662` logs `logger.warning` and returns, with no corresponding `on_event_dropped` plugin hook fire (contrast with the runaway-chain path, which does fire that hook per #77 criterion 6) | LIBRARY-DEFECT | Low | **Low (unchanged)** | Confirmed silent-drop with no receipt-visible signal. Individually low (a typo'd actor id is normally caught in dev/CI), but compounds D-semantics-2: both actor-messaging failure paths are silent, so a supervision tree can be dark while every health signal reads green. CV-S06 (require explicit id/systemId + adoption-side resolution assertion) is the correct mitigation; not elevated to Medium/High because the register's higher tiers are reserved for money-loss/silent-state-corruption on the order path itself, and this requires a pre-existing config error (unresolvable target) to trigger. |

## Notes on process

- All six repros were executed fresh in this pass (not reused from a cached
  run) via the exact commands and interpreter specified in the environment
  brief; outputs are quoted verbatim above, no reduced parameterisation was
  needed (all six complete well under the 90s bound; the async lane run in
  `d1_sync_after0_chain.py` uses real 0.25s `sleep`s and completes in ~1.5s
  total wall time across ticks).
- No duplicate-of-known items were identified — none of the six match a
  cited LC/N/F/G/H id or a GitHub issue number found via read-only `gh`
  lookup at this pass (no such lookup was needed; the source document does
  not cite an existing upstream issue number for any of these six, only
  proposed future filings).
- No HARNESS-ERROR reclassifications: each repro's expected value traces to
  a normative citation (SCXML §3.13 for D-4, SCXML §5.9.2 `In()` for D-5, the
  library's own documented `output`/`escalate`/`sendTo` contracts for D-1,
  D-2, D-6, and observed engine-parity divergence vs the correct async/
  `SimulatedClock` lanes for D-3) that I independently checked against
  current source rather than accepting from the document as given.
- No severities were changed from the source document's own assessment;
  each was independently re-derived here using the register's stated scale
  (Blocker = money loss / silent state corruption on the order path; High =
  silent wrongness or hard architectural constraint; Medium; Low) and landed
  in the same place, which is recorded per-row above with a one-line reason
  rather than a bare confirmation.
