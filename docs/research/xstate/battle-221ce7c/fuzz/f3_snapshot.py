"""F3 -- snapshot fuzzer.

Contract under test:

  C1. ``from_snapshot`` on a MUTATED persisted blob must either restore a
      coherent machine, or raise one of ``ALLOWED_RESTORE_ERRORS``. A bare
      ``TypeError``/``KeyError``/``AttributeError``/``ValueError`` is a
      defect: the documented way to catch this library's failures is
      ``except XStateMachineError``, and #45's whole point is that a blob
      off Redis/disk is ordinary untrusted input.
  C2. It must never "load garbage silently": if it returns an interpreter,
      that interpreter's configuration must be legal (same B2 predicate as
      F2) and its status must be a documented value.
  C3. Round-trip fidelity on an UNMUTATED snapshot: save -> restore ->
      save must be stable in the fields that describe state
      (``configuration``, ``state_ids``, ``context``, ``deferred``,
      ``pending_events``, ``history``).

Mutations: bit/char flips in the JSON text, whole-field drops, type swaps,
version bumps, hash tampering, truncation, and structural injection of junk
into `configuration` / `pending_events` / `actors`.

Usage:
    python f3_snapshot.py [--cases N] [--seed S]
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import seed as hseed
from hypothesis import strategies as st

from common import (  # noqa: E402
    ALLOWED_RESTORE_ERRORS,
    OUT,
    Recorder,
    exc_sig,
)
import spin_oracle  # noqa: E402
from spin_oracle import Spin  # noqa: E402
from gen_config import EVENTS, make_logic, valid_machine  # noqa: E402

from xstate_statemachine import SyncInterpreter, create_machine  # noqa: E402

warnings.simplefilter("ignore")

REC = Recorder("F3 snapshot fuzzer")
VALID_STATUS = {"uninitialized", "running", "stopped", "error", "done"}


def config_ok(interp) -> str:
    """Same legality predicate as F2's B2."""
    active = set(interp._active_state_nodes)
    if interp.status != "running":
        return ""
    if not active:
        return "empty configuration on a running restored machine"
    for node in active:
        if node.parent is not None and node.parent not in active:
            return f"orphan active node {node.id}"
    for node in active:
        kids = getattr(node, "states", None)
        if not kids:
            continue
        n_active = len([c for c in kids.values() if c in active])
        if node.type == "parallel":
            if n_active != len(kids):
                return f"parallel {node.id} partially active"
        elif n_active != 1:
            return f"compound {node.id} has {n_active} active children"
    return ""


# -----------------------------------------------------------------------------
# 💥 Snapshot mutations
# -----------------------------------------------------------------------------
TEXT_MUTATIONS = ["flip_char", "delete_char", "truncate", "insert_junk"]
STRUCT_MUTATIONS = [
    "drop_field",
    "swap_type",
    "bump_version",
    "tamper_hash",
    "tamper_machine_id",
    "junk_configuration",
    "junk_state_ids",
    "junk_pending",
    "junk_deferred",
    "junk_history",
    "junk_actors",
    "junk_context",
    "nan_context",
    "deep_nest_context",
]
ALL_MUTATIONS = TEXT_MUTATIONS + STRUCT_MUTATIONS

JUNK = [None, 0, -1, 3.5, True, "", "zz", [], {}, [1], {"k": 1}]


def mutate_text(text: str, kind: str, rng: random.Random) -> str:
    if not text:
        return text
    if kind == "flip_char":
        i = rng.randrange(len(text))
        return text[:i] + rng.choice("{}[],:\"0aZ\\ ") + text[i + 1 :]
    if kind == "delete_char":
        i = rng.randrange(len(text))
        return text[:i] + text[i + 1 :]
    if kind == "truncate":
        return text[: rng.randrange(len(text))]
    if kind == "insert_junk":
        i = rng.randrange(len(text))
        return text[:i] + rng.choice(['"x"', "null", "}}", "1e999"]) + text[i:]
    return text


