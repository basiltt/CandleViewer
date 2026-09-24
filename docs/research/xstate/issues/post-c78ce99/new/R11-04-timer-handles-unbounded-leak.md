# `_timer_handles` grows by one retained entry per `raise(delay=)` beat and is never pruned — an unbounded leak on the heartbeat shape #212 just made legal

**Severity:** High
**Build:** `main` @ `c78ce99` (merge of PR #217, `fix/0.8.1-round10`; unreleased 0.8.1). `__version__` still reports `0.8.0` — **key on the commit.**
**r11:** R11-04 · **verified:** true
**Labels:** `bug`, `severity/high`, `area/interpreter`, `timers`, `perf`

---

## Summary

`Interpreter._schedule_send` registers a delayed self-send's timer handle under the **interpreter/machine id**, while the only pruner runs on **state exit** and pops by **state id**. The machine id is never an exiting state, so that list is **append-only for the interpreter's entire life**: exactly one dead `TimerHandle` is retained per `raise(delay=)` beat, on both engines and both action spellings, released only at `stop()`.

The `after:` path does this correctly — it registers under `owner_id=state.id` and *is* pruned. It is the control throughout below, and it stays flat.

**This is not a new mechanism, but it is newly unbounded.** Before #212, #206's chain charge killed a delayed self-send cycle at roughly `maxIterations` beats, capping retention at ~12 entries — which is why it never showed up. **#212 makes such a cycle a legal periodic process, so the growth now has no ceiling short of `stop()`.**

## Environment

- CPython 3.13.7, Windows 11 Pro 10.0.26200, fresh venv, neutral working directory (`C:/Users/basil`).
- `xstate-statemachine` `main` @ `c78ce99` (merge of PR #217 from `fix/0.8.1-round10`). `__version__` reports `0.8.0` (unreleased 0.8.1) — key on the commit.
- Both `def` and `async def` action spellings exercised, and **both engines** — the defect is present on all three cells.
- Every figure below is measured on the container itself (`len(i._timer_handles[i.id])`), not inferred from RSS; RSS is only a corroborating second signal.

## Minimal reproduction

Standalone — stdlib plus `xstate_statemachine` only, all helpers inlined, runs from any working directory. **Exit 1 = defect present** (`raise(delay=)` retains ~1.00 handle/beat while the `after:` control stays flat); **exit 0 = fixed**.

```python
"""R11-04 (STANDALONE): `_timer_handles` grows by exactly one retained entry per
`raise(delay=)` beat, on both engines, and nothing prunes it before `stop()`.

`Interpreter._schedule_send` registers the delayed-self-send handle as
`self._timer_handles.setdefault(self.id, []).append(handle)` -- keyed under the
INTERPRETER/MACHINE id. The only pruner runs on state exit and pops
`self._timer_handles.pop(state.id, [])`. The machine id is never an exiting
state, so the list is append-only for the interpreter's whole life. `_fire`
settles the send and clears `_armed_self_sends`/`_scheduled_sends` but leaves the
handle; `_cancel` clears the clock and `_armed_self_sends` but also leaves it.

The `after:` path registers under `owner_id=state.id` and IS pruned -- it is the
control below and it stays flat.

Before #212 this was capped: #206's chain trip killed a delayed self-send cycle
at ~`maxIterations` beats. #212 makes such a cycle a legal periodic process, so
the growth is now unbounded.

Exit 0 = handles/beat is ~0 on both spellings (defect fixed).
Exit 1 = `raise(delay=)` retains ~1.00 handle/beat while `after:` stays flat.

Stdlib + xstate_statemachine only. Runs from any cwd. Watchdog 60 s.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

from xstate_statemachine import (
    create_machine,
    Interpreter,
    SyncInterpreter,
    MachineLogic,
)

PERIOD_MS = 10
WINDOW_S = 5.0
LEAK_THRESHOLD = 0.5  # handles retained per beat


def raise_cfg() -> dict:
    """Ping-pong paced by a delayed self-send -- legal periodic work under #212."""
    arm = {"type": "raise", "params": {"event": "BEAT", "delay": PERIOD_MS}}
    return {
        "id": "leak",
        "initial": "up",
        "states": {
            "up": {"entry": [arm, "beat"], "on": {"BEAT": "down"}},
            "down": {"entry": [arm, "beat"], "on": {"BEAT": "up"}},
        },
    }


def after_cfg() -> dict:
    """Identical shape spelled with `after:` -- the leak-free control."""
    return {
        "id": "leak",
        "initial": "up",
        "states": {
            "up": {"entry": ["beat"], "after": {PERIOD_MS: "down"}},
            "down": {"entry": ["beat"], "after": {PERIOD_MS: "up"}},
        },
    }


def _handle_count(interp) -> int:
    return sum(len(v) for v in getattr(interp, "_timer_handles", {}).values())


async def run_async(cfg: dict, kind: str) -> dict:
    beats = {"n": 0}

    def _beat(i, c, e, a=None):  # noqa: ANN001  plain def
        beats["n"] += 1

    async def _beat_async(i, c, e, a=None):  # noqa: ANN001  async def
        beats["n"] += 1

    beat = _beat if kind == "def" else _beat_async

    machine = create_machine(cfg, logic=MachineLogic(actions={"beat": beat}))
    interp = Interpreter(machine)
    await interp.start()
    await asyncio.sleep(WINDOW_S)
    retained = _handle_count(interp)
    n = beats["n"]
    await interp.stop()
    return {
        "beats": n,
        "retained_handles": retained,
        "per_beat": round(retained / n, 4) if n else 0.0,
    }


def run_sync(cfg: dict) -> dict:
    beats = {"n": 0}

    def beat(i, c, e, a=None):  # noqa: ANN001
        beats["n"] += 1

    machine = create_machine(cfg, logic=MachineLogic(actions={"beat": beat}))
    interp = SyncInterpreter(machine)
    interp.start()
    # The sync engine has no run loop: it advances only when pumped. A NOOP the
    # chart does not declare is simply dropped, so it is a pure clock pump.
    t0 = time.time()
    while time.time() - t0 < WINDOW_S:
        time.sleep(0.004)
        interp.send("NOOP")
    retained = _handle_count(interp)
    n = beats["n"]
    interp.stop()
    return {
        "beats": n,
        "retained_handles": retained,
        "per_beat": round(retained / n, 4) if n else 0.0,
    }


async def main() -> int:
    results: dict = {}

    for kind in ("async def", "def"):
        results[f"ASYNC-ENGINE raise(delay=) / {kind}"] = await run_async(
            raise_cfg(), kind
        )
        results[f"ASYNC-ENGINE after: (control) / {kind}"] = await run_async(
            after_cfg(), kind
        )

    results["SYNC-ENGINE raise(delay=) / def"] = run_sync(raise_cfg())
    results["SYNC-ENGINE after: (control) / def"] = run_sync(after_cfg())

    print(json.dumps(results, indent=2))

    leaking = [
        cell
        for cell, r in results.items()
        if "raise(delay=)" in cell and r["per_beat"] >= LEAK_THRESHOLD
    ]
    controls_flat = all(
        r["per_beat"] < LEAK_THRESHOLD
        for cell, r in results.items()
        if "control" in cell
    )

    print()
    print(f"leaking raise(delay=) cells : {leaking}")
    print(f"after: controls all flat    : {controls_flat}")
    print(f"REPRODUCED: {bool(leaking) and controls_flat}")
    return 1 if leaking else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(asyncio.wait_for(main(), 60)))
    except asyncio.TimeoutError:
        print("WATCHDOG: exceeded 60 s")
        sys.exit(2)
```

## Observed

Verbatim fresh run of the block above, from neutral cwd `C:/Users/basil` at `c78ce99`:

```
{
  "ASYNC-ENGINE raise(delay=) / async def": {
    "beats": 308,
    "retained_handles": 308,
    "per_beat": 1.0
  },
  "ASYNC-ENGINE after: (control) / async def": {
    "beats": 307,
    "retained_handles": 1,
    "per_beat": 0.0033
  },
  "ASYNC-ENGINE raise(delay=) / def": {
    "beats": 313,
    "retained_handles": 313,
    "per_beat": 1.0
  },
  "ASYNC-ENGINE after: (control) / def": {
    "beats": 311,
    "retained_handles": 1,
    "per_beat": 0.0032
  },
  "SYNC-ENGINE raise(delay=) / def": {
    "beats": 383,
    "retained_handles": 383,
    "per_beat": 1.0
  },
  "SYNC-ENGINE after: (control) / def": {
    "beats": 382,
    "retained_handles": 1,
    "per_beat": 0.0026
  }
}

leaking raise(delay=) cells : ['ASYNC-ENGINE raise(delay=) / async def', 'ASYNC-ENGINE raise(delay=) / def', 'SYNC-ENGINE raise(delay=) / def']
after: controls all flat    : True
REPRODUCED: True
```

Exit code **1**. Exactly one dead handle retained per beat, for ever, on both engines and both action spellings; the `after:` control holds at a single live handle.

Corroborating, in separate probes: a 200-machine population over 24 s grows **+455.4 MB** on `raise(delay=)` against **+0.0 MB** idle and **−0.1 MB** on `after:` arms, strictly linear (170 → 284 → 393 → 500 MB) with **no plateau**, polled to convergence at 3/6/9/12 s and again at 6/12/18/24 s; memory is recovered on `stop()` + `gc`. A handle-provenance probe confirms 762 beats → 762 retained, of which **761 had already fired**. Each retained `TimerHandle` pins its `_fire` closure and through it the `target_event`, the `handle_box`, the key and the interpreter — which is why RSS tracks the handle count linearly rather than counting small objects.

### Why no usage bounds it

Six postures × both engines × both action flavours, attacking this from the "you are holding it wrong" direction first:

| posture | handles/beat |
|---|---|
| A — id-reusing ping-pong (supersede semantics) | 1.00 |
| B — no send id | 1.00 |
| C — long period (250 ms) | 1.00 |
| D — single self-looping state (never exits) | 1.00 |
| E — **explicit `cancel(sendId)` before each re-arm** | 1.00 |
| CTRL — `after: 10` | **0.00** |

Reusing the id does not help; explicitly cancelling does not help (because `_cancel` clears the clock and `_armed_self_sends` but never touches `_timer_handles`); a longer period changes the **rate**, never the ratio. A never-exiting state is the worst case, since no state exit ever runs.

## Expected

A self-paced `raise(delay=)` heartbeat is explicitly blessed as legal, unbounded periodic work — and nothing in that blessing, or anywhere else, warns that it retains state per beat.

`CHANGELOG.md:19-24` (the #212 entry):

> #206 charged a `raise(delay=)` self-send as a debt of the arming step; #212 showed that killed every self-paced heartbeat or poller at `maxIterations` beats regardless of period — the charge was time-blind. The rule is now the `after` rule: arming a delay ends the step's chain, the firing is a clock event. **A `raise(delay=)` heartbeat of any period runs indefinitely, exactly as an `after` one does**, and a 1 ms `raise(delay=)` ping-pong is a periodic process exactly as an `after: 1` ping-pong has always been.

and `CHANGELOG.md:93-98`:

> The shipped rule is the `after` rule […]: a delayed self-send is a timer, its firing is a clock event, and **a delayed ping-pong of any period is a periodic process — as an `after: 1` ping-pong has always been.**

**"Exactly as an `after` one does" is the contract, and `after` is leak-free**: `interpreter.py:2748` keys the handle under `owner_id` (the arming state) and `interpreter.py:2557` / `sync_interpreter.py:1488` prune it on that state's exit, which is why the control above stays at one handle across 380 beats. So the expected behaviour of a `raise(delay=)` heartbeat "of any period, indefinitely" is **constant** handle retention, not O(beats).

The reference implementations agree. XState v5's scheduler **deletes the scheduled entry when the timer fires** (`createScheduledEventId` entries are removed in `scheduler.ts`'s `handleEvent`/`cancel` path, so a fired delayed send leaves nothing behind), and SCXML §6.2 `<send delay=>` defines no retained record for a delivered send — only `<cancel>` addressing by `sendid` before delivery. Neither reference model requires keeping a fired handle.

## Root cause

Both engines register the delayed-self-send handle under the **machine id**, and the only pruner pops by **state id**. Open at `c78ce99`:

```python
# src/xstate_statemachine/interpreter.py:2354  (async engine, _schedule_send)
handle = self._set_timeout(_fire, delay / 1000.0, owner=self.id)
handle_box.append(handle)
self._timer_handles.setdefault(self.id, []).append(handle)   # <-- keyed under self.id
```

```python
# src/xstate_statemachine/sync_interpreter.py:1198  (sync engine, same shape)
handle = self._set_timeout(_fire, delay / 1000.0, owner=self.id)
self._timer_handles.setdefault(self.id, []).append(handle)   # <-- keyed under self.id
```

The pruners:

```python
# src/xstate_statemachine/interpreter.py:2557  (_cancel_state_tasks, on state exit)
for handle in self._timer_handles.pop(state.id, []):
    self.clock.clear_timeout(handle)
```

```python
# src/xstate_statemachine/sync_interpreter.py:1488  (_cancel_state_tasks_sync)
handles = self._timer_handles.pop(state.id, [])
```

`self.id` is the interpreter/machine id and is never an exiting `state.id`, so `_timer_handles[self.id]` is append-only. `_fire` settles the send and clears `_armed_self_sends` / `_scheduled_sends` but leaves the handle; `_cancel` clears the clock and `_armed_self_sends` but also leaves it. The only release is the wholesale `self._timer_handles.clear()` in `stop()` (`interpreter.py:1514-1517`, `sync_interpreter.py:687-690`).

Contrast `_schedule_after` at `interpreter.py:2748`, four hundred lines away, which does the right thing with the identical container:

```python
handle = self._set_timeout(_fire, delay_sec, owner=owner_id)
self._timer_handles.setdefault(owner_id, []).append(handle)   # owner_id == state.id
```

## Impact

**General.** Any interpreter that paces itself with `raise(delay=)` — a heartbeat, a poller, a retry backoff loop, a keepalive — grows its retained-handle list without bound for as long as it runs. Each retained handle pins a `_fire` closure and the event it would have delivered, so RSS tracks the count linearly: **+455 MB over 24 s at 200 machines and a 10 ms period, with no plateau**. Memory is only returned at `stop()`, so a process whose interpreters are meant to outlive it has no recovery point at all. The severity is amplified by two other 0.8.1 decisions:

1. **#212 explicitly endorses the shape that leaks.** A self-paced heartbeat went from "trips at `maxIterations`" to "legal periodic process" in the same release, so the documented-good path is now the leaking path.
2. **#213 makes `raise(delay=)` the only restart-safe in-chart deadline primitive.** `scheduled_sends` persists delayed self-sends; `after` deadlines are deliberately not persisted (#128). A caller who needs a deadline to survive a restart is steered onto `raise(delay=)` — and `after:`, the leak-free spelling, is precisely the one that loses the deadline across a snapshot.

So the recommended path to snapshot-safe deadlines is the one that leaks, with no in-API way to avoid it: posture E above shows even an explicit `cancel(sendId)` before each re-arm does not reclaim anything.

**Order management.** The concrete shape in our adoption audit (#26) is a **heartbeat machine group on a long-running OMS process**: one interpreter per venue session, each beating at 1–10 s to keep the session alive and to re-arm an ack deadline that must survive a process restart — i.e. exactly the `raise(delay=)` shape #213 steers us to rather than `after:`. These interpreters are started once at session open and are expected to run for the whole trading day and across weekend maintenance windows without a `stop()`. At a 1 s beat that is ~86k retained handles per session per day, times the venue-session count, on a process where an unplanned restart to reclaim memory is the one thing a session supervisor must not do — an OOM in the heartbeat group takes down order flow, not a background task. The leak is invisible to every liveness surface: status stays `running`, beats keep landing on time, and the only signal is RSS.

Held at **High** rather than Blocker/Critical because there is no corruption and no wrong semantics, memory **is** reclaimed at `stop()`, and `after:` remains a workaround for any deadline that does not need to survive a restart.

## Proposed fix

One line per engine — key the handle under the **arming state** so the existing state-exit pruner reaches it:

- `src/xstate_statemachine/interpreter.py:2354` — `self._timer_handles.setdefault(self.id, []).append(handle)` → `setdefault(owner_state_id, [])`, matching `_schedule_after` at `:2748`.
- `src/xstate_statemachine/sync_interpreter.py:1198` — the same substitution, matching `:1546`.

Equivalently, and with the same one-line-per-engine cost: **prune on fire** — have `_fire` (and `_cancel`) discard the handle from `_timer_handles` once it can no longer be needed, which is what XState v5's scheduler does.

If keying under the machine id is deliberate — e.g. so a send armed in one state and fired in another survives that state's exit — then the *fired/cancelled* entries still need removing in `_fire`/`_cancel`, and the retention should be documented so callers can bound interpreter lifetime deliberately.

## Acceptance criteria

Named tests, `def` × `async def` × both engines, with the handle count asserted flat over ≥1000 beats:

- `test_timer_handles_pruned_on_delayed_selfsend_fire__async_engine__def` and `…__async_engine__async_def` — run a `raise(delay=)` ping-pong for **≥1000 beats** on `Interpreter`; assert `sum(len(v) for v in i._timer_handles.values())` stays **O(armed), not O(beats)** (≤ a small constant, e.g. 4) at every 100-beat sample, i.e. flat rather than merely bounded at the end.
- `test_timer_handles_pruned_on_delayed_selfsend_fire__sync_engine__def` — the same ≥1000-beat assertion on `SyncInterpreter`, pumped by an undeclared NOOP.
- `test_timer_handles_pruned_after_cancel__both_engines` — arm, `cancel(send_id)`, re-arm in a ≥1000-iteration loop on each engine; assert retention does not grow with the loop count (today `_cancel` leaves the entry behind — posture E above).
- `test_timer_handles_flat_on_never_exiting_state` — the worst case: a single self-looping state that never exits, ≥1000 beats, handle count flat; guards against a fix that only works because states happen to exit.
- `test_after_path_retention_unchanged__def` / `__async_def`, both engines — regression guard: the `after:` control must remain flat at ≤1 handle, i.e. this is fixed by pruning the `raise(delay=)` path, not by loosening the `after` one.
- `test_delayed_selfsend_still_fires_after_arming_state_exits` — semantics guard for the `owner_state_id` variant of the fix: a send armed in state A and due after A exits must still deliver (or, if the chosen semantics is cancellation-on-exit, that must be stated in the CHANGELOG and asserted here deliberately).
- A soak assertion that RSS on a long-running heartbeat machine **plateaus** rather than growing linearly — polled to convergence over ≥10 s, never judged from a single sample.

## Related

- **#212** — establishes that a `raise(delay=)` heartbeat "of any period runs indefinitely, exactly as an `after` one does". That is the contract this violates, and the change that turned this from a ~12-entry cap into an unbounded leak.
- **#213** — snapshot layout v3 / `scheduled_sends`: makes `raise(delay=)` the only restart-safe in-chart deadline primitive, so the leaking spelling is the one callers are steered to.
- **#206** — the superseded chain-charge rule whose `maxIterations` trip previously masked this by killing the cycle at ~12 beats.
- Prior art on the same container: **#49** (state-owned clock timers pruned on exit — the mechanism that works here for `after:`), **#115** (`SimulatedClock._attach()` with no paired detach), **#106** (`Receipt.deferred` keyed in a set that never shrinks).

## Verification

- Repro executed fresh from neutral cwd `C:/Users/basil` against `c78ce99` (`git rev-parse HEAD` = `c78ce991e23c9cdaaeec99b29351ceb690044c2c`), venv `_ref/xstate-statemachine/.venv-main`, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`. **Exit code 1.** Output in *Observed* is that run, verbatim.
- The fenced block under *Minimal reproduction* is **byte-identical** to `repro/R11-04_timer_handles_unbounded_leak.py` (diff-checked after extraction), and imports nothing outside the stdlib and `xstate_statemachine`; all helpers are inlined; no `psutil`.
- Both action spellings (`def`, `async def`) and both engines (`Interpreter`, `SyncInterpreter`) are exercised in a single run, with the `after:` control on every cell.
- Source lines quoted in *Root cause* re-read at `c78ce99`: `interpreter.py:2354`, `:2557`, `:2748`, `:1514-1517`; `sync_interpreter.py:1198`, `:1488`, `:1546`, `:687-690`.
- Contract quotes re-read at `c78ce99`: `CHANGELOG.md:19-24`, `:93-98`.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all --limit 300 --search` over `timer_handles`, `leak`, `memory`, `heartbeat`, `timers` — no existing issue covers `_timer_handles` retention on the delayed-self-send path. Nearest neighbours (#115, #106, #200) are different containers and all CLOSED.
