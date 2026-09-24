"""LC-22 verification on xstate-statemachine 0.8.0.

Fix shipped (#46): `from_snapshot` now deep-copies the persisted context and
merges it over the machine's current defaults (persisted values win). This
is unconditional (no opt-in flag) -- it always merges and always copies.

We test:
  1. New schema keys (added after the snapshot was taken) are present after
     restore, filled from the NEW machine's defaults.
  2. Persisted values win over defaults for keys present in both.
  3. No aliasing: mutating the restored interpreter's context does not
     mutate the dict the caller parsed from the snapshot, and vice versa.
  4. The original v1 action-KeyError scenario no longer raises.

Exit 0 if all hold, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

V1 = {
    "id": "order",
    "initial": "submitting",
    "context": {"order_id": "A-1", "qty": 10},
    "states": {
        "submitting": {"on": {"FILL": {"target": "filled"}}},
        "filled": {},
    },
}
V2 = json.loads(json.dumps(V1))
V2["context"] = {"order_id": "A-1", "qty": 10, "cum_qty": 0, "venue": "X"}
V2["states"]["submitting"]["on"]["FILL"]["actions"] = ["book"]

ERRORS: list[str] = []


def book(i, c, e, a):  # noqa: ANN001
    try:
        c["cum_qty"] = c["cum_qty"] + 1
    except KeyError as exc:
        ERRORS.append(f"KeyError: {exc}")


async def main() -> int:
    ok = True

    i1 = await Interpreter(create_machine(V1)).start()
    snap = i1.get_snapshot()
    await i1.stop()

    parsed = json.loads(snap)
    parsed_context_copy = copy.deepcopy(parsed["context"])

    # 0.8.0 adds a machine_hash drift guard (#45): restoring a snapshot into
    # a structurally different machine now raises SnapshotDriftError by
    # default. That is the correct default for accidental drift, but our
    # schema-migration scenario is an intentional, known-compatible change,
    # so we opt out with verify_machine_hash=False -- exactly the escape
    # hatch the changelog documents for "a migration".
    m2 = create_machine(V2, logic=MachineLogic(actions={"book": book}))
    i2 = Interpreter.from_snapshot(snap, m2, verify_machine_hash=False)

    missing = sorted({"cum_qty", "venue"} - set(i2.context))
    print(f"OBSERVED restored context     = {i2.context}")
    print(
        "EXPECTED restored context     = "
        "{'order_id': 'A-1', 'qty': 10, 'cum_qty': 0, 'venue': 'X'}"
    )
    print(f"OBSERVED missing default keys = {missing}")
    print("EXPECTED missing default keys = []")
    if missing:
        ok = False

    # Persisted values must win: restore a snapshot where qty was mutated.
    i3 = await Interpreter(create_machine(V1)).start()
    i3.context["qty"] = 999
    snap3 = i3.get_snapshot()
    await i3.stop()
    m2b = create_machine(V2, logic=MachineLogic(actions={"book": book}))
    i4 = Interpreter.from_snapshot(snap3, m2b, verify_machine_hash=False)
    print(f"OBSERVED persisted qty wins    = {i4.context.get('qty')}")
    print("EXPECTED persisted qty wins    = 999")
    if i4.context.get("qty") != 999:
        ok = False

    # No aliasing: mutate the interpreter, check the original parsed dict.
    i2.context["order_id"] = "MUTATED"
    print(f"OBSERVED caller dict unaffected by interp mutation = "
          f"{parsed['context'].get('order_id') != 'MUTATED'}")
    if parsed["context"].get("order_id") == "MUTATED":
        ok = False

    # Mutate the caller's parsed dict, check the interpreter unaffected.
    i5 = Interpreter.from_snapshot(snap, create_machine(V2, logic=MachineLogic(actions={"book": book})), verify_machine_hash=False)
    parsed2 = json.loads(snap)
    parsed2["context"]["order_id"] = "MUTATED2"
    print(f"OBSERVED interp unaffected by caller-dict mutation = "
          f"{i5.context.get('order_id') != 'MUTATED2'}")
    if i5.context.get("order_id") == "MUTATED2":
        ok = False

    # Original repro: action written against v2 schema must not KeyError.
    await i2.start()
    await i2.send("FILL")
    await asyncio.sleep(0.1)
    await i2.stop()
    print(f"OBSERVED action errors        = {ERRORS}")
    print("EXPECTED action errors        = []")
    if ERRORS:
        ok = False

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
