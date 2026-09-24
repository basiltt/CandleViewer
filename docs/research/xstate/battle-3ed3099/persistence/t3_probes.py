# -*- coding: utf-8 -*-
"""T3 - targeted persistence probes.

Each `probe_*` is independent and prints PASS/FAIL/INFO lines. These are the
cases the property test cannot reach: receipts, corrupt blobs, hash drift,
v1 upcast, huge context, child actors.
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
import traceback

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.events import (
    AfterEvent,
    DoneEvent,
    ErrorEvent,
    Event,
    persist_event,
    restore_event,
    system_event,
)

import order_machine
from harness import attach_clock

RESULTS: list[tuple[str, str, str]] = []


def rec(name: str, verdict: str, detail: str = "") -> None:
    RESULTS.append((name, verdict, detail))
    print(f"[{verdict:5}] {name}  {detail}")


# ---------------------------------------------------------------------------
# P1 - deferred buffer survives a snapshot
# ---------------------------------------------------------------------------
async def probe_deferred() -> None:
    m = order_machine.build()
    i = await Interpreter(m, clock=SimulatedClock()).start()
    await asyncio.sleep(0.02)
    # FILL is unhandled in `draft` -> onUnhandled "defer" holds it
    await i.send("FILL", n=5)
    await i.send("DONE")
    await asyncio.sleep(0.05)
    before = i.deferred_count
    blob = i.get_snapshot()
    await i.stop()
    recs = json.loads(blob)["deferred"]
    i2 = Interpreter.from_snapshot(blob, order_machine.build())
    attach_clock(i2, SimulatedClock())
    await i2.start()
    await asyncio.sleep(0.02)
    after = i2.deferred_count
    # now unblock: SUBMIT should replay the held FILL
    await i2.send("SUBMIT", qty=3)
    await asyncio.sleep(0.08)
    rec(
        "P1 deferred buffer round-trips",
        "PASS" if before == after == 2 else "FAIL",
        f"before={before} after={after} records={recs} "
        f"replayed_ctx_filled={i2.context['filled']} "
        f"states={sorted(i2.current_state_ids)}",
    )
    await i2.stop()


# ---------------------------------------------------------------------------
# P2 - what does a `wait=True` awaiter get when the process dies?
# ---------------------------------------------------------------------------
async def probe_receipt_on_crash() -> None:
    slow = asyncio.Event()

    async def blocking_ack(interp, ctx, event):  # noqa: ANN001
        await slow.wait()
        return {"ack": 1}

    m = order_machine.build(ack=blocking_ack)
    i = await Interpreter(m, clock=SimulatedClock()).start()
    await asyncio.sleep(0.02)
    task = asyncio.ensure_future(i.send("SUBMIT", wait=True, qty=1))
    await asyncio.sleep(0.05)
    blob = i.get_snapshot()
    pend = json.loads(blob)["pending_events"]
    await i.stop()  # the crash surrogate
    try:
        r = await asyncio.wait_for(task, timeout=1.0)
        outcome = f"resolved: {r}"
        verdict = "INFO"
    except asyncio.TimeoutError:
        outcome = "HUNG (never resolved, never raised)"
        verdict = "FAIL"
    except Exception as e:  # noqa: BLE001
        outcome = f"raised {type(e).__name__}: {e}"
        verdict = "INFO"
    rec(
        "P2 wait=True awaiter at crash",
        verdict,
        f"{outcome}; persisted pending_events={pend}",
    )
    slow.set()


# ---------------------------------------------------------------------------
# P3 - in-flight invoke: dormancy reporting + restart semantics
# ---------------------------------------------------------------------------
async def probe_inflight_invoke() -> None:
    gate = asyncio.Event()
    calls = {"n": 0}

    async def gated(interp, ctx, event):  # noqa: ANN001
        calls["n"] += 1
        await gate.wait()
        return {"ack": calls["n"]}

    m = order_machine.build(ack=gated)
    i = await Interpreter(m, clock=SimulatedClock()).start()
    await asyncio.sleep(0.02)
    await i.send("SUBMIT", qty=2)
    await asyncio.sleep(0.05)
    live_dormant = i.has_dormant_invocations
    blob = i.get_snapshot()
    await i.stop()

    for restart in (False, True):
        i2 = Interpreter.from_snapshot(
            blob, order_machine.build(ack=gated), restart_services=restart
        )
        attach_clock(i2, SimulatedClock())
        before_start = (i2.has_dormant_invocations,
                        [tuple(p) for p in i2.pending_invocations()])
        await i2.start()
        await asyncio.sleep(0.05)
        after_start = (i2.has_dormant_invocations, calls["n"])
        rec(
            f"P3 in-flight invoke restart_services={restart}",
            "INFO",
            f"live_dormant={live_dormant} pre_start={before_start} "
            f"post_start(dormant, service_calls)={after_start} "
            f"states={sorted(i2.current_state_ids)}",
        )
        await i2.stop()
    gate.set()


# ---------------------------------------------------------------------------
# P4 - v1 -> v2 upcast for every event class
# ---------------------------------------------------------------------------
async def probe_v1_upcast() -> None:
    samples = [
        ("user Event", Event("SUBMIT", {"qty": 1})),
        ("system Event", system_event("___xstate_init")),
        ("DoneEvent", DoneEvent("done.invoke.ackSvc", {"ack": 1}, "ackSvc")),
        (
            "ErrorEvent",
            ErrorEvent(
                "error.platform.ackSvc", RuntimeError("nope"), "ackSvc"
            ),
        ),
        ("AfterEvent", AfterEvent("after.5000.order.submitted")),
    ]
    lines = []
    for label, ev in samples:
        v2 = persist_event(ev)
        v1 = {k: v for k, v in v2.items() if k != "kind"}  # strip the v2 disc.
        back = restore_event(v1)
        same_class = type(back) is type(ev)
        same_sys = getattr(back, "system", None) == getattr(ev, "system", None)
        lines.append(
            f"{label}: v1->{type(back).__name__} class_ok={same_class} "
            f"system={getattr(back, 'system', 'n/a')}"
            f"{'' if same_sys else ' <PROVENANCE CHANGED>'}"
        )
    rec("P4 v1 record upcast, per event class", "INFO", " | ".join(lines))


async def probe_v2_roundtrip() -> None:
    samples = [
        Event("SUBMIT", {"qty": 1}),
        system_event("___xstate_init"),
        DoneEvent("done.invoke.ackSvc", {"ack": 1}, "ackSvc"),
        ErrorEvent("error.platform.ackSvc", RuntimeError("nope"), "ackSvc"),
        AfterEvent("after.5000.order.submitted", 1.0, 2.0),
    ]
    bad = []
    for ev in samples:
        back = restore_event(json.loads(json.dumps(persist_event(ev))))
        if type(back) is not type(ev) or back.type != ev.type:
            bad.append(f"{type(ev).__name__}->{type(back).__name__}")
        if isinstance(ev, AfterEvent) and (
            back.scheduled_for != ev.scheduled_for
            or back.fired_at != ev.fired_at
        ):
            bad.append(
                f"AfterEvent lateness lost: {ev.scheduled_for}/{ev.fired_at}"
                f" -> {back.scheduled_for}/{back.fired_at}"
            )
    rec(
        "P5 v2 round-trip, per event class",
        "PASS" if not bad else "FAIL",
        "; ".join(bad) or "all classes round-trip",
    )


# ---------------------------------------------------------------------------
# P6 - hash drift
# ---------------------------------------------------------------------------
async def probe_hash_drift() -> None:
    i = await Interpreter(order_machine.build(), clock=SimulatedClock()).start()
    await asyncio.sleep(0.02)
    await i.send("SUBMIT", qty=1)
    await asyncio.sleep(0.05)
    blob = i.get_snapshot()
    await i.stop()

    drifted = copy.deepcopy(order_machine.ORDER_CONFIG)
    # a guard-free behavioural edit: retarget FILL's action list
    drifted["states"]["submitted"]["states"]["exchange"]["states"]["working"][
        "on"
    ]["FILL"] = {"actions": ["add_fill", "add_fill"]}
    m2 = create_machine(
        drifted,
        logic=MachineLogic(
            actions=dict(order_machine.ACTIONS),
            services={"ack_service": order_machine.ack_service},
        ),
    )
    try:
        Interpreter.from_snapshot(blob, m2)
        rec("P6 hash drift refused", "FAIL", "restore ACCEPTED a drifted machine")
    except Exception as e:  # noqa: BLE001
        rec("P6 hash drift refused", "PASS", f"{type(e).__name__}: {e}")

    # and the documented escape hatch
    try:
        i3 = Interpreter.from_snapshot(blob, m2, verify_machine_hash=False)
        attach_clock(i3, SimulatedClock())
        await i3.start()
        await asyncio.sleep(0.02)
        await i3.send("RISK_OK")
        await i3.send("FILL", n=1)
        await asyncio.sleep(0.05)
        rec(
            "P6b verify_machine_hash=False resumes on new shape",
            "INFO",
            f"states={sorted(i3.current_state_ids)} filled={i3.context['filled']}",
        )
        await i3.stop()
    except Exception as e:  # noqa: BLE001
        rec("P6b verify_machine_hash=False", "INFO", f"{type(e).__name__}: {e}")

    # a NON-behavioural edit must NOT invalidate stored snapshots
    cosmetic = copy.deepcopy(order_machine.ORDER_CONFIG)
    cosmetic["states"]["draft"]["description"] = "a docstring edit"
    m3 = create_machine(
        cosmetic,
        logic=MachineLogic(
            actions=dict(order_machine.ACTIONS),
            services={"ack_service": order_machine.ack_service},
        ),
    )
    try:
        Interpreter.from_snapshot(blob, m3)
        rec("P6c cosmetic edit still restores", "PASS", "description ignored")
    except Exception as e:  # noqa: BLE001
        rec("P6c cosmetic edit still restores", "FAIL", f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# P7 - truncated / corrupt JSON
# ---------------------------------------------------------------------------
async def probe_corrupt() -> None:
    i = await Interpreter(order_machine.build(), clock=SimulatedClock()).start()
    await asyncio.sleep(0.02)
    await i.send("SUBMIT", qty=1)
    await asyncio.sleep(0.05)
    blob = i.get_snapshot()
    await i.stop()
    d = json.loads(blob)

    cases = {
        "truncated at 60%": blob[: int(len(blob) * 0.6)],
        "empty string": "",
        "json null": "null",
        "json list": "[1,2,3]",
        "missing context": json.dumps({k: v for k, v in d.items()
                                       if k != "context"}),
        "missing state_ids+configuration": json.dumps(
            {k: v for k, v in d.items()
             if k not in ("state_ids", "configuration")}
        ),
        "unknown state id": json.dumps(
            {**d, "configuration": ["order.NOT_A_STATE"],
             "state_ids": ["order.NOT_A_STATE"]}
        ),
        "version 999": json.dumps({**d, "version": 999}),
        "version null": json.dumps({**d, "version": None}),
        "status garbage": json.dumps({**d, "status": "banana"}),
        "pending_events not a list": json.dumps({**d, "pending_events": 5}),
        "pending record missing type": json.dumps(
            {**d, "pending_events": [{"kind": "event"}]}
        ),
        "pending record bad kind": json.dumps(
            {**d, "pending_events": [{"kind": "wat", "type": "X"}]}
        ),
        "deferred not a list": json.dumps({**d, "deferred": "x"}),
        "history bad node": json.dumps({**d, "history": {"order": ["nope"]}}),
        "context not a dict": json.dumps({**d, "context": 42}),
        "actors not a dict": json.dumps({**d, "actors": [1]}),
    }
    for label, payload in cases.items():
        try:
            it = Interpreter.from_snapshot(payload, order_machine.build())
            detail = (f"ACCEPTED -> status={it.status} "
                      f"states={sorted(it.current_state_ids)} "
                      f"ctx={str(it.context)[:60]}")
            verdict = "INFO"
        except Exception as e:  # noqa: BLE001
            detail = f"{type(e).__name__}: {str(e)[:90]}"
            verdict = "INFO"
        rec(f"P7 corrupt/{label}", verdict, detail)


# ---------------------------------------------------------------------------
# P8 - huge context (1 MB)
# ---------------------------------------------------------------------------
async def probe_huge_context() -> None:
    i = await Interpreter(order_machine.build(), clock=SimulatedClock()).start()
    await asyncio.sleep(0.02)
    i.context["blob"] = "x" * (1024 * 1024)
    t0 = time.perf_counter()
    blob = i.get_snapshot()
    t1 = time.perf_counter()
    await i.stop()
    i2 = Interpreter.from_snapshot(blob, order_machine.build())
    t2 = time.perf_counter()
    attach_clock(i2, SimulatedClock())
    await i2.start()
    await asyncio.sleep(0.02)
    ok = i2.context.get("blob") == "x" * (1024 * 1024)
    rec(
        "P8 1 MB context round-trip",
        "PASS" if ok else "FAIL",
        f"blob_bytes={len(blob)} snapshot={1000*(t1-t0):.1f} ms "
        f"restore={1000*(t2-t1):.1f} ms intact={ok}",
    )
    await i2.stop()


# ---------------------------------------------------------------------------
# P9 - child actors (spawned + invoked) across a restore
# ---------------------------------------------------------------------------
CHILD = {
    "id": "child",
    "initial": "idle",
    "context": {"n": 0},
    "states": {
        "idle": {"on": {"BUMP": {"target": "idle", "actions": ["bump"]}}},
    },
}

PARENT = {
    "id": "parent",
    "initial": "run",
    "context": {},
    "states": {
        "run": {
            "entry": [{"type": "spawn_kid", "src": "kid"}],
            "invoke": {"id": "inv", "src": "kid"},
            "on": {"POKE": {"actions": [{"type": "send_to_kid"}]}},
        }
    },
}


def bump(interp, ctx, event, ad):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


async def probe_child_actors() -> None:
    child_machine = create_machine(
        CHILD, logic=MachineLogic(actions={"bump": bump})
    )

    def send_to_kid(interp, ctx, event, ad):  # noqa: ANN001
        pass

    logic = MachineLogic(
        actions={"send_to_kid": send_to_kid},
        services={"kid": child_machine},
    )
    m = create_machine(PARENT, logic=logic)
    i = await Interpreter(m, clock=SimulatedClock()).start()
    await asyncio.sleep(0.05)
    actors_live = sorted(i._actors.keys())
    for aid, actor in list(i._actors.items()):
        await actor.send("BUMP")
    await asyncio.sleep(0.05)
    live_ns = {aid: a.context.get("n") for aid, a in i._actors.items()}
    blob = i.get_snapshot()
    persisted = sorted((json.loads(blob).get("actors") or {}).keys())
    await i.stop()

    m2 = create_machine(PARENT, logic=MachineLogic(
        actions={"send_to_kid": send_to_kid},
        services={"kid": create_machine(
            CHILD, logic=MachineLogic(actions={"bump": bump}))},
    ))
    i2 = Interpreter.from_snapshot(blob, m2)
    attach_clock(i2, SimulatedClock())
    await i2.start()
    await asyncio.sleep(0.05)
    restored = sorted(i2._actors.keys())
    restored_ns = {aid: a.context.get("n") for aid, a in i2._actors.items()}
    pending_unrestorable = sorted(
        getattr(i2, "_pending_actor_snapshots", {}).keys()
    )
    rec(
        "P9 child actors across restore",
        "PASS" if restored == persisted == actors_live else "FAIL",
        f"live={actors_live} ns={live_ns} | persisted={persisted} | "
        f"restored={restored} ns={restored_ns} "
        f"unrestorable={pending_unrestorable}",
    )
    # can the restored children still be driven?
    for aid, a in list(i2._actors.items()):
        try:
            await a.send("BUMP")
        except Exception as e:  # noqa: BLE001
            rec("P9b restored child accepts events", "FAIL",
                f"{aid}: {type(e).__name__}: {e}")
            break
    else:
        await asyncio.sleep(0.05)
        after = {aid: a.context.get("n") for aid, a in i2._actors.items()}
        rec("P9b restored child accepts events", "INFO", f"after BUMP: {after}")
    await i2.stop()


# ---------------------------------------------------------------------------
# P10 - bounded inbox: are ACCEPTED-but-unprocessed events persisted?
# ---------------------------------------------------------------------------
async def probe_bounded_inbox() -> None:
    from xstate_statemachine.interpreter import OverflowPolicy

    gate = asyncio.Event()

    async def gated(interp, ctx, event):  # noqa: ANN001
        await gate.wait()
        return {"ack": 1}

    m = order_machine.build(ack=gated)
    i = Interpreter(
        m,
        clock=SimulatedClock(),
        max_queue_size=4,
        overflow_policy=OverflowPolicy.DROP_NEWEST,
    )
    await i.start()
    await asyncio.sleep(0.02)
    await i.send("SUBMIT", qty=1)
    await asyncio.sleep(0.03)  # parked in the gated invoke
    for n in range(10):
        await i.send("FILL", n=n)
    pending = [e.type for e in i.pending_events]
    blob = i.get_snapshot()
    persisted = [r["type"] for r in json.loads(blob)["pending_events"]]
    await i.stop()
    rec(
        "P10 bounded inbox persisted",
        "PASS" if pending == persisted else "FAIL",
        f"live={pending} persisted={persisted}",
    )
    gate.set()


async def main() -> None:
    for probe in (
        probe_deferred,
        probe_receipt_on_crash,
        probe_inflight_invoke,
        probe_v1_upcast,
        probe_v2_roundtrip,
        probe_hash_drift,
        probe_corrupt,
        probe_huge_context,
        probe_child_actors,
        probe_bounded_inbox,
    ):
        print(f"\n=== {probe.__name__} ===")
        try:
            await probe()
        except Exception:  # noqa: BLE001
            rec(probe.__name__, "ERROR", traceback.format_exc(limit=4))


if __name__ == "__main__":
    asyncio.run(main())
