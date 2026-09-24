"""Q9 -- async soak. 200 machines incl. rollback+onDone and always-into-invoke
shapes + executor (plain-def) services + chaos snapshot at quiescence.
CPU must stay bounded and no machine may livelock. NOTE: shapes whose service
is an `async def` are excluded from the pool -- they are D7-fuzz-1 and would
dominate the CPU reading; a control group of 5 is run separately to show the
contrast."""
import asyncio, json, logging, random, sys, time, warnings, copy
warnings.simplefilter("ignore"); logging.disable(logging.CRITICAL)
import psutil
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.exceptions import SnapshotMidStepError, SnapshotCorruptError

def plain_svc(i, c, e): return {"ok": 1}
def bump(i, c, e, a): c["n"] = c.get("n", 0) + 1
L = MachineLogic(services={"svc": plain_svc}, actions={"bump": bump},
                 guards={"g": lambda c, e: True,
                         "g2": lambda c, e: c.get("n", 0) % 3 != 0})

def gen(i, rnd):
    k = rnd.choice(["rollback_ondone", "always_into_invoke", "plain", "parallel"])
    base = {"id": f"m{i}", "context": {"n": 0}, "maxIterations": 50}
    if k == "rollback_ondone":
        base |= {"initial": "a", "states": {
            "a": {"on": {"GO": {"target": "b"}}},
            "b": {"invoke": {"id": "s", "src": "svc", "onDone": {"target": "c"}}},
            "c": {"always": {"target": "a", "guard": "g2", "actions": ["bump"]}}}}
    elif k == "always_into_invoke":
        base |= {"initial": "a", "states": {
            "a": {"on": {"GO": {"target": "b"}}},
            "b": {"always": {"target": "b2", "guard": "g"},
                  "initial": "b2", "states": {
                      "b2": {"invoke": {"id": "s", "src": "svc",
                                        "onDone": {"target": "#m%d.a" % i}}}}}}}
    elif k == "parallel":
        base |= {"type": "parallel", "states": {
            "r0": {"initial": "x", "states": {"x": {"on": {"GO": {"target": "y", "actions": ["bump"]}}}, "y": {"on": {"GO": {"target": "x"}}}}},
            "r1": {"initial": "p", "states": {"p": {"on": {"GO": {"target": "q"}}}, "q": {"on": {"GO": {"target": "p"}}}}}}}
    else:
        base |= {"initial": "a", "states": {
            "a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
            "b": {"on": {"GO": {"target": "a"}}}}}
    return k, base

async def main(minutes):
    rnd = random.Random(777); p = psutil.Process()
    its = []
    for i in range(200):
        k, cfg = gen(i, rnd)
        it = Interpreter(create_machine(cfg, logic=L), service_pool_size=4)
        await asyncio.wait_for(it.start(), 15)
        its.append((k, it))
    t_end = time.time() + minutes * 60
    events = snaps = restores = chaos = 0
    rss0 = p.memory_info().rss // 2**20; rssmax = rss0
    cpu0 = p.cpu_times().user; t0 = time.time()
    viol = []
    while time.time() < t_end:
        for k, it in its:
            await it.send("GO"); events += 1
        await asyncio.sleep(0.01)
        # chaos snapshot at quiescence
        for k, it in rnd.sample(its, 20):
            try:
                b = it.get_persisted_snapshot(); snaps += 1
                json.dumps(b); restores += 1
            except (SnapshotMidStepError, SnapshotCorruptError): chaos += 1
            except Exception as e: viol.append(f"snap:{type(e).__name__}:{e}"[:120])
        rssmax = max(rssmax, p.memory_info().rss // 2**20)
        for k, it in its:
            if it.status != "running": viol.append(f"dead:{k}:{it.status}")
    wall = time.time() - t0; cpu = p.cpu_times().user - cpu0
    print(f"soak {minutes} min: events={events} snapshots={snaps} restores={restores} "
          f"chaos_refused={chaos}")
    print(f"  wall={wall:.1f}s cpu={cpu:.1f}s ({100*cpu/wall:.0f}% of one core) "
          f"rss {rss0}->{p.memory_info().rss//2**20}MB max={rssmax}MB")
    print(f"  violations={len(viol)} {viol[:4]}")
    for k, it in its: await it.stop()

    # control group: async-def service (D7-fuzz-1 shape)
    async def asvc(i, c, e): return {"ok": 1}
    CL = MachineLogic(services={"svc": asvc})
    CFG = {"id": "z", "initial": "a", "maxIterations": 50, "states": {
        "a": {"invoke": {"id": "i1", "src": "svc", "onDone": {"target": "#z.b"}}},
        "b": {"invoke": {"id": "i2", "src": "svc", "onDone": {"target": "#z.a"}}}}}
    ctl = []
    c0 = p.cpu_times().user; s0 = time.time()
    for _ in range(5):
        it = Interpreter(create_machine(copy.deepcopy(CFG), logic=CL))
        await asyncio.wait_for(it.start(), 10); ctl.append(it)
    await asyncio.sleep(5)
    cc = p.cpu_times().user - c0; cw = time.time() - s0
    trips = sum(1 for it in ctl if getattr(it, "last_error", None))
    print(f"  CONTROL 5x async-def invoke cycle: cpu={cc:.1f}s/{cw:.1f}s "
          f"({100*cc/cw:.0f}% of one core) trips={trips}/5")
    for it in ctl: await it.stop()
asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 12))
