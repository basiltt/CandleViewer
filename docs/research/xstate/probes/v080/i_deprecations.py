"""I. DeprecationWarning emission and the 1.0 flips.

The 0.8.0 contract is "defaults preserve 0.7.x, with warnings pointing at
the 1.0 flips". A team that pins its behaviour before 1.0 needs those
warnings to actually reach it.

I1  actionErrorPolicy unset + a raising action -> one DeprecationWarning
I2  ... and it is ONE-SHOT per machine (not per event)
I3  setting the policy explicitly to "continue" silences it
I4  the warning is NOT emitted when no action ever raises
    (so a clean machine gets no signal it must pin the policy before 1.0)
I5  create_machine(strict_targets=False) with a bad target -> DeprecationWarning
I6  strict_targets default: a bad target is a hard InvalidConfigError
I7  reserved payload keys wait/priority in dict form -> DeprecationWarning
I8  the warning's stacklevel points at USER code, not library internals
I9  SyncInterpreter emits the same actionErrorPolicy warning
I10 two interpreters over the SAME machine object: does the second get a
    warning, or did the first consume the one-shot flag?
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Probe  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    InvalidConfigError,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

P = Probe("I — deprecations & the 1.0 flips")

CFG = {
    "id": "dp",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "on": {
                "BOOM": {"target": "b", "actions": ["boom"]},
                "FINE": {"target": "b", "actions": ["fine"]},
            }
        },
        "b": {"on": {"BACK": "a"}},
    },
}


def _boom(i, c, e, a):
    raise RuntimeError("boom")


def _fine(i, c, e, a):
    c["n"] += 1


def mk(policy=None):
    cfg = dict(CFG)
    if policy:
        cfg["actionErrorPolicy"] = policy
    return create_machine(cfg, logic=MachineLogic(actions={"boom": _boom, "fine": _fine}))


def _dep(caught):
    return [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]


async def i1():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        i = await Interpreter(mk()).start()
        await i.send("BOOM")
        await asyncio.sleep(0.05)
        await i.stop()
    deps = _dep(caught)
    return len(deps) == 1, f"DeprecationWarnings={[str(w.message)[:80] for w in deps]}"


async def i2():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        i = await Interpreter(mk()).start()
        for _ in range(5):
            await i.send("BOOM")
            await asyncio.sleep(0.02)
            await i.send("BACK")
            await asyncio.sleep(0.02)
        await i.stop()
    deps = _dep(caught)
    return len(deps) == 1, f"5 failing transitions produced {len(deps)} warning(s)"


async def i3():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        i = await Interpreter(mk("continue")).start()
        await i.send("BOOM")
        await asyncio.sleep(0.05)
        await i.stop()
    deps = _dep(caught)
    return len(deps) == 0, f"explicit 'continue' produced {len(deps)} warning(s)"


async def i4():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        i = await Interpreter(mk()).start()
        await i.send("FINE")
        await asyncio.sleep(0.05)
        await i.stop()
    deps = _dep(caught)
    return (
        len(deps) >= 1,
        f"a machine whose actions never raise got {len(deps)} warning(s) -- "
        f"it will still FLIP to rollback in 1.0 with no advance notice",
    )


BAD_TARGET = {
    "id": "bt",
    "initial": "a",
    "context": {},
    "states": {"a": {"on": {"GO": "nowhere_at_all"}}, "b": {}},
}


def i5():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        create_machine(BAD_TARGET, logic=MachineLogic(), strict_targets=False)
    deps = _dep(caught)
    return len(deps) >= 1, f"strict_targets=False warnings={[str(w.message)[:90] for w in deps]}"


def i6():
    try:
        create_machine(BAD_TARGET, logic=MachineLogic())
        return False, "an unresolvable target was ACCEPTED by default"
    except InvalidConfigError as exc:
        return True, f"InvalidConfigError: {str(exc)[:120]}"


async def i7():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        i = await Interpreter(mk("continue")).start()
        await i.send({"type": "FINE", "wait": True, "priority": False})
        await asyncio.sleep(0.05)
        await i.stop()
    deps = _dep(caught)
    return len(deps) >= 1, f"reserved-key warnings={[str(w.message)[:90] for w in deps]}"


async def i8():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        i = await Interpreter(mk()).start()
        await i.send("BOOM")
        await asyncio.sleep(0.05)
        await i.stop()
    deps = _dep(caught)
    if not deps:
        return False, "no warning to inspect"
    files = [os.path.basename(w.filename) for w in deps]
    in_library = [f for f in files if f in ("base_interpreter.py", "interpreter.py")]
    return (
        not in_library,
        f"warning attributed to {files} (should be user code, not library internals)",
    )


def i9():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        i = SyncInterpreter(mk()).start()
        i.send("BOOM")
        i.stop()
    deps = _dep(caught)
    return len(deps) == 1, f"sync engine warnings={len(deps)}"


async def i10():
    m = mk()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        i = await Interpreter(m).start()
        await i.send("BOOM")
        await asyncio.sleep(0.05)
        await i.stop()
        first = len(_dep(caught))
        j = await Interpreter(m).start()
        await j.send("BOOM")
        await asyncio.sleep(0.05)
        await j.stop()
        second = len(_dep(caught)) - first
    return (
        second >= 1,
        f"first interpreter warned {first}x, a SECOND interpreter over the same "
        f"machine object warned {second}x (the one-shot flag lives on the machine)",
    )


async def main():
    for pid, title, fn in [
        ("I1", "unset policy + raise -> warning", i1),
        ("I2", "warning is one-shot per machine", i2),
        ("I3", 'explicit "continue" is silent', i3),
        ("I4", "clean machine warned about the flip", i4),
        ("I7", "reserved wait/priority dict keys", i7),
        ("I8", "warning stacklevel points at user", i8),
        ("I10", "second interpreter, same machine", i10),
    ]:
        try:
            ok, d = await fn()
            P.check(pid, title, ok, d)
        except Exception as exc:  # noqa: BLE001
            P.record_exc(pid, title, exc)
    for pid, title, fn in [
        ("I5", "strict_targets=False warns", i5),
        ("I6", "strict_targets default raises", i6),
        ("I9", "sync engine emits the warning", i9),
    ]:
        try:
            ok, d = fn()
            P.check(pid, title, ok, d)
        except Exception as exc:  # noqa: BLE001
            P.record_exc(pid, title, exc)
    P.report()


if __name__ == "__main__":
    asyncio.run(main())
