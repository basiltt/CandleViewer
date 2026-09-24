---
r6: R6-06
title: "Bug: `get_persisted_snapshot()` called from inside an entry (or exit) action is ACCEPTED and persists a torn state — the in-flight guard's predicate is a conjunction with legality, which is true in that window"
labels: [bug, severity/high, area/persistence, area/interpreter]
severity: High
engines: both
repro_script: repro/R6-06_entry_window_torn_snapshot.py
commit: cec108b
python: 3.13.7
verified: true
---

## Summary

A snapshot taken from inside an **entry action** is accepted on **both engines**. It
persists `configuration=['oms','oms.filled']` together with `context={'filled_qty': 0}` —
the new leaf paired with a context the macrostep has not finished applying — and it
restores cleanly to `oms.filled` with `filled_qty=0`. No error, no warning, no hook.

For an order lifecycle that is a persisted, silently wrong "filled with zero quantity"
blob that survives a restart looking perfectly healthy.

## Environment

- Library: `xstate-statemachine` @ `cec108b` (unreleased 0.8.1; `__version__` reports `0.8.0`)
- Python 3.13.7, Windows 11
- Engines: **both** `Interpreter` and `SyncInterpreter` are affected
- Non-parallel machine — one region, so #142's legality test is trivially satisfied

## Minimal reproduction

Complete standalone script — also at `repro/R6-06_entry_window_torn_snapshot.py`.
Exit code **1** means the torn snapshot was accepted on both engines.

```python
"""R6-06 — a snapshot taken from inside an ENTRY action is
ACCEPTED and persists a TORN state: the new leaf with a half-applied context.

Round 5 replaced the any-leaf test with `_configuration_is_legal()` (exactly
one leaf per region, #142/#143). That closes the PARALLEL tear, but the
entry-action window still has a perfectly legal configuration -- the new leaf
is already active -- while the macrostep is still open and the entry actions
that write the context have not all run. The guard at
base_interpreter.py:1306 is `_step_in_flight() and not _configuration_is_legal()`,
so a legal-but-mid-step configuration passes.

Library only, no project machinery. cec108b (unreleased 0.8.1), Python 3.13.

Exit code 1 == the torn snapshot was accepted on BOTH engines.
"""
import asyncio, logging
logging.disable(logging.CRITICAL)
from xstate_statemachine import (Interpreter, SyncInterpreter, MachineLogic,
                                 SnapshotMidStepError, create_machine)

def build():
    cap = {}
    def record_fill(i_, ctx, e, am):
        # a realistic two-phase entry action: clear, then write
        ctx["filled_qty"] = 0
        try:
            cap["blob"] = cap["i"].get_persisted_snapshot()
            cap["r"] = "ACCEPTED"
        except SnapshotMidStepError:
            cap["r"] = "SnapshotMidStepError"
        ctx["filled_qty"] = 100          # the fill is only recorded HERE
    cfg = {"id":"oms","initial":"open","context":{"filled_qty":0},
           "states":{"open":{"on":{"FILL":"filled"}},
                     "filled":{"entry":["record_fill"]}}}
    return create_machine(cfg, logic=MachineLogic(actions={"record_fill":record_fill})), cap

TORN = []

def show(label, i, cap):
    print(f"--- {label}")
    print("  live after settle :", sorted(i.current_state_ids), "ctx=", dict(i.context))
    print("  snapshot mid-entry:", cap.get("r"))
    if cap.get("r") == "ACCEPTED":
        b = cap["blob"]
        print("     persisted state :", b["configuration"], " context:", b["context"])
        r = SyncInterpreter.from_snapshot(__import__("json").dumps(b),
                                          build()[0]).start()
        print("     restored        :", sorted(r.current_state_ids), "ctx=", dict(r.context))
        if r.context.get("filled_qty") == 0 and "oms.filled" in r.current_state_ids:
            print("     >>> TORN: state says FILLED, context says 0 filled")
            TORN.append(label)
        r.stop()

m, cap = build(); i = SyncInterpreter(m).start(); cap["i"] = i
i.send("FILL"); show("SyncInterpreter", i, cap); i.stop()

async def a():
    m, cap = build(); i = await Interpreter(m).start(); cap["i"] = i
    await i.send("FILL", wait=True); show("Interpreter (async)", i, cap); await i.stop()
asyncio.run(a())

print()
if len(TORN) == 2:
    print("REPRODUCED on both engines: %s" % ", ".join(TORN))
    raise SystemExit(1)
print("NOT reproduced.")
raise SystemExit(0)
```

## Observed (verbatim)

