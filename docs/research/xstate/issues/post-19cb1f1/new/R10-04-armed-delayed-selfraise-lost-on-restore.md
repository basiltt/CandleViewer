# An armed-but-unfired delayed self-`raise` has no snapshot representation and is silently lost on restore

**Severity:** Medium
**Build:** `main` @ `19cb1f1` (PR #211, commit `4dbf86e`; unreleased 0.8.1). `__version__` still reports `0.8.0` — **key on the commit.**
**Environment:** CPython 3.13.7, Windows 11, fresh venv, neutral working directory.
**Both `def` and `async def` action spellings exercised — the defect is present on both.**
**r10:** R10-04 · **Labels:** bug, severity/medium, area/interpreter, persistence, timers

---

## Summary

`_snapshot_pending_events` (`interpreter.py:1480-1497`) reads the priority queue plus the inbox deque only. A timer that is **armed but has not yet fired** therefore has **no representation in the snapshot at all** — unlike a *fired* `after`, which `#107` persists via the priority lane.

`#206` made the delayed self-send a **debt of the arming step**. A snapshot **discharges that debt** with no hook, no warning and no error. Restore does not re-run entry actions, so the machine resumes into a state whose only exit was the lost event, and stays there forever.

An **external** delayed send survives the same round-trip. That asymmetry is confirmed in the same run and is what makes this a defect rather than a documented limitation.

## Observed

| lane | snapshot `pending_events` | live after 650 ms | restored after 600 ms |
|---|---|---|---|
| `def` | `[]` | `['debt.b']` | **`['debt.a']`** — wedged |
| `async def` | `[]` | `['debt.b']` | **`['debt.a']`** — wedged |

The snapshot is taken 50 ms into a 300 ms window, at quiescence, and `get_persisted_snapshot()` raises nothing. There is no `deferred_events` entry either — the debt simply does not exist in the serialised form.

## Why it matters

The three properties combine badly:

1. The snapshot is **accepted** — no `SnapshotMidStepError`, no warning, nothing on `last_error`.
2. Restore **does not re-run entry actions**, so the arming action that would have re-established the debt never runs.
3. `has_dormant_timers` does not cover it, because from the restored interpreter's point of view no timer was ever armed.

The result is a machine that restores into a legal-looking configuration and is permanently wedged, with every observability surface reporting health. For anything driving a lifecycle off a delayed self-raise, a restart silently converts "in progress" into "stuck".

## Suggested direction

Either serialise armed-but-unfired self-delays (with their remaining duration, or an absolute deadline) alongside the fired ones `#107` already persists, **or** refuse the snapshot — `SnapshotMidStepError` or a dedicated error — when an undischarged self-delay debt is outstanding. Silently discharging it is the one option that leaves the caller no way to know.

If neither is desirable, documenting it explicitly under the snapshot guide's quiescence discussion would at least let callers avoid the shape. Our own wrapper now asserts there is no armed self-delay before snapshotting, and forbids any state whose only exit is a delayed self-raise on the persisted path.

## Environment

CPython 3.13.7, Windows 11, `xstate-statemachine` fresh venv, `main` @ `19cb1f1` (commit `19cb1f19fc75575abd85cfa9da738c458f20d015`, PR #211 merge commit `4dbf86e`). `__version__` reports `0.8.0` (unreleased 0.8.1) — key on the commit.

## Root cause

`src/xstate_statemachine/interpreter.py:1480-1497` (`Interpreter._snapshot_pending_events`) builds the persisted `pending_events` list purely from `self._priority_queue` and the inbox deque (`return [ev for ev, _ in self._priority_queue] + inbox`, line 1497). Neither collection has any entry for a delayed self-send that has been *armed* (scheduled via `_set_timeout` in `_schedule_send`, `interpreter.py:2206-2247`, `#206`) but has not yet fired: the pending timer handle lives in `self._chain_owed_sends` / `self._timer_handles` / `self._scheduled_sends`, none of which `_snapshot_pending_events` reads.

Consequently `get_persisted_snapshot()` (which calls `_snapshot_pending_events`) silently discharges the arming debt: the outstanding timer that was the *only* declared exit (`entry: [raise(delay=)]`, `on: {PONG: "b"}`) is not represented in the blob at all. `Interpreter.from_snapshot` restores state `a` with no queued/priority/armed record of the pending `PONG`, and restore does not re-run entry actions (by contract — restore is state resumption, not re-entry), so the timer is never re-armed. The interpreter is now permanently parked in `a` with no path forward.

## Impact

**General:** any state whose sole declared exit is a delayed self-`raise`/self-`send` armed in that state's entry action becomes permanently unresumable across a snapshot/restore cycle taken while the timer is still pending — with no error, no warning, and every health-observability surface (`status`, `last_error`, `has_dormant_timers`) reporting normal.

**Order-management relevance:** a state-machine-driven order lifecycle that uses a delayed self-raise to advance itself (e.g., "wait N ms then poll fill status") will silently freeze at that step if the process restarts (deploy, crash-recovery, horizontal rebalance) while the timer is armed but unfired — the order appears to be actively "in progress" on every introspectable surface while never actually progressing again.

## Proposed fix

Per the "Suggested direction" above: either (a) serialise armed-but-unfired self-delay debts in the snapshot, storing the remaining duration or an absolute deadline so `from_snapshot` can re-arm the timer, or (b) refuse to snapshot while an undischarged self-delay debt is outstanding (raise `SnapshotMidStepError` or a dedicated error), forcing the caller to wait for quiescence-with-no-armed-timers or handle the error explicitly. Silent discharge, the current behavior, is the one option that gives the caller no signal at all.

## Acceptance criteria

- `test_snapshot_serializes_armed_selfraise_timer__def` — snapshot a machine mid-window (armed but unfired self-`raise(delay=)`), assert the snapshot blob contains a representation of the pending debt (or that `get_persisted_snapshot()` raises a documented error instead).
- `test_snapshot_serializes_armed_selfraise_timer__async_def` — same, `async def` action.
- `test_restore_progresses_past_armed_selfraise__def` / `..._async_def` — restore from that snapshot, wait past the original delay, and assert the restored interpreter's `current_state_ids` matches what the live (never-restarted) interpreter would show at the same wall-clock offset (i.e., `debt.b`, not stuck at `debt.a`).
- `test_external_delayed_send_still_survives_snapshot__def` / `..._async_def` — regression guard: an externally-delivered delayed send (not self-armed) must continue to survive snapshot/restore exactly as today (the asymmetry this issue reports must be closed by fixing the self-armed case, not by breaking the external case).

## Related

- `#107` — persists a *fired* `after` via the priority lane; this issue is about a timer that has not yet fired.
- `#128` — `after` timers not re-armed by `from_snapshot()`, no dormancy signal for a lost timer; closely related persistence/restore gap for the sibling `after` mechanism.
- `#206` — introduces the self-armed delayed-send debt (`_chain_owed_sends`) this issue's snapshot gap discharges silently.
- R10-03 (this batch) — a different defect on the same `#206` debt, in the live chain-budget clear test rather than the snapshot path.
- R10-05 (this batch) — a related persistence/restore defect: restored `after` records are silently dropped rather than re-armed.

## Standalone repro

Stdlib + `xstate_statemachine` only. Runs from any working directory. Exit 1 = defect present.

```python
"""R10-04 (STANDALONE): an armed-but-unfired delayed self-`raise` has no
snapshot representation and is silently lost on restore.

`_snapshot_pending_events` (interpreter.py:1480-1497) reads the priority queue
plus the inbox deque only, so a timer that is ARMED but has not yet FIRED has no
representation in the snapshot at all -- unlike a *fired* `after`, which #107
persists via the priority lane. #206 made the delayed self-send a debt of the
arming step; a snapshot discharges that debt with no hook, no warning and no
error. Restore does not re-run entry actions, so the machine resumes into a
state whose ONLY exit was the lost event.

Part B: an EXTERNAL delayed send survives -- the asymmetry is the finding.

Exit 0 = the restored machine progresses like the live one (fixed).
Exit 1 = the restored machine is wedged while the live one progressed (defect).

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 40 s.
"""
from __future__ import annotations

import asyncio
import json
import sys

from xstate_statemachine import create_machine, Interpreter, MachineLogic

CFG = {
    "id": "debt",
    "initial": "a",
    "states": {
        # The ONLY exit from `a` is the delayed self-raise armed on entry.
        "a": {
            "entry": [{"type": "raise", "params": {"event": "PONG", "delay": 300}}],
            "on": {"PONG": "b"},
        },
        "b": {},
    },
}


def _build(kind: str):
    def _noop(i, c, e, a=None):
        return None

    async def _noop_async(i, c, e, a=None):
        return None

    fn = _noop if kind == "def" else _noop_async
    return create_machine(
        json.loads(json.dumps(CFG)), logic=MachineLogic(actions={"noop": fn})
    )


async def run(kind: str) -> dict:
    # --- live lane: arm, wait past the delay, observe progress -------------
    live = Interpreter(_build(kind))
    await live.start()
    await asyncio.sleep(0.05)          # 50 ms into the 300 ms window
    snap = live.get_persisted_snapshot()
    pend = list(snap.get("pending_events") or [])
    defr = list(snap.get("deferred_events") or [])
    await asyncio.sleep(0.60)          # well past the 300 ms delay
    live_states = sorted(live.current_state_ids)
    await live.stop()

    # --- restored lane: same blob, same wall clock ------------------------
    rest = Interpreter.from_snapshot(json.dumps(snap), _build(kind))
    await rest.start()
    await asyncio.sleep(0.60)
    rest_states = sorted(rest.current_state_ids)
    await rest.stop()

    return {
        "pending_in_snapshot": pend,
        "deferred_in_snapshot": defr,
        "live": live_states,
        "restored": rest_states,
    }


async def main() -> int:
    bad = 0
    for kind in ("def", "async def"):
        r = await run(kind)
        lost = r["live"] != r["restored"]
        print(f"[{kind}] snapshot pending_events={r['pending_in_snapshot']} "
              f"deferred={r['deferred_in_snapshot']}")
        print(f"[{kind}] live after 650ms  = {r['live']}")
        print(f"[{kind}] restored after 600ms = {r['restored']}"
              f"   {'<-- DEBT LOST' if lost else ''}")
        bad += 1 if lost else 0
    print()
    print("VERDICT:", "DEFECT PRESENT" if bad else "ok", f"({bad}/2 kinds)")
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
[def] snapshot pending_events=[] deferred=[]
[def] live after 650ms  = ['debt.b']
[def] restored after 600ms = ['debt.a']   <-- DEBT LOST
[async def] snapshot pending_events=[] deferred=[]
[async def] live after 650ms  = ['debt.b']
[async def] restored after 600ms = ['debt.a']   <-- DEBT LOST

VERDICT: DEFECT PRESENT (2/2 kinds)
```

## Verification

- Date: 2026-09-22
- Python: CPython 3.13.7 (`.venv-main`), `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`
- Commit: `main` @ `19cb1f1` (verified via `git rev-parse HEAD` = `19cb1f19fc75575abd85cfa9da738c458f20d015`)
- Command: `python new/repro/R10-04_delayed_selfraise_lost_on_restore.py`
- cwd: `C:/Users/basil` (neutral)
- Exit code: `1` (defect present, matches "Exit 1 = defect present")
- `verified: true`
