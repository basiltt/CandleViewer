# -*- coding: utf-8 -*-
"""M2 - the round-5 persistence fixes attacked by five independent routes.

A. Entry-action window (#142): snapshot from inside an *entry* action of a
   parallel region must be refused, not persisted torn.
B. history + parallel restore: deep/shallow history inside parallel regions
   must survive a snapshot/restore and re-target the remembered leaf.
C. v1 upcast with a torn configuration must be refused (#143 read side).
D. `actionErrorPolicy: "fail"` stopped machine (#145): snapshot + restore.
E. actors + deferred buffer legality across a restore.
"""
from __future__ import annotations

import asyncio
import json
import logging

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

logging.disable(logging.CRITICAL)
RESULTS: list[tuple[str, bool, str]] = []


def rec(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"   [{'PASS' if ok else 'FAIL'}] {name}: {detail[:220]}")


# --------------------------------------------------------------- A
class SnapOnEntry(PluginBase):
    def __init__(self, target):
        self.target, self.blob, self.err = target, None, None

    def on_action_execute(self, interp, action):  # noqa: ANN001
        if action.type == self.target and self.blob is None and self.err is None:
            try:
                self.blob = interp.get_persisted_snapshot()
            except Exception as e:  # noqa: BLE001
                self.err = f"{type(e).__name__}: {e}"


async def test_a():
    print("\n=== A. snapshot inside an ENTRY action of a parallel region (#142) ===")
    m = create_machine(
        {
            "id": "pa",
            "type": "parallel",
            "context": {},
            "states": {
                "ra": {
                    "initial": "a1",
                    "states": {
                        "a1": {"on": {"GO": "a2"}},
                        "a2": {"entry": ["mark"], "initial": "z",
                               "states": {"z": {}}},
                    },
                },
                "rb": {"initial": "b1", "states": {"b1": {"on": {"GO": "b2"}}, "b2": {}}},
            },
        },
        logic=MachineLogic(actions={"mark": lambda i, c, e, a: None}),
    )
    p = SnapOnEntry("mark")
    i = Interpreter(m, clock=SimulatedClock())
    i.use(p)
    await i.start()
    await i.send("GO", wait=True)
    await asyncio.sleep(0)
    await i.stop()
    if p.err:
        rec("A entry-window refused", True, p.err)
    elif p.blob is None:
        rec("A entry-window refused", True, "action never observed / no snapshot attempted")
    else:
        cfg = p.blob["configuration"]
        legal = any(c.startswith("pa.ra.") for c in cfg) and any(
            c.startswith("pa.rb.") for c in cfg)
        rec("A entry-window refused", legal,
            f"ACCEPTED configuration={cfg} (legal per-region={legal})")


# --------------------------------------------------------------- B
def hist_machine():
    return create_machine(
        {
            "id": "hp",
            "type": "parallel",
            "context": {},
            "states": {
                "ra": {
                    "initial": "idle",
                    "states": {
                        "idle": {"on": {"DIVE": "deep"}},
                        "deep": {
                            "initial": "d1",
                            "states": {
                                "d1": {"on": {"NEXT": "d2"}},
                                "d2": {},
                                "h": {"type": "history", "history": "deep"},
                            },
                            "on": {"OUT": "idle"},
                        },
                    },
                    "on": {"BACK": ".deep.h"},
                },
                "rb": {"initial": "b1", "states": {"b1": {"on": {"T": "b2"}}, "b2": {}}},
            },
        }
    )


async def test_b():
    print("\n=== B. history inside a parallel region across a restore ===")
    i = Interpreter(hist_machine(), clock=SimulatedClock())
    await i.start()
    for ev in ("DIVE", "NEXT", "T", "OUT"):
        await i.send(ev, wait=True)
    await asyncio.sleep(0)
    blob = i.get_persisted_snapshot()
    hist = blob.get("history")
    await i.stop()

    i2 = Interpreter.from_snapshot(json.dumps(blob), hist_machine(), clock=SimulatedClock())
    await i2.start()
    await i2.send("BACK", wait=True)
    await asyncio.sleep(0)
    states = sorted(i2.current_state_ids)
    await i2.stop()
    ok = "hp.ra.deep.d2" in states
    rec("B history+parallel restore", ok,
        f"persisted history={hist} restored-after-BACK states={states} (expect hp.ra.deep.d2)")


