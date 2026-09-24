---
id: DE-L7
title: "Docs/Perf: engine_* mint helpers are unprefixed in a public module, and _replace retypes on private engine subclasses is undocumented hardening"
labels: [documentation, docs, area/interpreter, events, severity/low]
severity: Info
repro_script: null
commit: de2da4e
verified: true
---

## Summary

This is one of the last items on the "make it perfect" list after twelve
rounds of adoption battle-testing — the library is already adopted and this
sits well inside "adopt with constraints", between that and "nothing open".
Round-12's our own refuted forgery claim refutation (our round-12 verdict note line
306) correctly found no public-API forgery vector, but named one residual
Info-level hardening option verbatim: "override `_replace` on the private
subclasses to return the public class." Separately, the three module-level
mint helpers (`engine_done`, `engine_error`, `engine_after` in `events.py`)
that are the "ONLY sanctioned way" to construct engine-owned events (per
their own docstrings) are ordinary, unprefixed, public-looking names living
in a module (`xstate_statemachine.events`) that end users can and do import
from directly — nothing about their naming signals "internal, do not call
this yourself" the way the `_Engine*` classes' leading underscore does.

## Environment

- `_ref/xstate-statemachine` @ `de2da4e` (targeting 0.8.1; `__version__` still
  0.8.0)
- `.venv-main`, `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`, cwd `C:/Users/basil`

## Current state

```python
"""DE-L7 repro: engine_* factories are unprefixed and importable from a
public module; _replace on a private engine subclass preserves the
engine-minted marker rather than downgrading to the public class.
STANDALONE: stdlib + xstate_statemachine only. Run from cwd C:/Users/basil.
"""
import sys
sys.path.insert(
    0,
    "C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/"
    "xstate-statemachine/src",
)
import xstate_statemachine as x
from xstate_statemachine.events import (
    engine_done, is_system_event,
)

# 1. engine_* factories are plain, unprefixed module-level functions --
#    not exported via __all__, but freely importable from the module.
print("engine_done in package __all__:", "engine_done" in x.__all__)
print("directly importable from events module:", engine_done)

# 2. _replace on a private engine subclass re-mints a genuine engine event
#    with the same subclass, i.e. still trusted as engine-owned.
ev = engine_done("done.invoke.fill", {"x": 1}, "fill")
print("original is_system_event:", is_system_event(ev))
mutated = ev._replace(data={"y": 2})
print("type after _replace:", type(mutated))
print("mutated is_system_event:", is_system_event(mutated))
```

Output on `de2da4e`:

```
engine_done in package __all__: False
directly importable from events module: <function engine_done at 0x...>
original is_system_event: True
type after _replace: <class 'xstate_statemachine.events._EngineDone'>
mutated is_system_event: True
```

## Evidence

- `events.py:560-571` (the `#195` design-note block) states explicitly:
  "The classes are not exported and have no public name; construct through
  the `engine_*` helpers only" — but the helpers themselves
  (`events.py:599-617`, `engine_done`/`engine_error`/`engine_after`) carry no
  underscore prefix and are not gated behind `__all__` membership either way
  (i.e. `from xstate_statemachine.events import engine_done` works exactly
  as easily as importing any other function in the module).
- our round-12 verdict note line 306 (our own refuted forgery claim REFUTED): "Subclass
  preservation across `_replace` / pickle / deepcopy is **documented
  intent**... Residual Info-level hardening option: override `_replace` on
  the private subclasses to return the public class."
- our round-12 security track §1 (R9-01/the separate import-path finding row): the import-path
  `_EngineDone` forgery is the standing Blocker for a *different* vector
  (constructing `_EngineDone` directly via its class name); this issue is
  about the adjacent, narrower surface — the sanctioned `engine_*` helpers
  themselves being unprefixed, and `_replace`'s type-preserving behaviour on
  an event a caller legitimately already holds.

## Requested change

1. Prefix the three mint helpers (`engine_done` → `_engine_done`, etc.) or
   otherwise move them to a clearly private location/naming convention
   consistent with the `_Engine*` classes they construct, so nothing in
   `xstate_statemachine.events` that mints trusted, system-flagged events
   reads as an ordinary public function.
2. Consider (as our own refuted forgery claim itself proposes) overriding `_replace` on
   `_EngineDone`/`_EngineError`/`_EngineAfter` to return the corresponding
   **public** `DoneEvent`/`ErrorEvent`/`AfterEvent` class instead of
   preserving the private subclass — so code that already holds a genuine
   engine event and calls `._replace(...)` on it (a legitimate, everyday
   NamedTuple operation) does not inadvertently keep minting new
   system-trusted events indefinitely from a single original.
