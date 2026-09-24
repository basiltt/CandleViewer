"""N3 -- new attacks aimed at the round-4 (3ed3099) fixes.

Each attack prints PASS / FAIL and a one-line observation. Exit code = FAILs.
No library source is modified.
"""
from __future__ import annotations
import asyncio, copy, json, logging, os, pickle, random, threading, time, warnings
warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

import xstate_statemachine as X
from xstate_statemachine import (
    Interpreter, MachineLogic, PluginBase, SyncInterpreter, create_machine,
    XStateMachineError,
)

FAILS = []


def rec(name, ok, obs):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {obs}")
    if not ok:
        FAILS.append(name)


def logic(sync=False):
    async def a_ok(i, c, e):
        return {"ok": 1}

    def s_ok(i, c, e):
        return {"ok": 1}

    return MachineLogic(
        actions={"noop": lambda i, c, e, a: None,
                 "bump": lambda i, c, e, a: c.__setitem__("n", c.get("n", 0) + 1)},
        guards={"g_true": lambda c, e: True, "g_false": lambda c, e: False},
        services={"svc": (s_ok if sync else a_ok)},
    )


PING = {"id": "m", "initial": "a", "context": {"n": 0},
        "states": {"a": {"on": {"GO": {"target": "b", "actions": "bump"}}},
                   "b": {"on": {"BACK": {"target": "a", "actions": "bump"}}}}}

# 🧮 Order-independent counter: every event is handled from every state, so a
#    concurrency attack measures DELIVERY, never transition-ordering luck.
COUNTER = {"id": "m", "initial": "a", "context": {"n": 0},
           "states": {"a": {"on": {"GO": {"actions": "bump"},
                                   "BACK": {"actions": "bump"}}}}}


# ---------------------------------------------------------------- A1 snapshot
def a1_snapshot_at_every_quiescent_point(n=2000):
    """Persistence: a snapshot at EVERY quiescent point of a 2k-event run must
    succeed, never raise SnapshotMidStepError, and round-trip stably."""
    it = SyncInterpreter(create_machine(copy.deepcopy(PING), logic=logic(True)))
    it.start()
    midstep = 0
    drift = 0
    other = None
    rng = random.Random(7)
    for i in range(n):
        it.send("GO" if i % 2 == 0 else "BACK")
        try:
            s = it.get_persisted_snapshot()
        except X.SnapshotMidStepError:
            midstep += 1
            continue
        except BaseException as e:
            other = f"{type(e).__name__}: {e}"
            break
        if rng.random() < 0.05:
            blob = json.dumps(s)
            try:
                r = SyncInterpreter.from_snapshot(
                    blob, create_machine(copy.deepcopy(PING), logic=logic(True)))
                s2 = r.get_persisted_snapshot()
                a = {k: v for k, v in s.items() if k != "taken_at"}
                b = {k: v for k, v in s2.items() if k != "taken_at"}
                if a != b:
                    drift += 1
                    if drift == 1:
                        other = "first drift: " + json.dumps(
                            {k: (a.get(k), b.get(k)) for k in set(a) | set(b)
                             if a.get(k) != b.get(k)}, default=str)[:300]
            except BaseException as e:
                other = f"roundtrip {type(e).__name__}: {e}"
                break
    rec("A1 snapshot at every quiescent point (2k events)",
        midstep == 0 and drift == 0 and other is None,
        f"midstep_raises={midstep} roundtrip_drift={drift} other={other}")


