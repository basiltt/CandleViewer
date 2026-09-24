---
r4: R4-36
title: "Feature: add an on_resolve_error plugin hook for unresolved transition targets"
labels: [enhancement, severity/low, area/observability]
severity: Low
repro_script: repro/R4-36_no_resolve_error_hook.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

When `strict_targets=False` is used at machine-build time and a transition's
target string cannot be resolved at runtime, the interpreter surfaces the
failure through `Receipt.error`, `last_error`, and an ERROR-level log record —
but no plugin hook fires for it. This is inconsistent with the two other
per-transition failure categories the interpreter already has dedicated hooks
for: `on_action_error` (action raises) and `on_guard_error` (guard raises).
For a long-running stateful service that centralizes all its error telemetry
in a `PluginBase` subclass (a common pattern for metrics/alerting), this
failure mode is invisible to that subclass and only catchable by polling
`last_error` after every `send()`.

## Environment

- Commit: 5e07ba8 (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- OS: Windows 11
- Editable install via `.venv-main`

## Minimal reproduction

```python
"""R4-36: StateNotFoundError under strict_targets=False has no dedicated
plugin hook.

When a transition's target cannot be resolved (allowed because the machine
was built with strict_targets=False), the interpreter surfaces the failure
via Receipt.error / last_error and an ERROR log record, but no plugin
on_* hook fires for it -- unlike action failures (on_action_error) and
guard failures (on_guard_error), which both have a dedicated hook.

Exits 1 (defect present: no dedicated hook fired) while the gap exists,
0 once a hook such as on_resolve_error is added and fires here.
"""
import sys

from xstate_statemachine import (
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)


class Recorder(PluginBase):
    def __init__(self):
        self.calls = []

    def on_action_error(self, interpreter, action, error):
        self.calls.append("on_action_error")

    def on_guard_error(self, interpreter, guard_name, event, error):
        self.calls.append("on_guard_error")

    def on_error(self, interpreter, error):
        self.calls.append("on_error")

    def on_transition_failed(self, interpreter, transition, failed_actions):
        self.calls.append("on_transition_failed")


def main() -> int:
    cfg = {
        "id": "m_snf",
        "initial": "a",
        "states": {"a": {"on": {"GO": "does.not.exist"}}},
    }
    machine = create_machine(cfg, logic=MachineLogic(), strict_targets=False)
    rec = Recorder()
    interp = SyncInterpreter(machine).use(rec).start()

    receipt = interp.send("GO", wait=True)

    print("OBSERVED:")
    print(f"  receipt.error        = {receipt.error!r}")
    print(f"  last_transition_ok   = {interp.last_transition_ok}")
    print(f"  last_error           = {interp.last_error!r}")
    print(f"  plugin hooks fired   = {rec.calls}")

    dedicated_hook_fired = any(
        name not in ("on_error",) for name in rec.calls
    ) and any("resolve" in name for name in rec.calls)

    print(
        "\nEXPECTED: a dedicated hook (e.g. on_resolve_error) fires, "
        "mirroring on_action_error / on_guard_error"
    )

    if dedicated_hook_fired:
        print("RESULT: dedicated resolve-error hook fired -- fixed")
        return 0
    else:
        print("RESULT: no dedicated resolve-error hook fired -- defect present")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

## Observed behaviour

```
OBSERVED:
  receipt.error        = StateNotFoundError("Could not resolve target state 'does.not.exist' from state 'm_snf.a'.")
  last_transition_ok   = False
  last_error           = StateNotFoundError("Could not resolve target state 'does.not.exist' from state 'm_snf.a'.")
  plugin hooks fired   = []

EXPECTED: a dedicated hook (e.g. on_resolve_error) fires, mirroring on_action_error / on_guard_error
RESULT: no dedicated resolve-error hook fired -- defect present
```

(A `DeprecationWarning` about `strict_targets=False` being removed in 1.0 is
also emitted, which is expected and unrelated to this finding.)

## Expected behaviour

The library's own `PluginBase` contract already establishes the pattern that
every distinct per-transition failure category gets its own hook so
observability code does not have to special-case one failure mode as
"poll a property" while all the others are "implement a callback". Both
`on_action_error` and `on_guard_error` exist for exactly this reason. A
resolver failure (raised from `_execute_transition` in
`base_interpreter.py`, see below) is architecturally the same kind of
per-transition failure and should follow the same contract.

## Root cause analysis

`src/xstate_statemachine/base_interpreter.py:2230` (`_execute_transition`)
resolves the transition's target at `base_interpreter.py:2255-2264`:

```python
target_state = (
    transition.resolved_target
    or self._resolve_target_state_node(transition)
)
if target_state is None:
    raise StateNotFoundError(
        transition.target_str, transition.source.id
    )
```

This is a bare `raise`, with no call site to a plugin hook, unlike the
action-error path (`base_interpreter.py:2603-2611`, `_run_one_action` /
`on_action_error`) and the guard-error path (`base_interpreter.py:4166`,
`on_guard_error`), both of which explicitly loop over `self._plugins` and
call the corresponding hook before/while surfacing the error via
`Receipt`/`last_error`. The `StateNotFoundError` raised here is instead
caught further up the call stack (e.g. `base_interpreter.py:3056`) and
converted into `Receipt.error` / `last_error` / a log record only, with no
plugin dispatch in between.

## Impact

For general users, any `PluginBase`-based observability/metrics layer will
have a blind spot for this one failure category, silently under-reporting
resolver failures relative to action/guard failures in dashboards or alerts
built purely on plugin hooks. For the adopting project's order-management
scenario, an order state machine that uses `strict_targets=False` (e.g.
during a migration where some target states are added dynamically) and
relies on a plugin-based audit trail would miss resolver failures in that
audit trail even though `last_error` still reflects them — a caller that
only wires up plugins (and doesn't also poll `last_error` after every
`send()`) gets an incomplete error log. The practical severity is Low
because checking `last_transition_ok`/`last_error` after every `send()` is
a sufficient existing substitute already recommended by the library's own
`Receipt` contract.

## Proposed fix

Add a new `on_resolve_error(interpreter, transition, error)` hook to
`PluginBase`, with a no-op default implementation (matching the pattern of
the existing hooks), and call it from the `target_state is None` branch in
`_execute_transition` (`base_interpreter.py:2264`) before raising
`StateNotFoundError`, mirroring how `_run_one_action` calls
`on_action_error` before continuing. No compatibility concerns: existing
`PluginBase` subclasses are unaffected since the new hook has a default
no-op implementation.

Alternative: fold this into a single generalized `on_transition_error`
hook that all three failure categories (action/guard/resolve) call, but
this would be a breaking rename of the two existing hooks and is not
recommended for a point release.

## Acceptance criteria

- [ ] `PluginBase.on_resolve_error(self, interpreter, transition, error)` exists with a no-op default.
- [ ] `_execute_transition` calls `on_resolve_error` on every registered plugin when target resolution fails (mirroring `on_action_error`/`on_guard_error`).
- [ ] `tests/test_plugins.py::test_on_resolve_error_hook_fires_on_unresolved_target` (new) asserts the hook fires exactly once with the correct transition/error.
- [ ] `repro/R4-36_no_resolve_error_hook.py` exits 0.

## Related

- Register source: `battle-5e07ba8/observability/probe_matrix.py` (probe 9, "StateNotFound under strict_targets=False").
- Register row: R4-36 in `30-r4-findings-register.md`.
- Sibling hooks: `on_action_error`, `on_guard_error` in `base_interpreter.py`.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: 5e07ba8 (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-36_no_resolve_error_hook.py` in a fresh process: exit code 1, output matches the Observed section above (`plugin hooks fired = []`, `receipt.error`/`last_error` both `StateNotFoundError`).
- Confirmed root cause: `base_interpreter.py`'s `_execute_transition` raises `StateNotFoundError` with no plugin dispatch when `target_state is None` (lines ~2255-2264), while the sibling failure paths do dispatch a hook — `_report_action_failure` calls `plugin.on_action_error(...)` (~2603-2611) and the guard-error path calls `plugin.on_guard_error(...)` (~4165-4166). Line numbers shift by a few lines from the register's citation but the code shape matches exactly.
- No external XState/SCXML claim to check (this is an internal API-consistency argument about the library's own `PluginBase` contract).
- Checked for duplicates: `gh issue list -R basiltt/xstate-statemachine --state all --search "resolve error hook"` returns only unrelated prior hook-related issues (#33, #35, #27, #39, #51, etc.), all closed and about different gaps (no `on_transition_failed`/guard-error hooks, which were already fixed). No duplicate for a dedicated `on_resolve_error` hook.
- No project name/label leakage found in the file.
- Status: reproducible, defect confirmed present.
