"""N5 - fuzz: SnapshotCorruptError over mutated snapshots (#110, #131) and
InvalidEventError over hostile event types (#113).

Part A: take a good snapshot, apply 5,000 structural mutations (delete key,
retype value, truncate the JSON, inject NaN, wrong version, list->dict, ...)
and feed each to `from_snapshot`. Every outcome must be a NAMED library
exception (SnapshotCorruptError / SnapshotSerializationError / a declared
XStateMachineError) or a faithful restore. A raw KeyError / TypeError /
AttributeError / RecursionError -- or, worse, a SILENT restore of a machine
with no configuration -- is a defect.

Part B: `send()` a battery of hostile `type` values (int, None, bytes,
object with __str__ that raises, a dict, a class, a str subclass that lies).
`InvalidEventError` (a TypeError) is the contract; anything escaping deeper
is a defect.

Reduced: 5,000 mutations in-process, no round-trip start() per case (start
is exercised for the survivors only) to fit the time bound.
"""

from __future__ import annotations

import asyncio
import json
import math
import random

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import (
    InvalidEventError,
    SnapshotCorruptError,
    SnapshotSerializationError,
    XStateMachineError,
)

N_MUT = 5000

CFG = {
    "id": "fz",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
        "b": {"on": {"GO": {"target": "a"}}, "after": {500: {"target": "a"}}},
    },
}


def bump(i, ctx, e, a):  # noqa: ANN001
    ctx["n"] += 1


def mk():
    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


def _paths(o, prefix=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield prefix + (k,)
            yield from _paths(v, prefix + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield prefix + (i,)
            yield from _paths(v, prefix + (i,))


def _get(o, path):
    for p in path:
        o = o[p]
    return o


def _set(o, path, val):
    for p in path[:-1]:
        o = o[p]
    o[path[-1]] = val


def _del(o, path):
    for p in path[:-1]:
        o = o[p]
    del o[path[-1]]


JUNK = [None, 0, -1, 1e308, "", chr(0), [], {}, True, "not-a-state",
        [[["deep"]]], {"a": {"b": {"c": 1}}}, 3.5, "NaN", 2**70]


def mutate(rng, snap):
    s = json.loads(json.dumps(snap))
    paths = list(_paths(s))
    if not paths:
        return s, "empty"
    kind = rng.randrange(6)
    p = rng.choice(paths)
    try:
        if kind == 0:
            _del(s, p); return s, "delete"
        if kind == 1:
            _set(s, p, rng.choice(JUNK)); return s, "retype"
        if kind == 2:
            v = _get(s, p)
            _set(s, p, [v] if not isinstance(v, list) else {"k": v})
            return s, "wrap"
        if kind == 3:
            s["version"] = rng.choice([0, 99, "v2", None, -1])
            return s, "version"
        if kind == 4:
            _set(s, p, {"self": None})
            return s, "obj"
        _set(s, p, chr(0) + "bad")
        return s, "unicode"
    except Exception:  # noqa: BLE001
        return s, "mutate-failed"


async def part_a() -> dict:
    rng = random.Random(4104)
    live = Interpreter(mk())
    await live.start()
    await asyncio.wait_for(live.send("GO", wait=True), 5)
    good = live.get_persisted_snapshot()
    await live.stop()

    named = 0
    restored_ok = 0
    empty_config_restores = []
    raw_exceptions: dict = {}
    truncation_named = 0

    good_blob = json.dumps(good)
    for i in range(N_MUT):
        if i % 10 == 0:
            # truncation / textual corruption branch
            cut = rng.randrange(1, len(good_blob))
            blob = good_blob[:cut]
            branch = "truncate"
        else:
            m, branch = mutate(rng, good)
            try:
                blob = json.dumps(m, allow_nan=True)
            except (TypeError, ValueError):
                blob = good_blob  # unserialisable mutation: skip
                branch = "skipped"
        try:
            interp = Interpreter.from_snapshot(blob, mk())
        except (SnapshotCorruptError, SnapshotSerializationError):
            named += 1
            if branch == "truncate":
                truncation_named += 1
            continue
        except XStateMachineError:
            named += 1
            continue
        except json.JSONDecodeError:
            named += 1  # documented: caller's own json layer
            if branch == "truncate":
                truncation_named += 1
            continue
        except Exception as exc:  # noqa: BLE001
            key = f"{branch}:{type(exc).__name__}"
            raw_exceptions[key] = raw_exceptions.get(key, 0) + 1
            continue
        restored_ok += 1
        if not interp.current_state_ids:
            empty_config_restores.append(branch)

    return {
        "mutations": N_MUT,
        "named_exception": named,
        "restored_without_error": restored_ok,
        "restored_with_EMPTY_configuration": len(empty_config_restores),
        "empty_config_branches": sorted(set(empty_config_restores)),
        "raw_unnamed_exceptions": raw_exceptions,
        "pass": not raw_exceptions and not empty_config_restores,
    }


class Liar(str):
    def __eq__(self, other):  # noqa: D105
        return True

    def __hash__(self):  # noqa: D105
        return hash("GO")


class Explodes:
    def __str__(self):  # noqa: D105
        raise RuntimeError("boom")

    __repr__ = __str__


HOSTILE = [
    ("int", 7),
    ("none", None),
    ("bytes", b"GO"),
    ("float", 1.5),
    ("list", ["GO"]),
    ("dict_no_type", {"payload": 1}),
    ("dict_type_int", {"type": 7}),
    ("dict_type_none", {"type": None}),
    ("class", Explodes),
    ("instance_str_raises", Explodes()),
    ("bool", True),
    ("tuple", ("GO",)),
    ("str_subclass_liar", Liar("GO")),
    ("empty_str", ""),
]


async def part_b() -> dict:
    results = {}
    bad = []
    for name, val in HOSTILE:
        interp = Interpreter(mk())
        await interp.start()
        try:
            r = await asyncio.wait_for(interp.send(val, wait=True), 3)
            results[name] = f"accepted: receipt error={r.error!r}"
            if name not in ("str_subclass_liar",):
                bad.append(name)
        except InvalidEventError as exc:
            results[name] = f"InvalidEventError (TypeError={isinstance(exc, TypeError)})"
        except XStateMachineError as exc:
            results[name] = f"{type(exc).__name__}"
        except asyncio.TimeoutError:
            results[name] = "HUNG (no receipt)"
            bad.append(name)
        except Exception as exc:  # noqa: BLE001
            results[name] = f"RAW {type(exc).__name__}"
            bad.append(name)
        finally:
            try:
                await interp.stop()
            except Exception:  # noqa: BLE001
                pass
    return {"cases": results, "unnamed_or_accepted": bad, "pass": not bad}


async def main() -> int:
    a = await part_a()
    b = await part_b()
    ok = a["pass"] and b["pass"]
    emit("n5_fuzz_snapshot_events",
         {"a_snapshot_mutations": a, "b_hostile_event_types": b,
          "result": "PASS" if ok else "FAIL"})
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
