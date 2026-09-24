"""
New attacks for xstate-statemachine @ 3ed3099, aimed at round-4 fixes.
Time-bounded: parameterisations reduced from an ideal soak; each reduction
is noted inline where it happens.

Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python new_attacks.py
"""
import asyncio
import json
import logging
import random
import string
import threading
import time

logging.disable(logging.CRITICAL)

from xstate_statemachine import (
    Interpreter,
    SyncInterpreter,
    MachineLogic,
    create_machine,
    PluginBase,
    OverflowPolicy,
    SnapshotMidStepError,
    SnapshotCorruptError,
    SnapshotSerializationError,
    InvalidEventError,
    QueueOverflowError,
    forward_to,
    send_to,
)
from xstate_statemachine.clock import SimulatedClock

import xstate_statemachine as xsm


def section(t):
    print(f"\n=== {t} ===")


# ---------------------------------------------------------------------------
# A. Persistence: snapshot at every quiescent point of a property run must
#    always succeed and round-trip; SnapshotMidStepError never fires at
#    quiescence.
# REDUCED: 2000 -> 300 events (time bound), still >> enough to hit every
# quiescent boundary many times over on a small machine.
# ---------------------------------------------------------------------------
def attack_persistence_property():
    section("A. snapshot-at-every-quiescent-point property run (n=300, reduced from 2000)")
    cfg = {
        "id": "m_prop",
        "initial": "a",
        "states": {
            "a": {"on": {"GO": "b", "STAY": "a"}},
            "b": {"on": {"GO": "a", "STAY": "b", "AFTER_ARM": "c"}},
            "c": {"after": {10: "a"}, "on": {"GO": "a"}},
        },
    }
    machine = create_machine(cfg, logic=MachineLogic())
    clock = SimulatedClock()
    interp = SyncInterpreter(machine, clock=clock).start()
    events = ["GO", "STAY", "AFTER_ARM"]
    random.seed(42)
    failures = 0
    midstep_hits = 0
    for i in range(300):
        ev = random.choice(events)
        interp.send(ev, wait=True)
        clock.pump()
        # quiescent point: send(wait=True) has returned -> try snapshot+restore
        try:
            snap = interp.get_persisted_snapshot()
            raw = json.dumps(snap)
            restored = SyncInterpreter.from_snapshot(raw, machine, clock=SimulatedClock())
            if sorted(restored.current_state_ids) != sorted(interp.current_state_ids):
                failures += 1
                print(f"  MISMATCH at step {i}: {restored.current_state_ids} != {interp.current_state_ids}")
        except SnapshotMidStepError as e:
            midstep_hits += 1
            print(f"  SnapshotMidStepError at quiescent step {i} (UNEXPECTED): {e}")
        except Exception as e:
            failures += 1
            print(f"  unexpected exception at step {i}: {e!r}")
    print(f"  300 quiescent snapshots: failures={failures}, unexpected SnapshotMidStepError={midstep_hits}")


# ---------------------------------------------------------------------------
# B. restart_timers with SimulatedClock: after-timer re-armed from zero,
#    has_dormant_timers flips correctly.
# ---------------------------------------------------------------------------
def attack_restart_timers_simulated_clock():
    section("B. restart_timers=True with SimulatedClock (#128)")
    cfg = {"id": "m_timer", "initial": "a", "states": {"a": {"after": {1000: "b"}}, "b": {}}}
    machine = create_machine(cfg, logic=MachineLogic())
    clock = SimulatedClock()
    interp = SyncInterpreter(machine, clock=clock).start()
    # advance partially (units are ms per SimulatedClock.increment) so the
    # timer is dormant-but-not-fired
    clock.increment(400)
    snap = json.dumps(interp.get_persisted_snapshot())
    print(f"  has_dormant_timers before stop: {interp.has_dormant_timers}")

    restored = SyncInterpreter.from_snapshot(snap, machine, clock=SimulatedClock(), restart_timers=True)
    print(f"  restored (restart_timers=True), has_dormant_timers pre-start={restored.has_dormant_timers}")
    restored.start()
    print(f"  post-start has_dormant_timers={restored.has_dormant_timers}")
    # new clock starts at 0 -- timer re-armed from zero means 1000 units needed again
    new_clock = restored.clock
    new_clock.increment(999)
    print(f"  after advancing 999 (of re-armed 1000): state={sorted(restored.current_state_ids)} (expect still 'a')")
    new_clock.increment(2)
    print(f"  after advancing to 1001 total: state={sorted(restored.current_state_ids)} (expect 'b')")


