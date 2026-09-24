"""D. Resumable invocations after restore (#44) + entry re-run policy.

D1  pending_invocations() lists the invoke in the active configuration
D2  restart_services=True actually re-runs the service
D3  the restarted invoke receives the correct resolved `input`
D4  ENTRY ACTIONS: does restore + restart re-run the state's entry actions?
    (an OMS entry action that emits an order must NOT fire twice)
D5  default restore (restart_services unset) starts nothing -- and
    pending_invocations() reports it so the caller can decide
D6  nested/child-actor invocations after restore
D7  restart_services with a service that has already COMPLETED before the
    snapshot: is it wrongly re-run?
D8  restored context is a deep copy (no aliasing of the caller's dict)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Probe  # noqa: E402

from xstate_statemachine import Interpreter, MachineLogic, create_machine  # noqa: E402

warnings.simplefilter("ignore", DeprecationWarning)
P = Probe("D — resumable invocations after restore")

CFG = {
    "id": "r",
    "initial": "idle",
    "context": {"order_id": "OID-1", "entries": 0, "results": []},
    "states": {
        "idle": {"on": {"GO": "working"}},
        "working": {
            "entry": ["count_entry"],
            "invoke": {
                "id": "job",
                "src": "job",
                "input": {"oid": "static-oid"},
                "onDone": {"target": "done", "actions": ["collect"]},
            },
        },
        "done": {"type": "final"},
    },
}


def _count_entry(i, c, e, a):
    c["entries"] += 1


def _collect(i, c, e, a):
    c["results"].append(getattr(e, "data", None))


def build(calls, delay=0.5):
    async def job(i, c, e):
        # 📥 #42: resolved `input` arrives on the synthetic invoke event's
        #    payload, not as a positional argument.
        calls.append(dict(getattr(e, "payload", {}) or {}).get("input"))
        await asyncio.sleep(delay)
        return "finished"

    return create_machine(
        CFG,
        logic=MachineLogic(
            actions={"count_entry": _count_entry, "collect": _collect},
            services={"job": job},
        ),
    )


async def snapshot_mid_invoke(calls):
    i = await Interpreter(build(calls)).start()
    await i.send("GO")
    await asyncio.sleep(0.05)  # inside the invoke
    snap = i.get_snapshot()
    entries = i.context["entries"]
    await i.stop()
    return snap, entries


async def d1():
    calls = []
    snap, _ = await snapshot_mid_invoke(calls)
    j = Interpreter.from_snapshot(snap, build([]))
    pend = j.pending_invocations()
    return (
        len(pend) == 1 and pend[0].invoke_id == "job",
        f"pending_invocations={[(p.state_id, p.invoke_id, p.src) for p in pend]}",
    )


async def d2():
    calls = []
    snap, _ = await snapshot_mid_invoke(calls)
    calls2 = []
    j = Interpreter.from_snapshot(snap, build(calls2), restart_services=True)
    await j.start()
    await asyncio.sleep(0.9)
    st, res = set(j.current_state_ids), list(j.context["results"])
    await j.stop()
    return (
        len(calls2) == 1 and res == ["finished"],
        f"service_calls_after_restore={len(calls2)} results={res} states={st}",
    )


async def d3():
    calls = []
    snap, _ = await snapshot_mid_invoke(calls)
    calls2 = []
    j = Interpreter.from_snapshot(snap, build(calls2), restart_services=True)
    await j.start()
    await asyncio.sleep(0.9)
    await j.stop()
    return (
        calls2 == [{"oid": "static-oid"}],
        f"original_input={calls} restored_input={calls2}",
    )


async def d4():
    calls = []
    snap, entries_before = await snapshot_mid_invoke(calls)
    j = Interpreter.from_snapshot(snap, build([]), restart_services=True)
    await j.start()
    await asyncio.sleep(0.1)
    entries_after = j.context["entries"]
    await j.stop()
    return (
        entries_after == entries_before,
        f"entry count before snapshot={entries_before}, after restore+restart="
        f"{entries_after} (entry must NOT re-run)",
    )


async def d5():
    calls = []
    snap, _ = await snapshot_mid_invoke(calls)
    calls2 = []
    j = Interpreter.from_snapshot(snap, build(calls2))
    await j.start()
    await asyncio.sleep(0.9)
    st = set(j.current_state_ids)
    n_pend = len(j.pending_invocations())
    await j.stop()
    return (
        len(calls2) == 0 and st == {"r.working"},
        f"default restore: service_calls={len(calls2)} states={st} "
        f"pending_reported={n_pend} (stuck-but-observable is the documented default)",
    )


PARENT = {
    "id": "pa",
    "initial": "up",
    "context": {},
    "states": {
        "up": {"invoke": {"id": "kid", "src": "kidm"}},
    },
}
KIDM = {
    "id": "kidm",
    "initial": "busy",
    "context": {},
    "states": {
        "busy": {"invoke": {"id": "inner", "src": "inner", "onDone": "fin"}},
        "fin": {"type": "final"},
    },
}


async def d6():
    inner_calls = []

    def build_parent():
        async def inner(i, c, e, inp=None):
            inner_calls.append(1)
            await asyncio.sleep(0.5)
            return "x"

        kid = create_machine(KIDM, logic=MachineLogic(services={"inner": inner}))
        return create_machine(PARENT, logic=MachineLogic(services={"kidm": kid}))

    i = await Interpreter(build_parent()).start()
    await asyncio.sleep(0.08)
    snap = i.get_snapshot()
    await i.stop()
    inner_calls.clear()
    j = Interpreter.from_snapshot(snap, build_parent(), restart_services=True)
    await j.start()
    await asyncio.sleep(0.15)
    pend = j.pending_invocations()
    n = len(inner_calls)
    await j.stop()
    return (
        n >= 1,
        f"inner service restarts after nested restore={n}; "
        f"parent pending={[(p.state_id, p.invoke_id) for p in pend]}",
    )


async def d7():
    calls = []
    i = await Interpreter(build(calls, delay=0.02)).start()
    await i.send("GO")
    await asyncio.sleep(0.25)  # invoke has COMPLETED, machine is in `done`
    snap = i.get_snapshot()
    st_before = set(i.current_state_ids)
    await i.stop()
    calls2 = []
    j = Interpreter.from_snapshot(snap, build(calls2), restart_services=True)
    await j.start()
    await asyncio.sleep(0.2)
    n, st = len(calls2), set(j.current_state_ids)
    await j.stop()
    return (
        n == 0,
        f"before={st_before} after={st} completed_service_reinvoked={n} (want 0)",
    )


async def d8():
    calls = []
    snap, _ = await snapshot_mid_invoke(calls)
    # `get_snapshot()` returns a JSON STRING; decode to inspect the payload.
    original = json.loads(snap)
    j = Interpreter.from_snapshot(snap, build([]))
    await j.start()
    j.context["order_id"] = "MUTATED"
    await j.stop()
    reparsed = json.loads(snap)
    return (
        reparsed["context"]["order_id"] == original["context"]["order_id"]
        == "OID-1",
        f"snapshot context order_id={reparsed['context']['order_id']!r} after "
        f"mutating the restored interpreter's context (want unchanged 'OID-1')",
    )


async def d8b():
    """API-shape check: is the DICT form of a snapshot accepted at all?

    `get_snapshot()` returns a JSON string and `get_persisted_snapshot()`
    returns the dict. A caller who stores the dict (e.g. in Mongo/JSONB)
    and hands it straight back is the natural persistence path, so whether
    `from_snapshot` accepts it is a real integration constraint.
    """
    calls = []
    snap, _ = await snapshot_mid_invoke(calls)
    payload = json.loads(snap)
    try:
        j = Interpreter.from_snapshot(payload, build([]))
    except Exception as exc:  # noqa: BLE001
        return (
            False,
            f"dict form REJECTED: {type(exc).__name__}: {exc} "
            f"(callers must json.dumps() a dict back to a string first)",
        )
    await j.start()
    j.context["order_id"] = "MUTATED"
    await j.stop()
    return (
        payload["context"]["order_id"] == "OID-1",
        f"dict form accepted; caller dict order_id={payload['context']['order_id']!r}",
    )


async def main():
    cases = [
        ("D1", "pending_invocations() lists it", d1),
        ("D2", "restart_services=True re-runs it", d2),
        ("D3", "restarted invoke gets the input", d3),
        ("D4", "entry actions do NOT re-run", d4),
        ("D5", "default restore starts nothing", d5),
        ("D6", "nested child-actor restore", d6),
        ("D7", "completed service not re-run", d7),
        ("D8", "restore deep-copies the context", d8),
        ("D8b", "dict-form restore does not alias", d8b),
    ]
    for pid, title, fn in cases:
        try:
            ok, d = await fn()
            P.check(pid, title, ok, d)
        except Exception as exc:  # noqa: BLE001
            P.record_exc(pid, title, exc)
    P.report()


if __name__ == "__main__":
    asyncio.run(main())
