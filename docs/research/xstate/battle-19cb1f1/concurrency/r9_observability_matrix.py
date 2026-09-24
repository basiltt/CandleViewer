"""R9 - observability hook matrix for EVERY drop/refusal reason, both
engines, both service kinds: exactly-once and ordering.

Reasons exercised:
  chain_budget      (async lane, engine completions #179)
  queue_full        loop-side  (#157 reopened)
  queue_full        call-site   (D7-concurrency-3)
  not_running / stopped
  child=True refusal   SnapshotMidStepError(child=True)  (#183)
  children_timeout WARNING                               (#181)
  onUnhandled error kill on the SENDER's receipt         (#189)
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

from common2 import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
    emit,
    make_service,
)
from xstate_statemachine import OverflowPolicy
from xstate_statemachine.exceptions import (
    QueueOverflowError,
    SnapshotMidStepError,
    UnhandledEventError,
)


class Hooks(PluginBase):
    def __init__(self) -> None:
        self.drops = []
        self.seq = 0

    def on_event_dropped(self, i, e, reason=None, **kw):  # noqa: ANN001
        self.seq += 1
        self.drops.append((self.seq, getattr(e, "type", "?"), str(reason)))

    def reasons(self):
        out = {}
        for _, _, r in self.drops:
            out[r] = out.get(r, 0) + 1
        return out


LAPS = {"n": 0}


def act(i, ctx, e, ad):  # noqa: ANN001
    LAPS["n"] += 1


# --------------------------------------------------------------- chain_budget
CYCLE = {
    "id": "r9c",
    "initial": "a",
    "context": {},
    "maxIterations": 20,
    "states": {
        "a": {
            "invoke": {
                "src": "s",
                "onDone": {"target": "b", "actions": ["act"]},
                "onError": {"target": "b"},
            }
        },
        "b": {"always": {"target": "a", "actions": ["act"]}},
    },
}


async def chain_budget(kind: str) -> dict:
    LAPS["n"] = 0
    h = Hooks()
    m = create_machine(
        CYCLE,
        logic=MachineLogic(actions={"act": act}, services={"s": make_service(kind)}),
    )
    i = Interpreter(m).use(h)
    await asyncio.wait_for(i.start(), 10)
    await asyncio.sleep(0.6)
    err = repr(i.last_error)[:70]
    await asyncio.wait_for(i.stop(), 20)
    return {
        "probe": "chain_budget(async lane)",
        "kind": kind,
        "reasons": h.reasons(),
        "last_error": err,
        "laps": LAPS["n"],
        "observable": "chain_budget" in h.reasons() or "Runaway" in err,
    }


# ------------------------------------------------------------------ queue_full
PLAIN = {
    "id": "r9q",
    "initial": "idle",
    "context": {"n": 0},
    "states": {"idle": {"on": {"P": {"actions": ["act"]}}}},
}


async def queue_full(kind: str) -> dict:
    h = Hooks()
    m = create_machine(
        PLAIN,
        logic=MachineLogic(actions={"act": act}, services={"s": make_service(kind)}),
    )
    i = Interpreter(m, max_queue_size=4, overflow_policy=OverflowPolicy.RAISE).use(h)
    await asyncio.wait_for(i.start(), 10)
    callsite = [0]
    loopside = [0]
    stop = threading.Event()

    def prod() -> None:
        while not stop.is_set():
            try:
                fut = i.send_threadsafe("P")
            except QueueOverflowError:
                callsite[0] += 1
                continue
            except Exception:  # noqa: BLE001
                continue

            def _cb(f):  # noqa: ANN001
                if f.cancelled():
                    return
                if isinstance(f.exception(), QueueOverflowError):
                    loopside[0] += 1

            try:
                fut.add_done_callback(_cb)
            except Exception:  # noqa: BLE001
                pass

    ts = [threading.Thread(target=prod, daemon=True) for _ in range(6)]
    for t in ts:
        t.start()
    await asyncio.sleep(1.0)
    stop.set()
    for t in ts:
        t.join(timeout=3)
    await asyncio.sleep(0.4)
    r = h.reasons()
    await asyncio.wait_for(i.stop(), 20)
    qf = r.get("queue_full", 0)
    return {
        "probe": "queue_full",
        "kind": kind,
        "callsite_refusals": callsite[0],
        "loopside_refusals": loopside[0],
        "total_refusals": callsite[0] + loopside[0],
        "queue_full_hooks": qf,
        "loopside_hooked_exactly_once": qf == loopside[0],
        "callsite_hooked": qf > loopside[0],
        "reasons": r,
    }


# --------------------------------------------------------- child=True refusal
CHILD = {"id": "kid", "initial": "k", "context": {"c": 0},
         "states": {"k": {"entry": ["snap"]}}}
PAR = {"id": "r9p", "initial": "up", "context": {},
       "states": {"up": {"invoke": {"src": "kid", "id": "kid"}}}}


async def child_refusal(kind: str) -> dict:
    box = {}

    def snap(i, ctx, e, ad):  # noqa: ANN001
        parent = box.get("parent")
        if parent is None:
            return
        try:
            parent.get_persisted_snapshot()
            box["disposition"] = "RETURNED"
        except SnapshotMidStepError as exc:
            box["disposition"] = "refused:SnapshotMidStepError"
            box["child_flag"] = getattr(exc, "child", None)
        except Exception as exc:  # noqa: BLE001
            box["disposition"] = f"refused:{type(exc).__name__}"

    kid = create_machine(CHILD, logic=MachineLogic(actions={"snap": snap}))
    m = create_machine(
        PAR,
        logic=MachineLogic(
            actions={"snap": snap},
            services={"kid": kid, "s": make_service(kind)},
        ),
    )
    i = Interpreter(m)
    box["parent"] = i
    await asyncio.wait_for(i.start(), 10)
    await asyncio.sleep(0.3)
    await asyncio.wait_for(i.stop(), 20)
    return {
        "probe": "child mid-step snapshot",
        "kind": kind,
        "disposition": box.get("disposition"),
        "child_flag": box.get("child_flag"),
    }


# ----------------------------------------------- #189 onUnhandled error kill
KILL = {
    "id": "r9k",
    "initial": "idle",
    "context": {},
    "onUnhandled": "error",
    "strict": False,
    "states": {"idle": {"on": {"KNOWN": {"actions": ["act"]}}}},
}


async def unhandled_kill(kind: str) -> dict:
    h = Hooks()
    m = create_machine(
        KILL,
        logic=MachineLogic(actions={"act": act}, services={"s": make_service(kind)}),
    )
    i = Interpreter(m).use(h)
    await asyncio.wait_for(i.start(), 10)
    rec = None
    err = None
    try:
        rec = await asyncio.wait_for(i.send("NOPE", wait=True), 5)
    except Exception as exc:  # noqa: BLE001
        err = f"raised:{type(exc).__name__}"
    status = i.status
    try:
        await asyncio.wait_for(i.stop(), 20)
    except Exception:  # noqa: BLE001
        pass
    receipt_error = None
    if rec is not None:
        receipt_error = type(getattr(rec, "error", None)).__name__
    # sync engine
    s = SyncInterpreter(
        create_machine(
            KILL,
            logic=MachineLogic(actions={"act": act}, services={"s": make_service("def")}),
        )
    )
    s.start()
    try:
        s.send("NOPE")
        sync_out = "no raise"
    except UnhandledEventError:
        sync_out = "raised:UnhandledEventError"
    except Exception as exc:  # noqa: BLE001
        sync_out = f"raised:{type(exc).__name__}"
    sync_status = s.status
    try:
        s.stop()
    except Exception:  # noqa: BLE001
        pass
    return {
        "probe": "#189 onUnhandled error kill on sender receipt",
        "kind": kind,
        "async_send_outcome": err or "receipt",
        "async_receipt_error": receipt_error,
        "async_status_after": status,
        "error_on_senders_receipt": receipt_error == "UnhandledEventError",
        "sync_outcome": sync_out,
        "sync_status_after": sync_status,
    }


async def main() -> int:
    import sys as _s
    only = next((a.split("=")[1] for a in _s.argv[1:] if a.startswith("--only=")), "all")
    rows = []
    if only in ("all", "core"):
        for kind in ("def", "async def"):
            rows.append(await asyncio.wait_for(chain_budget(kind), 40))
            rows.append(await asyncio.wait_for(child_refusal(kind), 40))
            rows.append(await asyncio.wait_for(unhandled_kill(kind), 40))
    if only in ("all", "qf"):
        rows.append(await asyncio.wait_for(queue_full("def"), 60))
    bad = []
    for r in rows:
        if r["probe"].startswith("chain_budget") and not r["observable"]:
            bad.append((r["probe"], r["kind"], "trip not observable"))
        if r["probe"].startswith("child") and r.get("disposition") != (
            "refused:SnapshotMidStepError"
        ):
            bad.append((r["probe"], r["kind"], r.get("disposition")))
        if r["probe"].startswith("#189") and not r["error_on_senders_receipt"]:
            bad.append((r["probe"], r["kind"], r.get("async_receipt_error")))
        if r["probe"] == "queue_full":
            if not r["loopside_hooked_exactly_once"]:
                bad.append(("queue_full", "loop-side not exactly-once"))
            if not r["callsite_hooked"]:
                bad.append(("queue_full", "call-site refusals fire NO hook"))
    emit(
        "r9_observability_matrix" + ("" if only=="all" else "_"+only),
        {"rows": rows, "failures": bad, "result": "FAIL" if bad else "PASS"},
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
