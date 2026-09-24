"""N-08 repro: user events namespaced `error.*` / `done.*` are invisible to a
`"*"` handler and exempt from `onUnhandled: "error"`.

`_matching_descriptors` exempts the prefixes
`("done.", "error.", "after.", "xstate.", "___xstate")` from wildcard and partial
matching, so the engine can tell its own synthesised lifecycle events apart from
user traffic. That list is now load-bearing in three places -- the matcher, the
`onUnhandled` policy, and `_check_strict`.

The user-facing consequence is undocumented: an application event that happens to
live in one of those namespaces is silently dropped.

  * `on: {"*": ...}` does NOT match `error.myapp.validation`
  * `onUnhandled: "error"` does NOT raise on an unhandled `done.review`

For a domain that naturally names events `done.review` / `error.validation` --
review workflows, validation pipelines, job runners -- this is exactly the
silent-drop class the 0.8.0 release set out to eliminate.

Exit 1 while the defect is present, 0 once it is fixed (or once such names are
rejected at `create_machine()` time, which is an equally good answer).
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

WILDCARD_CFG = {
    "id": "wc",
    "initial": "a",
    "context": {"caught": []},
    "states": {"a": {"on": {"*": {"actions": ["note"]}}}},
}

ONUNHANDLED_CFG = {
    "id": "ou",
    "initial": "a",
    "onUnhandled": "error",
    "states": {"a": {"on": {"PING": {"target": "a", "reenter": True}}}},
}


def _logic() -> MachineLogic:
    def note(_interp, ctx, event, _action):
        ctx["caught"].append(event.type)

    return MachineLogic(actions={"note": note})


async def wildcard_case() -> list[str]:
    interp = Interpreter(create_machine(WILDCARD_CFG, logic=_logic()))
    await interp.start()
    for ev in ("PLAIN", "error.myapp.validation", "done.review", "my.namespaced"):
        await interp.send(ev)
    await asyncio.sleep(0.05)
    caught = list(interp.context["caught"])
    try:
        await asyncio.wait_for(interp.stop(), timeout=5.0)
    except Exception:  # noqa: BLE001
        pass
    return caught


async def onunhandled_case() -> dict[str, str]:
    out: dict[str, str] = {}
    for ev in ("UNKNOWN_PLAIN", "done.review", "error.validation"):
        interp = Interpreter(create_machine(ONUNHANDLED_CFG))
        await interp.start()
        try:
            await interp.send(ev)
            await asyncio.sleep(0.05)
            out[ev] = "no error" if interp.is_running else "stopped"
        except Exception as exc:  # noqa: BLE001
            out[ev] = type(exc).__name__
        try:
            await asyncio.wait_for(interp.stop(), timeout=5.0)
        except Exception:  # noqa: BLE001
            pass
    return out


async def main() -> int:
    caught = await wildcard_case()
    unhandled = await onunhandled_case()

    print(f"OBSERVED '*' handler caught        : {caught}")
    print("EXPECTED '*' handler caught        : "
          "['PLAIN', 'error.myapp.validation', 'done.review', 'my.namespaced']")
    for ev, res in unhandled.items():
        print(f"OBSERVED onUnhandled='error' {ev:<22}: {res}")
    print("EXPECTED onUnhandled='error' for every unhandled user event: it is reported")

    control_wildcard = "PLAIN" in caught and "my.namespaced" in caught
    control_unhandled = unhandled.get("UNKNOWN_PLAIN") not in (None, "no error")
    if not (control_wildcard and control_unhandled):
        print("RESULT: INCONCLUSIVE - a control did not behave as expected")
        return 1

    missed_wildcard = [
        e for e in ("error.myapp.validation", "done.review") if e not in caught
    ]
    missed_unhandled = [
        e for e in ("done.review", "error.validation") if unhandled.get(e) == "no error"
    ]
    if missed_wildcard or missed_unhandled:
        print(f"OBSERVED invisible to '*'          : {missed_wildcard}")
        print(f"OBSERVED exempt from onUnhandled   : {missed_unhandled}")
        print("RESULT: DEFECT REPRODUCED")
        return 1
    print("RESULT: NOT REPRODUCED (fixed)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