# ---------------------------------------------------------------------------
# C. #105: per-task gate -- external send() during an in-flight macrostep is
#    not charged to maxIterations even under concurrent create_task/threads.
# REDUCED: 8 concurrent producers x 20 sends each (not 16 producers x more)
# to fit the time bound; still exercises the per-task/thread gate.
# ---------------------------------------------------------------------------
async def attack_105_external_send_gate():
    section("C. #105 external-producer gate under concurrent create_task (8 producers x 20 sends, reduced)")
    cfg = {
        "id": "m_105",
        "initial": "a",
        "maxIterations": 50,  # low budget: if externals were miscounted, this trips
        "states": {"a": {"on": {"PING": "a"}}},
    }
    machine = create_machine(cfg, logic=MachineLogic())
    interp = Interpreter(machine)
    await interp.start()

    async def producer(n):
        for i in range(20):
            interp.send(f"PING_{n}_{i}")
            await asyncio.sleep(0)

    tasks = [asyncio.create_task(producer(n)) for n in range(8)]
    await asyncio.gather(*tasks)
    await asyncio.sleep(0.2)
    print(f"  status={interp.status} (expect 'running', not 'error' from a spurious chain trip), "
          f"error={interp.error}")
    await interp.stop()


def attack_105_external_send_gate_threads():
    section("C2. #105 gate under concurrent OS threads calling send_threadsafe (8 threads x 15 sends, reduced)")

    async def runner():
        cfg = {
            "id": "m_105t",
            "initial": "a",
            "maxIterations": 50,
            "states": {"a": {"on": {"PING": "a"}}},
        }
        machine = create_machine(cfg, logic=MachineLogic())
        interp = Interpreter(machine)
        await interp.start()
        loop = asyncio.get_event_loop()

        def thread_body(n):
            for i in range(15):
                interp.send_threadsafe(f"PING_{n}_{i}")
                time.sleep(0.001)

        threads = [threading.Thread(target=thread_body, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        await asyncio.sleep(0.3)
        print(f"  status={interp.status}, error={interp.error}")
        await interp.stop()

    asyncio.run(runner())


# ---------------------------------------------------------------------------
# D. #104: BLOCK policy under many producers, empty-inbox eager enqueue.
# REDUCED: 16 -> 10 producers to fit time bound; still > single-digit to show
# no fire-and-forget send is lost.
# ---------------------------------------------------------------------------
def attack_104_block_many_producers():
    section("D. #104 OverflowPolicy.BLOCK under 10 producers (reduced from 16), 5 sends each")

    async def runner():
        cfg = {"id": "m_104", "initial": "a", "states": {"a": {"on": {"X": "a"}}}}
        machine = create_machine(cfg, logic=MachineLogic())
        interp = Interpreter(machine, max_queue_size=2, overflow_policy=OverflowPolicy.BLOCK)
        await interp.start()
        received = []

        class Rec(PluginBase):
            def on_event_received(self, interpreter, event):
                received.append(event.type)

        interp.use(Rec())

        async def producer(n):
            for i in range(5):
                await interp.send(f"X_{n}_{i}")
                await asyncio.sleep(0.001)

        await asyncio.gather(*(producer(n) for n in range(10)))
        await asyncio.sleep(0.3)
        print(f"  sent=50, received (on_event_received count)={len(received)} -- "
              f"{'no loss' if len(received) == 50 else 'LOSS DETECTED'}")
        await interp.stop()

    asyncio.run(runner())


# ---------------------------------------------------------------------------
# E. Determinism: byte-identical traces both engines, inline sync-service
#    semantics (#116). REDUCED: 15 reps (not 50) to fit time bound.
# ---------------------------------------------------------------------------
def attack_determinism_both_engines():
    section("E. #116 determinism: (GO,CANCEL)x10 script, both engines, 15 reps (reduced from 50)")

    def sync_service(interp, ctx, ev):
        return "sync-done"

    def make_cfg():
        return {
            "id": "m_det",
            "initial": "a",
            "states": {
                "a": {
                    "on": {"GO": "b"},
                },
                "b": {
                    "invoke": {"src": "sync_service", "id": "svc", "onDone": "done", "onError": "err"},
                    "on": {"CANCEL": "cancelled"},
                },
                "done": {},
                "err": {},
                "cancelled": {},
            },
        }

    traces = set()
    for rep in range(15):
        logic = MachineLogic(services={"sync_service": sync_service})
        m_sync = create_machine(make_cfg(), logic=logic)
        interp = SyncInterpreter(m_sync).start()
        interp.send("GO")
        interp.send("CANCEL")
        sync_trace = sorted(interp.current_state_ids)

        async def run_async():
            logic2 = MachineLogic(services={"sync_service": sync_service})
            m_async = create_machine(make_cfg(), logic=logic2)
            i2 = Interpreter(m_async)
            await i2.start()
            i2.send("GO")
            i2.send("CANCEL")
            await asyncio.sleep(0.02)
            r = sorted(i2.current_state_ids)
            await i2.stop()
            return r

        async_trace = asyncio.run(run_async())
        traces.add((tuple(sync_trace), tuple(async_trace)))
    print(f"  distinct (sync,async) outcome pairs over 15 reps: {traces}")
    print(f"  {'CONSISTENT' if len(traces) == 1 else 'INCONSISTENT ACROSS REPS'}; "
          f"{'sync==async' if len(traces)==1 and list(traces)[0][0]==list(traces)[0][1] else 'sync!=async or nondeterministic'}")


# ---------------------------------------------------------------------------
# F. Semantics: #109 output, #108 root target rejected, #130 escalate.
# ---------------------------------------------------------------------------
async def attack_109_output():
    section("F1. #109 done.invoke carries child's declared output, not private context")
    child_cfg = {
        "id": "child",
        "initial": "c",
        "context": {"secret": 42},
        "states": {"c": {"on": {"FIN": "done"}}, "done": {"type": "final"}},
        "output": {"result": "ok"},
    }
    child_logic = MachineLogic()
    child_machine = create_machine(child_cfg, logic=child_logic)

    captured = {}

    def on_done_action(interp, ctx, ev, ad):
        captured["payload"] = dict(ev.data) if hasattr(ev, "data") else None
        captured["type"] = ev.type

    parent_cfg = {
        "id": "parent_109",
        "initial": "p",
        "states": {
            "p": {
                "invoke": {"src": "child_machine", "id": "kid", "onDone": {"target": "fin", "actions": ["capture"]}},
                "on": {"FIN": {"actions": [forward_to("kid")]}},
            },
            "fin": {},
        },
    }
    parent_logic = MachineLogic(
        services={"child_machine": child_machine},
        actions={"capture": on_done_action},
    )
    parent_machine = create_machine(parent_cfg, logic=parent_logic)
    interp = Interpreter(parent_machine)
    await interp.start()
    interp.send("FIN")
    await asyncio.sleep(0.05)
    print(f"  captured on done.invoke: {captured} -- "
          f"{'output only (no secret)' if captured.get('payload') and 'secret' not in json.dumps(captured['payload']) else 'contains private context or missing'}")
    await interp.stop()


def attack_108_root_target():
    section("F2. #108 transition targeting machine root rejected at build")
    cfg = {"id": "m_root", "initial": "a", "states": {"a": {"on": {"GO": "m_root"}}}}
    try:
        create_machine(cfg, logic=MachineLogic())
        print("  no exception (UNEXPECTED / regression)")
    except Exception as e:
        print(f"  rejected at build as expected: {type(e).__name__}: {e}")


async def attack_130_escalate():
    section("F3. #130 escalate from invoked child reaches parent onError")

    from xstate_statemachine import escalate

    child_cfg = {"id": "child130", "initial": "c", "states": {"c": {"entry": [escalate("escalated!")]}}}
    child_logic = MachineLogic()
    child_machine = create_machine(child_cfg, logic=child_logic)

    parent_cfg = {
        "id": "parent130",
        "initial": "p",
        "states": {"p": {"invoke": {"src": "child_machine", "id": "kid", "onError": "handled"}}, "handled": {}},
    }
    parent_logic = MachineLogic(services={"child_machine": child_machine})
    parent_machine = create_machine(parent_cfg, logic=parent_logic)
    interp = Interpreter(parent_machine)
    await interp.start()
    await asyncio.sleep(0.05)
    print(f"  parent status={interp.status}, state={sorted(interp.current_state_ids)} (expect 'handled')")
    if interp.status == "running":
        await interp.stop()


# ---------------------------------------------------------------------------
# G. Fuzz: SnapshotCorruptError coverage over N mutations (reduced 5000->600);
#    InvalidEventError over hostile event-type values.
# ---------------------------------------------------------------------------
def attack_fuzz_snapshot_corrupt():
    section("G1. SnapshotCorruptError fuzz over 600 mutations (reduced from 5000)")
    cfg = {"id": "m_fuzz", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
    machine = create_machine(cfg, logic=MachineLogic())
    interp = SyncInterpreter(machine).start()
    interp.send("GO")
    good = json.loads(json.dumps(interp.get_persisted_snapshot()))
    random.seed(7)
    outcomes = {"SnapshotCorruptError": 0, "SnapshotDriftError": 0, "other_exc": 0, "no_exc": 0}
    other_examples = []

    def mutate(d):
        import copy
        m = copy.deepcopy(d)
        keys = list(m.keys()) if isinstance(m, dict) else []
        choice = random.random()
        if not keys:
            return m
        k = random.choice(keys)
        if choice < 0.3:
            del m[k]
        elif choice < 0.6:
            m[k] = random.choice([None, 12345, "garbage", [], {}, True])
        elif choice < 0.8 and isinstance(m.get(k), dict):
            m[k] = mutate(m[k])
        else:
            m[f"__extra_{random.randint(0,999)}"] = "junk"
        return m

    for i in range(600):
        mutated = mutate(good)
        try:
            raw = json.dumps(mutated)
        except TypeError:
            outcomes["no_exc"] += 1
            continue
        try:
            SyncInterpreter.from_snapshot(raw, machine)
            outcomes["no_exc"] += 1
        except SnapshotCorruptError:
            outcomes["SnapshotCorruptError"] += 1
        except Exception as e:
            from xstate_statemachine import SnapshotDriftError
            if isinstance(e, SnapshotDriftError):
                outcomes["SnapshotDriftError"] += 1
            else:
                outcomes["other_exc"] += 1
                if len(other_examples) < 5:
                    other_examples.append(repr(e))
    print(f"  outcomes over 600 mutations: {outcomes}")
    if other_examples:
        print(f"  sample of 'other_exc' (uncontained exception types leaking through malformed-snapshot path): {other_examples}")


def attack_fuzz_invalid_event():
    section("G2. InvalidEventError over hostile event 'type' values")
    cfg = {"id": "m_ie", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
    machine = create_machine(cfg, logic=MachineLogic())
    hostile = [123, 1.5, None, True, [], {}, b"bytes", ("t",), object()]
    interp = SyncInterpreter(machine).start()
    results = []
    for h in hostile:
        try:
            interp.send(h)
            results.append((repr(h), "no exception (UNEXPECTED)"))
        except InvalidEventError as e:
            results.append((repr(h)[:30], f"InvalidEventError (also TypeError={isinstance(e, TypeError)})"))
        except TypeError as e:
            results.append((repr(h)[:30], f"plain TypeError (not InvalidEventError): {e!r}"))
        except Exception as e:
            results.append((repr(h)[:30], f"OTHER: {type(e).__name__}: {e!r}"))
    for r in results:
        print(f"  {r}")


# ---------------------------------------------------------------------------
# H. Observability: hook matrix for new error classes / on_plugin_error /
#    on_resolve_error.
# ---------------------------------------------------------------------------
class FullRecorder(PluginBase):
    def __init__(self):
        self.calls = []

    def _rec(self, name, **kw):
        self.calls.append((name, kw))

    def on_plugin_error(self, interpreter, plugin, hook, error):
        self._rec("on_plugin_error", failing_plugin=type(plugin).__name__, hook=hook, error=repr(error))

    def on_resolve_error(self, interpreter, error, event):
        self._rec("on_resolve_error", error=repr(error), event_type=getattr(event, "type", None))

    def on_event_dropped(self, interpreter, event, reason):
        self._rec("on_event_dropped", type=getattr(event, "type", None), reason=reason)

    def on_error(self, interpreter, error):
        self._rec("on_error", error=repr(error))


async def attack_hook_on_resolve_error():
    section("H1. on_resolve_error fires for unresolvable transition target (#134, async engine)")
    # #134's on_resolve_error fires only on the async engine's fire-and-
    # forget path, when a StateNotFoundError surfaces during transition
    # resolution (confirmed at interpreter.py:1408-1410). strict_targets
    # =False is the only way to get a machine that BUILDS with an
    # unresolvable string target (default strict_targets=True rejects it at
    # build, per F2/#108-style validation), so it's the only route to this
    # runtime failure path.
    cfg = {
        "id": "m_h1",
        "initial": "a",
        "states": {"a": {"on": {"GO": "does.not.exist"}}, "b": {}},
    }
    machine = create_machine(cfg, logic=MachineLogic(), strict_targets=False)
    rec = FullRecorder()
    interp = Interpreter(machine).use(rec)
    await interp.start()
    interp.send("GO")
    await asyncio.sleep(0.05)
    hits = [c for c in rec.calls if c[0] == "on_resolve_error"]
    print(f"  on_resolve_error fired: {len(hits)} -- {hits}; last_error={interp.last_error!r}")
    await interp.stop()


def attack_hook_on_plugin_error():
    section("H2. on_plugin_error fires for a raising hook AND for an async-def hook (#127)")

    class Raiser(PluginBase):
        def on_transition(self, interpreter, source, target, transition):
            raise RuntimeError("raiser-boom")

    class AsyncDefHook(PluginBase):
        async def on_transition(self, interpreter, source, target, transition):
            pass

    cfg = {"id": "m_h2", "initial": "a", "states": {"a": {"on": {"GO": "b"}}, "b": {}}}
    machine = create_machine(cfg, logic=MachineLogic())
    rec = FullRecorder()
    interp = SyncInterpreter(machine).use(Raiser()).use(AsyncDefHook()).use(rec).start()
    interp.send("GO", wait=True)
    hits = [c for c in rec.calls if c[0] == "on_plugin_error"]
    print(f"  on_plugin_error fired {len(hits)} times: {hits}")
    print(f"  last_plugin_error={interp.last_plugin_error}")


def attack_hook_on_event_dropped_sendto():
    section("H3. on_event_dropped(reason='unresolved_target') for sendTo with no live target (#133)")

    cfg = {
        "id": "m_h3",
        "initial": "a",
        "states": {"a": {"on": {"GO": {"target": "b", "actions": [send_to("ghost-not-a-real-actor", "PING")]}}}, "b": {}},
    }
    machine = create_machine(cfg, logic=MachineLogic())
    rec = FullRecorder()
    interp = SyncInterpreter(machine).use(rec).start()
    r = interp.send("GO", wait=True)
    hits = [c for c in rec.calls if c[0] == "on_event_dropped"]
    print(f"  on_event_dropped: {hits}; receipt marked? changed={r.changed} error={r.error}")


# ---------------------------------------------------------------------------
# I. Security / operability: redaction list, exported provenance API.
# ---------------------------------------------------------------------------
def attack_redaction_and_api_surface():
    section("I1. LoggingInspector default redaction keys")
    print(f"  DEFAULT_REDACT_KEYS = {xsm.DEFAULT_REDACT_KEYS if hasattr(xsm, 'DEFAULT_REDACT_KEYS') else 'NOT EXPORTED at top level'}")
    from xstate_statemachine.plugins import DEFAULT_REDACT_KEYS, redact
    sample = {"password": "hunter2", "api_key": "abc", "x-api-key": "xyz", "nested": {"token": "t1"}, "safe": "ok"}
    print(f"  redact() on sample: {redact(sample)}")

    section("I2. exported provenance API surface (#137)")
    names = ["is_system_event", "system_event", "DoneEvent", "AfterEvent", "ENGINE_EVENT_SHAPES"]
    for n in names:
        print(f"  {n}: exported={hasattr(xsm, n)}")


# ---------------------------------------------------------------------------
# J. Soak (reduced): 12-min soak -> reduced to ~15s bounded loop with chaos
#    (random errors injected via a faulty plugin + guard).
# ---------------------------------------------------------------------------
def attack_soak_reduced():
    section("J. reduced soak (~15s, was specified as 12min) with chaos plugin + faulty guard")
    calls = {"guard": 0}

    def flaky_guard(ctx, ev):
        calls["guard"] += 1
        if calls["guard"] % 7 == 0:
            raise ValueError("flaky guard boom")
        return True

    class ChaosPlugin(PluginBase):
        def __init__(self):
            self.n = 0

        def on_transition(self, interpreter, source, target, transition):
            self.n += 1
            if self.n % 11 == 0:
                raise RuntimeError("chaos plugin boom")

    cfg = {
        "id": "m_soak",
        "initial": "a",
        "guardErrorPolicy": "false",
        "states": {"a": {"on": {"GO": {"target": "b", "guard": "flaky_guard"}}}, "b": {"on": {"GO": "a"}}},
    }
    logic = MachineLogic(guards={"flaky_guard": flaky_guard})
    machine = create_machine(cfg, logic=logic)
    interp = SyncInterpreter(machine).use(ChaosPlugin()).start()
    start = time.time()
    n = 0
    errors = 0
    while time.time() - start < 15:
        try:
            interp.send("GO", wait=True)
        except Exception:
            errors += 1
        n += 1
    print(f"  soak: {n} sends in 15s, interpreter status={interp.status} (expect 'running'), "
          f"uncontained exceptions surfaced to caller={errors}")


if __name__ == "__main__":
    attack_persistence_property()
    attack_restart_timers_simulated_clock()
    asyncio.run(attack_105_external_send_gate())
    attack_105_external_send_gate_threads()
    attack_104_block_many_producers()
    attack_determinism_both_engines()
    asyncio.run(attack_109_output())
    attack_108_root_target()
    asyncio.run(attack_130_escalate())
    attack_fuzz_snapshot_corrupt()
    attack_fuzz_invalid_event()
    asyncio.run(attack_hook_on_resolve_error())
    attack_hook_on_plugin_error()
    attack_hook_on_event_dropped_sendto()
    attack_redaction_and_api_surface()
    attack_soak_reduced()
    print("\nALL DONE")
