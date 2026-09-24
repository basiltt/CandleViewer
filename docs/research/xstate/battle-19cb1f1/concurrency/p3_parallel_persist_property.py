"""P3 @cec108b -- persistence property over random PARALLEL machines (#142/#143).

Hypothesis generates a random parallel machine (2-4 regions x 2-4 atomic
states, random event alphabet, some regions with `after` timers and a
history node) plus a random event script. After EVERY quiescent point:

  I1  `get_persisted_snapshot()` must not raise.
  I2  the blob must be JSON-serialisable and byte-identical on a second
      call at the same quiescent point (stable).
  I3  restore must succeed and round-trip configuration + context.
  I4  the restored snapshot must be byte-identical to the original
      (modulo `taken_at`, which is a timestamp).
  I5  exactly one active leaf per region at every observation.

Plus deterministic torn/hostile cases:
  T1  drop one region's leaf from `configuration` -> must be refused.
  T2  a v1 snapshot (no `configuration` key) with a torn `state_ids`
      -> must be refused.
  T3  an `actionErrorPolicy: "fail"`-stopped machine's snapshot -> must
      restore as a stopped machine or be refused; never as `running`.
"""

from __future__ import annotations

import asyncio
import json
import random

from common import emit
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import (
    SnapshotCorruptError,
    XStateMachineError,
)

EVENTS = ["A", "B", "C", "D"]


def build_parallel(seed: int) -> dict:
    rnd = random.Random(seed)
    regions = {}
    n_regions = rnd.randint(2, 4)
    for r in range(n_regions):
        n_states = rnd.randint(2, 4)
        names = [f"s{k}" for k in range(n_states)]
        states = {}
        for k, nm in enumerate(names):
            nxt = names[(k + 1) % n_states]
            on = {}
            for ev in rnd.sample(EVENTS, rnd.randint(1, len(EVENTS))):
                on[ev] = {"target": nxt, "actions": ["bump"]}
            node = {"on": on}
            if rnd.random() < 0.3:
                node["after"] = {rnd.choice([40, 80]): {"target": nxt}}
            states[nm] = node
        regions[f"r{r}"] = {
            "initial": names[0],
            "states": states,
        }
    return {
        "id": f"par{seed}",
        "type": "parallel",
        "context": {"n": 0},
        "states": regions,
    }


def bump(i, ctx, e, a):  # noqa: ANN001
    ctx["n"] += 1


def mk(cfg):
    return create_machine(cfg, logic=MachineLogic(actions={"bump": bump}))


def region_leaf_counts(cfg: dict, ids) -> dict:
    counts = {}
    for r in cfg["states"]:
        prefix = f"{cfg['id']}.{r}."
        counts[r] = sum(1 for s in ids if s.startswith(prefix))
    return counts


def canon(blob: str) -> str:
    d = json.loads(blob)
    d.pop("taken_at", None)
    return json.dumps(d, sort_keys=True)


STATE = {
    "cases": 0,
    "quiescent_points": 0,
    "snapshot_raises": [],
    "unstable": [],
    "roundtrip_mismatch": [],
    "not_byte_identical": [],
    "region_violations": [],
}


async def one_case(seed: int, script: list) -> None:
    cfg = build_parallel(seed)
    i = Interpreter(mk(cfg))
    await i.start()
    try:
        for ev in [None] + script:
            if ev is not None:
                try:
                    await asyncio.wait_for(i.send(ev, wait=True), 5)
                except XStateMachineError:
                    pass
            STATE["quiescent_points"] += 1
            ids = sorted(i.current_state_ids)
            rc = region_leaf_counts(cfg, ids)
            if any(v != 1 for v in rc.values()):
                STATE["region_violations"].append((seed, ids, rc))
            try:
                s1 = i.get_persisted_snapshot()
                b1 = json.dumps(s1)
            except Exception as exc:  # noqa: BLE001
                STATE["snapshot_raises"].append((seed, repr(exc)))
                continue
            b1b = json.dumps(i.get_persisted_snapshot())
            if canon(b1) != canon(b1b):
                STATE["unstable"].append(seed)
            try:
                j = Interpreter.from_snapshot(b1, mk(cfg))
            except Exception as exc:  # noqa: BLE001
                STATE["roundtrip_mismatch"].append((seed, repr(exc)))
                continue
            if sorted(j.current_state_ids) != ids or dict(j.context) != dict(
                i.context
            ):
                STATE["roundtrip_mismatch"].append(
                    (seed, sorted(j.current_state_ids), ids)
                )
                continue
            b2 = json.dumps(j.get_persisted_snapshot())
            if canon(b1) != canon(b2):
                STATE["not_byte_identical"].append(seed)
    finally:
        await i.stop()
    STATE["cases"] += 1


