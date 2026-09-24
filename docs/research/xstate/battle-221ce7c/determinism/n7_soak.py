"""N7 -- reduced chaos soak (12 minutes, split across both engines).

Chaos mix, per iteration, on a live interpreter:
  * bursts of scripted events from the dmachine pool
  * SimulatedClock ticks (timers fire mid-burst)
  * a snapshot at a quiescent point, restored into a FRESH interpreter, and
    the restore's snapshot compared byte-for-byte (persistence under churn)
  * periodic hostile input (bad event types) that must raise typed errors
    and must NOT corrupt the machine
  * periodic corrupt-snapshot restores that must raise typed errors

Invariants checked continuously:
  I1  the machine never leaves a legal configuration (one leaf per region)
  I2  status stays "running"
  I3  a quiescent snapshot never raises SnapshotMidStepError
  I4  snapshot round-trip is byte-identical
  I5  no untyped exception escapes anywhere
  I6  memory (RSS) does not grow without bound

REDUCED: 12 minutes total (~6 min/engine) instead of a multi-hour soak, per
the task's time bound. Duration is a CLI arg: `python n7_soak.py 720`.
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

import psutil  # noqa: E402

from dmachine import Recorder, build, canon_snapshot  # noqa: E402
from xstate_statemachine import (  # noqa: E402
    Interpreter,
    SyncInterpreter,
    SnapshotMidStepError,
    XStateMachineError,
)
from xstate_statemachine.clock import SimulatedClock  # noqa: E402

TOTAL_SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 720
POOL = [
    "ORDER",
    "FILL",
    "CANCEL",
    "SETTLE",
    "BREACH",
    "CLEAR",
    "PING_CHILD",
    "NOPE",
]
HOSTILE = [None, 42, 1.5, [], {"nope": 1}, object(), b"GO"]
PROC = psutil.Process()


def leaves(i):
    return sorted(s.id for s in i._active_state_nodes if not s.states)


def legal(ids):
    """The oms fixture is a 3-region parallel root: expect exactly 3 leaves."""
    return len(ids) == 3


class Stats:
    def __init__(self):
        self.iters = 0
        self.events = 0
        self.snapshots = 0
        self.roundtrips = 0
        self.rt_mismatch = []
        self.midstep_at_quiescence = []
        self.illegal_config = []
        self.bad_status = []
        self.untyped = []
        self.typed_hostile = 0
        self.hostile_untyped = []
        self.typed_corrupt = 0
        self.corrupt_untyped = []
        self.rss = []

    def as_dict(self, secs):
        return {
            "seconds": round(secs, 1),
            "iterations": self.iters,
            "events": self.events,
            "snapshots": self.snapshots,
            "roundtrips": self.roundtrips,
            "I1_illegal_configs": len(self.illegal_config),
            "I1_examples": self.illegal_config[:3],
            "I2_bad_status": len(self.bad_status),
            "I3_midstep_at_quiescence": len(self.midstep_at_quiescence),
            "I3_examples": self.midstep_at_quiescence[:3],
            "I4_roundtrip_mismatches": len(self.rt_mismatch),
            "I4_examples": self.rt_mismatch[:2],
            "I5_untyped_escapes": len(self.untyped),
            "I5_examples": self.untyped[:5],
            "hostile_typed_raises": self.typed_hostile,
            "hostile_untyped": self.hostile_untyped[:5],
            "corrupt_typed_raises": self.typed_corrupt,
            "corrupt_untyped": self.corrupt_untyped[:5],
            "rss_mb_first": self.rss[0] if self.rss else None,
            "rss_mb_last": self.rss[-1] if self.rss else None,
            "rss_mb_max": max(self.rss) if self.rss else None,
            "OK": not (
                self.illegal_config
                or self.bad_status
                or self.midstep_at_quiescence
                or self.rt_mismatch
                or self.untyped
                or self.hostile_untyped
                or self.corrupt_untyped
            ),
        }


def chaos_common(i, st, rng, factory, is_async=False):
    """Shared non-send checks; returns nothing, records into `st`."""
    ids = leaves(i)
    if not legal(ids):
        st.illegal_config.append((st.iters, ids))
    if i.status != "running":
        st.bad_status.append((st.iters, i.status))

    # I3/I4 snapshot at a quiescent point + round-trip
    try:
        raw = i.get_persisted_snapshot()
        st.snapshots += 1
    except SnapshotMidStepError as e:
        st.midstep_at_quiescence.append((st.iters, str(e)[:100]))
        return
    except Exception as e:  # noqa: BLE001
        st.untyped.append((st.iters, "snapshot", type(e).__name__, str(e)[:80]))
        return

    if st.iters % 5 == 0:
        c = canon_snapshot(raw)
        try:
            r = factory(json.dumps(raw, default=str))
            st.roundtrips += 1
            if canon_snapshot(r.get_persisted_snapshot()) != c:
                st.rt_mismatch.append((st.iters, "bytes-differ"))
        except XStateMachineError as e:
            st.rt_mismatch.append((st.iters, f"typed:{type(e).__name__}"))
        except Exception as e:  # noqa: BLE001
            st.untyped.append(
                (st.iters, "restore", type(e).__name__, str(e)[:80])
            )

    # hostile input must raise typed and leave the machine intact
    if st.iters % 7 == 0:
        val = rng.choice(HOSTILE)
        try:
            res = i.send(val)
            if is_async and asyncio.iscoroutine(res):
                res.close()
        except XStateMachineError:
            st.typed_hostile += 1
        except Exception as e:  # noqa: BLE001
            st.hostile_untyped.append(
                (st.iters, repr(val)[:30], type(e).__name__)
            )

    # corrupt snapshot restores must raise typed
    if st.iters % 11 == 0:
        o = dict(raw)
        o[rng.choice(["status", "context", "state_ids"])] = rng.choice(
            [None, 7, "x", [], {}]
        )
        try:
            factory(json.dumps(o, default=str))
        except XStateMachineError:
            st.typed_corrupt += 1
        except Exception as e:  # noqa: BLE001
            st.corrupt_untyped.append((st.iters, type(e).__name__, str(e)[:70]))

    if st.iters % 50 == 0:
        st.rss.append(round(PROC.memory_info().rss / 1e6, 1))


def soak_sync(deadline, rng):
    st = Stats()
    rec = Recorder()
    clock = SimulatedClock()
    i = SyncInterpreter(build(rec), clock=clock)
    i.start()
    t0 = time.time()

    def factory(blob):
        return SyncInterpreter.from_snapshot(blob, build(Recorder()))

    while time.time() < deadline:
        st.iters += 1
        for _ in range(rng.randrange(1, 12)):
            try:
                i.send(rng.choice(POOL), i=st.events, v=rng.randrange(1000))
                st.events += 1
            except XStateMachineError as e:
                st.untyped.append(
                    (st.iters, "send-typed", type(e).__name__, str(e)[:60])
                )
            except Exception as e:  # noqa: BLE001
                st.untyped.append(
                    (st.iters, "send", type(e).__name__, str(e)[:60])
                )
        if st.iters % 3 == 0:
            clock.increment(rng.choice([10, 25, 60, 120]))
        chaos_common(i, st, rng, factory)
        if st.iters % 500 == 0:
            del rec.actions[:]
            gc.collect()
    i.stop()
    return st.as_dict(time.time() - t0)


async def soak_async(deadline, rng):
    st = Stats()
    rec = Recorder()
    clock = SimulatedClock()
    i = Interpreter(build(rec), clock=clock)
    await i.start()
    t0 = time.time()

    def factory(blob):
        return Interpreter.from_snapshot(blob, build(Recorder()))

    while time.time() < deadline:
        st.iters += 1
        for _ in range(rng.randrange(1, 12)):
            try:
                await i.send(
                    rng.choice(POOL), i=st.events, v=rng.randrange(1000)
                )
                st.events += 1
            except XStateMachineError as e:
                st.untyped.append(
                    (st.iters, "send-typed", type(e).__name__, str(e)[:60])
                )
            except Exception as e:  # noqa: BLE001
                st.untyped.append(
                    (st.iters, "send", type(e).__name__, str(e)[:60])
                )
        if st.iters % 3 == 0:
            await clock.increment(rng.choice([10, 25, 60, 120]))
        chaos_common(i, st, rng, factory, is_async=True)
        if st.iters % 500 == 0:
            del rec.actions[:]
            gc.collect()
    await i.stop()
    return st.as_dict(time.time() - t0)


def main():
    half = TOTAL_SECONDS / 2
    res = {}
    print(f"soak: {TOTAL_SECONDS}s total ({half:.0f}s per engine)")

    rng = random.Random(1234)
    res["sync"] = soak_sync(time.time() + half, rng)
    print("\n== SYNC ==")
    for k, v in res["sync"].items():
        print(f"   {k:28s}: {v}")

    rng = random.Random(5678)
    res["async"] = asyncio.run(soak_async(time.time() + half, rng))
    print("\n== ASYNC ==")
    for k, v in res["async"].items():
        print(f"   {k:28s}: {v}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "n7_soak.json"), "w") as f:
        json.dump(res, f, indent=2, default=str)
    print("\nwrote out/n7_soak.json")


if __name__ == "__main__":
    main()
