# -*- coding: utf-8 -*-
"""T8 - property test with MID-MACROSTEP interruption.

T2 crashes only at quiescent boundaries (between `send()`s). This one
crashes at a random ACTION boundary inside a macrostep, via the
`on_action_execute` plugin hook -- i.e. exactly where a real process dies.

Property (the one the snapshot API advertises): a snapshot taken at ANY
moment restores to a machine that can reach the same final state as the
uninterrupted run.

We measure the weaker, strictly necessary property first: the snapshot's
recorded configuration is a LEGAL configuration -- non-empty, and with one
active leaf per parallel region. A torn snapshot fails that, so counting
tears bounds the exposure without needing full replay equivalence.

Run:
  python t8_midstep_property.py [N]      # default 2000 cases
"""
from __future__ import annotations

import asyncio
import json
import sys

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from xstate_statemachine import Interpreter
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

import order_machine
from harness import attach_clock

POOL = [
    {"type": "SUBMIT", "payload": {"qty": 7}},
    {"type": "RISK_OK"},
    {"type": "RISK_BAD"},
    {"type": "FILL", "payload": {"n": 2}},
    {"type": "DONE"},
    {"type": "RECHECK"},
    {"type": "CANCEL"},
    {"type": "CANCEL_OK"},
]
N = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 2000

STATS = {"snaps": 0, "empty": 0, "missing_region": 0, "legal": 0,
         "restore_error": 0, "cases": 0}
EXAMPLES: dict[str, str] = {}

# Which parallel regions must each have exactly one active leaf?
REGIONS = ("order.submitted.exchange", "order.submitted.risk")


def classify(blob: str) -> tuple[str, str]:
    d = json.loads(blob)
    ids = d["state_ids"]
    cfg = set(d["configuration"])
    if not ids:
        return "empty", f"configuration={d['configuration']}"
    if "order.submitted" in cfg:
        for region in REGIONS:
            leaves = [s for s in ids if s.startswith(region + ".")]
            if len(leaves) != 1:
                return (
                    "missing_region",
                    f"region {region} has leaves {leaves}; state_ids={ids}",
                )
    return "legal", ""


class SnapAt(PluginBase):
    """Snapshot at the nth action executed, then classify it."""

    def __init__(self, nth: int) -> None:
        self.nth = nth
        self.count = 0
        self.blob: str | None = None

    def on_action_execute(self, interp, action):  # noqa: ANN001
        if self.count == self.nth and self.blob is None:
            try:
                self.blob = interp.get_snapshot()
            except Exception as e:  # noqa: BLE001
                self.blob = f"__ERR__{e}"
        self.count += 1


async def _run(seq, nth):
    plug = SnapAt(nth)
    i = Interpreter(order_machine.build(), clock=SimulatedClock())
    i.use(plug)
    await i.start()
    await asyncio.sleep(0.02)
    for ev in seq:
        if i.status != "running":
            break
        await i.send(ev["type"], **(ev.get("payload") or {}))
        await asyncio.sleep(0.02)
    await i.stop()
    return plug.blob


@settings(
    max_examples=N,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    database=None,
)
@given(
    seq=st.lists(st.sampled_from(POOL), min_size=1, max_size=6),
    nth=st.integers(min_value=0, max_value=12),
)
def test_every_snapshot_is_a_legal_configuration(seq, nth):
    STATS["cases"] += 1
    blob = asyncio.run(_run(seq, nth))
    if blob is None:
        return  # fewer than `nth` actions ran; no snapshot taken
    STATS["snaps"] += 1
    if blob.startswith("__ERR__"):
        STATS["restore_error"] += 1
        EXAMPLES.setdefault("restore_error", blob[:200])
        return
    verdict, detail = classify(blob)
    STATS[verdict] += 1
    if verdict != "legal":
        EXAMPLES.setdefault(
            verdict, json.dumps({"seq": seq, "nth": nth, "why": detail})
        )


if __name__ == "__main__":
    try:
        test_every_snapshot_is_a_legal_configuration()
    except Exception as e:  # noqa: BLE001
        print("HYPOTHESIS RAISED:", type(e).__name__, e)
    s = STATS
    print(f"\ncases={s['cases']}  snapshots taken={s['snaps']}")
    print(f"  legal          : {s['legal']}")
    print(f"  EMPTY config   : {s['empty']}")
    print(f"  missing region : {s['missing_region']}")
    print(f"  snapshot raised: {s['restore_error']}")
    if s["snaps"]:
        bad = s["empty"] + s["missing_region"]
        print(f"  => {bad}/{s['snaps']} = {100.0*bad/s['snaps']:.1f}% TORN")
    for k, v in EXAMPLES.items():
        print(f"  example {k}: {v}")
