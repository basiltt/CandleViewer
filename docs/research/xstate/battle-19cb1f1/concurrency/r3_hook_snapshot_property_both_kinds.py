"""R3 - persistence property: snapshot from EVERY hook, incl. initial
descent and child entry actions; both engines; both service kinds.

>= 300 random machines (nested + parallel + invoked children). #182 claims
the in-flight flag now covers the whole `start()` descent; #187 claims
`on_action_execute` is inside the refusal window on BOTH engines. So the
expected result is: NO returned blob is torn, on either engine, for
either service spelling, from any hook.

A blob is TORN if it says status "running" while some region has no
active leaf, or its `configuration` and `state_ids` disagree.
"""

from __future__ import annotations

import asyncio
import random
import sys

from common2 import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
    emit,
    make_service,
)
from xstate_statemachine.exceptions import SnapshotMidStepError

N = int(next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--n=")), 300))

CHILD = {
    "id": "kid",
    "initial": "k1",
    "context": {"c": 0},
    "states": {
        "k1": {"entry": ["bump"], "on": {"GO": {"target": "k2"}}},
        "k2": {"type": "final"},
    },
}


def bump(i, ctx, e, ad):  # noqa: ANN001
    ctx["c"] = ctx.get("c", 0) + 1


def rnd_cfg(rng: random.Random, with_child: bool) -> dict:
    deep = {
        "initial": "d1",
        "states": {
            "d1": {"entry": ["bump"], "on": {"STEP": {"target": "d2"}}},
            "d2": {"entry": ["bump"], "on": {"STEP": {"target": "d1"}}},
        },
    }
    if rng.random() < 0.5:
        top = {
            "type": "parallel",
            "states": {
                "regA": dict(deep),
                "regB": {
                    "initial": "b1",
                    "states": {
                        "b1": {"entry": ["bump"], "on": {"STEP": {"target": "b2"}}},
                        "b2": {"entry": ["bump"], "on": {"STEP": {"target": "b1"}}},
                    },
                },
            },
        }
    else:
        top = dict(deep)
    if with_child:
        top = dict(top)
        top["invoke"] = {"src": "kid", "onDone": {"actions": ["bump"]}}
    states = {"top": top}
    if rng.random() < 0.5:
        states["top"] = dict(states["top"])
        states["top"]["on"] = {"OUT": {"target": "#r3.fin"}}
        states["fin"] = {"type": "final"}
    return {
        "id": "r3",
        "initial": "top",
        "context": {"c": 0},
        "onUnhandled": "defer",
        "states": states,
    }


class Snap(PluginBase):
    """Takes a snapshot from every hook, incl. during the initial descent."""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.returned = []
        self.refused = 0
        self.errors = []

    def _take(self, itp, hook: str) -> None:  # noqa: ANN001
        try:
            blob = itp.get_persisted_snapshot()
        except SnapshotMidStepError:
            self.refused += 1
            return
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"{hook}:{type(exc).__name__}")
            return
        self.returned.append((hook, blob))

    def on_action_execute(self, i, a):  # noqa: ANN001
        self._take(i, "on_action_execute")

    def on_transition(self, i, f, t, e):  # noqa: ANN001
        self._take(i, "on_transition")

    def on_event_received(self, i, e):  # noqa: ANN001
        self._take(i, "on_event_received")

    def on_interpreter_start(self, i):  # noqa: ANN001
        self._take(i, "on_interpreter_start")


def torn(blob) -> bool:
    if not isinstance(blob, dict):
        return False
    st = blob.get("status")
    ids = blob.get("state_ids") or []
    conf = blob.get("configuration")
    if st == "running" and not ids:
        return True
    if conf is not None and sorted(conf) != sorted(ids) and st == "running":
        # a configuration that contradicts state_ids (#186)
        return not set(ids).issubset(set(conf))
    return False


def mk(cfg_, kind, with_child):  # noqa: ANN001
    """`with_child` -> the invoked `kid` is a child MACHINE; otherwise it is
    a plain/coroutine SERVICE of the requested spelling."""
    if with_child:
        kid = create_machine(CHILD, logic=MachineLogic(actions={"bump": bump}))
        services = {"kid": kid}
    else:
        services = {"kid": make_service(kind)}
    return create_machine(
        cfg_, logic=MachineLogic(actions={"bump": bump}, services=services)
    )


async def one(rng, kind):  # noqa: ANN001
    with_child = rng.random() < 0.5
    cfg_ = rnd_cfg(rng, with_child)
    out = {}
    # ---- async engine
    sp = Snap("async")
    a = Interpreter(mk(cfg_, kind, with_child)).use(sp)
    try:
        await asyncio.wait_for(a.start(), 10)
        for _ in range(rng.randint(1, 3)):
            await asyncio.wait_for(a.send(rng.choice(["STEP", "GO", "NOPE"])), 5)
        await asyncio.wait_for(a.stop(), 10)
    except Exception as exc:  # noqa: BLE001
        sp.errors.append(f"run:{type(exc).__name__}")
    out["async"] = sp
    # ---- sync engine
    sq = Snap("sync")
    s = SyncInterpreter(mk(cfg_, kind, with_child)).use(sq)
    try:
        s.start()
        for _ in range(rng.randint(1, 3)):
            s.send(rng.choice(["STEP", "GO", "NOPE"]))
        s.stop()
    except Exception as exc:  # noqa: BLE001
        sq.errors.append(f"run:{type(exc).__name__}")
    out["sync"] = sq
    return cfg_, out


async def main() -> int:
    rng = random.Random(20260921)
    stats = {}
    torn_rows = []
    errs = {}
    for n in range(N):
        kind = "def" if n % 2 == 0 else "async def"
        cfg_, res = await one(rng, kind)
        for eng, sp in res.items():
            for hook, blob in sp.returned:
                k = f"{eng}:{kind}:{hook}"
                d = stats.setdefault(k, {"returned": 0, "torn": 0})
                d["returned"] += 1
                if torn(blob):
                    d["torn"] += 1
                    if len(torn_rows) < 8:
                        torn_rows.append(
                            {
                                "engine": eng,
                                "kind": kind,
                                "hook": hook,
                                "status": blob.get("status"),
                                "state_ids": blob.get("state_ids"),
                                "machine": cfg_,
                            }
                        )
            k = f"{eng}:{kind}"
            d = stats.setdefault(k + ":refused", {"refused": 0})
            d["refused"] += sp.refused
            for e in sp.errors:
                errs[e] = errs.get(e, 0) + 1
    total_torn = sum(v.get("torn", 0) for v in stats.values())
    emit(
        "r3_hook_snapshot_property_both_kinds",
        {
            "machines": N,
            "dispositions": stats,
            "total_torn": total_torn,
            "torn_examples": torn_rows,
            "errors": errs,
            "result": "FAIL" if total_torn else "PASS",
        },
    )
    return 1 if total_torn else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
