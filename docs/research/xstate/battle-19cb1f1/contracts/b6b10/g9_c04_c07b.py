# -*- coding: utf-8 -*-
"""C-04 (B16) and C-07b (B18) re-assessment against the corrected JSON @ 19cb1f1.

STANDALONE: stdlib + xstate_statemachine only; the two charts are inlined
verbatim from `battle-f28719c/contracts/B16.machine.json` /
`B18.machine.json` (which are byte-identical to the `.catalogue.json`
siblings -- sha1 9d8ad9937417 / 4e9e8a9b60be), so this runs from any cwd.

Question: were C-04 and C-07b fixed in a later contracts pass, or do they
still reproduce?  Exit 1 while either Blocker is present.

Usage:  python g9_c04_c07b.py [async|def]
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
)

STYLE = sys.argv[1] if len(sys.argv) > 1 else "async"
ROWS: List[Dict[str, Any]] = []


def rec(name: str, present: bool, note: Any) -> None:
    ROWS.append({"check": name, "blocker_present": present, "note": note})
    print(("PRESENT " if present else "fixed   ") + name + "  | "
          + json.dumps(note, default=str), flush=True)


B16 = {
    "id": "session",
    "actionErrorPolicy": "rollback",
    "onUnhandled": "defer",
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "strict": True,
    "type": "parallel",
    "context": {"elevated_until": None, "audit": []},
    "states": {
        "auth": {
            "initial": "pending_mfa",
            "states": {
                "pending_mfa": {
                    "on": {
                        "MFA_OK": {"target": "#session.auth.active"},
                        "MFA_FAILED": {"target": "#session.auth.revoked"},
                        "MFA_TIMEOUT": {"target": "#session.auth.revoked"},
                    }
                },
                "active": {
                    "on": {
                        "REQUEST": {"actions": ["touch_idle"]},
                        "IDLE_DEADLINE": {"target": "#session.auth.revoked"},
                        "ABSOLUTE_DEADLINE": {"target": "#session.auth.revoked"},
                        "REVOKE": {"target": "#session.auth.revoked"},
                        "LOGOUT": {"target": "#session.auth.revoked"},
                    }
                },
                "revoked": {"type": "final"},
            },
        },
        # The elevation region as catalogued: only REVOKE and the elevation's
        # own deadline clear it. LOGOUT / IDLE_DEADLINE / ABSOLUTE_DEADLINE
        # are not handled here at all.
        "elevation": {
            "initial": "normal",
            "states": {
                "normal": {
                    "tags": ["not_elevated"],
                    "on": {
                        "STEP_UP_OK": {
                            "target": "#session.elevation.elevated",
                            "actions": ["stamp_elevated_until", "audit_step_up"],
                        },
                        "STEP_UP_FAILED": {"actions": ["audit_step_up_failed"]},
                    },
                },
                "elevated": {
                    "tags": ["elevated"],
                    "entry": ["schedule_elevation_deadline"],
                    "on": {
                        "ELEVATION_DEADLINE": {
                            "target": "#session.elevation.normal",
                            "actions": ["clear_elevated"],
                        },
                        "STEP_UP_OK": {
                            "target": "#session.elevation.elevated",
                            "reenter": True,
                            "actions": ["stamp_elevated_until"],
                        },
                        "REVOKE": {
                            "target": "#session.elevation.normal",
                            "actions": ["clear_elevated"],
                        },
                    },
                },
            },
        },
    },
}


def b16_logic() -> MachineLogic:
    def noop(i, c, e, a):
        return None

    def stamp(i, c, e, a):
        c["elevated_until"] = 9_999_999

    def clear(i, c, e, a):
        c["elevated_until"] = None

    names = [
        "touch_idle", "audit_step_up", "audit_step_up_failed",
        "schedule_elevation_deadline",
    ]
    acts = {n: noop for n in names}
    acts["stamp_elevated_until"] = stamp
    acts["clear_elevated"] = clear
    return MachineLogic(actions=acts)


B18 = {
    "id": "kill_switch",
    "actionErrorPolicy": "rollback",
    "onUnhandled": "error",          # <-- as catalogued; C-07b is about this
    "guardErrorPolicy": "raise",
    "strictTargets": True,
    "strict": True,
    "initial": "clear",
    "context": {"owner": "op1", "elevated": False},
    "states": {
        "clear": {
            "on": {"ENGAGE": {"target": "#kill_switch.engaging",
                              "actions": ["record_engagement",
                                          "audit_kill_switch"]}}
        },
        "engaging": {
            "entry": ["block_new_orders_immediately",
                      "cancel_entry_and_poll_drains",
                      "broadcast_kill_switch"],
            "always": [{"target": "#kill_switch.engaged"}],
        },
        "engaged": {
            "on": {"RELEASE": {"target": "#kill_switch.clear",
                               "guard": "owner_and_elevated",
                               "actions": ["audit_kill_switch_released"]}}
        },
    },
}


def b18_logic() -> MachineLogic:
    def noop(i, c, e, a):
        return None

    names = ["record_engagement", "audit_kill_switch",
             "block_new_orders_immediately", "cancel_entry_and_poll_drains",
             "broadcast_kill_switch", "audit_kill_switch_released"]
    return MachineLogic(
        actions={n: noop for n in names},
        guards={"owner_and_elevated": lambda c, e: bool(c.get("elevated"))},
    )


async def c04() -> None:
    """C-04: does elevation survive LOGOUT / the deadlines / revocation?"""
    for ev in ("LOGOUT", "IDLE_DEADLINE", "ABSOLUTE_DEADLINE"):
        i = await Interpreter(create_machine(B16, logic=b16_logic())).start()
        await i.send("MFA_OK")
        await i.send("STEP_UP_OK")
        await asyncio.sleep(0.05)
        elevated_before = "elevated" in str(i.value)
        await i.send(ev)
        await asyncio.sleep(0.05)
        val = i.value
        still = "elevated" in str(val) and i.context["elevated_until"] is not None
        await i.stop()
        rec("C-04/B16 elevation outlives %s" % ev, still,
            {"before": elevated_before, "after": val,
             "elevated_until": i.context["elevated_until"]})

    # Acquirable after revocation?
    i = await Interpreter(create_machine(B16, logic=b16_logic())).start()
    await i.send("MFA_OK")
    await i.send("REVOKE")
    await asyncio.sleep(0.05)
    await i.send("STEP_UP_OK")
    await asyncio.sleep(0.05)
    got = "elevated" in str(i.value)
    await i.stop()
    rec("C-04/B16 elevation acquirable AFTER revocation", got,
        {"value": i.value, "elevated_until": i.context["elevated_until"]})


async def c07b() -> None:
    """C-07b: does a guard-denied RELEASE brick the kill switch?"""
    i = await Interpreter(create_machine(B18, logic=b18_logic())).start()
    await i.send("ENGAGE")
    await asyncio.sleep(0.05)
    engaged = i.value
    await i.send("RELEASE")          # guard denies: not elevated
    await asyncio.sleep(0.05)
    bricked = i.status == "error"
    err = type(i.last_error).__name__ if i.last_error else None
    val = i.value
    await i.stop()
    rec("C-07b/B18 guard-denied RELEASE bricks the switch [async]", bricked,
        {"engaged": engaged, "status_after": "error" if bricked else i.status,
         "err": err, "value": val})

    s = SyncInterpreter(create_machine(B18, logic=b18_logic()))
    s.start()
    s.send("ENGAGE")
    try:
        s.send("RELEASE")
    except Exception as exc:                       # noqa: BLE001
        pass
    bricked_s = s.status == "error" or s.last_error is not None
    rec("C-07b/B18 guard-denied RELEASE bricks the switch [sync]", bricked_s,
        {"status": s.status,
         "err": type(s.last_error).__name__ if s.last_error else None,
         "value": s.value})


async def main() -> None:
    print("### style=%s (B16/B18 are action+guard only; no services --\n"
          "###  the style axis is recorded for completeness)" % STYLE)
    await c04()
    await c07b()
    import pathlib
    p = pathlib.Path(__file__).parent / ("results/g9_c04_c07b.%s.json" % STYLE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ROWS, indent=1, default=str), encoding="utf-8")
    n = sum(1 for r in ROWS if r["blocker_present"])
    print("\n--- %d rows, %d still PRESENT" % (len(ROWS), n), flush=True)
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    asyncio.run(main())
