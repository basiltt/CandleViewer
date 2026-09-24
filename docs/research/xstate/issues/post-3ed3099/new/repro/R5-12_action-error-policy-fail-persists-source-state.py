"""R5-12 repro: `actionErrorPolicy: "fail"` leaves the configuration on the
SOURCE state, bricks the interpreter, and `get_persisted_snapshot()` happily
persists that bricked state.

The documented contract (README "Failure modes" table) is that `"fail"`
"also stops with `TransitionFailedError`". Observed instead: `status` becomes
`"error"`, the configuration is the *source* leaf, an earlier action in the
same entry list has already applied its outward effect, every subsequent send
is inert, and a snapshot taken now is accepted and reports
`{"status": "error", "state_ids": ["f.a"]}`.

Exits 1 while the defect is present, 0 once fixed.
Stdlib + xstate_statemachine only.
"""

import asyncio
import json
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "f",
    "initial": "a",
    "actionErrorPolicy": "fail",
    # `ok1` succeeds (its effect escapes), then `boom` raises.
    "states": {"a": {"on": {"GO": "b"}}, "b": {"entry": ["ok1", "boom"]}, "c": {}},
}

ran = []


def ok1(interp, ctx, evt, action_def=None):  # noqa: ANN001, D103
    ran.append("ok1")


def boom(interp, ctx, evt, action_def=None):  # noqa: ANN001, D103
    raise RuntimeError("boom")


async def main():
    logic = MachineLogic(actions={"ok1": ok1, "boom": boom})
    interp = await Interpreter(create_machine(CFG, logic=logic)).start()

    receipt = await interp.send("GO", wait=True)
    obs = {
        "receipt_changed": receipt.changed,
        "receipt_error": repr(receipt.error),
        "ids_after": sorted(interp.current_state_ids),
        "status": interp.status,
        "interpreter_error": type(interp.error).__name__ if interp.error else None,
        "ran": list(ran),
    }

    # The machine is now inert: further events change nothing.
    r2 = await interp.send("GO", wait=True)
    obs["second_send_changed"] = r2.changed
    obs["status_after_second_send"] = interp.status

    # ...and the bricked configuration is happily persisted.
    try:
        snap = interp.get_persisted_snapshot()
        obs["snapshot"] = {"status": snap["status"], "state_ids": snap["state_ids"]}
    except Exception as exc:  # noqa: BLE001
        obs["snapshot"] = "REFUSED: " + type(exc).__name__

    print("OBSERVED:")
    print(json.dumps(obs, indent=2))
    print(
        "\nEXPECTED: the configuration is NOT the source leaf ['f.a'] while "
        "status=='error',\n          and get_persisted_snapshot() REFUSES a "
        "bricked machine (or the\n          machine is stopped with "
        "TransitionFailedError per the documented contract)."
    )
    bad = (
        obs["ids_after"] == ["f.a"]
        and obs["status"] == "error"
        and isinstance(obs["snapshot"], dict)
    )
    if bad:
        print(
            "RESULT: FAIL -- source-state configuration under status='error', "
            "persisted without complaint."
        )
        return 1
    print("RESULT: PASS")
    return 0


sys.exit(asyncio.run(main()))
