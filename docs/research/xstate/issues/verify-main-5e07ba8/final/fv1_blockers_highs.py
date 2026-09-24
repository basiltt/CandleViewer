"""Final-verdict fresh-process re-reproduction: surviving Blockers + Highs.

Run with the pinned venv:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
  _ref/xstate-statemachine/.venv-main/Scripts/python fv1_blockers_highs.py

No library source is modified. Public API only.
"""
import asyncio
import json
import threading
import logging
import time


def _snap(interp):
    raw = interp.get_persisted_snapshot()
    return json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

logging.disable(logging.CRITICAL)

OUT = {}


# ---------- R4-12 (High): transition to the machine root empties configuration
def r4_12():
    cfg = {"id": "m", "initial": "a", "states": {"a": {"always": "#m"}, "b": {}}}
    s = SyncInterpreter(create_machine(cfg, logic=MachineLogic())).start()
    sync = (sorted(s.current_state_ids), s.status)
    snap = _snap(s)

    cfg2 = {"id": "m2", "initial": "a", "states": {"a": {"on": {"GO": "#m2"}}, "b": {}}}
    s2 = SyncInterpreter(create_machine(cfg2, logic=MachineLogic())).start()
    before = sorted(s2.current_state_ids)
    s2.send("GO")
    after = (sorted(s2.current_state_ids), s2.status)
    return {
        "always_start": sync,
        "snap_state_ids": snap.get("state_ids"),
        "snap_configuration": snap.get("configuration"),
        "on_before": before,
        "on_after": after,
        "REPRO": sync == ([], "running") and after == ([], "running"),
    }


# ---------- R4-19 (High): child output discarded; parent gets the child context
def r4_19():
    child = {
        "id": "kid",
        "initial": "w",
        "context": {"ctxkey": 1},
        "states": {
            "w": {"always": "fin"},
            "fin": {"type": "final", "output": {"code": 7}},
        },
    }
    parent = {
        "id": "m",
        "initial": "run",
        "states": {
            "run": {
                "invoke": {
                    "id": "kid",
                    "src": "kid",
                    "onDone": {"target": "done", "actions": ["cap"]},
                }
            },
            "done": {},
        },
    }
    seen = {}

    def cap(i, c, e, a):
        seen["data"] = getattr(e, "data", None)

    cm = create_machine(child, logic=MachineLogic())
    pm = create_machine(
        parent, logic=MachineLogic(services={"kid": cm}, actions={"cap": cap})
    )
    s = SyncInterpreter(pm).start()
    return {
        "parent_done_data": seen.get("data"),
        "expected": {"code": 7},
        "final_state": sorted(s.current_state_ids),
        "REPRO": seen.get("data") != {"code": 7},
    }


# ---------- R4-04 (Blocker): SyncInterpreter.start() never terminates
def r4_04(max_iter, budget_s):
    cfg = {
        "id": "m",
        "type": "parallel",
        "maxIterations": max_iter,
        "states": {
            "A": {
                "initial": "a1",
                "states": {
                    "a1": {
                        "invoke": {"id": "sv", "src": "sv", "onDone": {"target": "a1"}}
                    },
                    "a2": {},
                },
            },
            "B": {"initial": "b1", "states": {"b1": {"always": {"target": "#m.A.a1"}}}},
        },
    }

    def sv(i, c, e):
        return 1

    res = {}

    def run():
        try:
            st = time.time()
            SyncInterpreter(
                create_machine(cfg, logic=MachineLogic(services={"sv": sv}))
            ).start()
            res["elapsed_s"] = round(time.time() - st, 3)
        except Exception as ex:  # noqa: BLE001
            res["err"] = repr(ex)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(budget_s)
    return {"max_iterations": max_iter, "finished": not t.is_alive(), **res}


# ---------- R4-01 (Blocker): mid-macrostep torn snapshot restores inert
async def r4_01():
    cfg = {
        "id": "t",
        "initial": "a",
        "states": {"a": {"on": {"GO": {"target": "b", "actions": ["slow"]}}}, "b": {}},
    }

    async def slow(i, c, e, a):
        await asyncio.sleep(0.25)

    logic = lambda: MachineLogic(actions={"slow": slow})  # noqa: E731
    i = Interpreter(create_machine(cfg, logic=logic()))
    await i.start()
    task = asyncio.ensure_future(i.send("GO"))
    await asyncio.sleep(0.10)
    snap = _snap(i)
    torn = snap.get("state_ids") == []
    probe = {
        "queue_depth": i.queue_depth,
        "pending_events": list(i.pending_events),
        "is_running": i.is_running,
    }
    await task
    await i.stop()
    out = {
        "state_ids": snap.get("state_ids"),
        "configuration": snap.get("configuration"),
        "status": snap.get("status"),
        "public_probe_mid_window": probe,
        "torn": torn,
    }
    if torn:
        r = Interpreter.from_snapshot(json.dumps(snap), create_machine(cfg, logic=logic()))
        await r.start()
        rec = await r.send("PING", wait=True)
        out["restored_cfg"] = sorted(r.current_state_ids)
        out["restored_status"] = r.status
        out["restored_dormant"] = r.has_dormant_invocations
        out["ping_changed"] = rec.changed
        out["ping_error"] = repr(rec.error)
        await r.stop()
    out["REPRO"] = torn
    return out


