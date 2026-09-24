"""R8-08 STANDALONE: #186's `configuration`/`state_ids` agreement check is
one-sided. `base_interpreter.py:1722` is `snapshot.get("configuration") or
snapshot["state_ids"]` -- never compared. An EMPTIED/REWRITTEN `state_ids`
is accepted whenever `configuration` is (on its own) legal, and a DROPPED
`configuration` is accepted -- only an outright contradiction between two
present, non-empty fields is refused. Exits 1 while any non-contradiction
mutation is ACCEPTED; 0 once empty/absent is treated as disagreement too.
"""
import asyncio
import copy
import json

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "r4c",
    "initial": "top",
    "context": {"n": 0},
    "states": {
        "top": {
            "type": "parallel",
            "states": {
                "A": {
                    "initial": "a1",
                    "states": {"a1": {"on": {"S": {"target": "a2"}}}, "a2": {}},
                },
                "B": {
                    "initial": "b1",
                    "states": {"b1": {"on": {"S": {"target": "b2"}}}, "b2": {}},
                },
            },
        }
    },
}


def make_service(kind):
    def svc(i, ctx, e):
        return {"v": 1}

    async def asvc(i, ctx, e):
        return {"v": 1}

    return svc if kind == "def" else asvc


def mk(k):
    return create_machine(
        copy.deepcopy(CFG), logic=MachineLogic(services={"s": make_service(k)})
    )


async def base(k):
    i = Interpreter(mk(k))
    await asyncio.wait_for(i.start(), 10)
    await asyncio.wait_for(i.send("S", wait=True), 10)
    b = i.get_persisted_snapshot()
    await i.stop()
    return b if isinstance(b, dict) else json.loads(b)


def restore(engine, k, b):
    cls = Interpreter if engine == "async" else SyncInterpreter
    try:
        r = cls.from_snapshot(json.dumps(b), mk(k))
        return {
            "disposition": "ACCEPTED",
            "restored_to": sorted(getattr(r, "current_state_ids", [])),
        }
    except Exception as e:
        return {"disposition": f"refused:{type(e).__name__}"}


CASES = {
    "state_ids emptied": lambda b: b.update({"state_ids": []}),
    "state_ids rewritten to a different leaf": lambda b: b.update(
        {"state_ids": ["r4c.top.A.a1", "r4c.top.B.b1"]}
    ),
    "state_ids rewritten to garbage": lambda b: b.update(
        {"state_ids": ["r4c.NOT_A_STATE"]}
    ),
    "configuration dropped": lambda b: b.pop("configuration", None),
}


async def main():
    rows = []
    for k in ("def", "async def"):
        b0 = await base(k)
        for name, fn in CASES.items():
            for engine in ("async", "sync"):
                b = copy.deepcopy(b0)
                fn(b)
                r = restore(engine, k, b)
                rows.append(
                    {
                        "case": name,
                        "engine": engine,
                        "kind": k,
                        "blob_state_ids": b.get("state_ids"),
                        "blob_configuration": b.get("configuration"),
                        "truth": sorted(b0["state_ids"]),
                        **r,
                    }
                )
    bad = [
        r
        for r in rows
        if r["disposition"] == "ACCEPTED"
        and sorted(r.get("restored_to") or []) != r["truth"]
        and sorted(r["blob_state_ids"] or []) != r["truth"]
    ]
    contradiction_accepted = [r for r in rows if r["disposition"] == "ACCEPTED"]
    result = "FAIL" if contradiction_accepted else "PASS"
    out = {
        "result": result,
        "rows": rows,
        "accepted_contradictions": len(contradiction_accepted),
        "accepted_and_reader_would_be_misled": bad,
        "source": "base_interpreter.py:1722 `configuration or state_ids`"
        " (fields never compared)",
    }
    print(json.dumps(out, indent=2, default=str))
    print(f"OBSERVED: accepted_contradictions={len(contradiction_accepted)} ({result})")
    print(
        "EXPECTED: 0 -- an empty/absent `configuration` or `state_ids` on a "
        "version>=1 payload must be treated as disagreement (SnapshotCorruptError), "
        "not as 'no opinion'"
    )
    return 1 if contradiction_accepted else 0


raise SystemExit(asyncio.run(main()))