```
--- SyncInterpreter
  live after settle : ['oms.filled'] ctx= {'filled_qty': 100}
  snapshot mid-entry: ACCEPTED
     persisted state : ['oms', 'oms.filled']  context: {'filled_qty': 0}
     restored        : ['oms.filled'] ctx= {'filled_qty': 0}
     >>> TORN: state says FILLED, context says 0 filled
--- Interpreter (async)
  live after settle : ['oms.filled'] ctx= {'filled_qty': 100}
  snapshot mid-entry: ACCEPTED
     persisted state : ['oms', 'oms.filled']  context: {'filled_qty': 0}
     restored        : ['oms.filled'] ctx= {'filled_qty': 0}
     >>> TORN: state says FILLED, context says 0 filled

REPRODUCED on both engines: SyncInterpreter, Interpreter (async)
```

Process exit code `1`. The restored interpreter reports `last_transition_ok=True` and
`last_error=None`. An additional probe shows the **exit**-action window is accepted too,
so in a non-parallel machine the guard is **inert for every action window**.

## Expected

`get_persisted_snapshot()` called from inside an action raises `SnapshotMidStepError`.

The library's own published contract says exactly this in four places:

- `docs/api/index.md:713` — *"Raises `SnapshotMidStepError` **[0.8.1]** (#102) if called
  while a macrostep is in flight (e.g. from inside an action) — snapshot after
  `send(wait=True)` resolves, from an `on_transition` hook, or after `stop(drain=True)`."*
- `docs/api/index.md:1787` — *"`get_persisted_snapshot()` was called while a macrostep is
  in flight … Snapshotting from inside an action."*
- `docs/_guide/snapshots.md:134` — *"A snapshot must be taken from a settled interpreter"*
- `docs/_guide/troubleshooting.md:56` — *"called while a macrostep is in flight — e.g.
  from inside an action (0.8.1)"*

