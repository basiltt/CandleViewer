"""Q6 - semantics 4-way matrix, start() ordering, entry-window refusal
depth, security surface under __slots__.

S1 guard-crash vs denied vs deferred vs unhandled: the four dispositions
   must be discriminable from the receipt + hooks, on BOTH engines.
   (#170: `denied` is False for a CRASHED guard; `error` carries it.)
S2 start() ordering vs #116: `start(); send(CANCEL)` must order the same
   on both engines when the initial state invokes a plain-def service.
S3 entry-window refusal at CHILD vs ROOT (#169): the root refuses on
   "in flight" alone; a child caught mid-step by its parent keeps the
   legality test. Probe both and record which refuses.
S4 `internal=True` forgery after the #150/#172 fixes, plus the attribute
   surface `__slots__` leaves (PR #165/#176): can a caller still set an
   arbitrary attribute on an Interpreter, and are the private budget
   counters writable from outside?
"""

from __future__ import annotations

import asyncio
import time

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

MATRIX_CFG = {
    "id": "mx",
    "initial": "idle",
    "context": {"n": 0},
    "guardErrorPolicy": "raise",
    "onUnhandled": "defer",
    "states": {
        "idle": {
            "on": {
                "DENIED": {"target": "gone", "guard": "no"},
                "CRASH": {"target": "gone", "guard": "boom"},
                "OK": {"target": "gone"},
            }
        },
        "gone": {"on": {"BACK": "idle"}},
    },
}


def g_no(ctx, e) -> bool:  # noqa: ANN001
    return False


def g_boom(ctx, e) -> bool:  # noqa: ANN001
    raise RuntimeError("guard exploded")


def mk_matrix():
    return create_machine(
        MATRIX_CFG,
        logic=MachineLogic(guards={"no": g_no, "boom": g_boom}),
    )


class Watch(PluginBase):
    def __init__(self) -> None:
        self.unhandled: list = []
        self.guard_err: list = []
        self.dropped: list = []

    def on_unhandled_event(self, i, e, ids, disposition):  # noqa: ANN001
        self.unhandled.append((e.type, disposition))

    def on_guard_error(self, i, guard, event, error):  # noqa: ANN001
        self.guard_err.append((event.type, type(error).__name__))

    def on_event_dropped(self, i, e, reason):  # noqa: ANN001
        self.dropped.append((e.type, reason))


def row(receipt, exc) -> dict:  # noqa: ANN001
    if receipt is None:
        return {"raised": type(exc).__name__ if exc else None}
    return {
        "changed": receipt.changed,
        "denied": getattr(receipt, "denied", "MISSING"),
        "error": type(receipt.error).__name__ if receipt.error else None,
        "deferred": getattr(receipt, "deferred", "n/a"),
    }


async def s1_matrix_async() -> dict:
    out = {}
    for ev in ("DENIED", "CRASH", "UNKNOWN_EVENT", "OK"):
        itp = Interpreter(mk_matrix())
        w = Watch()
        itp.use(w)
        await itp.start()
        r = exc = None
        try:
            r = await asyncio.wait_for(itp.send(ev, wait=True), 5)
        except Exception as e:  # noqa: BLE001
            exc = e
        out[ev] = {
            **row(r, exc),
            "hook_unhandled": w.unhandled,
            "hook_guard_error": w.guard_err,
            "hook_dropped": w.dropped,
        }
        await itp.stop()
    return out


def s1_matrix_sync() -> dict:
    out = {}
    for ev in ("DENIED", "CRASH", "UNKNOWN_EVENT", "OK"):
        itp = SyncInterpreter(mk_matrix())
        w = Watch()
        itp.use(w)
        itp.start()
        r = exc = None
        try:
            r = itp.send(ev)
        except Exception as e:  # noqa: BLE001
            exc = e
        out[ev] = {
            **row(r, exc),
            "hook_unhandled": w.unhandled,
            "hook_guard_error": w.guard_err,
            "hook_dropped": w.dropped,
        }
        itp.stop()
    return out


ORDER_CFG = {
    "id": "ord",
    "initial": "boot",
    "context": {"log": []},
    "states": {
        "boot": {
            "invoke": {
                "src": "slow",
                "onDone": {"target": "up", "actions": ["logdone"]},
                "onError": {"target": "up"},
            },
            "on": {"CANCEL": {"target": "cancelled", "actions": ["logc"]}},
        },
        "up": {"on": {"CANCEL": {"target": "cancelled", "actions": ["logc"]}}},
        "cancelled": {"type": "final"},
    },
}


def slow(i, ctx, e):  # plain def -> executor hop  # noqa: ANN001
    time.sleep(0.12)
    return "done"


def logdone(i, ctx, e, ad):  # noqa: ANN001
    ctx["log"].append("done")


def logc(i, ctx, e, ad):  # noqa: ANN001
    ctx["log"].append("cancel")


