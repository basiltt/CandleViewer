"""P5 @cec108b -- fuzz: livelock watchdog, snapshot-mutation typing,
event-type fuzz.

A  Config fuzzer for LIVELOCK (#144/#151): random machines built from the
   two shapes that historically hung -- a nested `invoke` whose `onDone`
   re-enters a common ancestor, and `always` cycles across parallel
   regions -- driven on the SYNC engine (where the hang was) under a
   30 s watchdog thread. Any case exceeding the watchdog is a defect.
B  Snapshot mutation fuzzer, 5,000 mutations, against #146/#143/#158:
   every failure must be an XStateMachineError (ideally
   SnapshotCorruptError); no RAW TypeError/ValueError/AttributeError, and
   no silent restore of an illegal configuration.
C  Event-type fuzz vs InvalidEventError (#113/#161), including dict keys.
"""

from __future__ import annotations

import asyncio
import json
import random
import threading
import time

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.exceptions import (
    InvalidEventError,
    SnapshotCorruptError,
    XStateMachineError,
)

WATCHDOG_S = 30.0


# ---------------------------------------------------------------- A
def nested_invoke_cycle(seed: int) -> dict:
    rnd = random.Random(seed)
    depth = rnd.randint(1, 3)
    inner = {
        "initial": "go",
        "states": {
            "go": {
                "invoke": {
                    "id": f"j{seed}",
                    "src": "quick",
                    "onDone": {"target": f"#cyc{seed}.outer"},
                }
            }
        },
    }
    node = inner
    for d in range(depth):
        node = {"initial": "n", "states": {"n": node}}
    return {
        "id": f"cyc{seed}",
        "initial": "outer",
        "context": {"n": 0},
        "maxIterations": rnd.choice([5, 20, 50]),
        "states": {
            "outer": {"initial": "deep", "states": {"deep": node}},
        },
    }


def always_cycle(seed: int) -> dict:
    rnd = random.Random(seed)
    return {
        "id": f"alw{seed}",
        "type": "parallel",
        "context": {"n": 0},
        "maxIterations": rnd.choice([5, 20, 50]),
        "states": {
            "ra": {
                "initial": "a",
                "states": {
                    "a": {"always": {"target": "b", "actions": ["bump"]}},
                    "b": {"always": {"target": "a", "actions": ["bump"]}},
                },
            },
            "rb": {
                "initial": "x",
                "states": {
                    "x": {"always": {"target": "y"}},
                    "y": {"always": {"target": "x"}},
                },
            },
        },
    }


def quick(i, ctx, e):  # noqa: ANN001
    return {"v": 1}


def bump(i, ctx, e, a):  # noqa: ANN001
    ctx["n"] += 1


def run_sync_with_watchdog(cfg: dict) -> dict:
    result: dict = {}
    done = threading.Event()

    def body():
        try:
            m = create_machine(
                cfg,
                logic=MachineLogic(
                    actions={"bump": bump}, services={"quick": quick}
                ),
            )
            i = SyncInterpreter(m)
            i.start()
            result["status"] = i.status
            result["states"] = sorted(i.current_state_ids)
            result["last_error"] = repr(i.last_error)[:80]
            i.stop()
            result["outcome"] = "settled"
        except XStateMachineError as exc:
            result["outcome"] = f"named:{type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001
            result["outcome"] = f"RAW {type(exc).__name__}: {str(exc)[:60]}"
        finally:
            done.set()

    t = threading.Thread(target=body, daemon=True)
    t0 = time.perf_counter()
    t.start()
    finished = done.wait(WATCHDOG_S)
    result["elapsed_s"] = round(time.perf_counter() - t0, 3)
    if not finished:
        result["outcome"] = "LIVELOCK (watchdog)"
    return result


def a_livelock(cases: int = 24) -> dict:
    hangs = []
    raws = []
    outcomes: dict = {}
    for seed in range(cases):
        for name, builder in (
            ("nested_invoke", nested_invoke_cycle),
            ("always_parallel", always_cycle),
        ):
            r = run_sync_with_watchdog(builder(seed))
            key = f"{name}:{r['outcome'].split(':')[0]}"
            outcomes[key] = outcomes.get(key, 0) + 1
            if r["outcome"].startswith("LIVELOCK"):
                hangs.append((name, seed, r))
            if r["outcome"].startswith("RAW"):
                raws.append((name, seed, r["outcome"]))
    return {
        "cases": cases * 2,
        "outcome_histogram": outcomes,
        "livelocks": hangs[:3],
        "livelock_count": len(hangs),
        "raw_exceptions": raws[:3],
        "raw_count": len(raws),
        "watchdog_s": WATCHDOG_S,
        "pass": not hangs and not raws,
    }


# ---------------------------------------------------------------- B
FZ = {
    "id": "fz",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
        "b": {"on": {"GO": {"target": "a"}}, "after": {500: {"target": "a"}}},
    },
}


