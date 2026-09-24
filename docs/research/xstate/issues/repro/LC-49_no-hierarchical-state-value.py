"""LC-49 repro: no hierarchical `state.value` -- only a flat `Set[str]` of ids.

XState exposes `state.value` as a nested structure, e.g.

    {"life": "booking", "protection": {"risk": "armed"}}

which is what `@xstate/react`, the Stately inspector and every XState-shaped
consumer expect. This library exposes only `current_state_ids` (alias
`active_state_ids`), a flat set of fully-qualified *leaf* ids, so the parent /
region structure has to be reconstructed by string-splitting outside the
library.

Exits 1 when no hierarchical `value` is available.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from xstate_statemachine import Interpreter, create_machine

logging.disable(logging.CRITICAL)

CFG = {
    "id": "order",
    "type": "parallel",
    "context": {},
    "states": {
        "life": {
            "initial": "booking",
            "states": {"booking": {}, "filled": {}},
        },
        "protection": {
            "initial": "risk",
            "states": {
                "risk": {
                    "initial": "armed",
                    "states": {"armed": {}, "tripped": {}},
                }
            },
        },
    },
}

EXPECTED_VALUE = {"life": "booking", "protection": {"risk": "armed"}}


async def main() -> int:
    interp = Interpreter(create_machine(CFG))
    await interp.start()

    ids = sorted(interp.current_state_ids)
    value = getattr(interp, "value", None)
    snap = interp.get_snapshot() if hasattr(interp, "get_snapshot") else None
    snap_keys = sorted(snap.keys()) if isinstance(snap, dict) else type(snap).__name__
    await interp.stop()

    print("OBSERVED  current_state_ids:", ids)
    print("OBSERVED  interpreter.value:", value)
    print("OBSERVED  snapshot keys:", snap_keys)
    print("EXPECTED  interpreter.value ==", EXPECTED_VALUE)

    ok = value == EXPECTED_VALUE
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
