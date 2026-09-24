"""N-04 repro: `send_threadsafe()` bypasses `strict` mode and `event_schemas`.

`_check_strict` is called from `Interpreter.send`, `SyncInterpreter.send` and the
`raise` built-in -- but not from `send_threadsafe()`, which calls
`_prepare_event` and then `_enqueue` directly. On a `strict: True` machine:

  * `send("FIL")`             -> UnknownEventError("Did you mean 'FILL'?")
  * `send_threadsafe("FIL")`  -> accepted, future completes, event silently
                                 dropped at dispatch

Registered `event_schemas` validators are bypassed on the same path.

This matters because after #37 `send_threadsafe()` is the *recommended* -- and
effectively the only -- API for delivering an event from a foreign thread, since
bare `send()` now raises `WrongThreadError` and
`run_coroutine_threadsafe(interp.send(...))` does too. So the path a
multi-threaded production app is required to take is the one without the
guardrail the release added.

Exit 1 while the defect is present, 0 once it is fixed.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading

from xstate_statemachine import Interpreter, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "st",
    "initial": "a",
    "strict": True,
    "states": {"a": {"on": {"FILL": {"target": "b"}}}, "b": {}},
}


class QtySchema:
    """Minimal dependency-free validator: rejects a missing/negative qty."""

    def validate(self, payload):  # noqa: ANN001
        qty = (payload or {}).get("qty")
        if not isinstance(qty, int) or qty <= 0:
            raise ValueError(f"qty must be a positive int, got {qty!r}")


async def main() -> int:
    machine = create_machine(CFG, event_schemas={"FILL": QtySchema()})
    interp = Interpreter(machine, strict=True)
    await interp.start()
    loop = asyncio.get_running_loop()

    results: dict[str, str] = {}

    # --- control: typo on the ordinary send() path -------------------------
    try:
        await interp.send("FIL")
        results["send_typo"] = "accepted"
    except Exception as exc:  # noqa: BLE001
        results["send_typo"] = type(exc).__name__

    # --- control: bad payload on the ordinary send() path ------------------
    try:
        await interp.send("FILL", qty=-1)
        results["send_bad_payload"] = "accepted"
    except Exception as exc:  # noqa: BLE001
        results["send_bad_payload"] = type(exc).__name__

    # --- subject: same typo, from a foreign thread -------------------------
    def foreign(event_type: str, key: str, **payload) -> None:
        try:
            fut = interp.send_threadsafe(event_type, **payload)
            if hasattr(fut, "result"):
                fut.result(timeout=5)
            results[key] = "accepted"
        except Exception as exc:  # noqa: BLE001
            results[key] = type(exc).__name__

    for args in (("FIL", "threadsafe_typo", {}), ("FILL", "threadsafe_bad_payload", {"qty": -1})):
        event_type, key, payload = args
        t = threading.Thread(target=foreign, args=(event_type, key), kwargs=payload)
        t.start()
        while t.is_alive():
            await asyncio.sleep(0.01)
        t.join()

    await asyncio.sleep(0.05)
    states = sorted(interp.current_state_ids)
    try:
        await asyncio.wait_for(interp.stop(), timeout=5.0)
    except Exception:  # noqa: BLE001
        pass

    for k in (
        "send_typo",
        "send_bad_payload",
        "threadsafe_typo",
        "threadsafe_bad_payload",
    ):
        print(f"OBSERVED {k:<24}: {results.get(k)}")
    print(f"OBSERVED final states           : {states}")
    print("EXPECTED send_typo              : UnknownEventError")
    print("EXPECTED threadsafe_typo        : UnknownEventError  (same guardrail)")
    print("EXPECTED threadsafe_bad_payload : InvalidEventPayloadError")

    control_ok = results.get("send_typo") == "UnknownEventError"
    if not control_ok:
        print("RESULT: INCONCLUSIVE - strict mode did not reject the typo on send()")
        return 1

    bypassed = [
        k
        for k in ("threadsafe_typo", "threadsafe_bad_payload")
        if results.get(k) == "accepted"
    ]
    if bypassed:
        print(f"RESULT: DEFECT REPRODUCED (bypassed on: {', '.join(bypassed)})")
        return 1
    print("RESULT: NOT REPRODUCED (fixed)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
