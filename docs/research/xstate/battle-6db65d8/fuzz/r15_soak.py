"""R15 -- 12-minute SOAK with ASYNC services, the configuration the prior
round's soak deliberately excluded (it would have been dominated by
D7-fuzz-1). 200 machines incl. rollback+onDone and always->invoke shapes,
plus an EXTERNAL PRIORITY PRODUCER and a chaos snapshot at quiescence.

Pass criteria:
  * CPU bounded (no livelock)
  * 0 external events dropped  (the #180 property, measured end to end by an
    action watermark, not just by the hook)
  * no machine leaves "running"; no untyped snapshot error
  * RSS characterised (the prior round left an uncharacterised 32->186MB
    climb; this run reports the slope with chaos snapshots ON and, in the
    final segment, OFF).

Usage: r15_soak.py [minutes]
"""
import asyncio, copy, json, logging, random, sys, time, warnings
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import psutil
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)
from xstate_statemachine.exceptions import (
    SnapshotMidStepError,
    SnapshotCorruptError,
)


async def async_svc(i, c, e):
    await asyncio.sleep(0)
    return {"ok": 1}


def bump(i, c, e, a):
    c["n"] = c.get("n", 0) + 1


def extbump(i, c, e, a):
    c["ext"] = c.get("ext", 0) + 1


L = MachineLogic(
    services={"svc": async_svc},
    actions={"bump": bump, "extbump": extbump},
    guards={"g": lambda c, e: True, "g2": lambda c, e: c.get("n", 0) % 3 != 0},
)


class Drops(PluginBase):
    def __init__(self):
        self.d = {}

    def on_event_dropped(self, interp, event, reason=None, **kw):
        k = f"{reason}:{getattr(event, 'type', event)}"
        self.d[k] = self.d.get(k, 0) + 1


EXT = {"EXT": {"target": None, "internal": True, "actions": ["extbump"]}}


def gen(i, rnd):
    k = rnd.choice(
        ["rollback_ondone", "always_into_invoke", "plain", "parallel"]
    )
    base = {"id": f"m{i}", "context": {"n": 0, "ext": 0}, "maxIterations": 50}
    ext = {"EXT": {"actions": ["extbump"]}}  # internal self-handler
    if k == "rollback_ondone":
        base |= {
            "initial": "a",
            "states": {
                "a": {"on": {"GO": {"target": "b"}, **ext}},
                "b": {
                    "invoke": {"id": "s", "src": "svc", "onDone": {"target": "c"}},
                    "on": dict(ext),
                },
                "c": {
                    "always": {"target": "a", "guard": "g2", "actions": ["bump"]},
                    "on": dict(ext),
                },
            },
        }
    elif k == "always_into_invoke":
        base |= {
            "initial": "a",
            "states": {
                "a": {"on": {"GO": {"target": "b"}, **ext}},
                "b": {
                    "always": {"target": "b2", "guard": "g"},
                    "initial": "b2",
                    "on": dict(ext),
                    "states": {
                        "b2": {
                            "invoke": {
                                "id": "s",
                                "src": "svc",
                                "onDone": {"target": "#m%d.a" % i},
                            }
                        }
                    },
                },
            },
        }
    elif k == "parallel":
        base |= {
            "type": "parallel",
            "on": dict(ext),
            "states": {
                "r0": {
                    "initial": "x",
                    "states": {
                        "x": {"on": {"GO": {"target": "y", "actions": ["bump"]}}},
                        "y": {"on": {"GO": {"target": "x"}}},
                    },
                },
                "r1": {
                    "initial": "p",
                    "states": {
                        "p": {"on": {"GO": {"target": "q"}}},
                        "q": {"on": {"GO": {"target": "p"}}},
                    },
                },
            },
        }
    else:
        base |= {
            "initial": "a",
            "states": {
                "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}, **ext}},
                "b": {"on": {"GO": {"target": "a"}, **ext}},
            },
        }
    return k, base


async def main(minutes):
    rnd = random.Random(777)
    p = psutil.Process()
    its = []
    dr = Drops()
    for i in range(200):
        k, cfg = gen(i, rnd)
        it = Interpreter(create_machine(cfg, logic=L), service_pool_size=4)
        it.use(dr)
        await asyncio.wait_for(it.start(children_timeout=2.0), 15)
        its.append((k, it))
    t_end = time.time() + minutes * 60
    events = snaps = restores = chaos = 0
    ext_sent = 0
    rss0 = p.memory_info().rss // 2**20
    rssmax = rss0
    cpu0 = p.cpu_times().user
    t0 = time.time()
    viol = []
    rss_track = []
    chaos_on = True
    chaos_off_at = t_end - 60  # last minute: chaos OFF, to isolate RSS slope
    rss_at_chaos_off = None
    while time.time() < t_end:
        for k, it in its:
            await it.send("GO")
            events += 1
            # 🚚 external PRIORITY producer, interleaved with the machines'
            #    own self-generated completion chains
            it.send("EXT", priority=True)
            ext_sent += 1
        await asyncio.sleep(0.01)
        if chaos_on and time.time() > chaos_off_at:
            chaos_on = False
            rss_at_chaos_off = p.memory_info().rss // 2**20
        if chaos_on:
            for k, it in rnd.sample(its, 20):
                try:
                    b = it.get_persisted_snapshot()
                    snaps += 1
                    json.dumps(b)
                    restores += 1
                except (SnapshotMidStepError, SnapshotCorruptError):
                    chaos += 1
                except Exception as e:
                    viol.append(f"snap:{type(e).__name__}:{e}"[:120])
        rss = p.memory_info().rss // 2**20
        rssmax = max(rssmax, rss)
        rss_track.append((round(time.time() - t0), rss))
        for k, it in its:
            if it.status != "running":
                viol.append(f"dead:{k}:{it.status}")
    wall = time.time() - t0
    cpu = p.cpu_times().user - cpu0
    await asyncio.sleep(0.5)
    ext_applied = sum((it.context or {}).get("ext", 0) for _, it in its)
    ext_drop = sum(v for k, v in dr.d.items() if k.endswith(":EXT"))
    print(f"soak {minutes} min, ASYNC services, external priority producer:")
    print(
        f"  events={events} ext_sent={ext_sent} EXT_APPLIED={ext_applied} "
        f"EXT_LOST={ext_sent - ext_applied} ext_drop_hook={ext_drop}"
    )
    print(f"  snapshots={snaps} restores={restores} chaos_refused={chaos}")
    print(
        f"  wall={wall:.1f}s cpu={cpu:.1f}s ({100*cpu/wall:.0f}% of one core) "
        f"rss {rss0}->{p.memory_info().rss//2**20}MB max={rssmax}MB"
    )
    if rss_at_chaos_off is not None:
        print(
            f"  RSS at chaos-OFF (t-60s) = {rss_at_chaos_off}MB -> "
            f"end {p.memory_info().rss//2**20}MB  "
            f"(slope with chaos ON vs OFF isolates the snapshot churn)"
        )
    print(f"  drops={dr.d}")
    print(f"  violations={len(viol)} {viol[:4]}")
    json.dump(rss_track, open("out/r15_rss.json", "w"))
    print(f"  rss track -> out/r15_rss.json ({len(rss_track)} samples)")
    for k, it in its:
        await it.stop()


asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 12))
