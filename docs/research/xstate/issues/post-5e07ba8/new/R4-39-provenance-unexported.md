---
r4: R4-39
title: "Docs: is_system_event and system_event are undocumented and unexported from the package root"
labels: [documentation, severity/low, area/events]
severity: Low
repro_script: repro/R4-39_provenance_unexported.py
commit: 5e07ba8
python: 3.13.7
verified: true
---

## Summary

`is_system_event` is the single predicate that now decides `strict`,
`onUnhandled`, and `"*"` wildcard semantics — three of this release's
significant semantics changes all turn on it — yet it has no guide page at
all and cannot be imported from the package root (`import
xstate_statemachine as xsm; xsm.is_system_event` fails). `system_event`,
described in the changelog as "the ONLY way to produce" an engine event, is
likewise absent from `__all__` and not importable from the package root.
Both are currently reachable only via the internal `xstate_statemachine.events`
submodule, which is not part of the documented public surface.

## Environment

- Commit: 5e07ba8 (unreleased 0.8.1; `__version__` reports 0.8.0)
- Python: 3.13.7
- OS: Windows 11
- Editable install via `.venv-main`

## Current behaviour and why it is insufficient

```python
"""R4-39: the event-provenance mechanism (is_system_event / system_event) is
documented only in the changelog, and both symbols are unexported from the
package's public API.

is_system_event is the single predicate behind `strict`, `onUnhandled` and
`"*"` wildcard semantics -- yet it is absent from __all__ (and so not
importable from the package root, only from the internal `events` submodule),
and has no guide page. system_event, described in the changelog as "the ONLY
way to produce" an engine event, is likewise unexported.

Exits 1 (defect present) while either symbol is missing from
xstate_statemachine.__all__ / cannot be imported from the package root.
Exits 0 once both are exported.
"""
import sys


def main() -> int:
    import xstate_statemachine as xsm

    all_list = getattr(xsm, "__all__", [])
    is_system_event_exported = "is_system_event" in all_list
    system_event_exported = "system_event" in all_list

    is_system_event_importable = hasattr(xsm, "is_system_event")
    system_event_importable = hasattr(xsm, "system_event")

    print("OBSERVED:")
    print(f"  'is_system_event' in xstate_statemachine.__all__ = {is_system_event_exported}")
    print(f"  'system_event' in xstate_statemachine.__all__    = {system_event_exported}")
    print(f"  hasattr(xsm, 'is_system_event')                  = {is_system_event_importable}")
    print(f"  hasattr(xsm, 'system_event')                     = {system_event_importable}")

    print(
        "\nEXPECTED: both 'is_system_event' and 'system_event' are part of "
        "the public API (__all__) and importable from the package root, "
        "with a guide page covering provenance / persist_event / "
        "restore_event"
    )

    defect_present = not (
        is_system_event_exported
        and system_event_exported
        and is_system_event_importable
        and system_event_importable
    )
    if defect_present:
        print("\nRESULT: undocumented/unexported provenance symbols -- defect present")
        return 1
    else:
        print("\nRESULT: symbols exported and importable -- fixed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

## Observed behaviour

```
OBSERVED:
  'is_system_event' in xstate_statemachine.__all__ = False
  'system_event' in xstate_statemachine.__all__    = False
  hasattr(xsm, 'is_system_event')                  = False
  hasattr(xsm, 'system_event')                     = False

EXPECTED: both 'is_system_event' and 'system_event' are part of the public API (__all__) and importable from the package root, with a guide page covering provenance / persist_event / restore_event

