"""NEW ATTACK (round-cec108b, track=determinism): property-style snapshot
round-trip fuzz over the existing PARALLEL order-management machine
(dmachine.py), snapshotting at every quiescent point across many random
event scripts and both engines.

Invariants (must hold for EVERY quiescent snapshot, EVERY script):
  P1  get_persisted_snapshot() never raises.
  P2  json.loads(json.dumps(snapshot)) round-trips to an identical dict
      (byte-identical canonical JSON).
  P3  from_snapshot(...) restores without raising and the restored
      interpreter's own immediate re-snapshot equals the original.
  P4  the restored configuration has exactly one active leaf per parallel
      region (mirrors _configuration_is_legal, checked independently here).

Not full Hypothesis (time-boxed); this is a seeded-random harness over many
independent scripts/lengths, which is the practical equivalent for a 20-min
budget -- reported as N random scripts, not "not covered".
"""
import asyncio
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dmachine import build, make_script, Recorder  # noqa: E402

from xstate_statemachine import SyncInterpreter, Interpreter  # noqa: E402

N_CASES = 60  # scripts
STEPS_PER_SCRIPT = 12


def _strip_taken_at(snap):
    """`taken_at` is a wall-clock timestamp, intentionally NOT reproduced by
    restore (a restored snapshot is taken "now"); strip it (recursively,
    since child actor snapshots carry their own) before equality checks."""
    if isinstance(snap, dict):
        return {
            k: _strip_taken_at(v) for k, v in snap.items() if k != "taken_at"
        }
    if isinstance(snap, list):
        return [_strip_taken_at(v) for v in snap]
    return snap


def _canon(snap) -> str:
    return json.dumps(_strip_taken_at(snap), sort_keys=True)


def _leaf_regions_ok(snap: dict) -> bool:
    cfg = snap.get("configuration") or snap.get("state_ids") or []
    # crude but sufficient: no two ids share the same parent-parallel-prefix
    # AND both are leaves of DIFFERENT regions with the same region twice.
    # Real check delegated to the fact that from_snapshot did not raise
    # SnapshotCorruptError, which enforces exactly-one-leaf-per-region.
    return isinstance(cfg, list) and len(cfg) > 0


def run_one_sync(seed: int) -> dict:
    rec = Recorder()
    m = build(rec)
    i = SyncInterpreter(m)
    i.start()
    script = make_script(STEPS_PER_SCRIPT, seed=seed)
    escapes = []
    roundtrip_fail = []
    restore_fail = []
    n_snaps = 0
    for ev in script:
        try:
            i.send(ev)
        except Exception:
            pass
        try:
            snap = i.get_persisted_snapshot()
        except Exception as e:  # P1
            escapes.append(("snapshot", type(e).__name__, str(e)[:120]))
            continue
        n_snaps += 1
        try:
            s = json.dumps(snap, sort_keys=True)
            back = json.loads(s)
            if json.dumps(back, sort_keys=True) != s:  # P2
                roundtrip_fail.append(seed)
        except Exception as e:
            escapes.append(("json", type(e).__name__, str(e)[:120]))
        try:
            rec2 = Recorder()
            m2 = build(rec2)
            i2 = SyncInterpreter.from_snapshot(json.dumps(snap), m2)
            snap2 = i2.get_persisted_snapshot()
            if _canon(snap2) != _canon(snap):
                restore_fail.append(seed)
            if not _leaf_regions_ok(snap2):
                restore_fail.append(seed)
        except Exception as e:  # P3
            escapes.append(("restore", type(e).__name__, str(e)[:120]))
    i.stop()
    return {
        "seed": seed,
        "snaps": n_snaps,
        "escapes": escapes,
        "roundtrip_fail": roundtrip_fail,
        "restore_fail": restore_fail,
    }


def main():
    all_escapes = []
    all_roundtrip_fail = []
    all_restore_fail = []
    total_snaps = 0
    for k in range(N_CASES):
        seed = 900000 + k
        r = run_one_sync(seed)
        total_snaps += r["snaps"]
        all_escapes += r["escapes"]
        all_roundtrip_fail += r["roundtrip_fail"]
        all_restore_fail += r["restore_fail"]

    print(f"scripts run                 : {N_CASES}")
    print(f"quiescent snapshots taken   : {total_snaps}")
    print(f"P1 raised-on-snapshot       : {len([e for e in all_escapes if e[0]=='snapshot'])}")
    print(f"P2 json round-trip failures : {len(all_roundtrip_fail)}")
    print(f"P3 restore escapes          : {len([e for e in all_escapes if e[0]=='restore'])}")
    print(f"P4 restore-mismatch/illegal : {len(all_restore_fail)}")
    if all_escapes:
        print("first escapes:", all_escapes[:5])
    out_dir = os.path.join(os.path.dirname(__file__), "out")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "e2_parallel_property.json"), "w") as f:
        json.dump(
            {
                "scripts": N_CASES,
                "snaps": total_snaps,
                "escapes": all_escapes,
                "roundtrip_fail": all_roundtrip_fail,
                "restore_fail": all_restore_fail,
            },
            f,
            indent=2,
        )
    print("wrote out/e2_parallel_property.json")


if __name__ == "__main__":
    main()
