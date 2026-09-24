"""F. Strict mode + event schemas (#51) and G. cross-thread sends (#37).

F1  strict: an undeclared event type raises UnknownEventError at the call site
F2  the error carries a difflib suggestion
F3  strict does NOT reject a wildcard-covered event ('mouse.*', bare '*')
F4  ctor flag wins over the machine config key
F5  event_schemas: a bad payload raises InvalidEventPayloadError, strict or not
F6  a schema does NOT fire for an event type with no schema registered
F7  strict applies to an INTERNAL `raise` of a typo'd event too
F8  strict + SyncInterpreter parity
F9  system events (done./after.) are never rejected by strict
F10 does strict reject an event only declared on a DEEPLY NESTED state?
F11 does strict reject an event the machine handles only via `onUnhandled`?

G1  send() from a foreign thread raises WrongThreadError (no silent loss)
G2  send_threadsafe() from a foreign thread while the loop is saturated
G3  send_threadsafe ordering under contention from several threads
G4  send_threadsafe after the loop is closed reports a useful error
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Probe  # noqa: E402

from xstate_statemachine import (  # noqa: E402
    Interpreter,
    InvalidEventPayloadError,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    UnknownEventError,
    WrongThreadError,
    create_machine,
)

warnings.simplefilter("ignore", DeprecationWarning)
P = Probe("F/G — strict mode & cross-thread sends")

STRICT_CFG = {
    "id": "s",
    "initial": "a",
    "strict": True,
    "context": {"n": 0},
    "states": {
        "a": {
            "on": {
                "FILL": {"actions": ["bump"]},
                "CANCEL": "b",
            }
        },
        "b": {"on": {"DEEP_ONLY": {"actions": ["bump"]}}},
    },
}


def _bump(i, c, e, a):
    c["n"] += 1


def mk(cfg=None, **kw):
    return create_machine(cfg or STRICT_CFG, logic=MachineLogic(actions={"bump": _bump}), **kw)


async def f1():
    i = await Interpreter(mk()).start()
    try:
        await i.send("FILLL")
        return False, "no error raised for an undeclared event"
    except UnknownEventError as exc:
        return True, f"UnknownEventError: {exc}"
    finally:
        await i.stop()


async def f2():
    i = await Interpreter(mk()).start()
    try:
        await i.send("FIL")
        msg = "(no error)"
    except UnknownEventError as exc:
        msg = str(exc)
    await i.stop()
    return "FILL" in msg, f"message={msg!r}"


WILD_CFG = {
    "id": "w",
    "initial": "a",
    "strict": True,
    "context": {"n": 0},
    "states": {"a": {"on": {"mouse.*": {"actions": ["bump"]}, "*": {"actions": ["bump"]}}}},
}


async def f3():
    i = await Interpreter(mk(WILD_CFG)).start()
    errs = []
    for ev in ("mouse.move", "literally.anything"):
        try:
            await i.send(ev)
        except Exception as exc:  # noqa: BLE001
            errs.append((ev, type(exc).__name__))
    await asyncio.sleep(0.05)
    n = i.context["n"]
    await i.stop()
    return not errs, f"rejections={errs} handled={n}/2"


async def f4():
    cfg = dict(STRICT_CFG)
    cfg["strict"] = True
    i = await Interpreter(mk(cfg), strict=False).start()
    try:
        await i.send("NOT_A_REAL_EVENT")
        ok, detail = True, "ctor strict=False overrode config strict=True (no raise)"
    except UnknownEventError as exc:
        ok, detail = False, f"ctor flag did NOT win: {exc}"
    await asyncio.sleep(0.02)
    await i.stop()
    return ok, detail


class Fill:
    @staticmethod
    def validate(payload):
        if not isinstance(payload.get("qty"), int):
            raise ValueError("qty must be an int")


SCHEMA_CFG = {
    "id": "sc",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"FILL": {"actions": ["bump"]}, "OTHER": {"actions": ["bump"]}}}},
}


async def f5():
    m = create_machine(
        SCHEMA_CFG,
        logic=MachineLogic(actions={"bump": _bump}),
        event_schemas={"FILL": Fill},
    )
    i = await Interpreter(m).start()
    good = bad = None
    try:
        await i.send("FILL", qty=10)
        good = "accepted"
    except Exception as exc:  # noqa: BLE001
        good = f"WRONGLY rejected: {type(exc).__name__}"
    try:
        await i.send("FILL", qty="ten")
        bad = "WRONGLY accepted"
    except InvalidEventPayloadError as exc:
        bad = f"rejected: {type(exc).__name__}"
    await i.stop()
    return (
        good == "accepted" and bad.startswith("rejected"),
        f"valid payload -> {good}; invalid payload -> {bad}",
    )


async def f6():
    m = create_machine(
        SCHEMA_CFG,
        logic=MachineLogic(actions={"bump": _bump}),
        event_schemas={"FILL": Fill},
    )
    i = await Interpreter(m).start()
    try:
        await i.send("OTHER", anything="goes")
        ok, d = True, "unschema'd event accepted with an arbitrary payload"
    except Exception as exc:  # noqa: BLE001
        ok, d = False, f"unschema'd event rejected: {type(exc).__name__}: {exc}"
    await asyncio.sleep(0.02)
    await i.stop()
    return ok, d


RAISE_TYPO_CFG = {
    "id": "rt",
    "initial": "a",
    "strict": True,
    "context": {"n": 0},
    "states": {
        "a": {
            "on": {
                "GO": {
                    "actions": [{"type": "raise", "params": {"event": {"type": "TYPOO"}}}]
                },
                "TYPO": {"actions": ["bump"]},
            }
        }
    },
}


class FailHook(PluginBase):
    def __init__(self):
        self.failures = []

    def on_transition_failed(self, interp, transition, failed_actions):
        self.failures.append([type(e).__name__ for _, e in failed_actions])


async def f7():
    """An internal `raise` of a typo'd event under DEFAULT policy.

    `_check_strict` runs on the raised event too, so an `UnknownEventError`
    IS produced -- but it is raised inside an action, so it becomes an
    ACTION FAILURE, and the default `actionErrorPolicy: "continue"`
    swallows it: `status` stays "running" and `error` stays None. It is
    only observable via `on_transition_failed` or a non-default policy.
    """
    i = await Interpreter(mk(RAISE_TYPO_CFG)).start()
    hook = FailHook()
    i.use(hook)
    await i.send("GO")
    await asyncio.sleep(0.05)
    status, err = i.status, i.error
    await i.stop()
    surfaced_in_status = err is not None or status == "error"
    surfaced_in_hook = any("UnknownEventError" in f for f in hook.failures)
    return (
        surfaced_in_status,
        f"DEFAULT policy: status={status} error={type(err).__name__ if err else None}; "
        f"on_transition_failed saw={hook.failures} "
        f"(detected, but invisible on status/error unless a hook or "
        f"actionErrorPolicy!=continue is configured)",
    )


async def f7b():
    """Same machine under actionErrorPolicy='fail' -- now it is loud."""
    cfg = dict(RAISE_TYPO_CFG)
    cfg["actionErrorPolicy"] = "fail"
    i = await Interpreter(mk(cfg)).start()
    await i.send("GO")
    await asyncio.sleep(0.05)
    status, err = i.status, i.error
    await i.stop()
    return (
        status == "error",
        f'policy="fail": status={status} error={type(err).__name__ if err else None}',
    )


def f8():
    i = SyncInterpreter(mk()).start()
    try:
        i.send("FILLL")
        out = "NOT rejected"
    except UnknownEventError:
        out = "UnknownEventError"
    i.stop()
    return out == "UnknownEventError", f"sync engine: {out}"


async def f9():
    cfg = {
        "id": "sysev",
        "initial": "a",
        "strict": True,
        "context": {"n": 0},
        "states": {"a": {"after": {30: "b"}}, "b": {"type": "final"}},
    }
    i = await Interpreter(mk(cfg)).start()
    await asyncio.sleep(0.2)
    st, status, err = set(i.current_state_ids), i.status, i.error
    await i.stop()
    return (
        err is None and "sysev.b" in st,
        f"states={st} status={status} error={type(err).__name__ if err else None}",
    )


async def f10():
    i = await Interpreter(mk()).start()
    try:
        # DEEP_ONLY is declared on state `b`, which is not active yet.
        await i.send("DEEP_ONLY")
        ok, d = True, "accepted (strict is machine-wide, not per active state)"
    except UnknownEventError as exc:
        ok, d = False, f"rejected though declared elsewhere in the tree: {exc}"
    await asyncio.sleep(0.02)
    await i.stop()
    return ok, d


# ------------------------------------------------------------------- G1..G4
BUSY_CFG = {
    "id": "th",
    "initial": "a",
    "context": {"n": 0, "seen": []},
    "states": {"a": {"on": {"T": {"actions": ["bump2"]}}}},
}


def _bump2(i, c, e, a):
    c["n"] += 1
    c["seen"].append(getattr(e, "payload", {}).get("k"))


async def g1():
    m = create_machine(BUSY_CFG, logic=MachineLogic(actions={"bump2": _bump2}))
    i = await Interpreter(m).start()
    box = {}

    def foreign():
        try:
            i.send("T", k=0)
            box["out"] = "NO ERROR -- event may be silently lost"
        except WrongThreadError as exc:
            box["out"] = f"WrongThreadError ({type(exc).__name__})"
        except Exception as exc:  # noqa: BLE001
            box["out"] = f"{type(exc).__name__}: {exc}"

    t = threading.Thread(target=foreign)
    t.start()
    t.join()
    await asyncio.sleep(0.05)
    n = i.context["n"]
    await i.stop()
    return box["out"].startswith("WrongThreadError"), f"{box['out']}; processed={n}"


async def g2():
    """Foreign thread sends while the loop is saturated with CPU-ish work."""

    async def hog(i):
        # Saturate the loop with work that still yields, as a real app would.
        for _ in range(4000):
            await asyncio.sleep(0)

    m = create_machine(BUSY_CFG, logic=MachineLogic(actions={"bump2": _bump2}))
    i = await Interpreter(m).start()
    task = asyncio.create_task(hog(i))
    sent = 300

    def foreign():
        for k in range(sent):
            i.send_threadsafe("T", k=k)

    t = threading.Thread(target=foreign)
    t.start()
    await task
    t.join()
    await asyncio.sleep(0.8)
    n, seen = i.context["n"], list(i.context["seen"])
    await i.stop()
    return (
        n == sent and seen == list(range(sent)),
        f"delivered={n}/{sent}; order_preserved={seen == list(range(sent))}",
    )


async def g3():
    m = create_machine(BUSY_CFG, logic=MachineLogic(actions={"bump2": _bump2}))
    i = await Interpreter(m).start()
    nthreads, per = 6, 100

    def foreign(tid):
        for k in range(per):
            i.send_threadsafe("T", k=(tid, k))

    threads = [threading.Thread(target=foreign, args=(x,)) for x in range(nthreads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    await asyncio.sleep(1.2)
    seen = list(i.context["seen"])
    n = i.context["n"]
    await i.stop()
    per_thread_ok = all(
        [k for (tid, k) in seen if tid == x] == list(range(per))
        for x in range(nthreads)
    )
    return (
        n == nthreads * per and per_thread_ok,
        f"delivered={n}/{nthreads * per}; per-thread FIFO preserved={per_thread_ok}",
    )


def g4():
    """send_threadsafe after the owning loop is gone.

    Built on a SEPARATE thread so `asyncio.run` owns (and then closes) a
    loop that is not the probe's own.
    """
    box = {}

    def worker():
        async def build():
            m = create_machine(
                BUSY_CFG, logic=MachineLogic(actions={"bump2": _bump2})
            )
            i = await Interpreter(m).start()
            box["i"] = i
            await i.stop()

        asyncio.run(build())  # the loop is closed when this returns

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    i = box["i"]
    try:
        i.send_threadsafe("T", k=1)
        return False, "no error after the loop closed (event silently lost)"
    except RuntimeError as exc:
        return True, f"RuntimeError: {exc}"
    except Exception as exc:  # noqa: BLE001
        return True, f"{type(exc).__name__}: {exc}"


async def main():
    for pid, title, fn in [
        ("F1", "strict rejects unknown event", f1),
        ("F2", "error carries a suggestion", f2),
        ("F3", "wildcards are not rejected", f3),
        ("F4", "ctor flag beats config key", f4),
        ("F5", "event_schemas validate payload", f5),
        ("F6", "no schema -> no validation", f6),
        ("F7", "internal raise: default policy", f7),
        ("F7b", "internal raise: policy=fail", f7b),
        ("F9", "system events exempt", f9),
        ("F10", "strict is machine-wide", f10),
        ("G1", "send() from a foreign thread", g1),
        ("G2", "send_threadsafe under saturation", g2),
        ("G3", "send_threadsafe multi-thread FIFO", g3),
    ]:
        try:
            ok, d = await fn()
            P.check(pid, title, ok, d)
        except Exception as exc:  # noqa: BLE001
            P.record_exc(pid, title, exc)
    for pid, title, fn in [
        ("F8", "sync engine strict parity", f8),
        ("G4", "send_threadsafe after loop close", g4),
    ]:
        try:
            ok, d = fn()
            P.check(pid, title, ok, d)
        except Exception as exc:  # noqa: BLE001
            P.record_exc(pid, title, exc)
    P.report()


if __name__ == "__main__":
    asyncio.run(main())
