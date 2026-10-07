"""J-1/J-2: what exactly does SnapshotMidStepError guard, and what slips past.

Run: python p1_midstep_snapshot.py
"""

from __future__ import annotations

import asyncio
import json
import sys

sys.path.insert(0, r"<workspace>/_ref/xstate-statemachine")

from src.xstate_statemachine import (  # noqa: E402
    Interpreter,
    MachineLogic,
    SnapshotMidStepError,
    SyncInterpreter,
    create_machine,
)
from src.xstate_statemachine.plugins import PluginBase  # noqa: E402

OUT = {}


# --- J-1: parallel machine, one region transitions slowly -------------------
PAR = {
    "id": "par",
    "type": "parallel",
    "states": {
        "A": {
            "initial": "a1",
            "states": {
                "a1": {"on": {"GO": {"target": "a2", "actions": ["slow"]}}},
                "a2": {},
            },
        },
        "B": {"initial": "b1", "states": {"b1": {}}},
    },
}


async def j1() -> None:
    async def slow(i, c, e, a):
        await asyncio.sleep(0.3)

    i = await Interpreter(
        create_machine(PAR, logic=MachineLogic(actions={"slow": slow}))
    ).start()
    t = asyncio.ensure_future(i.send("GO"))
    await asyncio.sleep(0.1)
    try:
        snap = i.get_persisted_snapshot()
        OUT["j1_refused"] = False
        OUT["j1_state_ids"] = snap["state_ids"]
        OUT["j1_config"] = snap["configuration"]
        OUT["j1_raw"] = snap
    except SnapshotMidStepError:
        OUT["j1_refused"] = True
    await t
    await asyncio.sleep(0.35)
    OUT["j1_settled"] = i.get_persisted_snapshot()["state_ids"]
    await i.stop()
    # does the torn snapshot restore -- and to WHAT?
    if OUT.get("j1_refused") is False:
        try:
            r = SyncInterpreter.from_snapshot(
                json.dumps(OUT.pop("j1_raw"), default=str),
                create_machine(
                    PAR,
                    logic=MachineLogic(actions={"slow": lambda *a: None}),
                ),
            )
            OUT["j1_restored_value"] = r.value
            OUT["j1_restored_status"] = r.status
        except Exception as exc:  # noqa: BLE001
            OUT["j1_restore_error"] = f"{type(exc).__name__}: {exc}"

    # J-1c: from_snapshot with a non-str/None payload -- typed or bare?
    try:
        SyncInterpreter.from_snapshot(None, create_machine(PAR, logic=MachineLogic(actions={"slow": lambda *a: None})))  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        OUT["j1c_none_payload"] = type(exc).__name__
    try:
        SyncInterpreter.from_snapshot("{not json", create_machine(PAR, logic=MachineLogic(actions={"slow": lambda *a: None})))
    except Exception as exc:  # noqa: BLE001
        OUT["j1c_bad_json"] = type(exc).__name__


# --- J-2: is a snapshot legal from inside on_transition / entry action? -----
SEQ = {
    "id": "seq",
    "initial": "a",
    "states": {"a": {"on": {"GO": "b"}}, "b": {"entry": ["probe"]}},
}


class _Snapper(PluginBase):
    def __init__(self):
        self.res = None

    def on_transition(self, interp, frm, to, tr):
        if self.res is None:
            try:
                interp.get_persisted_snapshot()
                self.res = "ok"
            except SnapshotMidStepError:
                self.res = "refused"


async def j2() -> None:
    entry = {}

    def probe(i, c, e, a):
        try:
            i.get_persisted_snapshot()
            entry["r"] = "ok"
        except SnapshotMidStepError:
            entry["r"] = "refused"

    p = _Snapper()
    i = await Interpreter(
        create_machine(SEQ, logic=MachineLogic(actions={"probe": probe}))
    ).start()
    i.use(p)
    await i.send("GO", wait=True)
    await asyncio.sleep(0.05)
    OUT["j2_on_transition"] = p.res
    OUT["j2_entry_action"] = entry.get("r")
    await i.stop()


# --- J-2b: exit action (source exited, target not entered) ------------------
EXITCFG = {
    "id": "ex",
    "initial": "a",
    "states": {"a": {"exit": ["probe"], "on": {"GO": "b"}}, "b": {}},
}


def j2b_sync() -> None:
    res = {}

    def probe(i, c, e, a):
        try:
            i.get_persisted_snapshot()
            res["r"] = "ok"
        except SnapshotMidStepError:
            res["r"] = "refused"

    i = SyncInterpreter(
        create_machine(EXITCFG, logic=MachineLogic(actions={"probe": probe}))
    ).start()
    i.send("GO")
    OUT["j2b_sync_exit_action"] = res.get("r")
    i.stop()


async def j2b_async() -> None:
    res = {}

    async def probe(i, c, e, a):
        try:
            i.get_persisted_snapshot()
            res["r"] = "ok"
        except SnapshotMidStepError:
            res["r"] = "refused"

    i = await Interpreter(
        create_machine(EXITCFG, logic=MachineLogic(actions={"probe": probe}))
    ).start()
    await i.send("GO", wait=True)
    await asyncio.sleep(0.05)
    OUT["j2b_async_exit_action"] = res.get("r")
    await i.stop()


# --- J-3: is there any public quiescence API? -------------------------------
def j3() -> None:
    names = [
        n
        for n in dir(Interpreter)
        if not n.startswith("_")
        and any(k in n.lower() for k in ("settle", "quiesc", "idle", "wait", "drain", "step"))
    ]
    OUT["j3_public_quiescence_api"] = names


async def main() -> None:
    await j1()
    await j2()
    j2b_sync()
    await j2b_async()
    j3()
    print(json.dumps(OUT, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