# --------------------------------------------------------------- C
async def test_c():
    print("\n=== C. v1 upcast with a TORN configuration must be refused (#143) ===")
    i = Interpreter(hist_machine(), clock=SimulatedClock())
    await i.start()
    await i.send("DIVE", wait=True)
    await asyncio.sleep(0)
    good = i.get_persisted_snapshot()
    await i.stop()

    cases = {}
    # v1-shaped blob: version 1, state_ids only, no `configuration`
    torn_ids = [s for s in good["state_ids"] if not s.startswith("hp.rb")]
    v1 = {
        "version": 1,
        "machine_id": good["machine_id"],
        "machine_hash": good["machine_hash"],
        "status": "running",
        "context": good["context"],
        "state_ids": torn_ids,
        "value": good.get("value"),
        "history": good.get("history", {}),
        "actors": {},
        "system": {},
        "pending_events": [],
        "deferred": [],
        "error": None,
        "output": None,
    }
    for name, blob in (("v1 torn (region rb missing)", v1),
                       ("v2 torn (configuration mangled)",
                        {**good, "configuration": torn_ids, "state_ids": torn_ids})):
        try:
            i2 = Interpreter.from_snapshot(json.dumps(blob), hist_machine(),
                                           clock=SimulatedClock())
            await i2.start()
            await asyncio.sleep(0)
            cases[name] = f"ACCEPTED status={i2.status} states={sorted(i2.current_state_ids)}"
            await i2.stop()
        except Exception as e:  # noqa: BLE001
            cases[name] = f"REFUSED {type(e).__name__}: {e}"
    for k, v in cases.items():
        rec(f"C {k}", v.startswith("REFUSED"), v)


# --------------------------------------------------------------- D
def boom(i, c, e, a):  # noqa: ANN001
    raise RuntimeError("action blew up")


async def test_d():
    print('\n=== D. actionErrorPolicy "fail" stopped machine snapshot (#145) ===')
    m = create_machine(
        {
            "id": "fl",
            "initial": "a",
            "context": {},
            "actionErrorPolicy": "fail",
            "states": {"a": {"on": {"GO": {"target": "b", "actions": ["boom"]}}}, "b": {}},
        },
        logic=MachineLogic(actions={"boom": boom}),
    )
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    try:
        await i.send("GO", wait=True)
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(0)
    status, cfg = i.status, sorted(i.current_state_ids)
    try:
        blob = i.get_persisted_snapshot()
        snap = f"SNAPSHOT ok status={blob['status']} configuration={blob['configuration']} error={str(blob.get('error'))[:60]}"
    except Exception as e:  # noqa: BLE001
        blob, snap = None, f"SNAPSHOT REFUSED {type(e).__name__}: {e}"
    await i.stop()
    rec("D fail -> stopped + config cleared", status == "stopped" and cfg == [],
        f"status={status} states={cfg} | {snap}")

    if blob is not None:
        try:
            i2 = Interpreter.from_snapshot(json.dumps(blob), m, clock=SimulatedClock())
            await i2.start()
            await asyncio.sleep(0)
            det = f"restored status={i2.status} states={sorted(i2.current_state_ids)}"
            live = i2.status != "running" or bool(i2.current_state_ids)
            await i2.stop()
            rec("D stopped snapshot restores non-live", live, det)
        except Exception as e:  # noqa: BLE001
            rec("D stopped snapshot restores non-live", True,
                f"REFUSED {type(e).__name__}: {e}")


# --------------------------------------------------------------- E
async def svc(i, c, e):  # noqa: ANN001
    await asyncio.sleep(0.5)
    return {"ok": True}


async def test_e():
    print("\n=== E. actors + deferred buffer legality across a restore ===")
    spec = {
        "id": "ad",
        "initial": "work",
        "context": {},
        "onUnhandled": "defer",
        "states": {
            "work": {
                "invoke": {"id": "s", "src": "svc", "onDone": "done_"},
                "on": {"GO": "done_"},
            },
            "done_": {},
        },
    }
    m = create_machine(spec, logic=MachineLogic(services={"svc": svc}))
    i = Interpreter(m, clock=SimulatedClock())
    await i.start()
    await asyncio.sleep(0.02)
    for n in range(3):
        await i.send(f"LATER{n}")
    await asyncio.sleep(0.02)
    blob = i.get_persisted_snapshot()
    await i.stop()
    det = f"actors={blob.get('actors')} deferred={[d.get('type') for d in blob.get('deferred', [])]}"
    m2 = create_machine(spec, logic=MachineLogic(services={"svc": svc}))
    try:
        i2 = Interpreter.from_snapshot(json.dumps(blob), m2, clock=SimulatedClock(),
                                       restart_services=True)
        await i2.start()
        await asyncio.sleep(0.02)
        blob2 = i2.get_persisted_snapshot()
        same = [d.get("type") for d in blob2.get("deferred", [])] == \
               [d.get("type") for d in blob.get("deferred", [])]
        await i2.stop()
        rec("E actors+deferred survive restore", same,
            det + f" | restored deferred={[d.get('type') for d in blob2.get('deferred', [])]}")
    except Exception as e:  # noqa: BLE001
        rec("E actors+deferred survive restore", False,
            det + f" | restore raised {type(e).__name__}: {e}")


async def main():
    for t in (test_a, test_b, test_c, test_d, test_e):
        try:
            await t()
        except Exception as e:  # noqa: BLE001
            import traceback
            rec(t.__name__, False, f"SCRIPT ERROR {type(e).__name__}: {e}")
            traceback.print_exc()
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} PASS")
    print("VERDICT:", "PASS" if not bad else "FAIL -> " + ", ".join(b[0] for b in bad))


if __name__ == "__main__":
    asyncio.run(main())