- **SCXML** — [Algorithm for SCXML Interpretation](https://www.w3.org/TR/scxml/#AlgorithmforSCXMLInterpretation)
  defines a macrostep as ending *"in a configuration where the internal event queue is
  empty and no transitions are enabled by NULL"*, and enforces *"run-to-completion
  semantics"*. A configuration observed part-way through `enterStates` executable content
  is not an observable configuration under that model.
- **XState v5** — [Eventless transitions → Observability and transient states](https://stately.ai/docs/eventless-transitions):
  *"States that are only entered and left via eventless (`always`) transitions in the same
  step are transient: the machine passes through them without ever emitting a snapshot to
  subscribers."* v5 publishes a snapshot only at macrostep completion, so a leaf paired
  with an unfinished context is unreachable there.

## Root cause

**`base_interpreter.py:1306`** guards with a **conjunction**:

```python
if self._step_in_flight() and not self._configuration_is_legal():
    raise SnapshotMidStepError(...)
```

#142's per-region legality rewrite (`base_interpreter.py:1222`, `_configuration_is_legal`)
is correct and closed the *parallel* tear. But in the entry-action window the
configuration is **perfectly legal** — the new leaf is already active, exactly one per
region — while the macrostep is still open and context is half-applied. So the right-hand
conjunct is false and the guard never fires.

Legality was never the right predicate for this window; `_step_in_flight()`
(`base_interpreter.py:1218-1221`) alone is.

## Impact

For **order management** this is the worst kind of persistence bug: a durable blob that is
internally inconsistent and looks healthy. A realistic fill-recording entry action is
two-phase (clear, then write), and any snapshot taken between the phases — by a
checkpointing plugin, an audit hook, a crash-recovery `finally`, or simply a logging
action — persists `oms.filled` with `filled_qty=0`. On restart the machine believes the
order is filled and the position is flat, so it will not re-query, will not reconcile, and
will size the next order against a phantom position. Nothing in `last_transition_ok`,
`last_error` or any hook flags it.

## Two extensions beyond the original report

1. **Scope is wider than we first claimed.** The **exit**-action window is also accepted.
   In a non-parallel machine the guard is therefore inert for every action window.
2. **The obvious fix collides with a documented remedy.** The right predicate for the root
   call is `_step_in_flight()` alone — but `on_transition` hooks are documented as a
   *safe* snapshot site (`docs/api/index.md:713`), and `_step_in_flight()` is `True`
   inside `on_transition`. So the fix must either move the hook outside the in-flight
   window or exempt it explicitly. Worth deciding deliberately rather than discovering in
   a follow-up.

## Refutations attempted

- **Documented?** No — see the four citations above; the docs promise the opposite.
- **API misuse?** No. No configuration is missing, and it reproduces on both engines.
  #102 and #142 both post-date the behaviour.
- **Duplicate?** No. #102 closed the *no-leaf* window; #142/#143 closed the *parallel
  torn-region* window. `tests/test_round5_findings.py` pins only the parallel case.
- **Restore-side problem?** No — `from_snapshot` is behaving correctly; the blob it is
  given is already torn. #143's legality check passes because the configuration *is*
  legal.

## Proposed fix

Use `_step_in_flight()` alone for the root `get_persisted_snapshot()` call at
`base_interpreter.py:1306`, keeping `_configuration_is_legal()` for the recursive child
path where the settle-wait already applies. Resolve the `on_transition` collision
explicitly — either publish the hook after the macrostep closes, or set an explicit
"snapshot permitted" flag around it — and document whichever is chosen.

## Acceptance criteria

1. `tests/test_round6_findings.py::TestSnapshotActionWindows::test_entry_action_window_sync`
   — `get_persisted_snapshot()` inside an entry action on `SyncInterpreter` raises
   `SnapshotMidStepError`.
2. `…::test_entry_action_window_async` — **ASYNC-engine pin.** Same assertion on
   `Interpreter`.
3. `…::test_exit_action_window_both_engines` — same assertion from an exit action,
   parametrised over both engines.
4. `…::test_on_transition_hook_still_permitted` — a snapshot taken from an `on_transition`
   hook still succeeds (or, if the decision is to forbid it, the docs at
   `docs/api/index.md:713`, `docs/_guide/snapshots.md:134` and
   `docs/_guide/troubleshooting.md:56` are updated in the same change).
5. `…::test_quiescent_snapshot_unaffected` — after `send(wait=True)` resolves and after
   `stop(drain=True)`, snapshots still succeed and round-trip.
6. `…::test_parallel_case_not_regressed` — the existing #142/#143 parallel pin in
   `tests/test_round5_findings.py` continues to pass.

## Related

- **#102** (closed) — *Mid-macrostep configuration is snapshottable*; introduced
  `SnapshotMidStepError` and the guard this report finds incomplete. Closest prior art;
  the *no-leaf* window it closed is genuinely closed.
- **#142** (closed) — replaced the any-leaf test with `_configuration_is_legal()`. Correct
  as far as it goes; this report shows legality is not the right predicate for the action
  window. Its test pin covers only the parallel case, which is how this survived.
- **#143** (closed) — `from_snapshot()` configuration-legality check; passes here because
  the torn blob *is* legal, which is precisely the point.
- **#159** (closed) — `_report_snapshot_error`, the hook that would fire if the guard
  fired.
- **#87**, **#107**, **#110**, **#131** — persistence-correctness history.
- Our adoption audit (#26).

## Our mitigation meanwhile

We take snapshots only at quiescence through a factory wrapper, which avoids the window
entirely. That is why we can proceed on our non-order paths — but it is a convention
enforced on our side, and the library's own guard is the thing that should be catching it.

## Verification

Verified 2026-09-20 against `cec108b` (`.venv-main`, Python 3.13.7, Windows 11).

- **Repro run fresh:** `repro/R6-06_entry_window_torn_snapshot.py`; **exit code 1**.
  Output quoted verbatim in *Observed* — the mid-entry snapshot is `ACCEPTED` on
  `SyncInterpreter` **and** on `Interpreter`, persists
  `['oms','oms.filled']` with `{'filled_qty': 0}`, and restores to `oms.filled` with
  `filled_qty=0`.
- **Embedded script checked byte-identical** to the file under `repro/`.
- **Source lines confirmed open:** `base_interpreter.py:1306` is exactly
  `if self._step_in_flight() and not self._configuration_is_legal():`; the surrounding
  comment at `:1298-1305` cites #142 and the root-vs-child distinction;
  `_configuration_is_legal` is defined at `base_interpreter.py:1222` with the #142/#143
  rationale; `_step_in_flight` is at `:1218-1221`; `_report_snapshot_error` (#159) is
  called inside the branch that never fires.
- **Doc citations confirmed:** `docs/api/index.md:713`, `docs/api/index.md:1787`,
  `docs/_guide/snapshots.md:134` and `docs/_guide/troubleshooting.md:56` all read as
  quoted and all promise `SnapshotMidStepError` for the in-action case.
- **Citation URLs fetched:** W3C SCXML Appendix D (run-to-completion / macrostep
  definition) and the XState v5 *Eventless transitions* page, whose *Observability and
  transient states* section confirms v5 emits snapshots only at step completion.
- **Duplicate check:** searches for `snapshot`, `parity`. **#102**, **#142**, **#143**,
  **#159**, **#87**, **#107**, **#110**, **#131** are CLOSED and retained in *Related*;
  #102 (no-leaf window) and #142/#143 (parallel torn region) are distinct windows and
  their pins in `tests/test_round5_findings.py` remain valid. No open duplicate.
- **Labels** drawn only from the repository's label set; `area/snapshots` does not exist
  and was replaced with `area/interpreter` alongside `area/persistence`.
- **No project-name leak.**