def mutate_struct(snap: dict, kind: str, rng: random.Random) -> dict:
    snap = copy.deepcopy(snap)
    keys = sorted(snap)
    if kind == "drop_field":
        snap.pop(rng.choice(keys), None)
    elif kind == "swap_type":
        snap[rng.choice(keys)] = rng.choice(JUNK)
    elif kind == "bump_version":
        snap["version"] = rng.choice([3, 99, -1, "2", None, 2.5])
    elif kind == "tamper_hash":
        snap["machine_hash"] = rng.choice(["deadbeef", "", None, 0, []])
    elif kind == "tamper_machine_id":
        snap["machine_id"] = rng.choice(["other", "", None, 7])
    elif kind == "junk_configuration":
        snap["configuration"] = rng.choice(
            [["m.NOPE"], ["m", 7], [None], "m.a", {"m": 1}, [["m"]]]
        )
    elif kind == "junk_state_ids":
        snap["state_ids"] = rng.choice(
            [["m.NOPE"], [None], 5, {"a": 1}, [["m.a"]]]
        )
    elif kind == "junk_pending":
        snap["pending_events"] = rng.choice(
            [
                [{"kind": "bogus", "type": "GO"}],
                [{"type": None}],
                [{"kind": "error"}],
                ["GO"],
                [None],
                [{"kind": "done", "type": "done.invoke.x", "data": {"$": 1}}],
                "GO",
                [{}],
            ]
        )
    elif kind == "junk_deferred":
        snap["deferred"] = rng.choice(
            [[{"type": None}], ["GO"], [None], [{}], 5]
        )
    elif kind == "junk_history":
        snap["history"] = rng.choice(
            [{"m": ["m.NOPE"]}, {"m": None}, {None: ["m.a"]}, [], "x"]
        )
    elif kind == "junk_actors":
        snap["actors"] = rng.choice(
            [{"a": {}}, {"a": None}, {"a": {"snapshot": None}}, [], 5]
        )
    elif kind == "junk_context":
        snap["context"] = rng.choice([None, 5, "x", [], [1, 2]])
    elif kind == "nan_context":
        snap["context"] = {"n": float("nan"), "i": float("inf")}
    elif kind == "deep_nest_context":
        # 📏 300 is comfortably below CPython's 1000-frame default on its
        #    own, but `json.dumps` + `copy.deepcopy` + the restore path stack
        #    on top of it. Deeper values (2 000+) make the interpreter emit
        #    RecursionError from GC callbacks, which is noise rather than a
        #    library signal, so the depth is capped here.
        v: object = 1
        for _ in range(300):
            v = [v]
        snap["context"] = {"deep": v}
    return snap


# -----------------------------------------------------------------------------
# 🏃 Trial
# -----------------------------------------------------------------------------
def make_snapshot(cfg, events):
    """Build a machine, run it a little, and return (machine, snapshot dict)."""
    machine = create_machine(cfg, logic=make_logic(sync=True))
    spin_oracle._STATE["n"] = 0
    interp = SyncInterpreter(machine)
    interp.start()
    for ev in events:
        spin_oracle._STATE["n"] = 0
        try:
            interp.send(ev)
        except Exception:
            pass
    return machine, interp.get_persisted_snapshot()


def restore(text, machine, verify_hash=True):
    return SyncInterpreter.from_snapshot(
        text, machine, verify_machine_hash=verify_hash
    )


