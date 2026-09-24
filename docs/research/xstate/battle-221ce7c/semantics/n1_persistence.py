"""N1 — PERSISTENCE attacks on the round-5 fixes (#142/#143/#146/#145/#162).

Hypothesis property over random PARALLEL machines; entry-action window;
history+parallel restore; v1 upcast with torn configuration; "fail"-stopped
snapshot; actors + deferred buffer legality.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Dict, List

from n_harness import attack, main


def _strip(o: Any) -> Any:
    """Drop wall-clock `taken_at` stamps recursively (incl. child actors)."""
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k != "taken_at"}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def _canon(blob: Dict[str, Any]) -> str:
    """Byte-comparable form of a snapshot."""
    return json.dumps(_strip(blob), sort_keys=True)

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SnapshotCorruptError,
    SnapshotMidStepError,
    SyncInterpreter,
    create_machine,
)


def _rand_parallel(rng: random.Random, idx: int) -> Dict[str, Any]:
    """Random 2-3 region parallel machine with compound regions."""
    nregions = rng.randint(2, 3)
    regions: Dict[str, Any] = {}
    for r in range(nregions):
        nstates = rng.randint(2, 3)
        sts: Dict[str, Any] = {}
        names = [f"s{i}" for i in range(nstates)]
        for i, nm in enumerate(names):
            tgt = names[(i + 1) % nstates]
            on: Dict[str, Any] = {"GO": {"target": tgt, "actions": ["bump"]}}
            if rng.random() < 0.4:
                on[f"R{r}"] = {"target": names[rng.randrange(nstates)]}
            sts[nm] = {"on": on}
        regions[f"r{r}"] = {"initial": names[0], "states": sts}
    return {
        "id": f"m{idx}",
        "type": "parallel",
        "context": {"n": 0},
        "states": regions,
    }


def _logic() -> MachineLogic:
    def bump(i_, ctx, e, am):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"bump": bump})


@attack(
    "N1-01",
    "300 random PARALLEL machines: snapshot at EVERY quiescent point never raises and round-trips byte-identical",
    "#142/#143 legality must not reject a legal parallel configuration, nor accept a torn one",
)
def n1_01() -> Dict[str, Any]:
    rng = random.Random(20260919)
    fails: List[str] = []
    cases = 0
    snaps = 0
    for idx in range(300):
        cfg = _rand_parallel(rng, idx)
        m = create_machine(cfg, logic=_logic())
        i = SyncInterpreter(m).start()
        cases += 1
        try:
            for _ in range(12):
                ev = rng.choice(["GO", "R0", "R1", "R2", "NOPE"])
                i.send(ev)
                s1 = i.get_persisted_snapshot()
                b1 = _canon(s1)
                snaps += 1
                j = SyncInterpreter.from_snapshot(json.dumps(s1), create_machine(cfg, logic=_logic())).start()
                b2 = _canon(j.get_persisted_snapshot())
                if b1 != b2:
                    fails.append(f"{cfg['id']}: round-trip drift")
                    break
                if sorted(j.current_state_ids) != sorted(i.current_state_ids):
                    fails.append(f"{cfg['id']}: config drift")
                    break
                j.stop()
        except Exception as exc:  # noqa: BLE001
            fails.append(f"{cfg['id']}: {type(exc).__name__}: {exc}")
        finally:
            i.stop()
        if fails:
            break
    return {"ok": not fails, "cases": cases, "snapshots": snaps, "fails": fails[:5]}


@attack(
    "N1-02",
    "Snapshot from inside an ENTRY action is refused (SnapshotMidStepError) on both engines",
    "D5-semantics-1: the entry-action window has a legal leaf but a half-applied context",
)
async def n1_02() -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    def mk(kind: str):
        seen: Dict[str, Any] = {}
        holder: Dict[str, Any] = {}

        def probe(i_, ctx, e, am):  # noqa: ANN001
            ctx["filled"] = 0
            try:
                holder["i"].get_persisted_snapshot()
                seen["r"] = "ACCEPTED"
                seen["ctx"] = dict(holder["i"].context)
            except SnapshotMidStepError:
                seen["r"] = "SnapshotMidStepError"
            except Exception as exc:  # noqa: BLE001
                seen["r"] = f"{type(exc).__name__}"
            ctx["filled"] = 100

        cfg = {
            "id": "oms",
            "initial": "open",
            "context": {"filled": 0},
            "states": {
                "open": {"on": {"FILL": "filled"}},
                "filled": {"entry": ["probe"]},
            },
        }
        m = create_machine(cfg, logic=MachineLogic(actions={"probe": probe}))
        return m, seen, holder

    m, seen, holder = mk("sync")
    i = SyncInterpreter(m).start()
    holder["i"] = i
    i.send("FILL")
    i.stop()
    out["sync"] = dict(seen)

    m, seen, holder = mk("async")
    ai = await Interpreter(m).start()
    holder["i"] = ai
    await ai.send("FILL", wait=True)
    await ai.stop()
    out["async"] = dict(seen)

    ok = all(
        v.get("r") == "SnapshotMidStepError" for v in out.values()
    )
    return {"ok": ok, **out}


@attack(
    "N1-03",
    "history + parallel: deep history inside a parallel region restores to the remembered leaf",
    "history is a snapshot slot; parallel regions multiply the ways it can tear",
)
def n1_03() -> Dict[str, Any]:
    cfg = {
        "id": "hp",
        "type": "parallel",
        "states": {
            "a": {
                "initial": "idle",
                "states": {
                    "idle": {"on": {"WORK": "busy"}},
                    "busy": {
                        "initial": "b1",
                        "states": {
                            "b1": {"on": {"NEXT": "b2"}},
                            "b2": {},
                        },
                        "on": {"PAUSE": "#hp.a.idle"},
                    },
                    "hist": {"type": "history", "history": "deep"},
                },
            },
            "b": {
                "initial": "x",
                "states": {"x": {"on": {"T": "y"}}, "y": {}},
            },
        },
    }
    m = create_machine(cfg, logic=MachineLogic())
    i = SyncInterpreter(m).start()
    i.send("WORK")
    i.send("NEXT")
    i.send("T")
    before = sorted(i.current_state_ids)
    s = i.get_persisted_snapshot()
    hist = s.get("history")
    i.send("PAUSE")
    s2 = i.get_persisted_snapshot()
    j = SyncInterpreter.from_snapshot(json.dumps(s2), create_machine(cfg, logic=MachineLogic())).start()
    h2 = j.get_persisted_snapshot().get("history")
    after = sorted(j.current_state_ids)
    j.stop()
    i.stop()
    return {
        "ok": before == ["hp.a.busy.b2", "hp.b.y"]
        and h2 == s2.get("history")
        and after == ["hp.a.idle", "hp.b.y"]
        and "hp.a.busy.b2" in (h2 or {}).get("hp.a", []),
        "before": before,
        "hist_at_busy": hist,
        "after_restore": after,
        "hist_restored": h2,
    }


@attack(
    "N1-04",
    "v1 upcast with a TORN configuration is refused, not silently upcast",
    "#143 read-side legality must apply to the v1 migration path too",
)
def n1_04() -> Dict[str, Any]:
    cfg = {
        "id": "p2",
        "type": "parallel",
        "states": {
            "a": {"initial": "a1", "states": {"a1": {}, "a2": {}}},
            "b": {"initial": "b1", "states": {"b1": {}, "b2": {}}},
        },
    }
    m = create_machine(cfg, logic=MachineLogic())
    i = SyncInterpreter(m).start()
    good = i.get_persisted_snapshot()
    i.stop()
    results: Dict[str, str] = {}
    # torn: drop region b entirely
    torn = json.loads(json.dumps(good))
    torn["configuration"] = [
        s for s in torn["configuration"] if not s.startswith("p2.b")
    ]
    for label, blob in (("v2_torn", torn),):
        try:
            SyncInterpreter.from_snapshot(json.dumps(blob), create_machine(cfg, logic=MachineLogic())).start().stop()
            results[label] = "ACCEPTED"
        except SnapshotCorruptError as exc:
            results[label] = f"SnapshotCorruptError: {str(exc)[:70]}"
        except Exception as exc:  # noqa: BLE001
            results[label] = f"{type(exc).__name__}: {str(exc)[:70]}"
    # v1 shape: no `version`, `state_ids` style legacy keys
    v1 = {
        "status": "running",
        "context": {},
        "state_ids": ["p2.a.a1"],
        "machine_id": "p2",
    }
    try:
        SyncInterpreter.from_snapshot(json.dumps(v1), create_machine(cfg, logic=MachineLogic())).start().stop()
        results["v1_torn"] = "ACCEPTED"
    except SnapshotCorruptError as exc:
        results["v1_torn"] = f"SnapshotCorruptError: {str(exc)[:70]}"
    except Exception as exc:  # noqa: BLE001
        results["v1_torn"] = f"{type(exc).__name__}: {str(exc)[:70]}"
    ok = all(v != "ACCEPTED" for v in results.values()) and all(
        "SnapshotCorruptError" in v or "Error" in v for v in results.values()
    )
    return {"ok": ok, **results}


@attack(
    "N1-05",
    '"fail"-stopped machine: snapshot is stopped-typed and its restore is not a live zombie',
    "#145: status stopped + configuration cleared must persist coherently",
)
def n1_05() -> Dict[str, Any]:
    def boom(i_, ctx, e, am):  # noqa: ANN001
        raise RuntimeError("boom")

    cfg = {
        "id": "f",
        "initial": "a",
        "actionErrorPolicy": "fail",
        "states": {"a": {"on": {"GO": {"target": "b", "actions": ["boom"]}}}, "b": {}},
    }
    m = create_machine(cfg, logic=MachineLogic(actions={"boom": boom}))
    i = SyncInterpreter(m).start()
    try:
        i.send("GO")
    except Exception:  # noqa: BLE001,S110
        pass
    status = i.status
    ids = list(i.current_state_ids)
    err = type(i.error).__name__ if getattr(i, "error", None) else None
    try:
        s = i.get_persisted_snapshot()
        snap = {"status": s.get("status"), "config": s.get("configuration")}
        try:
            j = SyncInterpreter.from_snapshot(json.dumps(s), create_machine(cfg, logic=MachineLogic(actions={'boom': boom}))).start()
            restored = {"status": j.status, "ids": list(j.current_state_ids)}
            j.stop()
        except Exception as exc:  # noqa: BLE001
            restored = {"refused": f"{type(exc).__name__}: {str(exc)[:60]}"}
    except Exception as exc:  # noqa: BLE001
        snap = {"refused": f"{type(exc).__name__}"}
        restored = None
    ok = (
        status == "stopped"
        and ids == []
        and err == "TransitionFailedError"
        and (snap.get("status") == "stopped" or "refused" in snap)
        and (restored is None or restored.get("status") != "running")
    )
    return {
        "ok": ok,
        "live_status": status,
        "live_ids": ids,
        "error": err,
        "snapshot": snap,
        "restored": restored,
    }


@attack(
    "N1-06",
    "actors + deferred buffer: a snapshot with live child + deferred events round-trips legally",
    "#162/#146: deferred records and actor blobs are typed and re-checked per record",
)
async def n1_06() -> Dict[str, Any]:
    child = {
        "id": "kid",
        "initial": "run",
        "states": {"run": {"on": {"PING": {"actions": []}}}},
    }
    parent = {
        "id": "par",
        "initial": "up",
        "context": {"n": 0},
        "onUnhandled": "defer",
        "states": {
            "up": {
                "invoke": {"id": "kid", "src": "kid"},
                "on": {"GO": "down"},
            },
            "down": {},
        },
    }
    m = create_machine(
        parent,
        logic=MachineLogic(services={"kid": create_machine(child, logic=MachineLogic())}),
    )
    i = await Interpreter(m).start()
    for _ in range(50):
        await asyncio.sleep(0.005)
        if getattr(i, "_actors", None):
            break
    try:
        await i.send("LATER", wait=True)
    except Exception:  # noqa: BLE001,S110
        pass
    s = i.get_persisted_snapshot()
    b1 = _canon(s)
    await i.stop()
    m2 = create_machine(
        parent,
        logic=MachineLogic(services={"kid": create_machine(child, logic=MachineLogic())}),
    )
    try:
        j = await Interpreter.from_snapshot(json.dumps(s), m2).start()
        b2 = _canon(j.get_persisted_snapshot())
        await j.stop()
        rt = b1 == b2
        err = None
    except Exception as exc:  # noqa: BLE001
        rt = False
        err = f"{type(exc).__name__}: {str(exc)[:90]}"
    # hostile: non-str deferred record type
    bad = json.loads(json.dumps(s))
    if isinstance(bad.get("deferred"), list) and bad["deferred"]:
        bad["deferred"][0] = {"type": 7}
    else:
        bad["deferred"] = [{"type": 7}]
    try:
        Interpreter.from_snapshot(json.dumps(bad), m2)
        typed = "ACCEPTED"
    except SnapshotCorruptError:
        typed = "SnapshotCorruptError"
    except Exception as exc:  # noqa: BLE001
        typed = type(exc).__name__
    return {
        "ok": rt and typed == "SnapshotCorruptError",
        "round_trip": rt,
        "restore_error": err,
        "actors_in_blob": list((s.get("actors") or {}).keys()),
        "deferred_len": len(s.get("deferred") or []),
        "hostile_deferred": typed,
    }


if __name__ == "__main__":
    main("n1_persistence")
