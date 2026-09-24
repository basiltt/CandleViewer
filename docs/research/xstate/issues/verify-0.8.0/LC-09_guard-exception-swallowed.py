"""LC-09 verification on xstate-statemachine 0.8.0.

0.8.0 (#35) adds `guard_error_policy: "false" | "true" | "raise"` (default
"false", preserving 0.7.0 semantics) plus `PluginBase.on_guard_error`, which
fires under every policy so a raising guard is now distinguishable.
"""

from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.interpreter import Interpreter
from xstate_statemachine.plugins import PluginBase


class GuardSpy(PluginBase):
    def __init__(self) -> None:
        self.seen = []
        self.errors = []

    def on_guard_evaluated(self, interpreter, guard_type, event, result):  # noqa: ANN001
        self.seen.append((guard_type, result))

    def on_guard_error(self, interpreter, guard_type, event, error):  # noqa: ANN001
        self.errors.append((guard_type, type(error).__name__))


def build(guard_fn, policy=None):
    cfg = {
        "id": "m",
        "initial": "s",
        "states": {
            "s": {
                "on": {
                    "GO": [
                        {"target": "primary", "guard": "risk_ok"},
                        {"target": "fallback"},
                    ]
                }
            },
            "primary": {},
            "fallback": {},
        },
    }
    if policy is not None:
        cfg["guardErrorPolicy"] = policy
    return create_machine(cfg, logic=MachineLogic(guards={"risk_ok": guard_fn}))


def falsy(c, e):  # noqa: ANN001
    return False


def boom(c, e):  # noqa: ANN001
    raise ValueError("risk service unreachable")


async def run(guard_fn, policy=None):
    spy = GuardSpy()
    interp = Interpreter(build(guard_fn, policy))
    interp.use(spy)
    await interp.start()
    raised = None
    try:
        await interp.send("GO")
        await asyncio.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        raised = type(exc).__name__
    out = {
        "state": sorted(interp.current_state_ids),
        "raised": raised,
        "plugin_seen": spy.seen,
        "plugin_errors": spy.errors,
    }
    await interp.stop()
    return out


async def default_case() -> bool:
    """Default policy 'false': behaviour byte-identical to 0.7.0 EXCEPT
    on_guard_error must now fire, making the two cases distinguishable via
    the plugin hook even though state/raised are the same."""
    a = await run(falsy)
    b = await run(boom)
    print(f"DEFAULT OBSERVED: guard returns False -> {a}")
    print(f"DEFAULT OBSERVED: guard RAISES       -> {b}")
    print(
        "EXPECTED (default 'false'): state/raised identical to 0.7.0 (fallback branch, "
        "no raise) BUT plugin_errors distinguishes: [] vs [('risk_ok','ValueError')]"
    )
    same_state = a["state"] == b["state"] == ["m.fallback"]
    distinguishable = a["plugin_errors"] == [] and b["plugin_errors"] == [("risk_ok", "ValueError")]
    return same_state and distinguishable


async def policy_true_case() -> bool:
    b = await run(boom, policy="true")
    print(f"POLICY='true' OBSERVED: guard RAISES -> {b}")
    print("EXPECTED: guarded branch ('primary') selected; interpreter stays running")
    return b["state"] == ["m.primary"] and b["raised"] is None


async def policy_raise_case() -> bool:
    """Under 'raise', async Interpreter run loop logs+continues; caller send() itself
    doesn't propagate (fire-and-forget queue put), but the interpreter must not crash
    and on_guard_error must still have fired."""
    b = await run(boom, policy="raise")
    print(f"POLICY='raise' OBSERVED: guard RAISES -> {b}")
    print("EXPECTED: on_guard_error fired; interpreter remains running (state unchanged, no crash)")
    return b["plugin_errors"] == [("risk_ok", "ValueError")]


async def main() -> int:
    default_ok = await default_case()
    true_ok = await policy_true_case()
    raise_ok = await policy_raise_case()
    print(f"RESULT default_ok={default_ok} true_ok={true_ok} raise_ok={raise_ok}")
    return 0 if (default_ok and true_ok and raise_ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