3. Document the trade-off either way in the `#195` design-note block: if the
   type-preserving `_replace` behaviour is being kept intentionally (as our own refuted forgery claim
   accepts, since only in-process code with plugin-scope trust can reach it),
   say so explicitly next to the current "not exported and have no public
   name" claim, since that claim no longer feels self-evidently protective of
   the *helpers* if a caller can still hold a reference and keep re-deriving
   trusted events from it via `_replace`.

## Root cause analysis

N/A (asks / hardening request, not a defect with a single reachable failure
mode). Relevant locations: `events.py:599-617` (helper definitions),
`events.py:574-596` (`_EngineDone`/`_EngineError`/`_EngineAfter`, no
`_replace` override), `events.py:560-571` (the design-note claiming the
helpers are "the ONLY sanctioned way").

## Impact

Info-level. our own refuted forgery claim already concluded no public-API forgery vector exists
(every alternative requires importing a private name, poking a frozen
dataclass's private slot, or already holding an engine-minted event from
inside the machine's own trusted action/plugin scope). This ask closes the
last cosmetic gap between "trusted by design" and "looks trusted by
naming", for defense-in-depth and code-review clarity rather than because a
concrete exploit exists today.

## Proposed fix

See "Requested change" above — rename/relocate the three helpers and/or add
`_replace` overrides on the three private subclasses that return their
public superclass.

## Acceptance criteria

- The three mint helpers are renamed or otherwise clearly marked private
  (e.g. `_engine_done`), and all internal call sites are updated; a grep for
  the old public names inside `src/` returns nothing.
- If the `_replace` override is adopted: a new test (e.g.
  `test_engine_event_replace_downgrades_to_public_class`) asserts
  `engine_done(...)._replace(data=...)` returns a plain `DoneEvent` (not
  `_EngineDone`) and `is_system_event(...)` is `False` on the result.
- If the `_replace` override is *not* adopted (kept as documented intent):
  the `#195` design-note comment block explicitly states why, alongside the
  existing "not exported and have no public name" claim.

## Verification

Every factual claim in this issue was checked against the tree at
`de2da4e`, and the probe script `repro/DE-L7-repro.py` was run from the
neutral cwd `C:/Users/basil` with the `.venv-main` interpreter (exit 0 —
this is an observation probe, not a defect assertion):

```
engine_done in package __all__: False
directly importable from events module: <function engine_done at 0x...>
original is_system_event: True
type after _replace: <class 'xstate_statemachine.events._EngineDone'>
mutated is_system_event: True
```

Both halves of the observation hold:

1. **Naming.** `engine_done` is absent from the package `__all__`
   (confirmed by introspection) yet is importable directly from
   `xstate_statemachine.events` under an ordinary, unprefixed name —
   unlike the `_Engine*` classes beside it, whose leading underscore does
   signal internality.
2. **`_replace` retypes.** Calling `_replace` on an engine-minted event
   returns another `_EngineDone`, so `is_system_event` stays `True` on the
   derived value.

- Source locations confirmed open at this commit: `events.py:560-571`
  (the `#195` design-note block beginning "The public `DoneEvent` /
  `ErrorEvent` / `AfterEvent` are documented, ..."), `events.py:574-596`
  (`class _EngineDone(DoneEvent):` at `574`, with no `_replace` override
  on any of the three private subclasses), and `events.py:599-617`
  (`def engine_done(type, data, src) -> DoneEvent:` at `599`, and its two
  siblings).
- This issue deliberately claims **no** exploit. our own refuted forgery claim concluded no
  public-API forgery vector exists, and we agree — see our refutation
  note filed alongside this round's issues. What is filed here is only the
  residual hardening option that refutation itself named, plus the naming
  observation.
- Duplicate check: `gh issue list -R basiltt/xstate-statemachine --state all
  --limit 320` searched for `engine_done`, `_replace`, `is_system_event`,
  `events`. `#195` and `#203` are the originating threads and both CLOSED;
  nothing open covers helper naming or `_replace` typing.

## Related

- our round-12 verdict note (the forgery claim we refuted ourselves, which names this
  exact hardening option)
- our round-12 security track (the separate import-path forgery finding — the
  distinct, more severe import-path forgery vector this issue does not
  attempt to resolve)