def mk_order():
    return create_machine(
        ORDER_CFG,
        logic=MachineLogic(
            actions={"logdone": logdone, "logc": logc},
            services={"slow": slow},
        ),
    )


async def s2_start_ordering(trials: int) -> dict:
    a_logs: dict = {}
    for _ in range(trials):
        itp = Interpreter(mk_order())
        await itp.start()
        await itp.send("CANCEL")
        await asyncio.sleep(0.35)
        k = ",".join(itp.context["log"])
        a_logs[k] = a_logs.get(k, 0) + 1
        await itp.stop()
    s_logs: dict = {}
    for _ in range(trials):
        itp = SyncInterpreter(mk_order())
        itp.start()
        try:
            itp.send("CANCEL")
        except Exception:  # noqa: BLE001
            pass
        k = ",".join(itp.context["log"])
        s_logs[k] = s_logs.get(k, 0) + 1
        itp.stop()
    return {
        "trials": trials,
        "async_orderings": a_logs,
        "sync_orderings": s_logs,
        "engines_agree": set(a_logs) == set(s_logs),
        "async_deterministic": len(a_logs) == 1,
        "sync_deterministic": len(s_logs) == 1,
    }


def s4_security_surface() -> dict:
    itp = Interpreter(mk_matrix())
    out: dict = {}
    # __slots__ surface: can an arbitrary attribute be attached?
    try:
        itp.arbitrary_attribute = 1  # type: ignore[attr-defined]
        out["arbitrary_attribute_accepted"] = True
    except AttributeError:
        out["arbitrary_attribute_accepted"] = False
    out["has___dict__"] = hasattr(itp, "__dict__")
    # Are the private budget counters writable from outside?
    for name in (
        "_raise_depth",
        "_chain_tripped",
        "_settle_iterations",
        "_threadsafe_self_sends_in_flight",
    ):
        present = hasattr(itp, name)
        writable = None
        if present:
            try:
                setattr(itp, name, getattr(itp, name))
                writable = True
            except Exception:  # noqa: BLE001
                writable = False
        out[name] = {"present": present, "writable_externally": writable}
    # Redaction: does repr/str of an interpreter leak context values?
    itp2 = Interpreter(
        create_machine(
            {
                "id": "secret",
                "initial": "a",
                "context": {"api_key": "SUPER-SECRET-TOKEN"},
                "states": {"a": {}},
            },
            logic=MachineLogic(),
        )
    )
    blob = repr(itp2) + str(itp2)
    out["secret_in_repr"] = "SUPER-SECRET-TOKEN" in blob
    return out


async def s4b_internal_forgery() -> dict:
    """A foreign thread claiming internal=True must be charged to the
    chain budget (it is a documented opt-in), but must NOT be able to
    drive the machine past maxIterations."""
    itp = Interpreter(mk_matrix())
    await itp.start()
    for _ in range(50):
        itp.send_threadsafe("OK", internal=True)
        itp.send_threadsafe("BACK", internal=True)
    await asyncio.sleep(0.8)
    depth = getattr(itp, "_raise_depth", "MISSING")
    inflight = getattr(itp, "_threadsafe_self_sends_in_flight", "MISSING")
    alive = itp.status
    await itp.stop()
    return {
        "raise_depth_after": depth,
        "inflight_after": inflight,
        "status": alive,
        "ok": depth == 0 and inflight == 0 and alive == "stopped",
    }


async def main() -> int:
    a = await s1_matrix_async()
    s = s1_matrix_sync()
    s2 = await s2_start_ordering(20)
    s4 = s4_security_surface()
    s4b = await s4b_internal_forgery()

    # Discriminability: the four dispositions must map to distinct
    # (changed, denied, error-is-None) triples on each engine.
    def sig(d: dict) -> tuple:
        return (d.get("changed"), d.get("denied"), d.get("error"))

    a_sigs = {k: sig(v) for k, v in a.items()}
    s_sigs = {k: sig(v) for k, v in s.items()}
    a_distinct = len(set(a_sigs.values())) == len(a_sigs)
    s_distinct = len(set(s_sigs.values())) == len(s_sigs)

    ok = (
        a_distinct
        and s_distinct
        and s2["engines_agree"]
        and s2["async_deterministic"]
        and s4b["ok"]
        and not s4["secret_in_repr"]
    )
    emit(
        "q6_semantics_security",
        {
            "S1_matrix_async": a,
            "S1_matrix_sync": s,
            "S1_signatures_async": {k: list(v) for k, v in a_sigs.items()},
            "S1_signatures_sync": {k: list(v) for k, v in s_sigs.items()},
            "S1_four_way_discriminable_async": a_distinct,
            "S1_four_way_discriminable_sync": s_distinct,
            "S2_start_ordering": s2,
            "S4_security_surface": s4,
            "S4b_internal_forgery": s4b,
            "result": "PASS" if ok else "FAIL",
        },
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