# ------------------------------------------------- A2 restart_timers + clock
def a2_restart_timers():
    from xstate_statemachine import SimulatedClock
    cfg = {"id": "m", "initial": "a", "context": {"n": 0},
           "states": {"a": {"after": {1000: {"target": "b", "actions": "bump"}}}, "b": {}}}
    clk = SimulatedClock()
    it = SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=logic(True)), clock=clk)
    it.start()
    snap = it.get_persisted_snapshot()
    obs = []
    clk2 = SimulatedClock()
    r = SyncInterpreter.from_snapshot(
        json.dumps(snap), create_machine(copy.deepcopy(cfg), logic=logic(True)),
        clock=clk2)
    r.start()   # 🔁 the re-arm happens in start(), per the library's own test
    dormant = getattr(r, "has_dormant_timers", "MISSING")
    clk2.increment(5000)
    r.tick()
    fired_without = sorted(r.current_state_ids)
    obs.append(f"no-restart: has_dormant_timers={dormant} after+5s -> {fired_without}")
    ok_a = (dormant is True) and fired_without == ["m.a"]
    clk3 = SimulatedClock()
    r2 = SyncInterpreter.from_snapshot(
        json.dumps(snap), create_machine(copy.deepcopy(cfg), logic=logic(True)),
        clock=clk3, restart_timers=True)
    r2.start()
    d2 = getattr(r2, "has_dormant_timers", "MISSING")
    clk3.increment(5000)
    r2.tick()
    fired_with = sorted(r2.current_state_ids)
    obs.append(f"restart_timers=True: has_dormant_timers={d2} after+5s -> {fired_with}")
    ok_b = (d2 is False) and fired_with == ["m.b"]
    rec("A2 restart_timers= / has_dormant_timers with SimulatedClock",
        ok_a and ok_b, " | ".join(obs))


# ------------------------------------------------- A3 #105 per-task gate
def a3_external_producer_not_charged():
    """#105: an EXTERNAL producer sending during an in-flight step must not be
    charged to maxIterations. 16 tasks x 40 sends on a 1-deep machine."""
    cfg = copy.deepcopy(COUNTER)
    cfg["maxIterations"] = 50

    async def main():
        it = Interpreter(create_machine(cfg, logic=logic(False)))
        dropped = []

        class P(PluginBase):
            def on_event_dropped(self, i, e, reason):
                dropped.append((e.type, reason))

        it.use(P())
        await it.start()

        async def producer(k):
            for i in range(40):
                await it.send("GO" if (k + i) % 2 == 0 else "BACK")

        await asyncio.gather(*(producer(k) for k in range(16)))
        await asyncio.sleep(0.5)
        n = it.context.get("n", 0)
        await it.stop()
        return n, dropped

    n, dropped = asyncio.run(asyncio.wait_for(main(), 60))
    rec("A3 #105 16 concurrent producers not charged to maxIterations(50)",
        not dropped, f"context.n={n}/640 dropped={len(dropped)} sample={dropped[:3]}")


# ------------------------------------------------- A4 #104 BLOCK, 16 producers
def a4_block_policy():
    from xstate_statemachine import OverflowPolicy
    cfg = copy.deepcopy(COUNTER)

    async def main():
        it = Interpreter(create_machine(cfg, logic=logic(False)),
                         overflow_policy=OverflowPolicy.BLOCK, max_queue_size=8)
        dropped = []

        class P(PluginBase):
            def on_event_dropped(self, i, e, reason):
                dropped.append((e.type, reason))

        it.use(P())
        await it.start()

        async def producer(k):
            for i in range(30):
                await it.send("GO" if (k + i) % 2 == 0 else "BACK")

        await asyncio.gather(*(producer(k) for k in range(16)))
        for _ in range(100):
            await asyncio.sleep(0.05)
            if it.context.get("n", 0) >= 480:
                break
        n = it.context.get("n", 0)
        await it.stop()
        return n, dropped

    try:
        n, dropped = asyncio.run(asyncio.wait_for(main(), 90))
    except asyncio.TimeoutError:
        rec("A4 #104 BLOCK under 16 producers", False,
            "TIMED OUT (deadlock / lost wakeup)")
        return
    rec("A4 #104 BLOCK under 16 producers (480 sends, queue=8)",
        n == 480 and not dropped, f"applied={n}/480 dropped={len(dropped)}")


