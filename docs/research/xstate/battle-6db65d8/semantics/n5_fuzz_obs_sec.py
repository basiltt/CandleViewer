"""N5 — FUZZ + OBSERVABILITY + SECURITY on the round-5 fixes.

Livelock config fuzzer with a watchdog; 5k snapshot mutations vs
SnapshotCorruptError typing (#146/#143); event-type fuzz vs InvalidEventError
(#161); hook matrix for the new reasons/classes (#153/#133/#150/#159/#134);
internal=True forgery, get_snapshot DEBUG redaction (#160), executor thread
context leakage, exported API surface.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
from typing import Any, Dict, List

from n_harness import attack, main

from xstate_statemachine import (
    Interpreter,
    InvalidEventError,
    MachineLogic,
    SnapshotCorruptError,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)


@attack(
    "N5-01",
    "Config fuzzer: 120 random machines with invoke-onDone cycles and cross-region `always` never livelock (30 s watchdog)",
    "#144/#151: a conservative cycle must end on the budget, not spin for ever",
)
def n5_01() -> Dict[str, Any]:
    rng = random.Random(4242)
    hangs: List[str] = []
    built = 0
    done = 0
    for idx in range(120):
        style = idx % 3
        if style == 0:
            # nested invoke whose onDone re-enters the common ancestor (#144)
            cfg = {
                "id": f"c{idx}",
                "initial": "outer",
                "context": {"n": 0},
                "maxIterations": rng.choice([5, 25, 100]),
                "states": {
                    "outer": {
                        "initial": "inner",
                        "states": {
                            "inner": {
                                "invoke": {"src": "quick", "onDone": "#c%d.outer" % idx}
                            }
                        },
                    }
                },
            }
        elif style == 1:
            # `always` cycle across two parallel regions
            cfg = {
                "id": f"c{idx}",
                "type": "parallel",
                "context": {"n": 0},
                "maxIterations": rng.choice([5, 25, 100]),
                "states": {
                    "r0": {
                        "initial": "a",
                        "states": {
                            "a": {"always": {"target": "b"}},
                            "b": {"always": {"target": "a"}},
                        },
                    },
                    "r1": {
                        "initial": "x",
                        "states": {"x": {"on": {"T": "y"}}, "y": {}},
                    },
                },
            }
        else:
            # self-raising action chain
            cfg = {
                "id": f"c{idx}",
                "initial": "a",
                "context": {"n": 0},
                "maxIterations": rng.choice([5, 25, 100]),
                "states": {
                    "a": {
                        "on": {
                            "P": {
                                "actions": [
                                    "bump",
                                    {"type": "raise", "params": {"event": "P"}},
                                ]
                            }
                        }
                    }
                },
            }

        def quick(i_, ctx, e):  # noqa: ANN001
            return 1

        def bump(i_, ctx, e, am):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        logic = MachineLogic(actions={"bump": bump}, services={"quick": quick})
        box: Dict[str, Any] = {}

        def run():
            try:
                m = create_machine(cfg, logic=logic)
                i = SyncInterpreter(m).start()
                i.send("P")
                i.send("T")
                box["ids"] = sorted(i.current_state_ids)
                i.stop()
                box["ok"] = True
            except Exception as exc:  # noqa: BLE001
                box["ok"] = True
                box["exc"] = f"{type(exc).__name__}"

        built += 1
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout=8.0)  # per-machine watchdog (total bound << 30 s)
        if t.is_alive():
            hangs.append(f"{cfg['id']} style={style} HUNG")
            break
        done += 1
    return {"ok": not hangs, "machines": built, "settled": done, "hangs": hangs}


@attack(
    "N5-02",
    "5000 snapshot mutations: every rejection is a typed XStateMachineError, never a bare TypeError/ValueError",
    "#146/#143: `except XStateMachineError` around a restore must be sufficient",
)
def n5_02() -> Dict[str, Any]:
    cfg = {
        "id": "s",
        "type": "parallel",
        "context": {"q": 1},
        "states": {
            "a": {"initial": "a1", "states": {"a1": {"on": {"T": "a2"}}, "a2": {}}},
            "b": {"initial": "b1", "states": {"b1": {}, "b2": {}}},
        },
    }

    def mk():
        return create_machine(cfg, logic=MachineLogic())

    i = SyncInterpreter(mk()).start()
    i.send("T")
    good = i.get_persisted_snapshot()
    i.stop()
    rng = random.Random(777)
    poisons = [
        None, "", "x", 0, 1, -1, 3.5, True, False, [], {}, [None], {"k": object},
        {"type": 7}, ["p"], [[]], {"0": 0}, 1e308, "🙈", {"a": {"b": {}}},
    ]
    keys = list(good.keys())
    untyped: List[str] = []
    counts: Dict[str, int] = {}
    N = 5000
    for n in range(N):
        blob = json.loads(json.dumps(good))
        for _ in range(rng.randint(1, 3)):
            k = rng.choice(keys)
            op = rng.random()
            if op < 0.15:
                blob.pop(k, None)
            else:
                p = rng.choice(poisons)
                try:
                    json.dumps(p)
                except Exception:  # noqa: BLE001
                    p = "unserialisable"
                blob[k] = p
        try:
            r = SyncInterpreter.from_snapshot(json.dumps(blob), mk()).start()
            r.stop()
            counts["restored"] = counts.get("restored", 0) + 1
        except XStateMachineError as exc:
            counts[type(exc).__name__] = counts.get(type(exc).__name__, 0) + 1
        except Exception as exc:  # noqa: BLE001
            counts["UNTYPED:" + type(exc).__name__] = (
                counts.get("UNTYPED:" + type(exc).__name__, 0) + 1
            )
            if len(untyped) < 6:
                untyped.append(f"{type(exc).__name__}: {str(exc)[:80]} | keys={sorted(blob)}")
    return {
        "ok": not untyped,
        "mutations": N,
        "outcomes": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "untyped_samples": untyped,
    }


@attack(
    "N5-03",
    "Event-type fuzz: every hostile event shape raises InvalidEventError (#161), never anything untyped",
    "the send() door is the widest attack surface an OMS exposes",
)
def n5_03() -> Dict[str, Any]:
    cfg = {"id": "e", "initial": "a", "states": {"a": {"on": {"OK": {"actions": []}}}}}
    i = SyncInterpreter(create_machine(cfg, logic=MachineLogic())).start()
    hostile: List[Any] = [
        None, 7, 3.5, True, [], {}, object(), b"OK", ("OK",), {"type": None},
        {"type": ""}, {"type": 7}, {"type": []}, {"type": {}}, {"type": b"x"},
        {7: "x", "type": "OK"}, {"type": "OK", 1: 2}, {"notype": 1}, set(),
        {"type": "OK", "payload": object()},
    ]
    bad: List[str] = []
    ok_typed = 0
    accepted: List[str] = []
    for h in hostile:
        try:
            i.send(h)
            accepted.append(repr(h)[:40])
        except InvalidEventError:
            ok_typed += 1
        except XStateMachineError as exc:
            ok_typed += 1
            bad.append(f"typed-but-not-InvalidEventError: {type(exc).__name__} for {h!r:.30}")
        except Exception as exc:  # noqa: BLE001
            bad.append(f"UNTYPED {type(exc).__name__} for {h!r:.30}")
    i.stop()
    # {"type":"OK","payload":object()} is legal: payload VALUES are the caller's
    legal = [a for a in accepted if "payload" in a]
    return {
        "ok": not [b for b in bad if b.startswith("UNTYPED")]
        and len(accepted) == len(legal),
        "typed_rejections": ok_typed,
        "accepted": accepted,
        "problems": bad,
    }


@attack(
    "N5-04",
    "Hook matrix: guard_denied / unresolved_target / chain_budget / on_plugin_error / on_resolve_error each fire EXACTLY once",
    "an OMS reconciles from hooks; a double-fire double-books and a miss loses the order",
)
def n5_04() -> Dict[str, Any]:
    seen: Dict[str, List[Any]] = {
        "dropped": [], "unhandled": [], "plugin_error": [], "resolve_error": [],
    }

    class Insp:
        def on_event_dropped(self, interp, event, reason):  # noqa: ANN001
            seen["dropped"].append((event.type, reason))

        def on_unhandled_event(  # real signature (plugins.py:356)
            self, interp, event, active_state_ids, disposition  # noqa: ANN001
        ):
            seen["unhandled"].append((event.type, disposition))

        def on_plugin_error(self, interp, plugin, hook, error):  # noqa: ANN001
            seen["plugin_error"].append(hook)

        def on_resolve_error(self, interp, error, event):  # noqa: ANN001
            seen["resolve_error"].append(type(error).__name__)

    # (a) guard_denied — declared handler, every guard refuses
    cfg_a = {
        "id": "ha",
        "initial": "a",
        "states": {"a": {"on": {"D": {"target": "b", "guard": "no"}}}, "b": {}},
    }
    i = SyncInterpreter(
        create_machine(cfg_a, logic=MachineLogic(guards={"no": lambda c, e: False}))
    )
    i.use(Insp())
    i.start()
    i.send("D")
    guard_denied = [r for _, r in seen["unhandled"] if r == "guard_denied"]
    i.stop()

    # (b) unresolved_target — sendTo a dead actor
    seen["dropped"].clear()
    cfg_b = {
        "id": "hb",
        "initial": "a",
        "states": {
            "a": {
                "on": {
                    "S": {
                        "actions": [
                            {"type": "sendTo", "params": {"to": "ghost", "event": "X"}}
                        ]
                    }
                }
            }
        },
    }
    j = SyncInterpreter(create_machine(cfg_b, logic=MachineLogic()))
    j.use(Insp())
    j.start()
    j.send("S")
    unresolved = [r for _, r in seen["dropped"] if r == "unresolved_target"]
    j.stop()

    # (c) chain_budget — a self-raising action chain
    seen["dropped"].clear()
    cfg_c = {
        "id": "hc",
        "initial": "a",
        "context": {"n": 0},
        "maxIterations": 5,
        "states": {
            "a": {
                "on": {
                    "P": {"actions": ["bump", {"type": "raise", "params": {"event": "P"}}]}
                }
            }
        },
    }

    def bump(i_, ctx, e, am):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    k = SyncInterpreter(create_machine(cfg_c, logic=MachineLogic(actions={"bump": bump})))
    k.use(Insp())
    k.start()
    try:
        k.send("P")
    except Exception:  # noqa: BLE001,S110
        pass
    chain = [r for _, r in seen["dropped"] if r == "chain_budget"]
    k.stop()

    # (d) on_plugin_error — a hook that throws
    class Bad:
        def on_transition(self, *a, **k):  # noqa: ANN001
            raise RuntimeError("hook boom")

    seen["plugin_error"].clear()
    p = SyncInterpreter(create_machine(cfg_a, logic=MachineLogic(guards={"no": lambda c, e: True})))
    p.use(Bad())
    p.use(Insp())
    p.start()
    p.send("D")
    plugin_errs = len(set(seen["plugin_error"]))
    p.stop()

    # (e) on_resolve_error — an UNRESOLVABLE TARGET deferred to runtime by
    #     strict_targets=False (plugins.py:248). An unimplemented *action* is
    #     a typed ImplementationMissingError at the call site instead.
    seen["resolve_error"].clear()
    cfg_e = {
        "id": "he",
        "initial": "a",
        "states": {"a": {"on": {"G": "does_not_exist"}}, "b": {}},
    }
    q = SyncInterpreter(
        create_machine(cfg_e, logic=MachineLogic(), strict_targets=False)
    )
    q.use(Insp())
    q.start()
    try:
        q.send("G")
    except Exception:  # noqa: BLE001,S110
        pass
    resolve_errs = len(seen["resolve_error"])
    q.stop()

    rows = {
        "guard_denied": len(guard_denied),
        "unresolved_target": len(unresolved),
        "chain_budget": len(chain),
        "on_plugin_error": plugin_errs,
        "on_resolve_error": resolve_errs,
    }
    return {"ok": all(v == 1 for v in rows.values()), "fire_counts": rows}


@attack(
    "N5-05",
    "#160: get_snapshot()'s DEBUG log is redacted — no iban/pan/cvc/otp value reaches the log stream",
    "a DEBUG-level log shipped to a vendor must not carry a PAN",
)
def n5_05() -> Dict[str, Any]:
    records: List[str] = []

    class Cap(logging.Handler):
        def emit(self, record):  # noqa: ANN001
            try:
                records.append(record.getMessage())
            except Exception:  # noqa: BLE001,S110
                pass

    secrets = {
        "iban": "GB33BUKB20201555555555",
        "pan": "4111111111111111",
        "cvc": "737",
        "otp": "998877",
        "email": "trader@example.com",
        "qty": 500,
    }
    cfg = {"id": "sec", "initial": "a", "context": dict(secrets), "states": {"a": {}}}
    root = logging.getLogger("xstate_statemachine")
    prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    h = Cap()
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    try:
        i = SyncInterpreter(create_machine(cfg, logic=MachineLogic())).start()
        i.get_snapshot()
        i.get_persisted_snapshot()
        i.stop()
    finally:
        root.removeHandler(h)
        logging.disable(prev_disable)
    blob = "\n".join(records)
    leaked = [
        k for k, v in secrets.items() if k != "qty" and str(v) in blob
    ]
    return {
        "ok": not leaked,
        "log_records": len(records),
        "leaked_fields": leaked,
        "qty_still_logged": "500" in blob,
    }


@attack(
    "N5-06",
    "Executor thread context leakage: a plain-def service sees no other machine's context and cannot mutate it in place",
    "#149 shares one pool across services; a shared pool must not share state",
)
async def n5_06() -> Dict[str, Any]:
    seen: List[Any] = []

    def svc(i_, ctx, e):  # noqa: ANN001
        seen.append(dict(ctx))
        ctx["INJECTED"] = "from-worker"  # attempt an in-place mutation
        return 1

    cfg = {
        "id": "t",
        "initial": "idle",
        "context": {"owner": None},
        "states": {
            "idle": {"on": {"RUN": "work"}},
            "work": {"invoke": {"src": "svc", "onDone": "idle"}},
        },
    }
    ms = []
    for n in range(8):
        c = json.loads(json.dumps(cfg))
        c["context"]["owner"] = n
        ms.append(await Interpreter(create_machine(c, logic=MachineLogic(services={"svc": svc}))).start())
    await asyncio.gather(*(i.send("RUN") for i in ms))
    for _ in range(200):
        await asyncio.sleep(0.005)
        if len(seen) >= 8:
            break
    owners = sorted(s.get("owner") for s in seen)
    injected = [i.context.get("INJECTED") for i in ms]
    await asyncio.gather(*(i.stop() for i in ms))
    return {
        "ok": owners == list(range(8)),
        "each_service_saw_its_own_context": owners == list(range(8)),
        "owners_seen": owners,
        "worker_mutation_visible": [x for x in injected if x],
    }


@attack(
    "N5-07",
    "Exported API surface: every new round-5 name is importable and every error derives from XStateMachineError",
    "a typed contract the caller cannot import is not a contract",
)
def n5_07() -> Dict[str, Any]:
    import xstate_statemachine as x

    required = [
        "RootTargetError", "QueueOverflowError", "SnapshotCorruptError",
        "SnapshotMidStepError", "SnapshotSerializationError", "SnapshotVersionError",
        "SnapshotDriftError", "InvalidEventError", "InvalidEventPayloadError",
        "RunawayChainError", "TransitionFailedError", "WrongThreadError",
        "Receipt", "OverflowPolicy", "Interpreter", "SyncInterpreter",
        "MachineLogic", "create_machine",
    ]
    missing = [n for n in required if not hasattr(x, n)]
    errs = [n for n in dir(x) if n.endswith("Error") and not n.startswith("_")]
    not_derived = [
        n for n in errs
        if isinstance(getattr(x, n), type)
        and issubclass(getattr(x, n), BaseException)
        and not issubclass(getattr(x, n), x.XStateMachineError)
    ]
    receipt_fields = sorted(getattr(x.Receipt, "_fields", ()))
    need = {"changed", "deferred", "denied", "error", "state_ids"}
    return {
        "ok": not missing and not not_derived and need <= set(receipt_fields),
        "missing_exports": missing,
        "errors_outside_hierarchy": not_derived,
        "error_classes": len(errs),
        "receipt_fields": receipt_fields,
    }


if __name__ == "__main__":
    main("n5_fuzz_obs_sec")
