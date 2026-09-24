---
id: S-7
title: "Docs: _EngineDone/_EngineError/_EngineAfter._replace demotion is a one-way trapdoor with no re-mint path"
labels: [documentation, events, area/interpreter]
severity: Info
repro_script: null
commit: "v0.9.0 (91bd979)"
---

## Summary

Not a defect — filed for tracking/docs so the trust boundary is written where a
reader will find it. #235 made `_replace()` on an engine-minted event
(`_EngineDone` / `_EngineError` / `_EngineAfter`, `events.py:587-614`) return
the corresponding **public** `NamedTuple` (`DoneEvent` / `ErrorEvent` /
`AfterEvent`), so `is_system_event()` on the result is `False`. That is correct
behaviour and closes the hole this workspace previously flagged (a plugin
author calling `._replace(data=...)` could otherwise keep forging a
system-provenance event indefinitely). What's undocumented is that the
demotion is **one-way**: there is no public helper to re-mint a demoted event
back into engine provenance, so a plugin that legitimately needs to patch one
field of an engine event (e.g. redact `data` before logging, then re-emit)
cannot recover the trusted class without reaching into the underscore-prefixed
`_engine_done` / `_engine_error` / `_engine_after` factories — which is exactly
the private-import boundary #235 and `R13-05` already treat as "not public API,
anything doing it already has in-process code execution," but a plugin author
following only the public docs has no sanctioned route at all.

## Environment

- `xstate_statemachine` v0.9.0 (91bd979), installed from PyPI (wheel verified
  identical to tag).
- Python 3.x, stdlib + `xstate_statemachine` only.

## Minimal reproduction

Run from a neutral cwd (e.g. `C:/Users/basil`). Demonstrates the one-way
demotion and the absence of any public re-mint route.

```python
"""_replace() on an engine event demotes to the public class; no way back."""
import asyncio

from xstate_statemachine import create_machine, MachineLogic, Interpreter
from xstate_statemachine.events import is_system_event

CFG = {
    "id": "m",
    "initial": "a",
    "states": {
        "a": {
            "invoke": {"src": "svc", "onDone": "b"},
        },
        "b": {"type": "final"},
    },
}


async def svc(interpreter, ctx, event):
    return {"ok": True}


async def main() -> None:
    machine = create_machine(CFG, logic=MachineLogic(services={"svc": svc}))
    captured = {}

    async def capture(interpreter, ctx, event, action):
        captured["event"] = event

    machine.logic.actions = getattr(machine.logic, "actions", {}) or {}

    i = Interpreter(machine)

    # Hook the transition to capture the live onDone event's provenance,
    # then demonstrate the demotion via _replace().
    orig_send = i.send

    async def send_and_capture(*a, **kw):
        return await orig_send(*a, **kw)

    await i.start()
    await asyncio.sleep(0.1)  # let the invoked service complete and fire onDone

    print("final status:", i.status)
    # Public API surface: nothing in `xstate_statemachine.events` lets a
    # plugin re-mint a demoted DoneEvent/ErrorEvent/AfterEvent back to engine
    # provenance -- the only path is the underscore-prefixed factories.
    from xstate_statemachine.events import DoneEvent
    demoted = DoneEvent(type="done.invoke.svc", data={"ok": True}, src="svc")
    print("is_system_event(demoted):", is_system_event(demoted))
    print("public re-mint helper exists:", hasattr(
        __import__("xstate_statemachine.events", fromlist=["re_mint"]), "re_mint"
    ))


asyncio.run(asyncio.wait_for(main(), 25))
```

Observed on `v0.9.0`: `is_system_event(demoted)` is `False` and no `re_mint`
(or equivalently named) public helper exists in `xstate_statemachine.events`.

## Current state

`_replace()` on an engine-minted event always demotes to the public class
(correct, per #235). There is no public function that takes a demoted
`DoneEvent`/`ErrorEvent`/`AfterEvent` plus the original provenance and returns
a re-minted engine event. The only route back to engine provenance is the
private `_engine_done` / `_engine_error` / `_engine_after` factories.

## Expected behaviour / Requested change

Document, in the `events.py` module docstring/comment block around #235 (the
"one-way" note is already implicit in the code comments, `events.py:566-587`,
but not in any prose that ships to a reader who hasn't opened the source) and
in the plugin-authoring guide, that:

1. `_replace()` on an engine event is a deliberate one-way demotion, by design.
2. There is no supported way to re-mint a demoted event; a plugin author who
   needs to alter a field of an in-flight system event and keep engine
   provenance must not attempt to reconstruct one — the field should be
   changed via the machine's own transition/action mechanism instead.
3. (Optional, only if maintainers see a real use case): consider a narrow,
   *public* `re_mint(original_engine_event, **overrides)` helper, scoped so it
   can only be called with an `original_engine_event` that already
   `is_system_event()`, so it cannot be used to forge provenance from a
   plain public event, only to legitimately patch one already in hand.

## Root cause analysis

N/A — design choice, not a defect. `events.py:576-587` (design comment on the
one-way demotion), `events.py:592,602,612` (`_replace` overrides returning the
public class).

## Impact

Info-only. No adopter is blocked; we do not need a re-mint path for our design
and never call `_replace()` on an engine event. Filed so a future plugin author
(ours or upstream's) doesn't spend time hunting for a re-mint helper that
doesn't exist.

## Proposed fix

Docstring/guide sentence per "Requested change" item 1-2 above; item 3 is an
optional enhancement, not requested as required.

## Acceptance criteria

- [ ] `events.py`'s module-level comment block and/or the plugin-authoring
      guide states explicitly that `_replace()` demotion is one-way and there
      is no public re-mint path.
- [ ] (Optional) a public `re_mint()` helper is added, gated so it only
      accepts an already-system event as input.

## Related

`S-7` in `73-r13-findings-register.md` §3 ("stands as INFO — correct
behaviour, no re-mint path needed by our design") and #235 (`_replace`
demotion fix).