RESULT: undocumented/unexported provenance symbols -- defect present
```

A supporting scan of the `docs/` tree for the relevant terms (run separately,
`grep -rl <term> docs/`) found no guide-page hits for `is_system_event`,
`system_event`, `persist_event`, or `restore_event` — only changelog
mentions.

## Expected behaviour

Any symbol that is load-bearing for documented, user-configurable semantics
(`strict`, `onUnhandled`, `"*"` wildcard matching) should be part of the
public API and covered by a guide page, per the library's own convention of
maintaining `__all__` in `__init__.py` as "a clean and stable contract"
(the comment already present at `__init__.py:10`). A changelog entry is not
a substitute for API reference documentation, since changelogs are not
indexed by most doc tooling and are not where a user goes looking for "how
do I tell a system event from a user event".

## Root cause analysis

`src/xstate_statemachine/events.py` defines both symbols:

- `is_system_event` (`events.py:243`) — the predicate.
- `system_event` (`events.py:256`) — the constructor, "the ONLY way to
  produce" an `Event` with `is_system_event(...) == True`.

Neither name appears in `src/xstate_statemachine/events.py`'s own
`__all__` (it has none) nor in `src/xstate_statemachine/__init__.py:190`'s
`__all__` list, which is the file responsible for re-exporting the
package's public surface. Consequently `import xstate_statemachine as xsm`
does not expose either name, and `from xstate_statemachine import
is_system_event` fails with `ImportError`; only reaching into the internal
submodule (`from xstate_statemachine.events import is_system_event`) works,
which is not documented as supported. This has been unchanged since the
prior audit's G-12 finding.

## Impact

For general users, code that needs to distinguish an engine-originated
event (init/exit sentinels, `escalate`, etc.) from a user event — for
example, custom `onUnhandled` handling, logging middleware, or a plugin
that wants to skip system events — has no supported, documented way to do
so; the only path is to reach into an internal submodule that could change
without notice. For the adopting project's order-management scenario, any
plugin or event-sourcing/audit layer that needs to tell "the engine
generated this event" from "a human/upstream service generated this event"
(e.g. to avoid persisting internal engine bookkeeping events as if they
were business events) currently has to depend on undocumented internals to
do it correctly.

## Proposed API/text

1. Add `"is_system_event"` and `"system_event"` to
   `src/xstate_statemachine/__init__.py`'s `__all__` list and import
   statement, so both are reachable as `xstate_statemachine.is_system_event`
   / `xstate_statemachine.system_event`.
2. Add a guide page (e.g. `docs/guide/event-provenance.md`) covering: what
   provenance is, how `system_event`/`is_system_event` relate to `strict`,
   `onUnhandled`, and `"*"` wildcard matching, and how `persist_event` /
   `restore_event` carry provenance across a snapshot round-trip (see
   R4-40 for the deepcopy/pickle boundary this does *not* cover).
3. No compatibility concerns: this only adds new public names; nothing is
   removed or renamed.

## Acceptance criteria

- [ ] `is_system_event` and `system_event` are present in `xstate_statemachine.__all__` and importable from the package root.
- [ ] A new guide page documents provenance semantics and their relationship to `strict`/`onUnhandled`/`"*"`.
- [ ] `tests/test_public_api.py::test_provenance_symbols_exported` (new) asserts both names are in `__all__` and importable.
- [ ] `repro/R4-39_provenance_unexported.py` exits 0.

## Related

- Register source: `probes/main-5e07ba8/r24_docs_undocumented.py`.
- Register row: R4-39 in `30-r4-findings-register.md`.
- Prior finding: unchanged since audit #26's `G-12`.
- See also R4-40 (same mechanism, deepcopy/pickle boundary) — kept as a separate issue per the register's disposition notes, since that one is a documented-limitation item rather than a docs/export gap.

## Verification

- Date: 2026-09-19
- Python: 3.13.7 (`.venv-main`)
- Commit: 5e07ba8 (unreleased 0.8.1; `__version__` reports 0.8.0)
- Ran `repro/R4-39_provenance_unexported.py` in a fresh process: exit code 1, output matches the Observed section (both symbols absent from `__all__` and not `hasattr`-reachable from the package root).
- Confirmed root cause: `src/xstate_statemachine/events.py` defines `is_system_event` (function starts at line 243) and `system_event` (line 256), and neither name appears in `src/xstate_statemachine/__init__.py`'s exports — `grep -n "is_system_event\|system_event" __init__.py` returns zero matches, confirming both are absent from the root package's `__all__`/import list.
- No external XState/SCXML claim to check (this is a library-internal export/documentation gap, not an XState semantics parity claim).
- Checked for duplicates: `gh issue list -R basiltt/xstate-statemachine --state all --search "is_system_event provenance"` finds #79, #98, #85 — all CLOSED issues about the *pre-fix* name-prefix-based system-event detection being spoofable/incorrect (a correctness bug, now fixed by introducing this very `is_system_event`/`system_event` mechanism). None of them concerns the current gap (the fixed mechanism's own symbols being unexported/undocumented), so this is not a duplicate.
- No project name/label leakage found in the file.
- Status: reproducible, defect confirmed present.
