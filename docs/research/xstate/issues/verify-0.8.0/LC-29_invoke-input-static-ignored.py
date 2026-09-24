"""LC-29 verification on xstate-statemachine 0.8.0.

CHANGELOG [wave 2] "`invoke.input` may be a callable" (#42): fn({context,
event}) or fn(context, event), resolved per spawn via
`InvokeDefinition.resolve_input()`, deep-copied, and passed to a child
MACHINE as its creation `input` (previously never forwarded). This is
unconditional/additive (not an opt-in policy) -- default behaviour itself
changes to forward input correctly.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

CHILD = {
    "id": "leg",
    "initial": "work",
    # context factory receives {"input": <resolved value>} per the documented
    # contract (a plain-dict child context only gets context["input"] set,
    # declared keys are never overwritten -- so we use a factory here).
    "context": lambda args: {"snapshot": (args.get("input") or {}).get("snapshot")},
    "states": {"work": {"on": {"GO": "done"}}, "done": {"type": "final"}},
}

CHILD_PLAIN = {
    "id": "leg",
    "initial": "work",
    "context": {"snapshot": None},
    "states": {"work": {"on": {"GO": "done"}}, "done": {"type": "final"}},
}

PARENT_STATIC = {
    "id": "book",
    "context": {"profile": {"venue": "X", "size": 7}},
    "initial": "running",
    "states": {
        "running": {
            "invoke": {
                "id": "leg1",
                "src": "leg",
                "input": {"snapshot": {"venue": "X", "size": 7}},
            }
        }
    },
}


async def main() -> int:
    ok = True

    # 1) Callable input is resolved (not stored verbatim).
    cfg = {
        **PARENT_STATIC,
        "states": {
            "running": {
                "invoke": {
                    "id": "leg1",
                    "src": "leg",
                    "input": lambda ctx, evt: {"snapshot": ctx["profile"]},
                }
            }
        },
    }
    m = create_machine(cfg, logic=MachineLogic(services={"leg": create_machine(CHILD)}))
    inv = m.states["running"].invoke[0]
    resolved = inv.resolve_input({"profile": {"venue": "X", "size": 7}}, None)
    print(f"OBSERVED resolve_input(callable) = {resolved!r}")
    print("EXPECTED resolved dict, e.g. {'snapshot': {'venue': 'X', 'size': 7}}")
    if resolved != {"snapshot": {"venue": "X", "size": 7}}:
        ok = False

    # single-mapping arity form
    inv2_cfg = {
        **PARENT_STATIC,
        "states": {
            "running": {
                "invoke": {
                    "id": "leg1",
                    "src": "leg",
                    "input": lambda args: {"snapshot": args["context"]["profile"]},
                }
            }
        },
    }
    m2 = create_machine(inv2_cfg, logic=MachineLogic(services={"leg": create_machine(CHILD)}))
    inv2 = m2.states["running"].invoke[0]
    resolved2 = inv2.resolve_input({"profile": {"venue": "X", "size": 7}}, None)
    print(f"OBSERVED resolve_input(single-mapping arity) = {resolved2!r}")
    if resolved2 != {"snapshot": {"venue": "X", "size": 7}}:
        ok = False

    # 2) Static input reaches the spawned child's context (via a context
    # factory that reads {"input": ...} -- the documented contract).
    parent_m = create_machine(
        PARENT_STATIC, logic=MachineLogic(services={"leg": create_machine(CHILD)})
    )
    interp = await Interpreter(parent_m).start()
    await asyncio.sleep(0.05)
    child = next(iter(interp._actors.values()))
    print(f"OBSERVED spawned child context (factory) = {child.context}")
    print("EXPECTED context = {'snapshot': {'venue': 'X', 'size': 7}}")
    if child.context.get("snapshot") != {"venue": "X", "size": 7}:
        ok = False

    # 3) deep-copy: mutating parent context after spawn does not alias child
    parent_profile = interp.context["profile"]
    parent_profile["size"] = 999
    print(f"OBSERVED child context after parent mutation = {child.context}")
    if child.context.get("snapshot", {}).get("size") == 999:
        ok = False
        print("OBSERVED input was aliased, not deep-copied -- BAD")
    await interp.stop()

    # 4) plain-dict child context: input is stashed under context["input"],
    # declared keys ("snapshot") are NOT overwritten (documented behaviour).
    parent_m2 = create_machine(
        PARENT_STATIC, logic=MachineLogic(services={"leg": create_machine(CHILD_PLAIN)})
    )
    interp2 = await Interpreter(parent_m2).start()
    await asyncio.sleep(0.05)
    child2 = next(iter(interp2._actors.values()))
    print(f"OBSERVED spawned child context (plain dict) = {child2.context}")
    print("EXPECTED input reachable at context['input'], declared 'snapshot' key untouched")
    if child2.context.get("input") != {"snapshot": {"venue": "X", "size": 7}}:
        ok = False
    await interp2.stop()

    print("RESULT:", "FIXED (invoke.input resolved and forwarded to child)" if ok else "NOT FIXED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
