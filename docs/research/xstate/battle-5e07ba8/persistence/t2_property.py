# -*- coding: utf-8 -*-
"""T2 - hypothesis property test: random event sequence x random crash point.

Property: restoring at ANY point of a sequence and resuming with the rest
yields the same final configuration, context and emitted-action trace as an
uninterrupted run of the same sequence.

`__TICK__` events are excluded from the default pool because
D-persistence-2 (after timers are not re-armed on restore) makes every
timer case fail by construction; run with `--timers` to include them.

Run:
  python t2_property.py            # 2,000 cases
  python t2_property.py --timers   # include SimulatedClock ticks
"""
from __future__ import annotations

import asyncio
import json
import sys

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from harness import run_interrupted, run_plain

BASE_EVENTS = [
    {"type": "SUBMIT", "payload": {"qty": 7}},
    {"type": "RISK_OK"},
    {"type": "RISK_BAD"},
    {"type": "FILL", "payload": {"n": 1}},
    {"type": "FILL", "payload": {"n": 3}},
    {"type": "DONE"},
    {"type": "RETRY"},
    {"type": "RECHECK"},
    {"type": "CANCEL"},
    {"type": "CANCEL_OK"},
    {"type": "NOPE"},
]
TICKS = [
    {"type": "__TICK__", "ms": 6000},
    {"type": "__TICK__", "ms": 31000},
]

WITH_TIMERS = "--timers" in sys.argv
POOL = BASE_EVENTS + (TICKS if WITH_TIMERS else [])
MAXEX = 2000

FAILURES: list[str] = []
CASES = 0


def _events():
    return st.lists(st.sampled_from(POOL), min_size=1, max_size=8)


@settings(
    max_examples=MAXEX,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    database=None,
)
@given(seq=_events(), k=st.integers(min_value=0, max_value=8))
def test_restore_is_transparent(seq, k):
    global CASES
    CASES += 1
    k = min(k, len(seq))
    plain, (res, _blob) = asyncio.run(_both(seq, k))
    diffs = []
    for f in ("states", "context", "actions", "status"):
        a, b = getattr(plain, f), getattr(res, f)
        if a != b:
            diffs.append(f"{f}: plain={a!r} restored={b!r}")
    if diffs:
        FAILURES.append(
            json.dumps({"seq": seq, "k": k, "diffs": diffs}, default=str)
        )


async def _both(seq, k):
    plain = await run_plain(seq)
    res = await run_interrupted(seq, k)
    return plain, res


if __name__ == "__main__":
    try:
        test_restore_is_transparent()
    except Exception as e:  # hypothesis raises on the shrunk failure
        print("HYPOTHESIS RAISED:", type(e).__name__, e)
    uniq = sorted(set(FAILURES))
    print(f"\ncases run: {CASES}   failing cases: {len(FAILURES)}   "
          f"distinct: {len(uniq)}   timers={WITH_TIMERS}")
    for u in uniq[:15]:
        print(" -", u)
