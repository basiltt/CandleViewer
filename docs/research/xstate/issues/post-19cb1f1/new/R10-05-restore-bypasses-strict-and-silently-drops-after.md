# The restore path bypasses `strict`, and `#203` now silently **drops** a pre-0.8.1 persisted `after` deadline

**Severity:** Medium (migration cliff + documented-contract contradiction)
**Build:** `main` @ `19cb1f1` (PR #211, commit `4dbf86e`; unreleased 0.8.1). `__version__` still reports `0.8.0` — **key on the commit.**
**Environment:** CPython 3.13.7, Windows 11, fresh venv, neutral working directory.
**r10:** R10-05 · **Labels:** bug, severity/medium, area/interpreter, persistence, events

---

## Summary

Two symptoms, one code path.

**(a) `strict` is not applied to restored events.** `_check_strict` runs at the `send()` call site (`interpreter.py:914`, `self._check_strict(event_obj)  # #51: at the call site, pre-queue`), but the restore path re-enqueues via `_enqueue_restored` → `_put_inbox` (`interpreter.py:1499-1500`), bypassing it entirely. An undeclared event restored from `pending_events` is accepted under `strict: True`. This **contradicts the restore contract documented at `events.py:403-414`**. (`onUnhandled: "error"` does still catch it, so the blast radius is limited to configurations relying on `strict` alone.)

**(b) A 0.8.0-era persisted `after` record is now refused — and the deadline is dropped, not demoted.** A record written by 0.8.0 has `kind: "after"` (the v2 shape, so the v1 name-based fallback does not catch it) but **no `engine` flag**. `#203`'s new provenance gate correctly declines to let it drive a timer — but it declines **silently**: no raise, no WARNING, nothing on `last_error`, `status` stays `running`, and `has_dormant_timers` does not cover it because the event was already sitting in the persisted inbox rather than awaiting re-arm.

Also in the same area, and part of the same root: the priority lane is not restored **as a lane**. Records carry only `['kind', 'payload', 'type']`; `interpreter.py:356` holds `Tuple[AnyEvent, bool]` and `:1497` drops the flag, so the restored `_priority_queue` is `[]`.

## Observed

| symptom | result at `19cb1f1` |
|---|---|
| (a) `strict: True` + restored undeclared `BOGUS` | `status=running`, `last_error=None` — **accepted** |
| (b) pre-0.8.1 `after` record restored against a 60 s deadline | stays `['t.wait']`, `last_error=None` — **deadline silently dropped** |

For (b) against `f28719c`, the same blob restored to `t.late`. So the observable behaviour changed across the upgrade, in the direction of losing a deadline, with nothing emitted.

## Why this is worth fixing rather than documenting

**The security direction of `#203` is right and we are not asking for it back.** We verified separately that the external name/shape confusion boundary `#195`/`#203` target now holds in every probe we could construct. This report is only about the **failure mode**.

A dropped deadline is the worst available outcome for a persisted timer:

- Firing it would be wrong (that was the `#203` bug).
- Refusing it **loudly** — raising, or at minimum a WARNING plus something on `last_error` — lets the caller re-arm from context.
- Refusing it **silently** produces a machine that restores into a legal configuration, reports health on every surface, and simply never hits its deadline.

Anyone upgrading with live persisted state will hit this, and by construction they will not find out from the library.

## Suggested direction

1. Route restored events through `_check_strict` (or an equivalent), so the documented restore contract at `events.py:403-414` is what actually happens.
2. When the provenance gate refuses a **restored** `after`/`done`/`error` record, emit a WARNING naming the state and the event, and surface it on `last_error` or a dedicated hook. A refused restored *deadline* in particular should be loud.
3. Consider a one-release **demotion** path for pre-0.8.1 records — accept `kind: "after"` without an `engine` flag, log it as a migration warning, and drop support a release later. That converts a silent cliff into a visible deprecation.
4. Persist the lane flag alongside the record so the priority queue round-trips as a lane.

## Root cause

**(a) strict bypass on restore.** `send()` calls `self._check_strict(event_obj)` at the call site (`src/xstate_statemachine/interpreter.py:914`, comment `# #51: at the call site, pre-queue`) and `_enqueue_restored`/`internal raise()` similarly gate through `_check_strict` (`interpreter.py:1318`, `base_interpreter.py:3416`). But the restore path — `Interpreter._enqueue_restored` (`interpreter.py:1499-1500`) called from `from_snapshot` while replaying `pending_events` — goes straight to `_put_inbox` and never calls `_check_strict`. An event restored from a persisted `pending_events` list is therefore never validated against `strict`, in contradiction of the provenance/restore contract documented at `events.py:403-414` (a record without `"engine": true` "restores as the PUBLIC class: user traffic, subject to `strict` / `onUnhandled`" — the code applies the class correctly but skips the `strict` check on that class entirely for the restore path).

**(b) pre-0.8.1 `after` records silently dropped.** `restore_event`'s provenance check (`events.py:403-414`) computes `trusted = record.get("engine") is True` and routes accordingly. A 0.8.0-era persisted record has `kind: "after"` (the v2 shape) but was written before the `engine` flag existed, so `trusted` is `False`; the event restores as a plain public event rather than an engine-minted `AfterEvent`. Because `after`-transition selection is gated on provenance (`#203`, matching only an engine-minted `AfterEvent`), the untrusted restored record is never matched by the `after` transition it was meant to satisfy — it lands in the inbox as an unhandled/unmatched event with no raise, no warning, and no `last_error` set, and the state's `after` deadline is never revisited because the timer itself was never re-armed (that's a separate but related gap; see R10-04 in this batch for the analogous unarmed-timer case).

**Priority-lane restore (footnote in Summary):** the persisted record shape (`['kind', 'payload', 'type']`) has no slot for the lane flag that `interpreter.py:356` (`self._priority_queue: "deque[Tuple[AnyEvent, bool]]"`) requires, and `_snapshot_pending_events` (`interpreter.py:1497`) flattens `[ev for ev, _ in self._priority_queue]`, dropping the boolean. So even a *fired* `after` restored today loses its priority-lane standing and rejoins the plain inbox.

## Impact

**General:** (a) means `strict: True` alone is not restore-safe — any deployment relying on `strict` (without also setting `onUnhandled: "error"`) silently accepts arbitrary restored event types after a snapshot round-trip. (b) means every 0.8.0-era persisted `after` deadline is dropped on first restore against 0.8.1+, with zero observable signal — `status` stays `running`, `last_error` stays `None`.

**Order-management relevance:** an order-timeout or SLA-deadline modeled as `after` and persisted under 0.8.0, then restored under this build (e.g., after a rolling deploy), never fires — the timeout state is silently frozen and the order lifecycle waits forever past its documented deadline with every health surface reporting normal.

## Proposed fix

1. Route `_enqueue_restored` (or the shared restore-replay loop) through `_check_strict`, matching the documented contract at `events.py:403-414`.
2. When `restore_event` computes `trusted=False` for a `kind` that is normally engine-only (`after`/`done`/`error`), emit a WARNING naming the state and event type, and set `last_error` (or a dedicated hook) rather than silently accepting it as inert user traffic.
3. Consider a one-release demotion path for pre-0.8.1 `kind: "after"` records lacking `engine`: accept and re-arm with a migration WARNING, then drop support later — converting a silent cliff into a visible, time-boxed deprecation.
4. Persist the priority-lane boolean alongside `kind`/`payload`/`type` so a restored fired `after` keeps its lane standing.

## Acceptance criteria

- `test_restore_applies_strict_to_restored_events` — restore a snapshot whose `pending_events` contains an undeclared event type under `strict: True`; assert it is rejected (raised, or surfaced on `last_error`/a dedicated hook) rather than silently accepted with `status == "running"`.
- `test_restore_pre_081_after_record_is_loud` — restore a snapshot containing a `kind: "after"` record with no `engine` flag (the exact 0.8.0 shape); assert the interpreter surfaces a WARNING and/or `last_error`, rather than staying in the pre-deadline state with `last_error is None`.
- `test_restore_pre_081_after_record_is_loud__async` — same, exercised via an `async def` action machine to confirm the signal is engine-kind-independent.
- `test_restore_preserves_priority_lane_flag` — restore a snapshot with a *fired* `after` record; assert the restored `_priority_queue` (or its public equivalent) is non-empty / the event is delivered ahead of ordinary inbox traffic, not silently demoted to the plain inbox.
- All of the above run on both `Interpreter` and `SyncInterpreter` where the restore path applies.

## Related

- `#203` — introduces the provenance gate on `after` selection that symptom (b) interacts with; this issue does not ask for `#203` to be reverted.
- `#195` — DoneEvent/AfterEvent provenance marker, the mechanism symptom (b)'s `engine` flag comes from.
- `#107` — persists a fired `after` via the priority lane; the lane-flag drop noted here is a regression against that guarantee's full fidelity.
- `#51` — introduced `strict` mode; this issue is about a gap in its enforcement on the restore path specifically.
- R10-04 (this batch) — the sibling defect where an *unfired* self-armed timer has no snapshot representation at all; this issue covers the case where a record does exist but is refused silently.

## Standalone repro

Stdlib + `xstate_statemachine` only. Runs from any working directory. Exit 1 = defect present.

```python
"""R10-05 (STANDALONE): the restore path bypasses `strict`, and a 0.8.0-era
persisted `after` record is now silently REFUSED rather than demoted.

Two symptoms, one code path.

(a) `_check_strict` runs at the `send()` call site
    (base_interpreter.py:1767), but the restore path re-enqueues via
    `_enqueue_restored` -> `_put_inbox` (interpreter.py:1499-1500), bypassing
    it. So an undeclared event restored from `pending_events` is accepted under
    `strict: True`, contradicting the restore contract documented at
    events.py:403-414.

(b) MIGRATION CLIFF. A record written by 0.8.0 has `kind: "after"` (the v2
    shape, so the v1 name-based fallback does not catch it) but NO `engine`
    flag. #203's new provenance gate then refuses it -- and the deadline is
    DROPPED rather than demoted: no raise, no WARNING, nothing on `last_error`,
    and `has_dormant_timers` does not cover it because the event was already in
    the persisted inbox rather than awaiting re-arm.

The security direction of #203 is right. The failure mode is not: a refused
restored DEADLINE must be loud.

Exit 0 = strict gates restored events AND the pre-0.8.1 record is loud.
Exit 1 = either symptom present.

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 40 s.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import create_machine, Interpreter, MachineLogic

# `t.wait` carries a 60-SECOND deadline. Nothing legitimate can fire it inside
# this script's runtime, so reaching `t.late` means a forged/unvetted record
# drove it, and staying in `t.wait` after a restore that CARRIED a fired record
# means the deadline was silently dropped.
CFG = {
    "id": "t",
    "initial": "wait",
    "strict": True,
    "states": {
        "wait": {"after": {60000: "late"}},
        "late": {},
    },
}


def _build():
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


async def _restore(blob: dict) -> dict:
    interp = Interpreter.from_snapshot(json.dumps(blob), _build())
    await interp.start()
    await asyncio.sleep(0.35)
    out = {
        "states": sorted(interp.current_state_ids),
        "last_error": type(getattr(interp, "last_error", None)).__name__,
        "status": getattr(interp, "status", None),
    }
    await interp.stop()
    return out


async def main() -> int:
    bad = 0

    # Baseline blob at quiescence.
    live = Interpreter(_build())
    await live.start()
    await asyncio.sleep(0.05)
    base = live.get_persisted_snapshot()
    await live.stop()

    # --- (a) strict is not applied to restored events ---------------------
    b = json.loads(json.dumps(base))
    b["pending_events"] = [{"kind": "event", "type": "BOGUS", "payload": {}}]
    r = await _restore(b)
    leaked = r["last_error"] == "NoneType" and r["status"] == "running"
    print(f"(a) strict:True + restored undeclared 'BOGUS' -> "
          f"status={r['status']} last_error={r['last_error']} states={r['states']}")
    print(f"    {'<-- ACCEPTED, strict bypassed' if leaked else 'refused (ok)'}")
    bad += 1 if leaked else 0

    # --- (b) pre-0.8.1 `after` record: refused, and SILENTLY --------------
    b2 = json.loads(json.dumps(base))
    # Exactly what 0.8.0 wrote: kind=="after", NO "engine" flag.
    b2["pending_events"] = [
        {"kind": "after", "type": "after.60000.t.wait", "payload": {}}
    ]
    r2 = await _restore(b2)
    dropped_silently = (
        r2["states"] == ["t.wait"]
        and r2["last_error"] == "NoneType"
    )
    print(f"(b) pre-0.8.1 `after` record restored -> states={r2['states']} "
          f"last_error={r2['last_error']}")
    print(f"    {'<-- DEADLINE DROPPED SILENTLY' if dropped_silently else 'loud (ok)'}")
    bad += 1 if dropped_silently else 0

    print()
    print("VERDICT:", "DEFECT PRESENT" if bad else "ok", f"({bad}/2 symptoms)")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(asyncio.wait_for(main(), 40.0))
    except asyncio.TimeoutError:
        print("WATCHDOG TIMEOUT")
        rc = 1
    sys.exit(rc)
```

### Actual output at `19cb1f1`

```
(a) strict:True + restored undeclared 'BOGUS' -> status=running last_error=NoneType states=['t.wait']
    <-- ACCEPTED, strict bypassed
(b) pre-0.8.1 `after` record restored -> states=['t.wait'] last_error=NoneType
    <-- DEADLINE DROPPED SILENTLY

VERDICT: DEFECT PRESENT (2/2 symptoms)
```

## Verification

- Date: 2026-09-22
- Python: CPython 3.13.7 (`.venv-main`), `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`
- Commit: `main` @ `19cb1f1` (verified via `git rev-parse HEAD` = `19cb1f19fc75575abd85cfa9da738c458f20d015`)
- Command: `python new/repro/R10-05_restore_bypasses_strict_and_drops_after.py`
- cwd: `C:/Users/basil` (neutral)
- Exit code: `1` (defect present, matches "Exit 1 = defect present")
- `verified: true`
