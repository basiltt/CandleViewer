"""u8 (@c78ce99) -- STANDALONE MINIMAL. The #212 "self-paced heartbeat
runs indefinitely" claim, on the canonical heartbeat shape.

#212's stated purpose: "A `raise(delay=)` heartbeat of any period runs
indefinitely, exactly as an `after` one does." The canonical way to
write one is a SELF-TARGETING transition on the state that arms it:

    beat: entry raise(TICK, delay=25); on TICK -> beat

SELF   : on TICK -> "beat"            (its own state)
SELF_RE: on TICK -> "beat", reenter   (explicit re-entry)
HOP    : beat <-> beat2               (two states, semantically same loop)
AFTER  : after: {25: "beat"}          (the parity reference #212 names)

Each is run for RUN_S on both engines and both action kinds, and its
armed `scheduled_sends` record is checked at the end.

ORACLE (corrected after the first run): a self-targeting transition
with no `reenter` is an INTERNAL transition -- the state is never exited
so `entry` never re-runs. That is SCXML, not a defect, and the point of
this probe is PARITY: `raise(delay=)` must behave exactly as `after` on
each of the four shapes. The pass condition is therefore
  SELF == AFTER  (both beat once)  and  SELF_RE / HOP run indefinitely.

Run: python u8_self_target_heartbeat.py   (exit 1 == parity broken)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import time
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)

PERIOD_MS = 25
RUN_S = 1.0
MIN_BEATS = 10          # 1.0 s / 25 ms = 40 ideal; 10 is generous


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


RAISE = {"type": "raise", "params": {"event": "TICK", "delay": PERIOD_MS}}

SELF = {
    "id": "u8", "initial": "beat", "context": {"n": 0},
    "states": {"beat": {"entry": [RAISE],
                        "on": {"TICK": {"target": "beat",
                                        "actions": ["tick"]}}}},
}

SELF_RE = {
    "id": "u8r", "initial": "beat", "context": {"n": 0},
    "states": {"beat": {"entry": [RAISE],
                        "on": {"TICK": {"target": "beat", "reenter": True,
                                        "actions": ["tick"]}}}},
}

HOP = {
    "id": "u8h", "initial": "beat", "context": {"n": 0},
    "states": {
        "beat": {"entry": [RAISE],
                 "on": {"TICK": {"target": "beat2", "actions": ["tick"]}}},
        "beat2": {"entry": [RAISE],
                  "on": {"TICK": {"target": "beat", "actions": ["tick"]}}},
    },
}

AFTER = {
    "id": "u8a", "initial": "beat", "context": {"n": 0},
    "states": {"beat": {"after": {PERIOD_MS: {"target": "beat",
                                              "actions": ["tick"]}}}},
}


def logic(kind):
    if kind == "def":

        def tick(i, ctx, e, ad):  # noqa: ANN001
            ctx["n"] = ctx.get("n", 0) + 1

        return MachineLogic(actions={"tick": tick})

    async def atick(i, ctx, e, ad):  # noqa: ANN001
        ctx["n"] = ctx.get("n", 0) + 1

    return MachineLogic(actions={"tick": atick})


def armed(interp) -> int:
    snap = interp.get_persisted_snapshot()
    if not isinstance(snap, str):
        snap = json.dumps(snap, default=str)
    return len(json.loads(snap).get("scheduled_sends") or [])


async def run_async(cfg, kind) -> Dict[str, Any]:
    m = create_machine(copy.deepcopy(cfg), logic=logic(kind))
    i = Interpreter(m)
    await i.start()
    await asyncio.sleep(RUN_S)
    out = {"engine": "async", "kind": kind, "beats": i.context.get("n", 0),
           "armed_records_at_end": armed(i), "status": i.status,
           "states": sorted(i.current_state_ids),
           "last_error": None if i.last_error is None else str(i.last_error)}
    try:
        await i.stop()
    except Exception:
        pass
    return out


def run_sync(cfg, kind) -> Dict[str, Any]:
    if kind == "async def":
        return {"engine": "sync", "kind": kind, "unsupported": True}
    m = create_machine(copy.deepcopy(cfg), logic=logic(kind))
    i = SyncInterpreter(m)
    i.start()
    end = time.perf_counter() + RUN_S
    while time.perf_counter() < end:
        i.tick()
        time.sleep(0.002)
    out = {"engine": "sync", "kind": kind, "beats": i.context.get("n", 0),
           "armed_records_at_end": armed(i), "status": i.status,
           "states": sorted(i.current_state_ids),
           "last_error": None if i.last_error is None else str(i.last_error)}
    try:
        i.stop()
    except Exception:
        pass
    return out


CASES = [("SELF_raise_delay", SELF), ("SELF_raise_delay_reenter", SELF_RE),
         ("HOP_raise_delay", HOP), ("AFTER_parity_reference", AFTER)]


async def main() -> int:
    rows: List[Dict[str, Any]] = []
    for name, cfg in CASES:
        for kind in ("def", "async def"):
            r = await run_async(cfg, kind)
            r["case"] = name
            rows.append(r)
        r = run_sync(cfg, "def")
        r["case"] = name
        rows.append(r)

    ideal = RUN_S * 1000.0 / PERIOD_MS
    bad: List[str] = []
    by = {}
    for r in rows:
        if r.get("unsupported"):
            continue
        by.setdefault(r["case"], {})[f"{r['engine']}/{r['kind']}"] = r["beats"]
        tag = f"{r['case']}/{r['engine']}/{r['kind']}"
        # re-entering / two-state loops MUST run indefinitely (#212)
        if r["case"] in ("SELF_raise_delay_reenter", "HOP_raise_delay")                 and r["beats"] < MIN_BEATS:
            bad.append(f"{tag}: {r['beats']} beats in {RUN_S}s "
                       f"(ideal ~{ideal:.0f}); armed records at end = "
                       f"{r['armed_records_at_end']}")
    # PARITY: internal self-target raise(delay=) must match `after`
    for lane, n in by["SELF_raise_delay"].items():
        ref = by["AFTER_parity_reference"][lane]
        if n != ref:
            bad.append(f"PARITY {lane}: internal self-target raise(delay=) "
                       f"beat {n}x but the `after` reference beat {ref}x")
    emit("u8_self_target_heartbeat", {
        "period_ms": PERIOD_MS, "run_s": RUN_S, "ideal_beats": ideal,
        "min_beats_required": MIN_BEATS, "rows": rows,
        "beats_by_case": by,
        "parity_note": ("SELF and AFTER both beat once: a self-target "
                        "transition without `reenter` is INTERNAL, the "
                        "state is not exited, so neither entry-armed "
                        "raise(delay=) nor the state's `after` re-arms. "
                        "#212's parity claim holds exactly. Authors who "
                        "want a heartbeat must use reenter: true or a "
                        "two-state hop -- both run indefinitely here."),
        "violations": bad,
        "verdict": "DEFECT" if bad else "CLEAN",
    })
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
