"""N5 -- fuzz: SnapshotCorruptError coverage + InvalidEventError over hostile
event types.

F1  5000 byte/structure mutations of a REAL snapshot fed to from_snapshot().
    Contract: every outcome is a typed XStateMachineError (SnapshotCorruptError
    / InvalidConfigError / SnapshotDriftError / SnapshotVersionError /
    StateNotFoundError), or a clean successful restore. An untyped escape
    (KeyError, AttributeError, TypeError, RecursionError...) is a defect: an
    OMS restoring from Redis cannot catch what it cannot name.

F2  hostile `type=` values to send(): non-str types must raise
    InvalidEventError (also a TypeError), never escape the hierarchy and never
    be silently coerced.

REDUCED: 5000 mutations as specified, single engine (sync -- the restore path
is in base_interpreter and shared), because per-mutation restore dominates
runtime.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    MachineLogic,
    SyncInterpreter,
    XStateMachineError,
    create_machine,
)

N_MUT = 5000
SEED = 20260919

CFG = {
    "id": "fz",
    "type": "parallel",
    "context": {"n": 0, "log": []},
    "states": {
        "a": {
            "initial": "x",
            "states": {
                "x": {"on": {"GO": {"target": "y", "actions": ["bump"]}}},
                "y": {"on": {"GO": "x"}},
            },
        },
        "b": {
            "initial": "p",
            "states": {"p": {"on": {"GO": "q"}}, "q": {"on": {"GO": "p"}}},
        },
    },
}


def mk():
    def bump(i, c, e, a):
        c["n"] += 1
        c["log"].append("b")

    return create_machine(CFG, logic=MachineLogic(actions={"bump": bump}))


def good_snapshot():
    i = SyncInterpreter(mk())
    i.start()
    for _ in range(5):
        i.send("GO")
    s = json.dumps(i.get_persisted_snapshot(), default=str)
    i.stop()
    return s


# ---------------------------------------------------------------- mutators
def mutate(rng, base_obj, base_str):
    """Return (label, mutated_snapshot_string)."""
    kind = rng.randrange(8)
    if kind == 0:  # raw byte flip
        b = bytearray(base_str.encode())
        p = rng.randrange(len(b))
        b[p] = rng.randrange(256)
        return "byteflip", b.decode("utf-8", "replace")
    if kind == 1:  # truncate
        p = rng.randrange(1, len(base_str))
        return "truncate", base_str[:p]
    o = json.loads(base_str)
    if kind == 2:  # delete a top-level key
        k = rng.choice(list(o))
        o.pop(k)
        return f"delkey:{k}", json.dumps(o)
    if kind == 3:  # retype a top-level value
        k = rng.choice(list(o))
        o[k] = rng.choice([None, 0, "", [], {}, True, 1.5, [[[[]]]]])
        return f"retype:{k}", json.dumps(o)
    if kind == 4:  # corrupt state ids
        o["state_ids"] = rng.choice(
            [[], ["nope.nope"], [None], [123], "fz.a.x", [["x"]], {}]
        )
        return "state_ids", json.dumps(o)
    if kind == 5:  # corrupt version / hash
        o[rng.choice(["version", "machine_hash", "machine_id"])] = rng.choice(
            [999, -1, "x", None, [], {}]
        )
        return "envelope", json.dumps(o)
    if kind == 6:  # corrupt pending/deferred records
        o[rng.choice(["pending_events", "deferred"])] = rng.choice(
            [[{"kind": "nope"}], [{}], [None], "x", [{"type": 5}], 7]
        )
        return "eventlane", json.dumps(o)
    # kind 7: corrupt configuration / context
    o[rng.choice(["configuration", "context"])] = rng.choice(
        [None, [], "x", 7, {"a": {"b": {"c": [1, 2, 3]}}}, [None]]
    )
    return "cfg_or_ctx", json.dumps(o)


TYPED_OK = ("XStateMachineError",)


def f1():
    rng = random.Random(SEED)
    base = good_snapshot()
    base_obj = json.loads(base)
    outcomes = collections.Counter()
    escapes = []
    by_kind = collections.defaultdict(collections.Counter)

    for n in range(N_MUT):
        label, s = mutate(rng, base_obj, base)
        try:
            r = SyncInterpreter.from_snapshot(s, mk())
            # a restore that "succeeds" must at least be inspectable
            r.get_persisted_snapshot()
            outcomes["RESTORED"] += 1
            by_kind[label]["RESTORED"] += 1
        except XStateMachineError as e:
            nm = type(e).__name__
            outcomes[nm] += 1
            by_kind[label][nm] += 1
        except RecursionError as e:  # noqa: PERF203
            outcomes["ESCAPE:RecursionError"] += 1
            by_kind[label]["ESCAPE"] += 1
            if len(escapes) < 12:
                escapes.append((n, label, "RecursionError", str(e)[:100]))
        except Exception as e:  # noqa: BLE001
            nm = f"ESCAPE:{type(e).__name__}"
            outcomes[nm] += 1
            by_kind[label]["ESCAPE"] += 1
            if len(escapes) < 12:
                escapes.append((n, label, type(e).__name__, str(e)[:100]))

    n_escape = sum(v for k, v in outcomes.items() if k.startswith("ESCAPE"))
    return {
        "mutations": N_MUT,
        "outcomes": dict(outcomes),
        "untyped_escapes": n_escape,
        "escape_examples": escapes,
        "by_mutation_kind": {k: dict(v) for k, v in by_kind.items()},
        "OK": n_escape == 0,
    }


# ------------------------------------------------------------------ F2
class Weird:
    def __str__(self):
        return "GO"

    def __repr__(self):
        return "Weird()"


class Boom:
    def __str__(self):
        raise RuntimeError("str() exploded")

    __repr__ = __str__

    def __hash__(self):
        raise RuntimeError("hash exploded")


HOSTILE = [
    ("None", None),
    ("int", 42),
    ("float", 1.5),
    ("bool", True),
    ("list", ["GO"]),
    ("dict", {"type": "GO"}),
    ("tuple", ("GO",)),
    ("set", {"GO"}),
    ("bytes", b"GO"),
    ("bytearray", bytearray(b"GO")),
    ("object", object()),
    ("class", Weird),
    ("instance_str_GO", Weird()),
    ("instance_str_raises", Boom()),
    ("callable", lambda: "GO"),
    ("Ellipsis", Ellipsis),
    ("NotImplemented", NotImplemented),
    ("nested_list", [[["GO"]]]),
    ("empty_str", ""),
    ("whitespace", "   "),
]


def f2():
    rows = []
    for label, val in HOSTILE:
        i = SyncInterpreter(mk())
        i.start()
        before = dict(i.context)
        try:
            i.send(val)
            after = dict(i.context)
            rows.append(
                {
                    "input": label,
                    "outcome": "NO-RAISE",
                    "context_changed": after != before,
                    "typed": False,
                }
            )
        except Exception as e:  # noqa: BLE001
            nm = type(e).__name__
            rows.append(
                {
                    "input": label,
                    "outcome": nm,
                    "is_XStateMachineError": isinstance(e, XStateMachineError),
                    "is_TypeError": isinstance(e, TypeError),
                    "typed": isinstance(e, XStateMachineError),
                    "msg": str(e)[:90],
                }
            )
        finally:
            try:
                i.stop()
            except Exception:  # noqa: BLE001
                pass
    bad = [
        r
        for r in rows
        if r["outcome"] != "NO-RAISE" and not r.get("is_XStateMachineError")
    ]
    empties = [r for r in rows if r["input"] in ("empty_str", "whitespace")]
    return {
        "rows": rows,
        "untyped_raises": len(bad),
        "untyped_examples": bad[:6],
        "empty_string_handling": empties,
    }


def main():
    res = {"F1_snapshot_fuzz": f1(), "F2_hostile_event_types": f2()}

    print("== F1 snapshot fuzz ==")
    r = res["F1_snapshot_fuzz"]
    print(f"   mutations        : {r['mutations']}")
    print(f"   untyped escapes  : {r['untyped_escapes']}")
    for k, v in sorted(r["outcomes"].items(), key=lambda x: -x[1]):
        print(f"      {k:36s}: {v}")
    for e in r["escape_examples"]:
        print(f"      ESCAPE {e}")

    print("\n== F2 hostile event types ==")
    for row in res["F2_hostile_event_types"]["rows"]:
        print(f"   {row['input']:22s} -> {row['outcome']:26s} {row}")
    print(
        f"   untyped raises: "
        f"{res['F2_hostile_event_types']['untyped_raises']}"
    )

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "n5_fuzz.json"), "w") as f:
        json.dump(res, f, indent=2, default=str)
    print("\nwrote out/n5_fuzz.json")


if __name__ == "__main__":
    main()