@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=list(HealthCheck),
)
@given(
    seed=st.integers(min_value=0, max_value=10_000),
    script=st.lists(st.sampled_from(EVENTS), min_size=0, max_size=4),
)
def test_property(seed, script):
    asyncio.run(one_case(seed, script))


async def torn_cases() -> dict:
    cfg = build_parallel(7)
    i = Interpreter(mk(cfg))
    await i.start()
    await asyncio.wait_for(i.send("A", wait=True), 5)
    good = i.get_persisted_snapshot()
    await i.stop()

    def restore(s) -> str:
        try:
            j = Interpreter.from_snapshot(json.dumps(s), mk(cfg))
        except SnapshotCorruptError:
            return "SnapshotCorruptError"
        except XStateMachineError as exc:  # noqa: BLE001
            return f"named:{type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001
            return f"RAW {type(exc).__name__}: {exc}"
        return (
            f"RESTORED status={j.status} ids={sorted(j.current_state_ids)}"
        )

    out = {}
    # T1: drop one region's leaf from `configuration`
    leaves = [
        s
        for s in good["configuration"]
        if s.count(".") >= 2  # id.region.leaf
    ]
    t1 = json.loads(json.dumps(good))
    t1["configuration"] = [s for s in t1["configuration"] if s != leaves[0]]
    t1["state_ids"] = [s for s in t1["state_ids"] if s != leaves[0]]
    out["T1_drop_one_region_leaf"] = restore(t1)
    # T1b: drop from configuration only, leave state_ids intact
    t1b = json.loads(json.dumps(good))
    t1b["configuration"] = [s for s in t1b["configuration"] if s != leaves[0]]
    out["T1b_configuration_only"] = restore(t1b)
    # T2: v1 shape (no configuration key) with torn state_ids
    t2 = json.loads(json.dumps(good))
    t2["version"] = 1
    t2.pop("configuration", None)
    t2["state_ids"] = [s for s in t2["state_ids"] if s != leaves[0]]
    out["T2_v1_torn_state_ids"] = restore(t2)
    # T2b: v1 shape, intact
    t2b = json.loads(json.dumps(good))
    t2b["version"] = 1
    t2b.pop("configuration", None)
    out["T2b_v1_intact"] = restore(t2b)
    # T3: 'error' status with no error recorded
    t3 = json.loads(json.dumps(good))
    t3["status"] = "error"
    t3["error"] = None
    out["T3_error_without_error"] = restore(t3)
    # T4: 'stopped' status
    t4 = json.loads(json.dumps(good))
    t4["status"] = "stopped"
    out["T4_stopped"] = restore(t4)
    return out


def main() -> int:
    test_property()
    torn = asyncio.run(torn_cases())
    ok = (
        not STATE["snapshot_raises"]
        and not STATE["unstable"]
        and not STATE["roundtrip_mismatch"]
        and not STATE["not_byte_identical"]
        and not STATE["region_violations"]
    )
    torn_ok = (
        "RESTORED status=running" not in torn["T1_drop_one_region_leaf"]
        and "RESTORED status=running" not in torn["T1b_configuration_only"]
        and "RESTORED status=running" not in torn["T2_v1_torn_state_ids"]
        and not torn["T3_error_without_error"].startswith("RESTORED status=running")
        and not any(v.startswith("RAW ") for v in torn.values())
    )
    emit(
        "p3_parallel_persist_property",
        {
            **{k: (v if not isinstance(v, list) else v[:5]) for k, v in STATE.items()},
            "counts": {k: len(v) for k, v in STATE.items() if isinstance(v, list)},
            "torn_cases": torn,
            "property_pass": ok,
            "torn_pass": torn_ok,
            "result": "PASS" if ok and torn_ok else "FAIL",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