def trial(cfg, events, mutation, rng_seed, verify_hash) -> None:
    REC.cases += 1
    rng = random.Random(rng_seed)
    try:
        machine, snap = make_snapshot(cfg, events)
    except (Spin, Exception):
        REC.bump("setup.failed")
        return

    # --- C3: clean round-trip first -----------------------------------------
    clean = json.dumps(snap, default=str)
    try:
        spin_oracle._STATE["n"] = 0
        back = restore(clean, machine)
        again = back.get_persisted_snapshot()
        for field in (
            "configuration",
            "state_ids",
            "context",
            "deferred",
            "pending_events",
            "history",
        ):
            a = json.dumps(snap.get(field), sort_keys=True, default=str)
            b = json.dumps(again.get(field), sort_keys=True, default=str)
            if a != b:
                REC.bump(f"C3.roundtrip_drift.{field}")
                REC.record(
                    "C3-roundtrip-not-stable",
                    field,
                    f"save->restore->save changed '{field}': {a[:200]} != "
                    f"{b[:200]}",
                    {"config": cfg, "events": events, "field": field},
                    len(clean),
                )
        REC.bump("C3.roundtrip_ok")
    except Spin:
        REC.bump("C3.roundtrip_never_settles")
    except Exception as exc:  # noqa: BLE001
        REC.bump("C3.roundtrip_failed")
        REC.record(
            "C3-clean-snapshot-fails-to-restore",
            exc_sig(exc),
            f"an UNMUTATED snapshot failed to restore: "
            f"{type(exc).__name__}: {exc}",
            {"config": cfg, "events": events, "snapshot": snap},
            len(clean),
            exc,
        )

    # --- C1 / C2: mutated restore -------------------------------------------
    if mutation in TEXT_MUTATIONS:
        text = mutate_text(clean, mutation, rng)
        mutated_repr = {"mutation": mutation, "seed": rng_seed}
    else:
        mutated = mutate_struct(snap, mutation, rng)
        text = json.dumps(mutated, default=str)
        mutated_repr = {"mutation": mutation, "snapshot": mutated}

    repro = {
        "config": cfg,
        "events": events,
        "verify_hash": verify_hash,
        **mutated_repr,
    }
    size = len(text)

    try:
        spin_oracle._STATE["n"] = 0
        restored = restore(text, machine, verify_hash=verify_hash)
    except ALLOWED_RESTORE_ERRORS:
        REC.bump(f"C1.{mutation}.typed_reject")
        return
    except Spin:
        REC.bump(f"C1.{mutation}.never_settles")
        REC.record(
            "C1-restore-does-not-terminate",
            mutation,
            "from_snapshot never settled",
            repro,
            size,
        )
        return
    except RecursionError as exc:
        REC.bump(f"C1.{mutation}.recursion")
        REC.record(
            "C1-untyped-restore-error",
            f"{mutation}/RecursionError",
            f"{mutation} -> RecursionError (not an XStateMachineError)",
            repro,
            size,
            exc,
        )
        return
    except Exception as exc:  # noqa: BLE001
        REC.bump(f"C1.{mutation}.untyped")
        REC.record(
            "C1-untyped-restore-error",
            f"{mutation}/{exc_sig(exc)}",
            f"{mutation} -> {type(exc).__name__}: {exc}",
            repro,
            size,
            exc,
        )
        return

    # Restored without complaint: C2 says it must not be garbage.
    REC.bump(f"C1.{mutation}.accepted")
    # 🧷 `status` is not even guaranteed to be hashable after a restore: the
    #    snapshot value is assigned verbatim, so a list/dict lands on the
    #    attribute. Compare defensively.
    status = restored.status
    if not isinstance(status, str) or status not in VALID_STATUS:
        REC.bump(f"C2.{mutation}.bad_status")
        REC.record(
            "C2-restored-undocumented-status",
            f"{mutation}/{type(status).__name__}",
            f"restored status={status!r} ({type(status).__name__}) is not "
            f"one of {sorted(VALID_STATUS)}",
            repro,
            size,
        )
    reason = ""
    try:
        reason = config_ok(restored)
    except Exception:  # noqa: BLE001 - harness must not abort the run
        REC.bump(f"C2.{mutation}.inspect_failed")
    if reason:
        REC.bump(f"C2.{mutation}.illegal_config")
        REC.record(
            "C2-garbage-restored-silently",
            f"{mutation}/{reason.split()[0]}",
            f"{mutation} restored with NO error but: {reason}",
            repro,
            size,
        )
    # A restored machine must also survive one event without an untyped error.
    try:
        spin_oracle._STATE["n"] = 0
        restored.send("GO")
    except Spin:
        REC.bump(f"C2.{mutation}.send_never_settles")
    except Exception as exc:  # noqa: BLE001
        if not isinstance(exc, ALLOWED_RESTORE_ERRORS):
            from common import ALLOWED_SEND_ERRORS

            if not isinstance(exc, ALLOWED_SEND_ERRORS):
                REC.bump(f"C2.{mutation}.send_untyped")
                REC.record(
                    "C2-restored-machine-breaks-on-first-event",
                    f"{mutation}/{exc_sig(exc)}",
                    f"restored OK, then send('GO') -> "
                    f"{type(exc).__name__}: {exc}",
                    repro,
                    size,
                    exc,
                )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20260918)
    ap.add_argument("--out", default="f3_snapshot.json")
    args = ap.parse_args()

    spin_oracle._STATE["limit"] = 20000

    @hseed(args.seed)
    @settings(
        max_examples=args.cases,
        deadline=None,
        suppress_health_check=list(HealthCheck),
        phases=[Phase.generate],
        database=None,
    )
    @given(
        valid_machine(max_depth=3),
        st.lists(st.sampled_from(EVENTS), max_size=4),
        st.sampled_from(ALL_MUTATIONS),
        st.integers(min_value=0, max_value=1_000_000),
        st.booleans(),
    )
    def run(cfg, events, mutation, rng_seed, verify_hash):
        trial(cfg, events, mutation, rng_seed, verify_hash)

    run()
    REC.report()
    REC.dump(os.path.join(OUT, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
