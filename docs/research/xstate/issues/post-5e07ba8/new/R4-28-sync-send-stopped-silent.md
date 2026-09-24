---
r4: R4-28
title: "Bug: send() to a stopped SyncInterpreter is silent while the async engine fires on_event_dropped"
labels: [bug, severity/medium, area/interpreter, area/sync-interpreter, area/observability]
severity: Medium
repro_script: repro/R4-28_sync_send_stopped_silent.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

Sending an event to a stopped or already-done `SyncInterpreter` returns
normally and fires **no hook whatsoever** — not `on_event_received`, not
`on_unhandled_event`, not `on_event_dropped`. The async `Interpreter`, given
the identical scenario, fires `on_event_dropped(reason='not_running')`. The
sync engine simply has no `not_running` drop-hook path in its `send()`. For
any code that relies on plugin hooks for observability/auditing (which is
the library's documented mechanism for exactly this kind of thing), a
command sent into a stopped sync interpreter leaves no trace at all, while
the identical code path on the async engine is fully hooked and observable.

## Environment

- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- Install: editable clone at `_ref/xstate-statemachine`, run via its
  `.venv-main` interpreter

## Minimal reproduction

```python
"""R4-28: send() to a stopped/done machine is silent on the sync engine
(no hook fires at all) while the async engine fires on_event_dropped(reason=
'not_running'). SyncInterpreter has no `not_running` drop-hook path in
send(); Interpreter's send() does.

Exits 1 while the sync engine fires zero hooks (received/unhandled/dropped)
for a send() after stop(), and the async engine fires on_event_dropped for
the identical scenario.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(
    0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src"
)
from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "#m.b"}}, "b": {}}}
LOGIC = MachineLogic(actions={"noop": lambda i, c, e, a: None})


class Watch(PluginBase):
    def __init__(self):
        self.ev, self.un, self.dr = [], [], []

    def on_event_received(self, i, e):
        self.ev.append(e.type)

    def on_unhandled_event(self, i, e, *a, **k):
        self.un.append(e.type)

    def on_event_dropped(self, i, e, reason=None, *a, **k):
        self.dr.append((e.type, reason))


def sync_hooks():
    w = Watch()
    i = SyncInterpreter(create_machine(CFG, logic=LOGIC))
    i.use(w)
    i.start()
    i.stop()
    i.send("GO")
    return (w.ev, w.un, w.dr)


async def async_hooks():
    w = Watch()
    i = Interpreter(create_machine(CFG, logic=LOGIC))
    i.use(w)
    await i.start()
    await i.stop()
    await i.send("GO")
    await asyncio.sleep(0.05)
    return (w.ev, w.un, w.dr)


if __name__ == "__main__":
    s = sync_hooks()
    a = asyncio.run(async_hooks())
    print(f"OBSERVED: sync hooks={s}  async hooks={a}")
    print(
        "EXPECTED: parity -- either both fire on_event_dropped(reason='not_running'), "
        "or both raise a typed InterpreterStoppedError"
    )
    sync_silent = s == ([], [], [])
    async_dropped = a[2] != []
    if sync_silent and async_dropped:
        print("FAIL: sync send() after stop() is silent (no hook at all); async fires on_event_dropped")
        sys.exit(1)
    print("PASS: engines are at parity for send() after stop()")
    sys.exit(0)
```

## Observed behaviour

```
OBSERVED: sync hooks=([], [], [])  async hooks=([], [], [('GO', 'not_running')])
EXPECTED: parity -- either both fire on_event_dropped(reason='not_running'), or both raise a typed InterpreterStoppedError
FAIL: sync send() after stop() is silent (no hook at all); async fires on_event_dropped
```

## Expected behaviour

Sending an event to an interpreter that is not running should be observable
through the same plugin hook mechanism on both engines — either both engines
fire `on_event_dropped(reason='not_running')`, or both raise a typed
`XStateMachineError` subclass (e.g. an `InterpreterStoppedError`). Silently
swallowing the send with zero signal on one engine while the other engine
is fully instrumented is an engine-parity and observability gap.

## Root cause analysis

`SyncInterpreter.send()` has no `not_running`/stopped-state check that
invokes the `on_event_dropped` hook path; it simply falls through without
touching the event pipeline (and without touching any plugin hook) when the
interpreter is not running. `Interpreter.send()` has this check and invokes
`on_event_dropped(reason='not_running')` on its plugins.

## Impact

This is not state corruption, but it is an observability gap on precisely
the engine (`sync_interpreter.py`) most likely to be used on an order-
decision hot path for its lower overhead: a command sent into a stopped
interpreter (e.g. after a crash-recovery race, or a command arriving after
a graceful shutdown) leaves no trace in an audit log built from
`on_event_dropped`/`on_event_received`/`on_unhandled_event` hooks on the sync
engine, while the identical scenario is fully recorded on the async engine.
Any monitoring or alerting built on these hooks will silently miss dropped
commands on the sync engine.

## Proposed fix

Add the equivalent `not_running` drop-hook call to `SyncInterpreter.send()`,
matching `Interpreter.send()`'s behavior, so both engines fire
`on_event_dropped(reason='not_running')` for a send() to a stopped/done
interpreter.

## Acceptance criteria

- [ ] `SyncInterpreter.send()` fires `on_event_dropped(reason='not_running')`
      (or the sync-engine equivalent hook) when called on a stopped or
      already-done interpreter, matching `Interpreter.send()`.
- [ ] A test named `test_sync_send_after_stop_fires_dropped_hook` (or
      equivalent) exists under `tests/`.
- [ ] `repro/R4-28_sync_send_stopped_silent.py` exits 0 once fixed.

## Related

- Register row R4-28 (filed Medium, stands as filed on re-triage).
- Source: `battle-5e07ba8/fuzz/repros.py` (`d3`).

## Verification

- Date: 2026-09-19
- Python: `.venv-main` interpreter, version 3.13.7
- Commit: `5e07ba8` (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-28_sync_send_stopped_silent.py` fresh, standalone: exit code
  `1`, output matched the Observed section verbatim (`sync hooks=([], [],
  [])  async hooks=([], [], [('GO', 'not_running')])`).
- Confirmed root cause: `SyncInterpreter.send()` (`sync_interpreter.py:459+`)
  checks `if self.status != "running": logger.warning(...); return None` —
  a log line only, no plugin hook call of any kind. `Interpreter`'s send
  path (`interpreter.py`) calls `_refuse_if_not_running()`
  (`interpreter.py:790`), which invokes
  `plugin.on_event_dropped(self, event_obj, "not_running")`
  (`interpreter.py:805`) and is exercised from the async `send()`'s
  `_processing`/queue-entry checks (`interpreter.py:606, 620, 633`).
- This finding is an engine-parity/observability claim about the library's
  own plugin API, not an external XState/SCXML semantics claim, so no
  external URL fetch applies.
- No project name/label leak found. No duplicate found; `gh issue list`
  search for "on_event_dropped" surfaced #38 (queue backpressure/
  observability, unrelated) and #77 (macrostep budget event drops, a
  different code path) — neither covers send-after-stop hook parity.
