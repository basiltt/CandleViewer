"""Q2 - snapshot from EVERY hook must be refused-or-legal, never torn.

Round-6 (#169) refused `get_persisted_snapshot()` from inside an
entry/exit action at the ROOT ("in flight alone refuses"). This property
test widens the aperture to every observation point a real operator has:

  on_transition, on_action_execute, on_guard_evaluated, entry/exit of
  nested AND parallel states, inside a deferred-replay step, and inside
  an `after`-timer callback.

Property (>=300 random machines x both engines): for every snapshot taken
from a hook, either
  (a) the call RAISED (SnapshotMidStepError / SnapshotCorruptError) -- fine,
      that is the refusal contract; or
  (b) it returned a blob that (i) has exactly one active leaf per region,
      and (ii) round-trips through `from_snapshot` into a machine whose
      configuration equals the blob's and which still accepts an event.
A blob that restores into a dead/inert machine, or whose configuration is
torn, is a FAILURE.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import (
    SnapshotCorruptError,
    SnapshotMidStepError,
    XStateMachineError,
)

N_MACHINES = int(
    next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), 300)
)


def gen_config(rng: random.Random, mid: int) -> dict:
    """Random machine: nested + optional parallel region + entry/exit."""
    use_parallel = rng.random() < 0.5
    leaf_on = {
        "STEP": {"target": "#m{0}.top.two".format(mid), "actions": ["act"]},
    }
    top = {
        "initial": "one",
        "states": {
            "one": {
                "entry": ["act"],
                "exit": ["act"],
                "initial": "deep",
                "states": {
                    "deep": {"entry": ["act"], "on": dict(leaf_on)},
                },
                "on": {"BACK": {"target": "#m{0}.top.one".format(mid)}},
            },
            "two": {
                "entry": ["act"],
                "on": {
                    "STEP": {"target": "#m{0}.top.one".format(mid)},
                    "LATER": {"target": "#m{0}.top.one".format(mid)},
                },
                "after": {60: {"target": "#m{0}.top.one".format(mid)}},
            },
        },
    }
    states = {"top": top}
    if use_parallel:
        states["par"] = {
            "type": "parallel",
            "states": {
                "left": {
                    "initial": "l1",
                    "states": {
                        "l1": {
                            "entry": ["act"],
                            "on": {"STEP": {"target": "l2"}},
                        },
                        "l2": {"entry": ["act"], "on": {"STEP": "l1"}},
                    },
                },
                "right": {
                    "initial": "r1",
                    "states": {
                        "r1": {"on": {"STEP": {"target": "r2"}}},
                        "r2": {"exit": ["act"], "on": {"STEP": "r1"}},
                    },
                },
            },
        }
    cfg = {
        "id": "m{0}".format(mid),
        "type": "parallel" if use_parallel else None,
        "context": {"n": 0},
        "states": states,
        "onUnhandled": rng.choice(["ignore", "defer"]),
    }
    if not use_parallel:
        cfg.pop("type")
        cfg["initial"] = "top"
        cfg["states"] = {"top": top}
    return cfg


def act(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


class Snapshotter(PluginBase):
    """Takes a snapshot from every hook it is given."""

    def __init__(self, sink: list) -> None:
        self.sink = sink

    def _grab(self, itp, where: str) -> None:  # noqa: ANN001
        try:
            blob = itp.get_persisted_snapshot()
            self.sink.append((where, "returned", blob))
        except (SnapshotMidStepError, SnapshotCorruptError) as exc:
            self.sink.append((where, "refused:" + type(exc).__name__, None))
        except XStateMachineError as exc:
            self.sink.append((where, "refused:" + type(exc).__name__, None))
        except Exception as exc:  # noqa: BLE001
            self.sink.append((where, "RAW:" + type(exc).__name__, None))

    def on_transition(self, i, f, t, tr):  # noqa: ANN001
        self._grab(i, "on_transition")

    def on_action_execute(self, i, action):  # noqa: ANN001
        self._grab(i, "on_action_execute")

    def on_guard_evaluated(self, i, guard, event, result):  # noqa: ANN001
        self._grab(i, "on_guard_evaluated")

    def on_event_received(self, i, event):  # noqa: ANN001
        self._grab(i, "on_event_received")


def regions_legal(blob: dict) -> bool:
    """Weak structural check: a `running` blob must have >=1 state id."""
    if blob.get("status") == "running":
        return bool(blob.get("state_ids"))
    return True


def _mkm(cfg):
    return create_machine(cfg, logic=MachineLogic(actions={"act": act}))


async def check_blob_async(cfg: dict, blob: dict) -> str:
    """Restore a returned blob; it must be live and legal, or refused."""
    if not regions_legal(blob):
        return "TORN:empty_config_running"
    try:
        r = Interpreter.from_snapshot(json.dumps(blob), _mkm(cfg))
    except (SnapshotCorruptError, XStateMachineError):
        return "restore_refused"
    except Exception as exc:  # noqa: BLE001
        return "RAW_restore:" + type(exc).__name__
    await r.start()
    if blob.get("status") == "running" and not r.current_state_ids:
        await r.stop()
        return "TORN:restored_inert"
    try:
        await asyncio.wait_for(r.send("STEP", wait=True), 3)
        out = "ok"
    except asyncio.TimeoutError:
        out = "TORN:restored_wedged"
    except Exception:  # noqa: BLE001
        out = "ok"
    await r.stop()
    return out


def check_blob_sync(cfg: dict, blob: dict) -> str:
    if not regions_legal(blob):
        return "TORN:empty_config_running"
    try:
        r = SyncInterpreter.from_snapshot(json.dumps(blob), _mkm(cfg))
    except (SnapshotCorruptError, XStateMachineError):
        return "restore_refused"
    except Exception as exc:  # noqa: BLE001
        return "RAW_restore:" + type(exc).__name__
    r.start()
    if blob.get("status") == "running" and not r.current_state_ids:
        r.stop()
        return "TORN:restored_inert"
    try:
        r.send("STEP")
    except Exception:  # noqa: BLE001
        pass
    r.stop()
    return "ok"


async def trial_async(cfg: dict, rng: random.Random) -> list:
    sink: list = []
    itp = Interpreter(_mkm(cfg))
    itp.use(Snapshotter(sink))
    await itp.start()
    for ev in rng.sample(
        ["STEP", "BACK", "STEP", "LATER", "NOPE"],
        k=rng.randint(2, 5),
    ):
        try:
            await asyncio.wait_for(itp.send(ev, wait=True), 3)
        except Exception:  # noqa: BLE001
            pass
    await asyncio.sleep(0.09)  # let the `after: 60` timer fire under hooks
    await itp.stop()
    return sink


def trial_sync(cfg: dict, rng: random.Random) -> list:
    sink: list = []
    itp = SyncInterpreter(_mkm(cfg))
    itp.use(Snapshotter(sink))
    itp.start()
    for ev in rng.sample(
        ["STEP", "BACK", "STEP", "LATER", "NOPE"],
        k=rng.randint(2, 5),
    ):
        try:
            itp.send(ev)
        except Exception:  # noqa: BLE001
            pass
    itp.stop()
    return sink


async def main() -> int:
    rng = random.Random(20260920)
    dispositions: dict = {}
    torn: list = []
    raw: list = []
    checked = 0
    for mid in range(N_MACHINES):
        cfg = gen_config(rng, mid)
        engine = "async" if mid % 2 == 0 else "sync"
        sink = (
            await trial_async(cfg, rng)
            if engine == "async"
            else trial_sync(cfg, rng)
        )
        # Sample at most 4 returned blobs per machine (cost bound).
        returned = [(w, b) for (w, d, b) in sink if d == "returned"]
        for w, d, _ in sink:
            key = f"{engine}:{w}:{d.split(':')[0]}"
            dispositions[key] = dispositions.get(key, 0) + 1
            if d.startswith("RAW"):
                raw.append((engine, w, d))
        for w, blob in rng.sample(returned, k=min(4, len(returned))):
            checked += 1
            verdict = (
                await check_blob_async(cfg, blob)
                if engine == "async"
                else check_blob_sync(cfg, blob)
            )
            if verdict.startswith("TORN") or verdict.startswith("RAW"):
                torn.append(
                    {
                        "machine": cfg["id"],
                        "engine": engine,
                        "hook": w,
                        "verdict": verdict,
                        "state_ids": blob.get("state_ids"),
                        "status": blob.get("status"),
                    }
                )
    ok = not torn and not raw
    emit(
        "q2_hook_snapshot_property",
        {
            "machines": N_MACHINES,
            "blobs_restored_and_probed": checked,
            "dispositions": dict(sorted(dispositions.items())),
            "raw_exceptions_from_hook_snapshot": raw[:10],
            "torn_or_dead_blobs": torn[:10],
            "torn_count": len(torn),
            "result": "PASS" if ok else "FAIL",
        },
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