# ------------------------------------------------- A5 determinism 50x
def a5_determinism():
    SCRIPT = ["GO", "BACK"] * 40

    def trace_sync():
        tr = []

        class P(PluginBase):
            def on_transition(self, i, f, t, e):
                tr.append((e.type, tuple(sorted(n.id for n in t))))

        it = SyncInterpreter(create_machine(copy.deepcopy(PING), logic=logic(True)))
        it.use(P())
        it.start()
        for e in SCRIPT:
            it.send(e)
        it.stop()
        return json.dumps(tr)

    async def _a():
        tr = []

        class P(PluginBase):
            def on_transition(self, i, f, t, e):
                tr.append((e.type, tuple(sorted(n.id for n in t))))

        it = Interpreter(create_machine(copy.deepcopy(PING), logic=logic(False)))
        it.use(P())
        await it.start()
        for e in SCRIPT:
            await it.send(e, wait=True)
        await it.stop()
        return json.dumps(tr)

    def trace_async():
        return asyncio.run(_a())

    s = {trace_sync() for _ in range(50)}
    a = {trace_async() for _ in range(50)}
    same = (len(s) == 1 and len(a) == 1 and s == a)
    rec("A5 determinism: 50x byte-identical traces, both engines + parity",
        same, f"distinct sync={len(s)} async={len(a)} cross_engine_equal={s == a}")


# ------------------------------------------------- A6 #116 inline sync service
def a6_inline_sync_service():
    """#116: a plain-sync invoke completes at the same point on both engines."""
    cfg = {"id": "m", "initial": "idle", "context": {"ok": 0, "cancel": 0},
           "states": {
               "idle": {"on": {"GO": "work"}},
               "work": {"invoke": {"id": "i", "src": "svc",
                                   "onDone": {"target": "done", "actions": "bump_ok"}},
                        "on": {"CANCEL": {"target": "idle", "actions": "bump_cancel"}}},
               "done": {"on": {"GO": "work"}}}}

    def L():
        return MachineLogic(
            actions={"bump_ok": lambda i, c, e, a: c.__setitem__("ok", c["ok"] + 1),
                     "bump_cancel": lambda i, c, e, a: c.__setitem__("cancel", c["cancel"] + 1)},
            services={"svc": lambda i, c, e: {"v": 1}})

    it = SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=L()))
    it.start()
    for _ in range(10):
        it.send("GO")
        it.send("CANCEL")
    sync_ctx = dict(it.context)
    it.stop()

    async def _a():
        it2 = Interpreter(create_machine(copy.deepcopy(cfg), logic=L()))
        await it2.start()
        for _ in range(10):
            await it2.send("GO", wait=True)
            await it2.send("CANCEL", wait=True)
        c = dict(it2.context)
        await it2.stop()
        return c

    async_ctx = asyncio.run(asyncio.wait_for(_a(), 60))
    rec("A6 #116 inline sync service: (GO,CANCEL)x10 parity",
        sync_ctx == async_ctx, f"sync={sync_ctx} async={async_ctx}")


# ------------------------------------------------- A7 #108 root target
def a7_root_target():
    bad = [{"id": "m", "initial": "a", "states": {"a": {"on": {"GO": "#m"}}}},
           {"id": "m", "initial": "a", "states": {"a": {"always": "#m"}}},
           {"id": "m", "initial": "a", "states": {"a": {"after": {10: "#m"}}}},
           {"id": "m", "initial": "a", "invoke": {"id": "i", "src": "svc", "onDone": "#m"},
            "states": {"a": {}}}]
    outs = []
    for c in bad:
        try:
            create_machine(copy.deepcopy(c), logic=logic(True))
            outs.append("ACCEPTED")
        except XStateMachineError as e:
            outs.append(type(e).__name__)
        except BaseException as e:
            outs.append("UNTYPED " + type(e).__name__)
    rec("A7 #108 root-target rejected at build (on/always/after/onDone)",
        all(o.endswith("Error") and not o.startswith("UNTYPED") for o in outs),
        str(outs))


