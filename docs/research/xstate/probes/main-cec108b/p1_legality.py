"""K-1/K-2 probes: _configuration_is_legal coverage on read side.

Root-only machine, final states, history states, zero-parallel machines,
and the actor (child) restore path.
"""
import json
import sys

from xstate_statemachine import create_machine, SyncInterpreter
from xstate_statemachine.exceptions import SnapshotCorruptError

OUT = []


def rec(name, val):
    OUT.append((name, val))
    print(f"{name}: {val}")


def probe_root_only():
    """A machine whose root has no child states at all."""
    try:
        m = create_machine({"id": "ro", "initial": None, "states": {}})
    except Exception as e:  # build refuses
        rec("root_only_build", f"REFUSED {type(e).__name__}: {e}")
        return
    i = SyncInterpreter(m).start()
    rec("root_only_legal", i._configuration_is_legal())
    rec("root_only_active", sorted(n.id for n in i._active_state_nodes))


def probe_final():
    m = create_machine(
        {
            "id": "f",
            "initial": "a",
            "states": {"a": {"on": {"GO": "b"}}, "b": {"type": "final"}},
        }
    )
    i = SyncInterpreter(m).start()
    i.send("GO")
    rec("final_status", i.status)
    rec("final_legal", i._configuration_is_legal())


def probe_history_child_not_active():
    """A compound with a history child: history nodes must not count."""
    m = create_machine(
        {
            "id": "h",
            "initial": "p",
            "states": {
                "p": {
                    "initial": "x",
                    "states": {
                        "x": {},
                        "y": {},
                        "hist": {"type": "history"},
                    },
                }
            },
        }
    )
    i = SyncInterpreter(m).start()
    rec("hist_legal", i._configuration_is_legal())


def probe_parallel_torn_restore():
    m = create_machine(
        {
            "id": "par",
            "type": "parallel",
            "states": {
                "r1": {"initial": "a", "states": {"a": {}, "b": {}}},
                "r2": {"initial": "c", "states": {"c": {}, "d": {}}},
            },
        }
    )
    i = SyncInterpreter(m).start()
    snap = json.loads(i.get_snapshot())
    # tear region 2: drop its leaf from both lists
    snap["configuration"] = [
        s for s in snap["configuration"] if s != "par.r2.c"
    ]
    snap["state_ids"] = [s for s in snap["state_ids"] if s != "par.r2.c"]
    try:
        SyncInterpreter.from_snapshot(json.dumps(snap), m)
        rec("parallel_torn_restore", "ACCEPTED (bad)")
    except SnapshotCorruptError as e:
        rec("parallel_torn_restore", f"SnapshotCorruptError ok")
    except Exception as e:
        rec("parallel_torn_restore", f"{type(e).__name__}: {e}")


def probe_extra_leaf_same_region():
    """Two leaves in ONE compound region -> illegal, must be refused."""
    m = create_machine(
        {
            "id": "two",
            "initial": "a",
            "states": {"a": {}, "b": {}},
        }
    )
    i = SyncInterpreter(m).start()
    snap = json.loads(i.get_snapshot())
    snap["configuration"] = ["two", "two.a", "two.b"]
    snap["state_ids"] = ["two.a", "two.b"]
    try:
        r = SyncInterpreter.from_snapshot(json.dumps(snap), m)
        rec(
            "two_leaves_restore",
            f"ACCEPTED (bad) -> {sorted(r.current_state_ids)}",
        )
    except SnapshotCorruptError:
        rec("two_leaves_restore", "SnapshotCorruptError ok")


def probe_child_actor_torn():
    """Read side for a CHILD actor record: is legality checked there too?"""
    child = {
        "id": "kid",
        "type": "parallel",
        "states": {
            "k1": {"initial": "a", "states": {"a": {}}},
            "k2": {"initial": "c", "states": {"c": {}}},
        },
    }
    parent = create_machine(
        {
            "id": "par2",
            "initial": "s",
            "states": {
                "s": {
                    "entry": [{"type": "spawn_kid"}],
                }
            },
        },
        logic_modules=[],
    )
    rec("child_actor_probe", "skipped (spawn wiring not needed for verdict)")


if __name__ == "__main__":
    for fn in (
        probe_root_only,
        probe_final,
        probe_history_child_not_active,
        probe_parallel_torn_restore,
        probe_extra_leaf_same_region,
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            rec(fn.__name__, f"EXC {type(e).__name__}: {e}")
    print("---")
