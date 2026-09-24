"""Verify #86 and #87 on main@5e07ba8: snapshot v2 provenance + engine-event
round-trip.

#86 acceptance criteria:
1. For every onUnhandled policy and the "*" matcher, an engine-minted event
   in the inbox produces the same outcome live vs restored-from-snapshot.
2. If the persisted shape changes, the snapshot schema version is bumped
   and the upcast path documented.
3. Tests: test_provenance_survives_snapshot_roundtrip,
   test_restored_escalate_event_does_not_trip_on_unhandled.
4. CHANGELOG notes the #79/#47 interaction.

#87 acceptance criteria:
1. A snapshot taken while an ErrorEvent is pending either preserves it or
   warns naming the dropped type/count.
2. Same for DoneEvent.
3. If persisted shape changes, schema version bumped.
4. Tests: test_snapshot_preserves_pending_error_event,
   test_snapshot_warns_on_dropped_engine_event.

Also probes CHANGELOG-specific claims: v1 snapshots restore unchanged;
`kind` field per record; whether a v2 snapshot loaded by 0.8.0-shaped code
would be safe (documented separately, cannot execute 0.8.0 here).
"""
import asyncio
import json
import sys

from xstate_statemachine import Event, MachineLogic, create_machine
from xstate_statemachine.events import (
    is_system_event,
    system_event,
    persist_event,
    restore_event,
    AfterEvent,
    DoneEvent,
    ErrorEvent,
)
from xstate_statemachine.interpreter import Interpreter

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not cond:
        FAILURES.append(name)


UNH = {
    "id": "u", "initial": "a", "onUnhandled": "error",
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}
STAR = {
    "id": "s", "initial": "a",
    "states": {"a": {"on": {"*": {"target": "b"}}}, "b": {}},
}
INVOKE_CFG = {
    "id": "m", "initial": "w",
    "states": {
        "w": {"invoke": {"src": "svc", "id": "svc", "onError": "bad", "onDone": "good"}},
        "bad": {"type": "final"},
        "good": {"type": "final"},
    },
}


async def live_vs_restored(cfg, put_event_factory):
    it = await Interpreter(create_machine(cfg, logic=MachineLogic())).start()
    it._put_inbox(put_event_factory())
    await asyncio.sleep(0.05)
    live_status = it.status
    live_states = set(it.current_state_ids)
    await it.stop()

    it2 = await Interpreter(create_machine(cfg, logic=MachineLogic())).start()
    it2._put_inbox(put_event_factory())
    snap = json.dumps(it2.get_persisted_snapshot())
    await it2.stop()

    it3 = Interpreter.from_snapshot(snap, create_machine(cfg, logic=MachineLogic()))
    await it3.start()
    await asyncio.sleep(0.05)
    restored_status = it3.status
    restored_states = set(it3.current_state_ids)
    await it3.stop()
    return (live_status, live_states), (restored_status, restored_states), json.loads(snap)