# ------------------------------------------------- A8 #109 output / #130 escalate
def a8_output_and_escalate():
    """#109: done.invoke must carry the child's declared `output`, never its
    private context.  #130: `escalate` from an invoked child must reach the
    parent's `onError`.  Both engines."""
    CHILD = {"id": "c", "initial": "w", "context": {"secret": "s3cr3t"},
             "states": {"w": {"always": "d"},
                        "d": {"type": "final", "output": {"result": 42}}}}
    PARENT = {"id": "p", "initial": "w", "context": {"got": None},
              "states": {"w": {"invoke": {"src": "kid", "id": "kid",
                                          "onDone": {"target": "d", "actions": "keep"}}},
                         "d": {}}}

    def PL():
        return MachineLogic(
            services={"kid": create_machine(copy.deepcopy(CHILD))},
            actions={"keep": lambda i, c, e, a: c.__setitem__("got", e.data)})

    s_it = SyncInterpreter(create_machine(copy.deepcopy(PARENT), logic=PL()))
    s_it.start()
    for _ in range(50):
        if s_it.value == "d":
            break
        s_it.tick()
        time.sleep(0.01)
    sync_got = s_it.context["got"]
    s_it.stop()

    async def _a():
        i = await Interpreter(create_machine(copy.deepcopy(PARENT), logic=PL())).start()
        await asyncio.sleep(0.2)
        g = i.context["got"]
        await i.stop()
        return g

    async_got = asyncio.run(asyncio.wait_for(_a(), 30))
    leak = [g for g in (sync_got, async_got)
            if g is not None and "s3cr3t" in json.dumps(g, default=str)]
    ok_out = sync_got == async_got == {"result": 42} and not leak
    rec("A8a #109 done.invoke carries declared output, not child context",
        ok_out, f"sync={sync_got!r} async={async_got!r} secret_leak={bool(leak)}")

    # ---- #130: escalate from an invoked child reaches the parent's onError.
    ECHILD = {"id": "c", "initial": "w",
              "states": {"w": {"always": {"actions": {"type": "escalate",
                                                      "params": {"error": "boom"}}}}}}
    EPARENT = {"id": "p", "initial": "w", "context": {"err": None},
               "states": {"w": {"invoke": {"src": "kid", "id": "kid",
                                           "onError": {"target": "d", "actions": "grab"}}},
                          "d": {}}}

    def EL():
        return MachineLogic(
            services={"kid": create_machine(copy.deepcopy(ECHILD))},
            actions={"grab": lambda i, c, e, a: c.__setitem__(
                "err", type(e).__name__)})

    async def _e():
        i = await Interpreter(create_machine(copy.deepcopy(EPARENT), logic=EL())).start()
        await asyncio.sleep(0.3)
        v, err = i.value, i.context["err"]
        await i.stop()
        return v, err

    try:
        v, err = asyncio.run(asyncio.wait_for(_e(), 30))
        rec("A8b #130 escalate from invoked child reaches parent onError",
            v == "d" and err is not None, f"parent value={v!r} onError event={err!r}")
    except BaseException as e:
        rec("A8b #130 escalate from invoked child reaches parent onError",
            False, f"{type(e).__name__}: {e}")


# ------------------------------------------------- A9 InvalidEventError fuzz
def a9_hostile_event_types(n=1500):
    it = SyncInterpreter(create_machine(copy.deepcopy(PING), logic=logic(True)))
    it.start()
    rng = random.Random(11)
    pool = [None, 123, 1.5, b"GO", [], {}, {"type": None}, {"type": 123},
            {"type": b"x"}, {"type": ""}, {"type": []}, {"type": {"a": 1}},
            object(), True, (), frozenset(), {"no_type": 1}, "", "\x00",
            "GO" * 10000, {"type": "GO", "payload": object()}]
    untyped = []
    for _ in range(n):
        ev = rng.choice(pool)
        try:
            it.send(copy.copy(ev) if isinstance(ev, (dict, list)) else ev)
        except XStateMachineError:
            pass
        except BaseException as e:
            untyped.append(f"{type(ev).__name__}->{type(e).__name__}")
    rec(f"A9 InvalidEventError over {n} hostile event objects",
        not untyped, f"untyped={len(untyped)} kinds={sorted(set(untyped))[:4]}")


