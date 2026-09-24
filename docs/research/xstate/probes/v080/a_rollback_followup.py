"""A-follow-up: confirm the two rollback findings with controls.

A11c  control: without the failing action, does the raised PING arrive?
A11s  same escape on the SYNC engine?
A12c  control: without the failing action, does the sendTo reach the child?
      (A12 "passing" is only meaningful if the control shows delivery.)
A16   does the escaped raise get delivered even under policy "fail"
      (machine already in error status)?
A17   read-immediately trap: last_transition_ok is reset to True by the NEXT
      event, including an unhandled one.
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Probe  # noqa: E402

import a_rollback as A  # noqa: E402
from xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)
P = Probe("A-follow — controls for the rollback findings")


def _noop(i, c, e, a):
    pass


async def a11c():
    def note(i, c, e, a):
        c["seen"].append(e.type)

    m = A.mk(A.RAISE_CFG, MachineLogic(actions={"note": note, "boom": _noop}))
    i = await Interpreter(m).start()
    await i.send("GO")
    await asyncio.sleep(0.05)
    seen = list(i.context["seen"])
    st = i.current_state_ids
    await i.stop()
    return seen == ["PING"], f"control (no failure): seen={seen} states={st}"


def a11s():
    def note(i, c, e, a):
        c["seen"].append(e.type)

    m = A.mk(A.RAISE_CFG, MachineLogic(actions={"note": note, "boom": A._boom}))
    i = SyncInterpreter(m).start()
    i.send("GO")
    seen = list(i.context["seen"])
    return seen == [], f"sync engine: seen={seen} states={i.current_state_ids}"


async def a16():
    def note(i, c, e, a):
        c["seen"].append(e.type)

    m = A.mk(
        A.RAISE_CFG,
        MachineLogic(actions={"note": note, "boom": A._boom}),
        policy="fail",
    )
    i = await Interpreter(m).start()
    await i.send("GO")
    await asyncio.sleep(0.05)
    seen = list(i.context["seen"])
    st, status = i.current_state_ids, i.status
    await i.stop()
    return seen == [], f'policy="fail": seen={seen} status={status} states={st}'


async def a12c():
    hits = {"n": 0}

    def hit(i, c, e, a):
        hits["n"] += 1

    kid = create_machine(A.KID, logic=MachineLogic(actions={"hit": hit}))
    m = A.mk(
        A.SENDTO_CFG, MachineLogic(actions={"boom": _noop}, services={"kidm": kid})
    )
    i = await Interpreter(m).start()
    await asyncio.sleep(0.03)
    await i.send("GO")
    await asyncio.sleep(0.1)
    n, st = hits["n"], i.current_state_ids
    await i.stop()
    return n == 1, f"control (no failure): child hits={n} states={st}"


async def a17():
    m = A.mk(A.OK_CFG, MachineLogic(actions={"boom": A._boom}))
    i = await Interpreter(m).start()
    await i.send("BAD")
    await asyncio.sleep(0.02)
    after_fail = i.last_transition_ok
    await i.send("UNKNOWN_EVENT")
    await asyncio.sleep(0.02)
    after_unhandled = i.last_transition_ok
    await i.stop()
    return (
        after_fail is False and after_unhandled is True,
        f"after failure={after_fail}; after an UNHANDLED event={after_unhandled} "
        f"(flag is per-event, not sticky)",
    )


async def main():
    cases = [
        ("A11c", "control: raise delivered normally", a11c),
        ("A12c", "control: sendTo delivered normally", a12c),
        ("A16", "escaped raise under policy=fail", a16),
        ("A17", "last_transition_ok not sticky", a17),
    ]
    for pid, title, fn in cases:
        try:
            ok, d = await fn()
            P.check(pid, title, ok, d)
        except Exception as exc:  # noqa: BLE001
            P.record_exc(pid, title, exc)
    try:
        ok, d = a11s()
        P.check("A11s", "sync: raise rolled back", ok, d)
    except Exception as exc:  # noqa: BLE001
        P.record_exc("A11s", "sync: raise rolled back", exc)
    P.report()


if __name__ == "__main__":
    asyncio.run(main())
