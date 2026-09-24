"""N8b - #130 residual: `escalate` from an invoked child only reaches the
parent's `onError` when the `invoke` declares an explicit `id`.

#130 says escalate from an invoked child reaches the parent's `onError`.
The library's own regression test (tests/test_round4_findings.py,
TestEscalateRoutesToOnError) writes `{"src": "kid", "id": "kid", ...}` --
with the id. `id` is OPTIONAL on an `invoke` (the engine synthesises one:
the log line for the id-less case shows `ID: 'p.w'`, the state's id).

Drop the `id` and the escalation is silently lost: the parent sits in the
invoking state forever, `onError` never fires, no hook, no receipt error.

Control in the same script: a plain CALLABLE service that raises reaches
`onError` in BOTH shapes -- so this is specific to the escalate path, not
to id-less invokes in general.
"""

from __future__ import annotations

import asyncio

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine

ESC_CHILD = {
    "id": "c",
    "initial": "w",
    "states": {
        "w": {
            "entry": [
                {"type": "escalate",
                 "params": {"error": "child exploded"}}
            ]
        }
    },
}


async def run(with_id: bool, kind: str) -> dict:
    invoke = {"src": "kid", "onError": "caught"}
    if with_id:
        invoke["id"] = "kid"
    parent = {
        "id": "p",
        "initial": "w",
        "states": {"w": {"invoke": invoke}, "caught": {}},
    }
    if kind == "callable":
        async def kid(i, ctx, ev):  # noqa: ANN001
            raise ValueError("plain service failure")

        logic = MachineLogic(services={"kid": kid})
    else:
        logic = MachineLogic(
            services={"kid": create_machine(ESC_CHILD, logic=MachineLogic())}
        )

    interp = Interpreter(create_machine(parent, logic=logic))
    await interp.start()
    for _ in range(80):
        if "p.caught" in interp.current_state_ids:
            break
        await asyncio.sleep(0.02)
    out = {
        "invoke_declares_id": with_id,
        "failure_kind": kind,
        "states": sorted(interp.current_state_ids),
        "status": interp.status,
        "last_error": repr(interp.last_error),
        "reached_onError": "p.caught" in interp.current_state_ids,
    }
    await interp.stop()
    return out


async def main() -> int:
    cases = []
    for kind in ("callable", "escalate"):
        for with_id in (True, False):
            cases.append(await run(with_id, kind))
    by = {(c["failure_kind"], c["invoke_declares_id"]): c["reached_onError"]
          for c in cases}
    ok = all(by.values())
    emit("n8b_escalate_needs_invoke_id", {
        "cases": cases,
        "matrix_reached_onError": {f"{k[0]},id={k[1]}": v
                                   for k, v in by.items()},
        "control_callable_works_without_id": by[("callable", False)],
        "escalate_works_with_id": by[("escalate", True)],
        "escalate_works_without_id": by[("escalate", False)],
        "result": "PASS" if ok else "FAIL",
    })
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
