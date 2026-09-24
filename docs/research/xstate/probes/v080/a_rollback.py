"""A. actionErrorPolicy = "rollback" / "fail" — adversarial probe (#27).

Attacks, OMS-style:
  A1  raise in a TRANSITION action           -> context + configuration restored
  A2  raise in an ENTRY action (nested)      -> config restored, target not kept
  A3  raise in an EXIT action                -> config restored
  A4  raise during start() initial entry     -> machine fails, no half state
  A5  parallel target, entry raises in region 2 -> region 1 not left half-entered
  A6  after-timer armed by the partially-entered target is CANCELLED
  A7  invoke armed by the partially-entered target is CANCELLED
  A8  after-timer of the state we EXITED is RE-ARMED by the rollback
  A9  on_transition_failed fires exactly once per failing transition
  A10 last_transition_ok False after failure, True after a later good one
  A11 `raise` already queued by an earlier action in the same list:
      is that side effect rolled back?
  A12 `sendTo` to a child already delivered: rolled back?
  A13 policy "fail" -> status error + TransitionFailedError, machine stops
  A14 targetless/internal self-transition -> context restored
  A15 SYNC engine parity for A1
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
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)

P = Probe("A — actionErrorPolicy rollback/fail")


class Boom(RuntimeError):
    pass


class FailWatcher(PluginBase):
    def __init__(self) -> None:
        self.failures = []
        self.unhandled = []

    def on_transition_failed(self, interp, transition, failed_actions):
        self.failures.append((transition.source.id, len(failed_actions)))

    def on_unhandled_event(self, interp, event, active, disposition):
        self.unhandled.append((event.type, disposition))


def mk(cfg, logic, policy="rollback", **kw):
    cfg = dict(cfg)
    cfg["actionErrorPolicy"] = policy
    return create_machine(cfg, logic=logic, **kw)


# ---------------------------------------------------------------- A1 / A15
TRANS_CFG = {
    "id": "t",
    "initial": "a",
    "context": {"n": 0, "log": []},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["bump", "boom"]}}},
        "b": {},
    },
}


def _bump(i, c, e, a):
    c["n"] += 1
    c["log"].append("bump")


def _boom(i, c, e, a):
    raise Boom("transition action")


TRANS_LOGIC = lambda: MachineLogic(actions={"bump": _bump, "boom": _boom})  # noqa: E731


async def a1():
    w = FailWatcher()
    m = mk(TRANS_CFG, TRANS_LOGIC())
    i = await Interpreter(m).start()
    i.use(w)
    await i.send("GO")
    await asyncio.sleep(0.02)
    ok = i.current_state_ids == {"t.a"} and i.context["n"] == 0
    detail = f"states={i.current_state_ids} n={i.context['n']} log={i.context['log']}"
    await i.stop()
    return ok, detail


def a15():
    m = mk(TRANS_CFG, TRANS_LOGIC())
    i = SyncInterpreter(m).start()
    i.send("GO")
    ok = i.current_state_ids == {"t.a"} and i.context["n"] == 0
    return ok, f"states={i.current_state_ids} n={i.context['n']}"


# ---------------------------------------------------------------- A2 entry
ENTRY_CFG = {
    "id": "e",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {
            "initial": "b1",
            "entry": ["bump"],
            "states": {"b1": {"entry": ["boom"]}},
        },
    },
}


async def a2():
    w = FailWatcher()
    m = mk(ENTRY_CFG, MachineLogic(actions={"bump": _bump, "boom": _boom}))
    i = await Interpreter(m).start()
    i.use(w)
    await i.send("GO")
    await asyncio.sleep(0.02)
    ok = i.current_state_ids == {"e.a"} and i.context["n"] == 0
    detail = f"states={i.current_state_ids} n={i.context['n']} fails={w.failures}"
    await i.stop()
    return ok, detail


# ---------------------------------------------------------------- A3 exit
EXIT_CFG = {
    "id": "x",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"exit": ["boom"], "on": {"GO": "b"}},
        "b": {"entry": ["bump"]},
    },
}


async def a3():
    m = mk(EXIT_CFG, MachineLogic(actions={"bump": _bump, "boom": _boom}))
    i = await Interpreter(m).start()
    await i.send("GO")
    await asyncio.sleep(0.02)
    ok = i.current_state_ids == {"x.a"} and i.context["n"] == 0
    detail = f"states={i.current_state_ids} n={i.context['n']}"
    await i.stop()
    return ok, detail


# ---------------------------------------------------------------- A4 start()
START_CFG = {
    "id": "s",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"entry": ["boom"]}},
}


async def a4():
    m = mk(START_CFG, MachineLogic(actions={"boom": _boom}))
    i = Interpreter(m)
    try:
        await i.start()
    except Exception as exc:  # noqa: BLE001
        return True, f"start raised {type(exc).__name__}"
    detail = f"status={i.status} err={type(i.error).__name__ if i.error else None} states={i.current_state_ids}"
    ok = i.status == "error"
    await i.stop()
    return ok, detail


# ---------------------------------------------------------------- A5 parallel
PAR_CFG = {
    "id": "p",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {
            "type": "parallel",
            "states": {
                "r1": {"initial": "r1a", "states": {"r1a": {"entry": ["bump"]}}},
                "r2": {"initial": "r2a", "states": {"r2a": {"entry": ["boom"]}}},
            },
        },
    },
}


async def a5():
    m = mk(PAR_CFG, MachineLogic(actions={"bump": _bump, "boom": _boom}))
    i = await Interpreter(m).start()
    await i.send("GO")
    await asyncio.sleep(0.02)
    ok = i.current_state_ids == {"p.idle"} and i.context["n"] == 0
    detail = f"states={i.current_state_ids} n={i.context['n']}"
    await i.stop()
    return ok, detail


# ------------------------------------------------- A6 timer armed by target
TIMER_CFG = {
    "id": "tm",
    "initial": "a",
    "context": {"n": 0, "ticks": 0},
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {
            "initial": "b1",
            "after": {30: {"target": "c", "actions": ["tick"]}},
            "states": {"b1": {"entry": ["boom"]}},
        },
        "c": {},
    },
}


async def a6():
    def tick(i, c, e, a):
        c["ticks"] += 1

    m = mk(TIMER_CFG, MachineLogic(actions={"tick": tick, "boom": _boom}))
    i = await Interpreter(m).start()
    await i.send("GO")
    await asyncio.sleep(0.15)
    ok = i.context["ticks"] == 0 and i.current_state_ids == {"tm.a"}
    detail = f"states={i.current_state_ids} ticks={i.context['ticks']}"
    await i.stop()
    return ok, detail


# ------------------------------------------------ A7 invoke armed by target
INVOKE_CFG = {
    "id": "iv",
    "initial": "a",
    "context": {"n": 0, "svc": 0},
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {
            "initial": "b1",
            "invoke": {"id": "s", "src": "svc", "onDone": {"target": "c"}},
            "states": {"b1": {"entry": ["boom"]}},
        },
        "c": {},
    },
}


async def a7():
    started = {"count": 0, "finished": 0}

    async def svc(i, c, e):
        started["count"] += 1
        await asyncio.sleep(0.05)
        started["finished"] += 1
        return "done"

    m = mk(INVOKE_CFG, MachineLogic(actions={"boom": _boom}, services={"svc": svc}))
    i = await Interpreter(m).start()
    await i.send("GO")
    await asyncio.sleep(0.2)
    ok = started["finished"] == 0 and i.current_state_ids == {"iv.a"}
    detail = (
        f"states={i.current_state_ids} svc_started={started['count']} "
        f"svc_finished={started['finished']}"
    )
    await i.stop()
    return ok, detail


# ------------------------------------------ A8 exited state's timer re-armed
REARM_CFG = {
    "id": "ra",
    "initial": "a",
    "context": {"n": 0, "ticks": 0},
    "states": {
        "a": {
            "after": {60: {"target": "z", "actions": ["tick"]}},
            "on": {"GO": {"target": "b", "actions": ["boom"]}},
        },
        "b": {},
        "z": {},
    },
}


async def a8():
    def tick(i, c, e, a):
        c["ticks"] += 1

    m = mk(REARM_CFG, MachineLogic(actions={"tick": tick, "boom": _boom}))
    i = await Interpreter(m).start()
    await asyncio.sleep(0.01)
    await i.send("GO")
    await asyncio.sleep(0.25)
    ok = i.context["ticks"] == 1 and i.current_state_ids == {"ra.z"}
    detail = f"states={i.current_state_ids} ticks={i.context['ticks']}"
    await i.stop()
    return ok, detail


# ------------------------------------------------- A9 hook fires exactly once
async def a9():
    w = FailWatcher()
    m = mk(TRANS_CFG, TRANS_LOGIC())
    i = await Interpreter(m).start()
    i.use(w)
    await i.send("GO")
    await asyncio.sleep(0.02)
    ok = len(w.failures) == 1
    await i.stop()
    return ok, f"on_transition_failed calls={w.failures}"


# ------------------- A9b: entry AND transition action both raise ("continue")
BOTH_CFG = {
    "id": "bo",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["boom"]}}},
        "b": {"entry": ["boom"]},
    },
}


async def a9b():
    w = FailWatcher()
    m = mk(BOTH_CFG, MachineLogic(actions={"boom": _boom}), policy="continue")
    i = await Interpreter(m).start()
    i.use(w)
    await i.send("GO")
    await asyncio.sleep(0.02)
    await i.stop()
    return len(w.failures) == 1, f"continue-policy hook calls={w.failures}"


# ----------------------------------------------------- A10 last_transition_ok
OK_CFG = {
    "id": "lt",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"BAD": {"target": "b", "actions": ["boom"]}, "GOOD": "c"}},
        "b": {},
        "c": {},
    },
}


async def a10():
    m = mk(OK_CFG, MachineLogic(actions={"boom": _boom}))
    i = await Interpreter(m).start()
    seq = [i.last_transition_ok]
    await i.send("BAD")
    await asyncio.sleep(0.02)
    seq.append(i.last_transition_ok)
    await i.send("GOOD")
    await asyncio.sleep(0.02)
    seq.append(i.last_transition_ok)
    await i.stop()
    return seq == [True, False, True], f"sequence={seq} states={i.current_state_ids}"


# ---------------------- A10b: last_transition_ok after an UNHANDLED event
async def a10b_async():
    m = mk(OK_CFG, MachineLogic(actions={"boom": _boom}))
    i = await Interpreter(m).start()
    await i.send("BAD")
    await asyncio.sleep(0.02)
    before = i.last_transition_ok
    await i.send("NOPE")
    await asyncio.sleep(0.02)
    after = i.last_transition_ok
    await i.stop()
    return before, after


def a10b_sync():
    m = mk(OK_CFG, MachineLogic(actions={"boom": _boom}))
    i = SyncInterpreter(m).start()
    i.send("BAD")
    before = i.last_transition_ok
    i.send("NOPE")
    after = i.last_transition_ok
    return before, after


async def a10b():
    ab, aa = await a10b_async()
    sb, sa = a10b_sync()
    ok = aa == sa
    return ok, f"async: {ab}->{aa}  sync: {sb}->{sa} (engines must agree)"


# --------------------------------- A11 `raise` side effect queued then rolled back
RAISE_CFG = {
    "id": "rs",
    "initial": "a",
    "context": {"n": 0, "seen": []},
    "states": {
        "a": {
            "on": {
                "GO": {
                    "target": "b",
                    "actions": [
                        {"type": "raise", "params": {"event": "PING"}},
                        "boom",
                    ],
                },
                "PING": {"actions": ["note"]},
            }
        },
        "b": {"on": {"PING": {"actions": ["note"]}}},
    },
}


async def a11():
    def note(i, c, e, a):
        c["seen"].append(e.type)

    m = mk(RAISE_CFG, MachineLogic(actions={"note": note, "boom": _boom}))
    i = await Interpreter(m).start()
    await i.send("GO")
    await asyncio.sleep(0.05)
    seen = list(i.context["seen"])
    await i.stop()
    ok = seen == []
    return ok, f"seen={seen} states={i.current_state_ids} (rollback should undo the raise)"


# ---------------------------------------------- A12 sendTo child before failure
SENDTO_CFG = {
    "id": "st",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "invoke": {"id": "kid", "src": "kidm"},
            "on": {
                "GO": {
                    "target": "b",
                    "actions": [
                        {
                            "type": "sendTo",
                            "params": {"to": "kid", "event": {"type": "HIT"}},
                        },
                        "boom",
                    ],
                }
            },
        },
        "b": {},
    },
}

KID = {
    "id": "kidm",
    "initial": "idle",
    "context": {"hits": 0},
    "states": {"idle": {"on": {"HIT": {"actions": ["hit"]}}}},
}


async def a12():
    hits = {"n": 0}

    def hit(i, c, e, a):
        hits["n"] += 1

    kid = create_machine(KID, logic=MachineLogic(actions={"hit": hit}))
    m = mk(SENDTO_CFG, MachineLogic(actions={"boom": _boom}, services={"kidm": kid}))
    i = await Interpreter(m).start()
    await asyncio.sleep(0.03)
    await i.send("GO")
    await asyncio.sleep(0.08)
    ok = hits["n"] == 0
    detail = f"child hits={hits['n']} states={i.current_state_ids} (rollback should undo sendTo)"
    await i.stop()
    return ok, detail


# ------------------------------------------------------------- A13 "fail"
async def a13():
    m = mk(TRANS_CFG, TRANS_LOGIC(), policy="fail")
    i = await Interpreter(m).start()
    await i.send("GO")
    await asyncio.sleep(0.03)
    ok = i.status == "error" and type(i.error).__name__ == "TransitionFailedError"
    detail = f"status={i.status} error={type(i.error).__name__ if i.error else None} states={i.current_state_ids} ctx_n={i.context['n']}"
    await i.stop()
    return ok, detail


# ---------------------------------------- A14 targetless self-transition ctx
SELF_CFG = {
    "id": "sf",
    "initial": "a",
    "context": {"n": 0, "log": []},
    "states": {"a": {"on": {"GO": {"actions": ["bump", "boom"]}}}},
}


async def a14():
    m = mk(SELF_CFG, TRANS_LOGIC())
    i = await Interpreter(m).start()
    await i.send("GO")
    await asyncio.sleep(0.02)
    ok = i.context["n"] == 0
    detail = f"n={i.context['n']} log={i.context['log']}"
    await i.stop()
    return ok, detail


async def main() -> None:
    P.run("A1", "rollback: transition action", lambda: asyncio.run_coroutine_threadsafe)  # placeholder replaced below
    P.results.clear()

    async_cases = [
        ("A1", "transition action raises", a1),
        ("A2", "nested entry action raises", a2),
        ("A3", "exit action raises", a3),
        ("A4", "start() initial entry raises", a4),
        ("A5", "parallel region entry raises", a5),
        ("A6", "target's after-timer cancelled", a6),
        ("A7", "target's invoke cancelled", a7),
        ("A8", "source's after-timer re-armed", a8),
        ("A9", "on_transition_failed once", a9),
        ("A9b", "continue-policy hook count", a9b),
        ("A10", "last_transition_ok sequence", a10),
        ("A10b", "last_transition_ok engine parity", a10b),
        ("A11", "queued `raise` rolled back", a11),
        ("A12", "delivered `sendTo` rolled back", a12),
        ("A13", 'policy "fail" stops machine', a13),
        ("A14", "targetless self-transition ctx", a14),
    ]
    for pid, title, fn in async_cases:
        try:
            ok, detail = await fn()
            P.check(pid, title, ok, detail)
        except Exception as exc:  # noqa: BLE001
            P.record_exc(pid, title, exc)

    try:
        ok, detail = a15()
        P.check("A15", "SYNC engine parity (A1)", ok, detail)
    except Exception as exc:  # noqa: BLE001
        P.record_exc("A15", "SYNC engine parity (A1)", exc)

    P.report()


if __name__ == "__main__":
    asyncio.run(main())
