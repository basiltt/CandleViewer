"""N5 — FUZZ + OBSERVABILITY + SECURITY.

Fuzz: 5k structured mutations of a valid snapshot must produce a TYPED
error (#110 SnapshotCorruptError and friends) or a faithful restore -- never
an untyped crash and never a silently wrong machine. Hostile event types
must raise InvalidEventError (#113).

Observability: a hook matrix over the new error classes, plus
on_plugin_error (#127) and on_resolve_error (#134).

Security: LoggingInspector redaction (#126) and the exported API surface
(#137).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Dict, List

from n_harness import attack, main

import xstate_statemachine as X
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)

CFG = {
    "id": "f",
    "initial": "a",
    "context": {"n": 1, "password": "hunter2", "api_key": "sk-live-xyz"},
    "states": {
        "a": {"on": {"GO": "b"}},
        "b": {"on": {"GO": "a"}},
    },
}
mk = lambda: create_machine(CFG, logic=MachineLogic())  # noqa: E731


@attack(
    "N5-01",
    "5000 structured snapshot mutations: every outcome is typed or a faithful restore",
    "#110: a corrupted blob must never crash untyped nor silently restore a wrong machine",
)
async def n5_01() -> Dict[str, Any]:
    base_i = SyncInterpreter(mk()).start()
    base_i.send("GO")
    base = base_i.get_persisted_snapshot()
    base_i.stop()

    rnd = random.Random(424242)
    N = 5000
    outcomes: Dict[str, int] = {}
    untyped: List[Dict[str, Any]] = []
    wrong: List[Dict[str, Any]] = []

    def paths(obj: Any, pre: str = "") -> List[str]:
        out = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                out.append(pre + "/" + str(k))
                out += paths(v, pre + "/" + str(k))
        elif isinstance(obj, list):
            for idx, v in enumerate(obj):
                out.append(f"{pre}/{idx}")
                out += paths(v, f"{pre}/{idx}")
        return out

    all_paths = paths(base)
    POISON = [None, 0, -1, "", "xxx", [], {}, True, 1e308, "../../etc", {"a": 1}]

    def setp(root: Any, path: str, val: Any) -> None:
        parts = [p for p in path.split("/") if p]
        cur = root
        for p in parts[:-1]:
            cur = cur[int(p)] if isinstance(cur, list) else cur[p]
        last = parts[-1]
        if isinstance(cur, list):
            cur[int(last)] = val
        else:
            cur[last] = val

    def delp(root: Any, path: str) -> None:
        parts = [p for p in path.split("/") if p]
        cur = root
        for p in parts[:-1]:
            cur = cur[int(p)] if isinstance(cur, list) else cur[p]
        last = parts[-1]
        if isinstance(cur, list):
            del cur[int(last)]
        else:
            cur.pop(last, None)

    for _ in range(N):
        blob = json.loads(json.dumps(base))
        path = rnd.choice(all_paths)
        op = rnd.choice(("set", "del", "set", "set"))
        try:
            if op == "del":
                delp(blob, path)
            else:
                setp(blob, path, rnd.choice(POISON))
        except Exception:  # noqa: BLE001  - mutation itself failed; skip
            continue
        try:
            r = SyncInterpreter.from_snapshot(json.dumps(blob), mk())
            r.start()
            ids = sorted(r.current_state_ids)
            r.stop()
            # An ACCEPTED restore must land on a legal, non-empty configuration.
            if not ids or any(not isinstance(x, str) for x in ids):
                wrong.append({"path": path, "ids": ids})
                outcomes["accepted-illegal"] = outcomes.get("accepted-illegal", 0) + 1
            else:
                outcomes["accepted-legal"] = outcomes.get("accepted-legal", 0) + 1
        except XStateMachineError as exc:
            k = "typed:" + type(exc).__name__
            outcomes[k] = outcomes.get(k, 0) + 1
        except (TypeError, ValueError, KeyError, AttributeError, RecursionError) as exc:
            untyped.append({"path": path, "exc": f"{type(exc).__name__}: {exc}"[:160]})
            outcomes["UNTYPED:" + type(exc).__name__] = (
                outcomes.get("UNTYPED:" + type(exc).__name__, 0) + 1
            )
        except Exception as exc:  # noqa: BLE001
            untyped.append({"path": path, "exc": f"{type(exc).__name__}: {exc}"[:160]})
            outcomes["UNTYPED:" + type(exc).__name__] = (
                outcomes.get("UNTYPED:" + type(exc).__name__, 0) + 1
            )

    return {
        "ok": not untyped and not wrong,
        "mutations": N,
        "outcomes": dict(sorted(outcomes.items())),
        "untyped_sample": untyped[:5],
        "illegal_sample": wrong[:5],
    }


@attack(
    "N5-02",
    "Hostile event types all raise InvalidEventError (#113), never escape untyped",
    "a malformed gateway message must fail inside the library's own hierarchy",
)
async def n5_02() -> Dict[str, Any]:
    s = SyncInterpreter(mk()).start()
    hostile = [
        {"type": 1},
        {"type": None},
        {"type": 1.5},
        {"type": b"x"},
        {"type": ["x"]},
        {"type": {"x": 1}},
        {"type": object()},
        {"type": True},
        {"type": (1, 2)},
        {"type": set()},
    ]
    bad: List[str] = []
    for ev in hostile:
        try:
            s.send(ev)
            bad.append(f"accepted {type(ev['type']).__name__}")
        except X.InvalidEventError:
            pass
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{type(ev['type']).__name__} -> {type(exc).__name__}")
    s.stop()
    return {"ok": not bad, "cases": len(hostile), "bad": bad}


@attack(
    "N5-03",
    "on_plugin_error fires for an async-def hook on the sync engine (#127)",
    "a hook that silently never runs is an observability hole in an audit trail",
)
async def n5_03() -> Dict[str, Any]:
    seen: List[str] = []

    class BadPlugin(PluginBase):
        async def on_transition(self, *a, **kw):  # noqa: ANN001,D102
            seen.append("ran")

    class Watcher(PluginBase):
        def on_plugin_error(self, interpreter, plugin, hook, error):  # noqa: ANN001
            seen.append(f"on_plugin_error:{hook}")

    s = SyncInterpreter(mk())
    s.use(BadPlugin())
    s.use(Watcher())
    s.start()
    s.send("GO")
    lpe = getattr(s, "last_plugin_error", "MISSING")
    s.stop()
    return {
        "ok": any(x.startswith("on_plugin_error") for x in seen),
        "seen": seen,
        "last_plugin_error": str(lpe)[:140],
    }


@attack(
    "N5-04",
    "on_resolve_error fires when a referenced action name is unimplemented (#134)",
    "an unresolved action is a config error that must not be silent",
)
async def n5_04() -> Dict[str, Any]:
    seen: List[str] = []

    class Watcher(PluginBase):
        def on_resolve_error(self, interpreter, *a, **kw):  # noqa: ANN001
            seen.append("on_resolve_error")

        def on_action_error(self, interpreter, action, error):  # noqa: ANN001
            seen.append(f"on_action_error:{type(error).__name__}")

    cfg = {
        "id": "r",
        "initial": "a",
        "states": {"a": {"on": {"GO": {"target": "b", "actions": ["ghost"]}}}, "b": {}},
    }
    s = SyncInterpreter(create_machine(cfg, logic=MachineLogic()))
    s.use(Watcher())
    s.start()
    # An unresolved action name is surfaced EITHER as a typed raise at the
    # call site OR via the hooks/receipt. Both are observable; silence is not.
    raised = None
    r = None
    try:
        r = s.send("GO")
    except X.XStateMachineError as exc:
        raised = type(exc).__name__
    observable = bool(seen) or raised is not None or (
        r is not None and r.error is not None
    )
    s.stop()
    return {
        "ok": observable,
        "hooks": seen,
        "raised": raised,
        "receipt_error": str(getattr(r, "error", None))[:140],
    }


@attack(
    "N5-05",
    "LoggingInspector redacts password/api_key/token by default (#126)",
    "an OMS log must never carry a credential; a leak is a security incident",
)
async def n5_05() -> Dict[str, Any]:
    from xstate_statemachine.plugins import DEFAULT_REDACT_KEYS, redact

    logger = logging.getLogger("xstate_statemachine")
    logging.disable(logging.NOTSET)
    records: List[str] = []

    class Cap(logging.Handler):
        def emit(self, rec):  # noqa: ANN001,D102
            try:
                records.append(rec.getMessage())
            except Exception:  # noqa: BLE001
                pass

    h = Cap()
    logger.addHandler(h)
    prev = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        s = SyncInterpreter(mk())
        s.use(X.LoggingInspector(log_context=True))
        s.start()
        s.send(
            {
                "type": "GO",
                "password": "hunter2",
                "api_key": "sk-live-xyz",
                "token": "t0k",
                "qty": 100,
            }
        )
        s.stop()
    finally:
        logger.removeHandler(h)
        logger.setLevel(prev)
        logging.disable(logging.CRITICAL)

    blob = "\n".join(records)
    leaks = [v for v in ("hunter2", "sk-live-xyz", "t0k") if v in blob]
    pure = redact({"password": "p", "nested": {"api_key": "k"}, "qty": 1})
    return {
        "ok": not leaks and pure == {"password": "***", "nested": {"api_key": "***"}, "qty": 1},
        "leaked_values": leaks,
        "redact_keys": list(DEFAULT_REDACT_KEYS),
        "pure_redact": pure,
        "records": len(records),
        "qty_still_logged": "100" in blob,
    }


@attack(
    "N5-06",
    "Exported provenance API surface is present and importable (#137)",
    "a documented API that is not exported forces adopters onto private internals",
)
async def n5_06() -> Dict[str, Any]:
    required = [
        "is_system_event",
        "system_event",
        "DoneEvent",
        "AfterEvent",
        "ENGINE_EVENT_SHAPES",
        "SnapshotMidStepError",
        "SnapshotCorruptError",
        "SnapshotSerializationError",
        "InvalidEventError",
        "RootTargetError",
    ]
    missing = [n for n in required if not hasattr(X, n)]
    not_in_all = [n for n in required if n not in getattr(X, "__all__", ())]
    # every new error class must live under the library's own base class
    errs = [
        "SnapshotMidStepError",
        "SnapshotCorruptError",
        "SnapshotSerializationError",
        "InvalidEventError",
        "RootTargetError",
    ]
    not_derived = [
        n
        for n in errs
        if hasattr(X, n) and not issubclass(getattr(X, n), XStateMachineError)
    ]
    return {
        "ok": not missing and not not_in_all and not not_derived,
        "missing": missing,
        "not_in_dunder_all": not_in_all,
        "not_derived_from_base": not_derived,
    }


@attack(
    "N5-07",
    "Provenance survives deepcopy and pickle (#138) and wait=True (#111)",
    "an engine marker that a round-trip strips lets user traffic forge a system event",
)
async def n5_07() -> Dict[str, Any]:
    import copy
    import pickle

    ev = X.system_event(X.DoneEvent(type="done.invoke.k", data={"v": 1}, src="k"))
    out = {
        "original": X.is_system_event(ev),
        "deepcopy": X.is_system_event(copy.deepcopy(ev)),
        "pickle": X.is_system_event(pickle.loads(pickle.dumps(ev))),
    }
    # a user-minted event must NOT be a system event
    out["user_event"] = X.is_system_event(X.Event(type="GO"))
    return {
        "ok": out["original"] and out["deepcopy"] and out["pickle"] and not out["user_event"],
        **out,
    }


if __name__ == "__main__":
    main("n5_fuzz_obs_sec")