# ------------------------------------------------- A10 SnapshotCorruptError 5k
def a10_corrupt_mutations(n=5000):
    m = create_machine(copy.deepcopy(PING), logic=logic(True))
    it = SyncInterpreter(m)
    it.start()
    it.send("GO")
    clean = json.dumps(it.get_persisted_snapshot())
    rng = random.Random(3)
    untyped = {}
    silent = 0
    typed = 0
    for _ in range(n):
        b = list(clean)
        for _ in range(rng.randint(1, 3)):
            i = rng.randrange(len(b))
            op = rng.random()
            if op < .45:
                b[i] = rng.choice('0123456789abcdefXYZ{}[]",:null')
            elif op < .7:
                b[i] = ''
            else:
                b.insert(i, rng.choice('{}[]",:0'))
        blob = ''.join(b)
        try:
            SyncInterpreter.from_snapshot(
                blob, create_machine(copy.deepcopy(PING), logic=logic(True)))
            silent += 1
        except XStateMachineError:
            typed += 1
        except BaseException as e:
            tb = e.__traceback__
            while tb.tb_next:
                tb = tb.tb_next
            k = f"{type(e).__name__}@{os.path.basename(tb.tb_frame.f_code.co_filename)}:{tb.tb_lineno}"
            untyped[k] = untyped.get(k, 0) + 1
    rec(f"A10 SnapshotCorruptError over {n} byte-level mutations",
        not untyped,
        f"typed={typed} accepted={silent} untyped={sum(untyped.values())} "
        f"{dict(list(untyped.items())[:4])}")


# ------------------------------------------------- A11 hook matrix
def a11_hook_matrix():
    """#127 on_plugin_error (async def hook on the sync engine)."""
    obs = {}

    class Bad(PluginBase):
        async def on_transition(self, i, f, t, e):
            pass

    class Watch(PluginBase):
        def on_plugin_error(self, i, plugin, hook, exc):
            obs.setdefault("plugin_error", []).append((hook, type(exc).__name__))

        def on_resolve_error(self, i, *a, **k):
            obs.setdefault("resolve_error", []).append(str(a[:2]))

        def on_event_dropped(self, i, e, reason):
            obs.setdefault("dropped", []).append((e.type, reason))

    it = SyncInterpreter(create_machine(copy.deepcopy(PING), logic=logic(True)))
    it.use(Bad())
    it.use(Watch())
    it.start()
    it.send("GO")
    lpe = getattr(it, "last_plugin_error", "MISSING")
    ok = bool(obs.get("plugin_error")) and lpe not in (None, "MISSING")
    rec("A11 #127 async-def hook reported via on_plugin_error/last_plugin_error",
        ok, f"hooks={ {k: v[:2] for k, v in obs.items()} } last_plugin_error="
            f"{type(lpe).__name__ if lpe not in (None, 'MISSING') else lpe}")


# ------------------------------------------------- A12 redaction
def a12_redaction():
    from xstate_statemachine import LoggingInspector
    import io as _io, logging as _lg
    _lg.disable(_lg.NOTSET)
    buf = _io.StringIO()
    h = _lg.StreamHandler(buf)
    lg = _lg.getLogger("xstate_statemachine")
    lg.addHandler(h)
    lg.setLevel(_lg.DEBUG)
    cfg = copy.deepcopy(PING)
    cfg["context"] = {"n": 0, "password": "hunter2", "api_key": "AK-LIVE-1",
                      "token": "tok_abc", "secret": "s3cr3t",
                      "authorization": "Bearer z", "ssn": "123-45-6789",
                      "card_number": "4111111111111111",
                      "private_key": "-----BEGIN", "client_secret": "cs_1"}
    it = SyncInterpreter(create_machine(cfg, logic=logic(True)))
    it.use(LoggingInspector())
    it.start()
    it.send("GO")
    it.stop()
    lg.removeHandler(h)
    _lg.disable(_lg.CRITICAL)
    text = buf.getvalue()
    leaked = [v for v in ("hunter2", "AK-LIVE-1", "tok_abc", "s3cr3t", "Bearer z",
                          "123-45-6789", "4111111111111111", "-----BEGIN", "cs_1")
              if v in text]
    rec("A12 LoggingInspector redacts sensitive context keys",
        not leaked, f"leaked={leaked} log_bytes={len(text)}")