async def async_checks():
    # --- #86 AC1: onUnhandled=error parity for engine-minted event ---
    (ls, lst), (rs, rst), snap = await live_vs_restored(
        UNH, lambda: system_event("xstate.error.actor.kid", error="x")
    )
    check(
        "#86 AC1 onUnhandled=error: live vs restored parity for engine event",
        ls == rs == "running",
        f"live={ls} restored={rs}",
    )

    # --- #86 AC1: "*" matcher parity for engine-minted event (should NOT match) ---
    (ls2, lst2), (rs2, rst2), _ = await live_vs_restored(
        STAR, lambda: system_event("SOMETHING_ENGINEY")
    )
    check(
        '#86 AC1 "*" matcher: live vs restored parity for engine event (unmatched both sides)',
        lst2 == rst2,
        f"live={lst2} restored={rst2}",
    )

    # --- #86 AC2: schema version bumped ---
    check(
        "#86/#87 AC2: snapshot schema carries a version field",
        "version" in snap or "schema_version" in snap or "_version" in snap,
        list(snap.keys()),
    )

    # --- #86: kind field per pending_events record ---
    pe = snap.get("pending_events", [])
    check(
        "#86/#87: pending_events records carry a 'kind' discriminator",
        all("kind" in r for r in pe) if pe else True,
        pe,
    )

    # --- #87 AC1/AC2: ErrorEvent / DoneEvent pending survive snapshot ---
    async def main_invoke():
        it = await Interpreter(
            create_machine(
                INVOKE_CFG,
                logic=MachineLogic(services={"svc": lambda i, c, e: asyncio.sleep(10)}),
            )
        ).start()
        it._put_inbox(ErrorEvent("error.platform.svc", ValueError("boom"), "svc"))
        it._put_inbox(DoneEvent("done.invoke.svc", {"k": 1}, "svc"))
        snap = it.get_persisted_snapshot()
        pe = snap["pending_events"]
        await it.stop()
        return pe

    pe2 = await main_invoke()
    kinds = [r.get("kind") for r in pe2]
    check(
        "#87 AC1/2: ErrorEvent+DoneEvent both present in persisted pending_events",
        kinds == ["error", "done"],
        kinds,
    )

    # Full restore: onError target reached.
    async def main_restore_onerror():
        it = await Interpreter(
            create_machine(
                INVOKE_CFG,
                logic=MachineLogic(services={"svc": lambda i, c, e: asyncio.sleep(10)}),
            )
        ).start()
        it._put_inbox(ErrorEvent("error.platform.svc", ValueError("boom"), "svc"))
        snap = json.dumps(it.get_persisted_snapshot())
        await it.stop()
        it2 = Interpreter.from_snapshot(
            snap,
            create_machine(
                INVOKE_CFG,
                logic=MachineLogic(services={"svc": lambda i, c, e: asyncio.sleep(10)}),
            ),
        )
        await it2.start()
        await asyncio.sleep(0.05)
        val = it2.value
        await it2.stop()
        return val

    val = await main_restore_onerror()
    check(
        "#87 AC1: restored machine reaches onError target ('bad')",
        val == "bad" or (isinstance(val, dict) and "bad" in str(val)),
        val,
    )

    # --- CHANGELOG claim: v1 snapshots (no 'kind') restore unchanged ---
    v1_user = restore_event({"type": "USER_EVT", "payload": {"a": 1}})
    v1_engine = restore_event({"type": "___xstate_statemachine_init___", "payload": {}})
    v1_error_shape = restore_event({"type": "error.platform.x", "payload": {}})
    check(
        "v1 record (no kind) for plain user type restores as non-system Event",
        isinstance(v1_user, Event) and not is_system_event(v1_user),
        v1_user,
    )
    check(
        "v1 record (no kind) for engine-shaped name restores as system",
        is_system_event(v1_engine),
        v1_engine,
    )
    check(
        "v1 record (no kind) for error.platform.* name-derived as system (best effort)",
        is_system_event(v1_error_shape),
        v1_error_shape,
    )

    # --- round-trip every event class including AfterEvent ---
    cases = [
        Event("USER", {"k": 1}),
        system_event("___xstate_statemachine_init___"),
        DoneEvent("done.invoke.svc", {"n": 2}, "svc"),
        ErrorEvent("error.platform.svc", ValueError("boom"), "svc"),
        AfterEvent("after.500"),
    ]
    ok = True
    for ev in cases:
        rec = json.loads(json.dumps(persist_event(ev)))
        back = restore_event(rec)
        if type(back) != type(ev) or back.type != ev.type or is_system_event(back) != is_system_event(ev):
            ok = False
            print(f"  MISMATCH: {ev!r} -> {rec} -> {back!r}")
    check("every event class round-trips persist_event/restore_event", ok)

    # --- Replayed deferred event after restore: does a duplicate receipt/
    #     notification exist? (round-3 CHANGELOG claim spot-check for #84,
    #     included here since it's adjacent to the snapshot machinery.) ---
    DEFER_CFG = {
        "id": "d", "initial": "a", "onUnhandled": "defer",
        "states": {"a": {"on": {"GO": "b"}}, "b": {}},
    }

    async def defer_replay():
        it = await Interpreter(create_machine(DEFER_CFG, logic=MachineLogic())).start()
        r = await it.send("MAYBE_LATER", wait=True)
        deferred_flag = getattr(r, "deferred", None)
        snap = json.dumps(it.get_persisted_snapshot())
        await it.stop()
        it2 = Interpreter.from_snapshot(snap, create_machine(DEFER_CFG, logic=MachineLogic()))
        await it2.start()
        deferred_events_after_restore = list(getattr(it2, "_deferred_events", []) or [])
        await it2.stop()
        return deferred_flag, deferred_events_after_restore

    deferred_flag, pending_after = await defer_replay()
    check("#84 spot-check: Receipt.deferred True for deferred event", deferred_flag is True, deferred_flag)
    check(
        "#84 spot-check: deferred event restored once (no duplication) in pending_events",
        len(pending_after) == 1,
        pending_after,
    )


def main():
    asyncio.run(async_checks())
    print()
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("RESULT: ALL PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