def fz_mk():
    return create_machine(FZ, logic=MachineLogic(actions={"bump": bump}))


async def b_snapshot_fuzz(n: int = 5000) -> dict:
    live = Interpreter(fz_mk())
    await live.start()
    await asyncio.wait_for(live.send("GO", wait=True), 5)
    good = live.get_persisted_snapshot()
    await live.stop()

    rnd = random.Random(20260919)
    raw: dict = {}
    named: dict = {}
    restored_illegal = []
    restored_ok = 0
    JUNK = [
        7,
        -1,
        0,
        "junk",
        "",
        None,
        True,
        [],
        {},
        [None],
        {"x": None},
        3.5,
        {"1": 2},
        {2: "x"},
    ]
    for k in range(n):
        s = json.loads(json.dumps(good))
        branch = rnd.choice(
            ["retype", "delete", "wrap", "unicode", "obj", "version", "nested"]
        )
        keys = list(s)
        key = rnd.choice(keys)
        if branch == "retype":
            s[key] = rnd.choice(JUNK)
        elif branch == "delete":
            s.pop(key, None)
        elif branch == "wrap":
            s[key] = [s[key]]
        elif branch == "unicode":
            s[key] = "\ud800￿\x00"
        elif branch == "obj":
            s[key] = {"nested": s[key]}
        elif branch == "version":
            s["version"] = rnd.choice(JUNK + [99, "2"])
        else:  # nested
            if isinstance(s.get("context"), dict):
                s["context"] = rnd.choice(JUNK)
            else:
                s["status"] = rnd.choice(JUNK)
        try:
            blob = json.dumps(s)
        except (TypeError, ValueError):
            continue
        try:
            j = Interpreter.from_snapshot(blob, fz_mk())
        except SnapshotCorruptError:
            named["SnapshotCorruptError"] = (
                named.get("SnapshotCorruptError", 0) + 1
            )
            continue
        except XStateMachineError as exc:
            nm = type(exc).__name__
            named[nm] = named.get(nm, 0) + 1
            continue
        except Exception as exc:  # noqa: BLE001
            tag = f"{branch}:{type(exc).__name__}"
            raw[tag] = raw.get(tag, 0) + 1
            continue
        restored_ok += 1
        ids = sorted(j.current_state_ids)
        leaves = [x for x in ids if x.count(".") >= 1]
        if j.status == "running" and not leaves:
            restored_illegal.append((branch, key, ids))
    return {
        "mutations": n,
        "named_exceptions": named,
        "raw_unnamed_exceptions": raw,
        "raw_total": sum(raw.values()),
        "restored_without_error": restored_ok,
        "restored_running_with_no_leaf": restored_illegal[:5],
        "restored_illegal_count": len(restored_illegal),
        "pass": not raw and not restored_illegal,
    }


# ---------------------------------------------------------------- C
async def c_event_fuzz() -> dict:
    i = Interpreter(fz_mk())
    await i.start()
    cases = {
        "int": 1,
        "float": 1.5,
        "none": None,
        "bytes": b"GO",
        "list": ["GO"],
        "tuple": ("GO",),
        "bool": True,
        "dict_no_type": {"payload": 1},
        "dict_type_int": {"type": 5},
        "dict_type_none": {"type": None},
        "dict_type_empty": {"type": ""},
        "dict_nonstr_key": {"type": "GO", 5: "x"},
        "set": {"GO"},
        "class": Interpreter,
        "empty_str": "",
    }
    out = {}
    for name, ev in cases.items():
        try:
            r = await asyncio.wait_for(i.send(ev, wait=True), 3)  # type: ignore[arg-type]
            out[name] = f"accepted (error={r.error!r})"
        except InvalidEventError as exc:
            out[name] = f"InvalidEventError (TypeError={isinstance(exc, TypeError)})"
        except XStateMachineError as exc:
            out[name] = f"named:{type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001
            out[name] = f"RAW {type(exc).__name__}"
    alive = i.is_running
    await i.stop()
    accepted = [k for k, v in out.items() if v.startswith("accepted")]
    raws = [k for k, v in out.items() if v.startswith("RAW")]
    return {
        "cases": out,
        "accepted": accepted,
        "raw": raws,
        "interpreter_alive_after": alive,
        "pass": not raws and accepted in ([], ["empty_str"]),
    }


def main() -> int:
    res = {"a_livelock_fuzz": a_livelock()}
    res["b_snapshot_mutation_fuzz"] = asyncio.run(b_snapshot_fuzz())
    res["c_event_type_fuzz"] = asyncio.run(c_event_fuzz())
    res["result"] = (
        "PASS"
        if all(v["pass"] for v in res.values() if isinstance(v, dict))
        else "FAIL"
    )
    emit("p5_fuzz", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
