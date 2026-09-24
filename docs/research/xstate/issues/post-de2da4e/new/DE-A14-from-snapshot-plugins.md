---
id: DE-A14
title: "Feature: from_snapshot(plugins=...) so a restore-time refusal can reach on_invalid_event / on_snapshot_error"
labels: [enhancement, persistence, plugins, severity/low]
severity: Low
repro_script: repro/DE-L4-repro.py
commit: de2da4e
verified: true
---

## Summary

This is from our "make it perfect" list after twelve rounds of adoption
review: the library is adopted and running, and these are the few items
left between *adopt with constraints* and *nothing open*.

`from_snapshot` has no `plugins=` parameter, so a restore-time refusal is
structurally unobservable to any `PluginBase` hook. `#214`'s restore path
correctly refuses an undeclared restored event under `strict` and records
it on `last_error` — but `_admit_restored` runs *inside* `from_snapshot`,
strictly before the caller holds the interpreter it would call `.use()` on.
Every other refusal in the library reaches a plugin hook; this one alone
requires attribute polling.

We'd like `from_snapshot` to accept `plugins=` (mirroring
`Interpreter.__init__`) so restore-time refusals reach `on_invalid_event`
— or a new `on_snapshot_error` — the way runtime errors already do.

*(Filed as one item. We had drafted the observability gap and the
`plugins=` ask separately; they are the same defect seen from both ends,
so we merged them rather than open two threads.)*

## Environment

- `xstate-statemachine` @ `de2da4e` (main; `__version__` still `0.8.0`,
  `CHANGELOG.md` `[Unreleased]` targets 0.8.1)
- `.venv-main`, CPython 3.13.7, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`
- cwd `C:/Users/basil` (neutral — outside any project tree)

## Minimal reproduction

```python
"""Re-run our carried restore-observability finding (on_invalid_event unreachable on restore path)
against de2da4e. STANDALONE: stdlib + xstate_statemachine only.
"""
import sys, json
sys.path.insert(0, "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine import create_machine, MachineLogic, SyncInterpreter, PluginBase

cfg = {
    "id": "m", "initial": "w", "strict": True,
    "states": {"w": {"on": {"GO": "done_state"}}, "done_state": {"type": "final"}},
}
m = create_machine(cfg, logic=MachineLogic())
interp = SyncInterpreter(m).start()
snap = json.loads(interp.get_snapshot())
snap["pending_events"] = [{"type": "UNDECLARED", "payload": {}}]
snap = json.dumps(snap)


class Spy(PluginBase):
    def __init__(self):
        self.invalid = []

    def on_invalid_event(self, interpreter, exc, raw):
        self.invalid.append((exc, raw))


spy = Spy()
# The only place `use()` is reachable is on the returned interpreter --
# but _admit_restored runs INSIDE from_snapshot, before this line.
restored = SyncInterpreter.from_snapshot(snap, m)
restored.use(spy)
print("last_error after restore:", restored.last_error)
print("on_invalid_event fired during restore (spy.invalid):", spy.invalid)
reproduced = spy.invalid == [] and restored.last_error is not None
print("hook unreachable during restore (spy empty, last_error set):", reproduced)
print()
print("REPRODUCED:", reproduced)
sys.exit(1 if reproduced else 0)
```

## Observed behaviour

```
last_error after restore: Event 'UNDECLARED' is not declared by machine 'm'. Known events: GO.
on_invalid_event fired during restore (spy.invalid): []
hook unreachable during restore (spy empty, last_error set): True
```

The refusal is correct and is recorded on `last_error`. The spy never
fires, because there is no point in the call sequence at which it could
have been attached.

## Expected behaviour

```python
spy = Spy()
restored = SyncInterpreter.from_snapshot(snap, m, plugins=[spy])
# spy.invalid now carries the refusal, in addition to last_error
```

Either hook is fine by us:

- reuse the existing `on_invalid_event` (a restored undeclared event is
  an invalid event, just one that arrived via a different door), or
- add a dedicated `on_snapshot_error` if a restore refusal is considered
  a distinct event class.

We have no strong preference — only that *some* plugin callback fires
rather than the refusal being reachable solely by polling an attribute.

## Root cause analysis

- `base_interpreter.py:1922-1940` — the restore loop. Each persisted
  record is routed through `interpreter._admit_restored(ev)`
  (`base_interpreter.py:1935`) and skipped on refusal. This is `#214`
  working correctly.
- `base_interpreter.py:1222` — `_admit_restored` is where the refusal is
  decided, and it runs inside the `from_snapshot` classmethod body.
- `from_snapshot`'s signature (`base_interpreter.py:1694`, both engines)
  is `(snapshot_str, machine, *, verify_machine_hash, restart_services,
  restart_timers, clock, minimum_version, expected_machine_hash)` —
  confirmed by introspection on this commit. There is no `plugins=`.

So the interpreter's `_plugins` list is necessarily empty at the moment
the refusal is decided, and the caller's first opportunity to attach one
is after `from_snapshot` has already returned.

## Impact

Low. The `last_error`-polling workaround is functional and we use it
(read `last_error` immediately after `from_snapshot`, before `start()`).
The cost is uniformity: a supervisor that wires error handling through
plugin hooks has to special-case exactly one path, and an adopter who
does not know to poll gets a silent restore that quietly dropped an event.

## Proposed fix

```python
@classmethod
def from_snapshot(cls, snapshot_str, machine, *, plugins=None, ...):
    interpreter = cls(machine)
    for p in plugins or []:
        interpreter.use(p)
    # ... existing admission logic, now with plugins attached, so a
    # refusal in _admit_restored can notify on_invalid_event /
    # on_snapshot_error before from_snapshot returns.
```

## Acceptance criteria

- `from_snapshot(snap, machine, plugins=[p])` registers `p` before
  admission runs, on both `Interpreter` and `SyncInterpreter`.
- A restore refusal (undeclared event under `strict`, per the repro
  above) invokes the chosen hook on every registered plugin, **in
  addition to** — not instead of — setting `last_error`.
- A named test (e.g. `test_from_snapshot_plugins_observe_refusal`) covers
  at least the `strict` undeclared-event shape on both engines and
  asserts the hook fired exactly once with the refusing exception.
- `from_snapshot(...)` calls with no `plugins=` are byte-for-byte
  unaffected (the parameter is optional and defaults to `None`).

## Verification

- Repro run from cwd `C:/Users/basil` with the `.venv-main` interpreter:
  **exit 1**, no `ImportError`, output as quoted above, `REPRODUCED: True`.
- The block under "## Minimal reproduction" is byte-identical to
  `repro/DE-L4-repro.py`.
- Root-cause lines confirmed open in current source at `de2da4e`:
  `base_interpreter.py:1222` (`def _admit_restored`),
  `base_interpreter.py:1935` (`if not interpreter._admit_restored(ev)`),
  and the `from_snapshot` signature confirmed by `inspect.signature` on
  both engines — no `plugins` parameter.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state
  all --limit 320` searched for `from_snapshot plugins`, `plugins`,
  `on_invalid_event` — nothing open; `#214` and `#205` are the nearest
  and both CLOSED.

## Related

- `#214` — the restore-path `strict` fix whose refusal this makes
  observable; **noted on that thread in an earlier round and promoted to
  its own issue for tracking**.
- `#205` — the snapshot trust-boundary thread.
- Our adoption audit (#26).
