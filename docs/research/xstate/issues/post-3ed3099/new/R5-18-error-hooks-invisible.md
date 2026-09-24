---
r5: R5-18
title: "Bug: InvalidEventError and SnapshotMidStepError raise correctly but emit to no plugin hook"
labels: [bug, severity/medium, area/plugins]
severity: Medium
repro_script: repro/R5-18_error-hooks-invisible.py
commit: 3ed3099
python: 3.13.7
verified: true
---

## Summary

`send()` correctly raises `InvalidEventError` for a malformed event, and a
mid-action `get_persisted_snapshot()` correctly raises
`SnapshotMidStepError` — the raise-side contract from round 4's `#113` /
`#127`-adjacent hardening works. But neither error reaches any `PluginBase`
hook: a spy bound to every declared `on_*` hook sees only routine
`on_transition` / `on_interpreter_*` / `on_action_execute` /
`on_event_received` traffic, never anything error- or drop-shaped. An
audit log built exclusively from plugin hooks (the documented integration
point, per `PluginBase`'s docstring) is therefore blind to both error
classes even though the caller's own `try/except` sees them fine. The
plumbing that *does* exist is sound elsewhere — `on_plugin_error` fires for
a raising hook, `on_event_dropped` fires with `reason="unresolved_target"` —
so this is a completeness gap in the observability contract, not a broken
mechanism.

## Environment

- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (`main`,
  `[Unreleased] — targeting 0.8.1`; `__version__` still reports `0.8.0`,
  so this build is identified by commit).
- Python: CPython 3.13.7
- OS: Windows 11 Pro 10.0.26200
- Editable install of the repo into a local venv; no library source
  modified.

## Minimal reproduction

```python
"""R5-18 repro: new error classes (InvalidEventError, SnapshotMidStepError,
SnapshotSerializationError) raise correctly but reach NO plugin hook -- an
audit log built from hooks never sees them.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""
import sys

from xstate_statemachine import (
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)


class Spy(PluginBase):
    def __init__(self):
        self.calls = []


def _bind_spy_hooks():
    names = [
        n for n in dir(PluginBase)
        if n.startswith("on_") and callable(getattr(PluginBase, n))
    ]

    def make(name):
        def hook(self, *a, **kw):
            self.calls.append(name)

        return hook

    for n in names:
        setattr(Spy, n, make(n))
    return names


_bind_spy_hooks()

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


def invalid_event_case():
    spy = Spy()
    i = SyncInterpreter(create_machine(CFG, logic=MachineLogic()))
    i.use(spy)
    i.start()
    raised = None
    try:
        i.send(42)  # non-str event type -> InvalidEventError
    except Exception as e:  # noqa: BLE001
        raised = type(e).__name__
    i.stop()
    error_hook_fired = any(
        "error" in c or "failed" in c or "dropped" in c for c in spy.calls
    )
    return raised, sorted(set(spy.calls)), error_hook_fired


def midstep_case():
    spy = Spy()
    res = {}

    def grab(i, c, e, a):
        try:
            i.get_persisted_snapshot()
            res["raise"] = "NO-RAISE"
        except Exception as ex:  # noqa: BLE001
            res["raise"] = type(ex).__name__

    cfg = {
        "id": "ms",
        "initial": "a",
        "states": {
            "a": {"on": {"GO": {"target": "b", "actions": ["grab"]}}},
            "b": {},
        },
    }
    m = create_machine(cfg, logic=MachineLogic(actions={"grab": grab}))
    i = SyncInterpreter(m)
    i.use(spy)
    i.start()
    i.send("GO")
    i.stop()
    error_hook_fired = any(
        "error" in c or "failed" in c or "dropped" in c for c in spy.calls
    )
    return res.get("raise"), sorted(set(spy.calls)), error_hook_fired


def main() -> int:
    raised1, hooks1, fired1 = invalid_event_case()
    raised2, hooks2, fired2 = midstep_case()

    print("OBSERVED:")
    print(f"  send(42) raised            : {raised1}")
    print(f"  hooks seen (InvalidEvent)   : {hooks1}")
    print(f"  error-shaped hook fired     : {fired1}")
    print(f"  mid-action snapshot raised  : {raised2}")
    print(f"  hooks seen (MidStep)        : {hooks2}")
    print(f"  error-shaped hook fired     : {fired2}")

    print("EXPECTED:")
    print("  both raises are true errors, AND a dedicated plugin hook (e.g.")
    print("  on_transition_failed / on_snapshot_error) fires so an audit log")
    print("  built from hooks alone observes them")

    fail = (raised1 == "InvalidEventError" and not fired1) or (
        raised2 == "SnapshotMidStepError" and not fired2
    )
    if fail:
        print("RESULT: FAIL - error raised but invisible to every plugin hook")
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(main())
```

## Observed behaviour

```
OBSERVED:
  send(42) raised            : InvalidEventError
  hooks seen (InvalidEvent)   : ['on_interpreter_start', 'on_interpreter_stop', 'on_transition']
  error-shaped hook fired     : False
  mid-action snapshot raised  : SnapshotMidStepError
  hooks seen (MidStep)        : ['on_action_execute', 'on_event_received', 'on_interpreter_start', 'on_interpreter_stop', 'on_transition']
  error-shaped hook fired     : False
EXPECTED:
  both raises are true errors, AND a dedicated plugin hook (e.g.
  on_transition_failed / on_snapshot_error) fires so an audit log
  built from hooks alone observes them
RESULT: FAIL - error raised but invisible to every plugin hook
```

## Expected behaviour

`PluginBase`'s own docstring frames plugins as the primary observability
surface: `on_action_error`, `on_guard_error`, `on_resolve_error`,
`on_transition_failed` and `on_plugin_error` already exist precisely so an
audit log never has to `try/except` around interpreter calls. The same
contract should extend to `InvalidEventError` (raised by `_prepare_event`
before any transition begins — no transition to attach `on_transition_failed`
to, so it needs its own signal) and to `SnapshotMidStepError` /
`SnapshotSerializationError` (raised by snapshot/persistence code paths that
currently have no hook at all). XState v5's own `inspect()` API does not
have a dedicated error-shaped inspection event either (its four event
types are `@xstate.actor`, `@xstate.event`, `@xstate.snapshot`, and
`@xstate.microstep` — stately.ai/docs/inspection), so this issue does not
lean on that as precedent; the closer XState precedent is the state-level
`onError` transition, which surfaces actor/execution/communication errors
on `event.error` without requiring the caller to wrap every call site in
`try/except` (github.com/statelyai/xstate releases, "Add state-level
onError transitions for handling `xstate.error.*` events") — the same
principle this issue's fix follows for `PluginBase` hooks.

## Root cause analysis

- `sync_interpreter.py` `send()` calls `self._prepare_event(event_or_type, **payload)`
  (`base_interpreter.py:1851`) directly; `_prepare_event` raises
  `InvalidEventError` (`:1892`, `:1898`) with no plugin loop around the
  raise — the call happens before the event is ever queued, so none of the
  transition-scoped hooks (`on_transition_failed` at `base_interpreter.py:3711`,
  `on_action_error` at `:2897`) are in scope.
- `get_persisted_snapshot()` raises `SnapshotMidStepError` when
  `self._processing` is set (guarding the mid-macrostep tear from R4-01);
  the raise is a plain `raise` with no `for plugin in self._plugins: ...`
  loop, unlike `_report_resolve_error` (`base_interpreter.py:1031-1039`),
  which is the pattern this should follow.
- `SnapshotSerializationError` is raised by `_assert_json_safe`
  (`events.py:345-354`), called from `persist_event`, again with no plugin
  notification.
- Existing, working precedent for the same class of gap: `on_resolve_error`
  (`base_interpreter.py:1031`) was added specifically so "observability
  code no longer has to poll `last_error` for this one case" — the same
  reasoning applies unaddressed to these three error classes.

## Impact

General: any adopter relying on plugin hooks as the single source of truth
for an audit/metrics pipeline (the documented integration pattern) silently
misses malformed-event rejections and mid-macrostep snapshot refusals —
exactly the events a security or compliance audit most wants recorded,
since they represent hostile or buggy callers.

Concrete order-management scenario: an OMS wiring a `PluginBase` subclass
to Splunk/Datadog for compliance logging sees zero record of a downstream
service sending a malformed order event (`InvalidEventError`) or of a
concurrent snapshotter colliding with an in-flight transition
(`SnapshotMidStepError`). Both look, from the audit trail, like nothing
happened — but the interpreter behind the scenes rejected real input.

## Proposed fix

Add two hooks to `PluginBase` (default no-op, following the existing
pattern) and fire them at the raise sites:

- `on_invalid_event(self, interpreter, exc, raw_event)` — called from
  `_prepare_event`'s except-and-reraise wrapper (or by having callers of
  `_prepare_event` wrap it) before the `InvalidEventError` propagates.
- `on_snapshot_error(self, interpreter, exc)` — called from
  `get_persisted_snapshot()` / `persist_event()` immediately before
  `SnapshotMidStepError` / `SnapshotSerializationError` propagate, mirroring
  `_report_resolve_error`'s `for plugin in self._plugins: plugin.on_resolve_error(...)`
  shape exactly.

Compatibility: purely additive — new no-op hook methods on `PluginBase`,
new call sites that fire-then-reraise (behavior for callers without a
plugin is unchanged).

## Acceptance criteria

- [ ] `repro/R5-18_error-hooks-invisible.py` exits `0`.
- [ ] `tests/test_plugins.py::test_invalid_event_fires_on_invalid_event_hook`
- [ ] `tests/test_plugins.py::test_midstep_snapshot_fires_on_snapshot_error_hook`
- [ ] `tests/test_plugins.py::test_serialization_error_fires_on_snapshot_error_hook`
- [ ] `tests/test_plugins.py::test_hooks_fire_before_reraise_not_swallowing_original_exception`
- [ ] Changelog entry documenting the two new hooks.

## Related

- Register source: R5-18, evidence `determinism/n6_observability.py::O1`,
  `triage-r5/t4_final.py`.
- Adjacent, not counted this round: `31-r5-gate.md` **LC-48** raised a
  similar-shaped claim about `on_transition_failed` ordering relative to
  `on_transition`; that was a single unreplicated run and is not folded
  into this issue — flag for a separate two-run repro if pursued.
- `#113` (InvalidEventError itself), `#134`/`#127` (on_resolve_error /
  on_plugin_error precedent this issue's fix follows).

## Verification

- Date: 2026-09-19
- Python: CPython 3.13.7 (`.venv-main`)
- Commit: `3ed3099096d15544e96c9d9458c21c2a30ef48e3` (`main`, unreleased 0.8.1)
- Re-ran `repro/R5-18_error-hooks-invisible.py` fresh: exit 1.
- Root-cause file:line citations checked against `src/xstate_statemachine`
  at this commit; all confirmed exact.
- Duplicates check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 150 --search "<keyword>"` run for this finding's keywords; no
  round-4 issue (#102-#138, all CLOSED) covers this exact gap — closest related are #134/#127/#33 (plugin hook precedent), none of which added the two missing hooks this issue proposes.