# ------------------------------------------------- A13 exported provenance API
def a13_exported_api():
    want = ["is_system_event", "system_event", "DoneEvent", "AfterEvent",
            "ENGINE_EVENT_SHAPES", "SnapshotMidStepError", "SnapshotCorruptError",
            "SnapshotSerializationError", "InvalidEventError"]
    missing = [w for w in want if not hasattr(X, w)]
    not_in_all = [w for w in want if w not in getattr(X, "__all__", [])]
    prov = []
    if hasattr(X, "system_event"):
        ev = X.system_event("xstate.probe")
        prov.append(("orig", X.is_system_event(ev)))
        prov.append(("deepcopy", X.is_system_event(copy.deepcopy(ev))))
        try:
            prov.append(("pickle", X.is_system_event(pickle.loads(pickle.dumps(ev)))))
        except Exception as e:
            prov.append(("pickle", f"ERR {type(e).__name__}"))
    ok = not missing and not not_in_all and all(v is True for _, v in prov)
    rec("A13 exported provenance API + marker survives deepcopy/pickle",
        ok, f"missing={missing} not_in___all__={not_in_all} provenance={prov}")


# ------------------------------------------------- A14 non-JSON pending data
def a14_non_json_pending():
    """#131: non-JSON *pending event* data must raise SnapshotSerializationError
    rather than being stringified. Separately probe non-JSON *context*, which
    #131 does not name -- a snapshot that silently drops or stringifies it is a
    persistence-fidelity question in its own right."""
    # (a) pending event data -- the #131 path.
    cfg = {"id": "m", "initial": "a",
           "states": {"a": {"on": {"HOLD": {"target": "a"}}}}}
    it = SyncInterpreter(create_machine(copy.deepcopy(cfg), logic=logic(True)))
    it.start()
    it._event_queue.append(X.Event("PEND", {"blob": object()})
                           if hasattr(X, "Event") else None)
    try:
        it.get_persisted_snapshot()
        a_out, a_ok = "SNAPSHOT SUCCEEDED with non-JSON pending payload", False
    except X.SnapshotSerializationError:
        a_out, a_ok = "typed SnapshotSerializationError", True
    except XStateMachineError as e:
        a_out, a_ok = f"typed {type(e).__name__}", True
    except BaseException as e:
        a_out, a_ok = f"UNTYPED {type(e).__name__}: {e}", False
    rec("A14a #131 non-JSON pending-event data -> SnapshotSerializationError",
        a_ok, a_out)

    # (b) non-JSON context -- round-trip fidelity, not #131.
    it2 = SyncInterpreter(create_machine(copy.deepcopy(PING), logic=logic(True)))
    it2.start()
    sentinel = object()
    it2.context["blob"] = sentinel
    try:
        snap = it2.get_persisted_snapshot()
        blob = snap.get("context", {}).get("blob", "<ABSENT>")
        try:
            json.dumps(snap)
            jsonable = True
        except BaseException:
            jsonable = False
        b_out = (f"snapshot taken; context['blob']={blob!r:.60} "
                 f"json.dumps(snapshot)_ok={jsonable}")
        b_ok = jsonable
    except XStateMachineError as e:
        b_out, b_ok = f"typed {type(e).__name__}", True
    except BaseException as e:
        b_out, b_ok = f"UNTYPED {type(e).__name__}: {e}", False
    rec("A14b non-JSON context: snapshot is either refused or JSON-serialisable",
        b_ok, b_out)


ATTACKS = (a1_snapshot_at_every_quiescent_point, a2_restart_timers,
           a3_external_producer_not_charged, a4_block_policy, a5_determinism,
           a6_inline_sync_service, a7_root_target, a8_output_and_escalate,
           a9_hostile_event_types, a10_corrupt_mutations, a11_hook_matrix,
           a12_redaction, a13_exported_api, a14_non_json_pending)

if __name__ == "__main__":
    import sys
    only = sys.argv[1:]
    for f in ATTACKS:
        if only and not any(o in f.__name__ for o in only):
            continue
        t0 = time.time()
        try:
            f()
        except BaseException as e:
            rec(f.__name__, False, f"HARNESS {type(e).__name__}: {e}")
        print(f"      ({time.time() - t0:.1f}s)")
    print(f"\n==== {len(FAILS)} attack(s) FAILED: {FAILS} ====")
    raise SystemExit(len(FAILS))
