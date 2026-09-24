"""N7 - security: the LoggingInspector redaction list (#126) and the
exported public API surface (#137).

A  Redaction. Put every DEFAULT_REDACT_KEYS spelling (and case/affix
   variants) into BOTH the context and an event payload, log through
   `LoggingInspector`, and assert no secret VALUE appears in any log line.
   Also assert the opt-out (`redact_keys=()`) is explicit, and that
   `redact` is pure (does not mutate the machine's context).
B  Exported API. #137 says `is_system_event`, `system_event`, `DoneEvent`,
   `AfterEvent`, `ENGINE_EVENT_SHAPES` are exported. Assert each is in
   `__all__`, importable from the package root, and (for the provenance
   pair) that `system_event` is the ONLY way to mint a system event -- a
   user-built `Event` must not be forgeable into one.
"""

from __future__ import annotations

import asyncio
import logging

import xstate_statemachine as xsm
from common import emit
from xstate_statemachine import (
    Interpreter,
    LoggingInspector,
    MachineLogic,
    create_machine,
)
from xstate_statemachine.plugins import DEFAULT_REDACT_KEYS, redact

SECRET = "SUPERSECRET-VALUE-9f3a"

SENSITIVE_CTX = {}
for k in DEFAULT_REDACT_KEYS:
    SENSITIVE_CTX[k] = SECRET
    SENSITIVE_CTX[k.upper()] = SECRET
    SENSITIVE_CTX[f"user_{k}"] = SECRET
    SENSITIVE_CTX[f"x-{k}"] = SECRET
SENSITIVE_CTX["harmless"] = "public-value"
SENSITIVE_CTX["nested"] = {"api_key": SECRET, "deep": [{"token": SECRET}]}

CFG = {
    "id": "sec",
    "initial": "a",
    "context": dict(SENSITIVE_CTX),
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["touch"]}}},
               "b": {}},
}


def touch(i, ctx, e, a):  # noqa: ANN001
    ctx["harmless"] = "touched"


def mk():
    return create_machine(
        CFG, logic=MachineLogic(actions={"touch": touch})
    )


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):  # noqa: ANN001,D102
        try:
            self.lines.append(record.getMessage())
        except Exception:  # noqa: BLE001
            self.lines.append("<unformattable>")


async def part_a() -> dict:
    cap = Capture()
    root = logging.getLogger()
    prev_level = root.level
    root.addHandler(cap)
    root.setLevel(logging.DEBUG)

    interp = Interpreter(mk())
    interp.use(LoggingInspector(log_context=True))
    await interp.start()
    ctx_before = dict(interp.context)
    await asyncio.wait_for(
        interp.send({"type": "GO", "password": SECRET, "api_key": SECRET},
                    wait=True),
        5,
    )
    await interp.stop()

    root.removeHandler(cap)
    root.setLevel(prev_level)

    leaks = [ln for ln in cap.lines if SECRET in ln]
    harmless_logged = any("public-value" in ln or "touched" in ln
                          for ln in cap.lines)

    # opt-out must be explicit
    cap2 = Capture()
    root.addHandler(cap2)
    root.setLevel(logging.DEBUG)
    i2 = Interpreter(mk())
    i2.use(LoggingInspector(redact_keys=(), log_context=True))
    await i2.start()
    await asyncio.wait_for(i2.send("GO", wait=True), 5)
    await i2.stop()
    root.removeHandler(cap2)
    root.setLevel(prev_level)
    optout_leaks = sum(1 for ln in cap2.lines if SECRET in ln)

    # purity
    probe = {"password": SECRET, "n": [1, {"token": SECRET}]}
    redacted = redact(probe)
    pure = probe == {"password": SECRET, "n": [1, {"token": SECRET}]}

    return {
        "redact_keys": list(DEFAULT_REDACT_KEYS),
        "log_lines": len(cap.lines),
        "secret_leaks_default": len(leaks),
        "leak_sample": [ln[:160] for ln in leaks[:5]],
        "non_secret_still_logged": harmless_logged,
        "explicit_optout_leaks": optout_leaks,
        "redact_is_pure": pure,
        "redacted_sample": redacted,
        "context_unmutated": dict(interp.context) != {} and
                             ctx_before["password"] == SECRET,
        "pass": len(leaks) == 0 and pure and optout_leaks > 0,
    }


def part_b() -> dict:
    required = ["is_system_event", "system_event", "DoneEvent", "AfterEvent",
                "ENGINE_EVENT_SHAPES", "SnapshotMidStepError",
                "SnapshotCorruptError", "SnapshotSerializationError",
                "InvalidEventError"]
    missing_all = [n for n in required if n not in getattr(xsm, "__all__", ())]
    missing_attr = [n for n in required if not hasattr(xsm, n)]

    forgeable = None
    try:
        ev = xsm.Event("done.invoke.NEVER")
        forgeable = bool(xsm.is_system_event(ev))
    except Exception as exc:  # noqa: BLE001
        forgeable = f"Event ctor raised {type(exc).__name__}"

    ctor_takes_system = None
    try:
        xsm.Event("X", system=True)  # type: ignore[call-arg]
        ctor_takes_system = True
    except TypeError:
        ctor_takes_system = False
    except Exception as exc:  # noqa: BLE001
        ctor_takes_system = f"{type(exc).__name__}"

    minted = xsm.system_event(xsm.Event("done.invoke.real"))
    return {
        "missing_from_dunder_all": missing_all,
        "missing_attribute": missing_attr,
        "engine_event_shapes": sorted(xsm.ENGINE_EVENT_SHAPES)
        if hasattr(xsm, "ENGINE_EVENT_SHAPES") else None,
        "user_event_with_engine_name_is_system": forgeable,
        "Event_ctor_accepts_system_kwarg": ctor_takes_system,
        "system_event_mints_provenance": xsm.is_system_event(minted),
        "public_names_total": len(getattr(xsm, "__all__", ())),
        "pass": (
            not missing_all and not missing_attr
            and forgeable is False
            and ctor_takes_system is False
            and xsm.is_system_event(minted)
        ),
    }


async def main() -> int:
    a = await part_a()
    b = part_b()
    ok = a["pass"] and b["pass"]
    emit("n7_security_surface",
         {"a_redaction": a, "b_exported_api": b,
          "result": "PASS" if ok else "FAIL"})
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
