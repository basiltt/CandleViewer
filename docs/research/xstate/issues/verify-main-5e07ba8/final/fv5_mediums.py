"""Medium-tier re-checks feeding the release note: R4-02 restore validation,
R4-19 on the async engine, and the #99 async-side reopen. Public API only.
"""
import asyncio
import json
import logging

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

logging.disable(logging.CRITICAL)


def _snapstr(interp):
    raw = interp.get_persisted_snapshot()
    return raw if isinstance(raw, str) else json.dumps(raw, default=str)


CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}


def r4_02():
    """from_snapshot() performs no legality/status validation."""
    s = SyncInterpreter(create_machine(CFG, logic=MachineLogic())).start()
    good = json.loads(_snapstr(s))
    results = {}

    # (a) nonsense status accepted verbatim
    blob = dict(good, status="banana")
    try:
        r = SyncInterpreter.from_snapshot(
            json.dumps(blob), create_machine(CFG, logic=MachineLogic())
        )
        results["status_banana"] = {"accepted": True, "status": r.status}
    except Exception as ex:  # noqa: BLE001
        results["status_banana"] = {"accepted": False, "err": repr(ex)}

    # (b) empty configuration accepted -> permanently inert machine
    blob = dict(good, configuration=[], state_ids=[])
    try:
        r = SyncInterpreter.from_snapshot(
            json.dumps(blob), create_machine(CFG, logic=MachineLogic())
        )
        r.start()
        r.send("GO")
        results["empty_configuration"] = {
            "accepted": True,
            "state_ids": sorted(r.current_state_ids),
            "status": r.status,
            "value": r.value,
        }
    except Exception as ex:  # noqa: BLE001
        results["empty_configuration"] = {"accepted": False, "err": repr(ex)}

    # (c) malformed shapes: what class of exception escapes?
    for name, mut in {
        "missing_status": lambda d: {k: v for k, v in d.items() if k != "status"},
        "missing_context": lambda d: {k: v for k, v in d.items() if k != "context"},
        "configuration_int": lambda d: dict(d, configuration=7),
        "pending_events_str": lambda d: dict(d, pending_events="nope"),
    }.items():
        try:
            SyncInterpreter.from_snapshot(
                json.dumps(mut(good)), create_machine(CFG, logic=MachineLogic())
            )
            results[name] = "accepted (no error)"
        except Exception as ex:  # noqa: BLE001
            results[name] = type(ex).__name__ + ": " + str(ex)[:80]
    return results


async def r4_19_async():
    child = {
        "id": "kid",
        "initial": "w",
        "context": {"ctxkey": 1},
        "states": {
            "w": {"always": "fin"},
            "fin": {"type": "final", "output": {"code": 7}},
        },
    }
    parent = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {
                    "id": "kid",
                    "src": "kid",
                    "onDone": {"target": "done", "actions": ["cap"]},
                }
            },
            "done": {},
        },
    }
    seen = {}

    def cap(i, c, e, a):
        seen["data"] = getattr(e, "data", None)

    pm = create_machine(
        parent,
        logic=MachineLogic(
            services={"kid": create_machine(child, logic=MachineLogic())},
            actions={"cap": cap},
        ),
    )
    i = Interpreter(pm)
    await i.start()
    for _ in range(50):
        if "data" in seen:
            break
        await asyncio.sleep(0.02)
    out = {
        "parent_done_data": seen.get("data"),
        "expected": {"code": 7},
        "REPRO": seen.get("data") != {"code": 7},
    }
    await i.stop()
    return out


async def issue_99_async():
    """Unhandled failure of an invoked CHILD MACHINE: async parent parks."""
    child = {
        "id": "kid",
        "initial": "w",
        "states": {"w": {"entry": ["boom"]}},
    }

    def boom(i, c, e, a):
        raise ValueError("child boom")

    parent = {
        "id": "m",
        "initial": "run",
        "states": {"run": {"invoke": {"id": "kid", "src": "kid"}}},  # no onError
    }
    cm = create_machine(child, logic=MachineLogic(actions={"boom": boom}))

    i = Interpreter(create_machine(parent, logic=MachineLogic(services={"kid": cm})))
    await i.start()
    await asyncio.sleep(0.5)
    async_res = {"status": i.status, "last_error": repr(i.last_error)}
    await i.stop()

    cm2 = create_machine(child, logic=MachineLogic(actions={"boom": boom}))
    s = SyncInterpreter(
        create_machine(parent, logic=MachineLogic(services={"kid": cm2}))
    )
    try:
        s.start()
    except Exception as ex:  # noqa: BLE001
        pass
    sync_res = {"status": s.status, "last_error": repr(s.last_error)}
    return {
        "async": async_res,
        "sync": sync_res,
        "REPRO_asymmetry": async_res["status"] != sync_res["status"],
    }


async def main():
    print(
        json.dumps(
            {
                "R4-02": r4_02(),
                "R4-19_async": await r4_19_async(),
                "issue_99_async_reopen": await issue_99_async(),
            },
            indent=1,
            default=str,
        )
    )


asyncio.run(main())