# ---------- R4-06 (High): external events charged to the chain budget
async def r4_06(burst):
    cfg = {
        "id": "m",
        "initial": "a",
        "context": {"n": 0},
        "states": {"a": {"on": {"T": {"actions": ["inc"]}, "SLOW": {"actions": ["slow"]}}}},
    }

    def inc(i, c, e, a):
        c["n"] += 1

    async def slow(i, c, e, a):
        await asyncio.sleep(0.4)

    dropped = []

    class P:
        def on_event_dropped(self, i, ev, reason):
            dropped.append(reason)

        def __getattr__(self, n):
            return lambda *a, **k: None

    i = Interpreter(create_machine(cfg, logic=MachineLogic(actions={"inc": inc, "slow": slow})))
    i.use(P())
    await i.start()
    await i.send("SLOW")
    await asyncio.sleep(0.02)
    for _ in range(burst):
        await i.send("T")
    for _ in range(400):
        if i.queue_depth == 0:
            break
        await asyncio.sleep(0.02)
    n = i.context["n"]
    ok = i.last_transition_ok
    await i.stop()
    return {
        "burst": burst,
        "applied": n,
        "lost": burst - n,
        "dropped_reasons": dropped[:5],
        "last_transition_ok": ok,
        "REPRO": burst - n > 0,
    }


# ---------- R4-07 (High): Receipt.deferred false positives + id-set growth
def r4_07(n):
    cfg = {
        "id": "m",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"BACK": "a"}}},
    }
    s = SyncInterpreter(create_machine(cfg, logic=MachineLogic())).start()
    false_pos = 0
    checked = 0
    for _ in range(n):
        s.send("GO")
        r = s.send("BACK", wait=True)
        if r is not None:
            checked += 1
            if getattr(r, "deferred", False) and r.changed:
                false_pos += 1
    leaked = len(getattr(s, "_deferred_this_step", ()))
    return {
        "receipts_checked": checked,
        "false_positives_deferred_and_changed": false_pos,
        "leaked_ids_in__deferred_this_step": leaked,
        "REPRO": false_pos > 0 or leaked > 0,
    }


# ---------- R4-11 (High): priority lane never persisted
async def r4_11():
    cfg = {
        "id": "m",
        "initial": "a",
        "states": {"a": {"on": {"SLOW": {"actions": ["slow"]}, "A": {}, "B": {}}}},
    }

    async def slow(i, c, e, a):
        await asyncio.sleep(0.5)

    i = Interpreter(create_machine(cfg, logic=MachineLogic(actions={"slow": slow})))
    await i.start()
    await i.send("SLOW")
    await asyncio.sleep(0.02)
    await i.send("A")
    await i.send("B")
    await i.send("URGENT", priority=True)
    snap = _snap(i)
    names = [p.get("type") for p in snap.get("pending_events", [])]
    out = {
        "status": i.status,
        "queue_depth": i.queue_depth,
        "drain_pending_visible": None,
        "snapshot_pending": names,
        "REPRO": "URGENT" not in names,
    }
    await i.stop()
    return out


# ---------- R4-03 (High): BLOCK fire-and-forget send is not delivered
async def r4_03():
    from xstate_statemachine import OverflowPolicy

    cfg = {
        "id": "m",
        "initial": "a",
        "context": {"n": 0},
        "states": {"a": {"on": {"GO": {"actions": ["inc"]}}}},
    }

    def inc(i, c, e, a):
        c["n"] += 1

    res = {}
    for pol in ("BLOCK", "RAISE", "DROP_NEWEST"):
        i = Interpreter(
            create_machine(cfg, logic=MachineLogic(actions={"inc": inc})),
            max_queue_size=10,
            overflow_policy=getattr(OverflowPolicy, pol),
        )
        await i.start()
        i.send("GO")  # fire-and-forget, deliberately not awaited
        await asyncio.sleep(0.15)
        res[pol] = {"n": i.context["n"], "queue_depth": i.queue_depth}
        await i.stop()
    res["REPRO"] = res["BLOCK"]["n"] == 0 and res["RAISE"]["n"] == 1
    return res


async def main():
    OUT["R4-12"] = r4_12()
    OUT["R4-19"] = r4_19()
    OUT["R4-01"] = await r4_01()
    OUT["R4-06"] = await r4_06(1500)
    OUT["R4-07"] = r4_07(1500)
    OUT["R4-11"] = await r4_11()
    OUT["R4-03"] = await r4_03()
    print(json.dumps(OUT, indent=1, default=str))


asyncio.run(main())
