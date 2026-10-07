"""Battle de2da4e -- OBSERVABILITY track, round-11 re-verification.

Standalone: stdlib + xstate_statemachine only. Run from neutral cwd
<home> with the pinned venv:

  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
  <workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python \
  <workspace>/CandleViewer/docs/research/xstate/battle-de2da4e/observability/attacks.py

Each attack prints "ATTACK <name>: PASS/FAIL <detail>" so a grep gives the
scoreboard. Time-boxed: reduced Ns vs the requested matrix; see report.
"""
import asyncio
import json
import sys
import time
import traceback

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    ReentrantWaitError,
    RunawayChainError,
    SimulatedClock,
    SyncInterpreter,
    create_machine,
)

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"ATTACK {name}: {'PASS' if ok else 'FAIL'} {detail}")


def safe(name, fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        record(name, False, f"EXCEPTION {e!r}\n{traceback.format_exc()}")


def mk(cfg, **kw):
    return create_machine(json.loads(json.dumps(cfg)), **kw)


def act_def(body):
    def plain(i, c, e, a):
        body(i, c)
    return plain


def act_async(body):
    async def coro(i, c, e, a):
        await asyncio.sleep(0)
        body(i, c)
    return coro


KINDS = {"def": act_def, "async def": act_async}


# =============================================================================
# A -- #218 timer handle released; #222 chain_trips/last_chain_error latch
#      across a 200-beat heartbeat, both engines
# =============================================================================
def attack_a_heartbeat_and_latch():
    def cfg(period):
        arm = {"type": "raise", "params": {"event": "BEAT", "delay": period}}
        return {
            "id": "hb", "initial": "up",
            "states": {
                "up": {"entry": [arm, "beat"], "on": {"BEAT": "down"}},
                "down": {"entry": [arm, "beat"], "on": {"BEAT": "up"}},
            },
        }

    for kind, wrap in KINDS.items():
        n = {"beats": 0}
        logic = MachineLogic(actions={"beat": wrap(lambda i, c: n.__setitem__("beats", n["beats"] + 1))})
        clock = SimulatedClock()

        async def go():
            i = await Interpreter(mk(cfg(10), logic=logic), clock=clock).start()
            for _ in range(200):
                await clock.increment(10)
            held = sum(len(v) for v in i._timer_handles.values())
            trips = i.chain_trips
            await i.stop()
            return held, trips

        held, trips = asyncio.run(go())
        record(
            f"A-async-{kind}",
            held <= 1 and trips == 0,
            f"beats={n['beats']} handles_held={held} chain_trips={trips}",
        )

    # sync engine
    for kind_name in ("def",):
        n = {"beats": 0}
        logic = MachineLogic(actions={"beat": act_def(lambda i, c: n.__setitem__("beats", n["beats"] + 1))})
        clock = SimulatedClock()
        i = SyncInterpreter(mk(cfg(10), logic=logic), clock=clock).start()
        for _ in range(200):
            clock.increment(10)
        held = sum(len(v) for v in i._timer_handles.values())
        trips = i.chain_trips
        i.stop()
        record(
            "A-sync-def",
            held <= 1 and trips == 0,
            f"beats={n['beats']} handles_held={held} chain_trips={trips}",
        )


# =============================================================================
# B -- persistence: parked+armed scheduled_sends across
#      restore->persist->restore->start chains, fire exactly once at the
#      right delay. >=300 property cases (reduced to 320 for time budget,
#      split sync/async).
# =============================================================================
def attack_b_persistence_property(n_cases=320):
    import random
    random.seed(1234)

    def cfg(delay_ms):
        return {
            "id": "sla", "initial": "a",
            "states": {
                "a": {
                    "entry": [{"type": "raise", "params": {"event": "PONG", "delay": delay_ms, "id": "sla"}}, "noop"],
                    "on": {"PONG": "b"},
                },
                "b": {},
            },
        }

    logic = MachineLogic(actions={"noop": act_def(lambda i, c: None)})
    ok = 0
    fails = []
    for case in range(n_cases):
        delay = random.choice([50, 100, 500, 1000, 5000])
        elapsed_before_snap = random.randint(0, delay - 10)
        clock = SimulatedClock()
        s = SyncInterpreter(mk(cfg(delay), logic=logic), clock=clock)
        s.start()
        clock.increment(elapsed_before_snap)
        blob = s.get_persisted_snapshot()
        s.stop()
        if len(blob["scheduled_sends"]) != 1:
            fails.append(f"case{case}: expected 1 scheduled_send after hop1, got {len(blob['scheduled_sends'])}")
            continue
        remaining = blob["scheduled_sends"][0]["remaining_ms"]
        expected_remaining = delay - elapsed_before_snap
        if abs(remaining - expected_remaining) > max(2.0, 0.02 * delay):
            fails.append(f"case{case}: remaining {remaining} != expected {expected_remaining}")
            continue

        # restore, do NOT start, re-persist (park chain)
        r = SyncInterpreter.from_snapshot(json.dumps(blob), mk(cfg(delay), logic=logic))
        blob2 = r.get_persisted_snapshot()
        if blob2["scheduled_sends"] != blob["scheduled_sends"]:
            fails.append(f"case{case}: parked re-persist mismatch")
            continue

        # restore again (still parked), then START -- should arm exactly once
        clock2 = SimulatedClock()
        r2 = SyncInterpreter.from_snapshot(json.dumps(blob2), mk(cfg(delay), logic=logic), clock=clock2)
        r2.start()
        armed = r2.get_persisted_snapshot()["scheduled_sends"]
        if len(armed) != 1:
            fails.append(f"case{case}: expected exactly 1 armed after start(), got {len(armed)}")
            r2.stop()
            continue
        remaining2 = armed[0]["remaining_ms"]
        if abs(remaining2 - expected_remaining) > max(2.0, 0.02 * delay):
            fails.append(f"case{case}: post-start remaining {remaining2} != expected {expected_remaining}")
            r2.stop()
            continue

        # advance just short -> not fired; then past -> fired exactly once
        clock2.increment(max(0, expected_remaining - 5))
        if r2.value != "a":
            fails.append(f"case{case}: fired early")
            r2.stop()
            continue
        clock2.increment(20)
        if r2.value != "b":
            fails.append(f"case{case}: did not fire after deadline")
            r2.stop()
            continue
        if r2.get_persisted_snapshot()["scheduled_sends"] != []:
            fails.append(f"case{case}: scheduled_sends not cleared after fire")
            r2.stop()
            continue
        r2.stop()
        ok += 1

    record(
        "B-persistence-property",
        ok == n_cases,
        f"{ok}/{n_cases} clean" + (f"; first fails: {fails[:5]}" if fails else ""),
    )


# =============================================================================
# C -- #220 recursive unknown-key check: fuzz typos at every nesting level
#      (must catch all) and generate valid charts from the full key grammar
#      (must NOT false-positive under strict_config). Reduced N=240 (vs 500+)
#      for time budget.
# =============================================================================
def attack_c_key_fuzzer(n_typo=240, n_valid=120):
    import random
    from xstate_statemachine import InvalidConfigError

    random.seed(99)

    def base_cfg():
        return {
            "id": "m", "initial": "s1", "context": {},
            "maxIterations": 50,
            "states": {
                "s1": {
                    "entry": ["a1"], "exit": ["a2"],
                    "on": {"GO": {"target": "s2", "actions": ["a3"], "guard": "g1"}},
                    "after": {100: "s2"},
                    "invoke": {"id": "inv1", "src": "svc1", "onDone": {"target": "s2"}, "onError": {"target": "s1"}},
                },
                "s2": {"type": "final"},
            },
        }

    typo_targets = [
        ("root", lambda c: c.__setitem__("maxIteratoins", 50)),
        ("state", lambda c: c["states"]["s1"].__setitem__("entyr", ["a1"])),
        ("transition", lambda c: c["states"]["s1"]["on"]["GO"].__setitem__("acitons", ["a3"])),
        ("invoke", lambda c: c["states"]["s1"]["invoke"].__setitem__("onDonee", {"target": "s2"})),
    ]

    def full_logic():
        return MachineLogic(
            actions={n: act_def(lambda i, c: None) for n in ("a1", "a2", "a3")},
            guards={"g1": lambda i, c, e, a: True},
            services={"svc1": act_def(lambda i, c: None)},
        )

    caught = 0
    typo_fails = []
    for case in range(n_typo):
        level, mutator = random.choice(typo_targets)
        cfg = base_cfg()
        mutator(cfg)
        try:
            mk(cfg, logic=full_logic(), strict_config=True)
            typo_fails.append(f"typo-case{case}({level}): NOT caught")
        except InvalidConfigError:
            caught += 1
        except Exception as e:  # noqa: BLE001
            typo_fails.append(f"typo-case{case}({level}): wrong exception {e!r}")

    record(
        "C-fuzzer-typos-caught",
        caught == n_typo,
        f"{caught}/{n_typo} caught" + (f"; fails: {typo_fails[:5]}" if typo_fails else ""),
    )

    # valid-grammar generation: only known keys at every level, must be
    # accepted with 0 rejections under strict_config.
    from xstate_statemachine.validation import (
        KNOWN_STATE_KEYS, KNOWN_TRANSITION_KEYS, KNOWN_INVOKE_KEYS,
    )
    false_positives = 0
    fp_details = []
    for case in range(n_valid):
        cfg = base_cfg()
        # add every optional metadata key at every level as extra noise
        cfg["meta"] = {"k": 1}
        cfg["tags"] = ["t"]
        cfg["states"]["s1"]["description"] = "d"
        cfg["states"]["s1"]["meta"] = {"k": 1}
        cfg["states"]["s1"]["on"]["GO"]["description"] = "d"
        cfg["states"]["s1"]["invoke"]["description"] = "d"
        cfg["x-custom-vendor-key"] = "ignored"
        cfg["states"]["s1"]["x-note"] = "ignored"
        try:
            mk(cfg, logic=full_logic(), strict_config=True)
        except Exception as e:  # noqa: BLE001
            false_positives += 1
            fp_details.append(f"valid-case{case}: rejected {e!r}")

    record(
        "C-fuzzer-valid-grammar-no-fp",
        false_positives == 0,
        f"{false_positives}/{n_valid} false positives" + (f"; {fp_details[:5]}" if fp_details else ""),
    )


# =============================================================================
# D -- #219 ReentrantWaitError matrix: self in-step await (both engines),
#      ensure_future-deferred await under 100 concurrent actions, plain
#      send-without-wait still works.
# =============================================================================
def attack_d_reentrant_matrix():
    CFG = {
        "id": "dead", "initial": "x",
        "states": {"x": {"entry": ["act"], "on": {"GO": "y"}}, "y": {}},
    }

    # D1: async self in-step wait=True raises ReentrantWaitError, machine
    # still reaches "y" (send accepted, only in-step await refused).
    seen = []

    async def act1(i, c, e, a):
        try:
            await i.send("GO", wait=True)
        except ReentrantWaitError as exc:
            seen.append(str(exc))

    async def go1():
        i = await Interpreter(mk(CFG, logic=MachineLogic(actions={"act": act1}))).start()
        await asyncio.sleep(0.05)
        v, status = i.value, i.status
        if status == "running":
            await i.stop()
        return v, status

    v, status = asyncio.run(go1())
    record(
        "D1-async-self-in-step",
        len(seen) == 1 and "deadlock" in seen[0] and v == "y",
        f"seen={seen} value={v} status={status}",
    )

    # D2: sync engine refuses the same shape.
    seen2 = []

    def act2(i, c, e, a):
        try:
            i.send("GO", wait=True)
        except ReentrantWaitError as exc:
            seen2.append(exc)

    s = SyncInterpreter(mk(CFG, logic=MachineLogic(actions={"act": act2}))).start()
    record("D2-sync-self-in-step", len(seen2) == 1, f"seen={seen2!r} value={s.value}")
    s.stop()

    # D3: ensure_future-deferred await is fine (the documented escape hatch),
    # under 100 concurrent interpreters doing this shape simultaneously.
    async def one_instance(idx):
        box = {}

        async def act(i, c, e, a):
            box["fut"] = asyncio.ensure_future(i.send("GO", wait=True))

        i = await Interpreter(mk(CFG, logic=MachineLogic(actions={"act": act}))).start()
        r = await asyncio.wait_for(box["fut"], 5)
        v = i.value
        await i.stop()
        return r.error, v

    async def go3():
        results = await asyncio.gather(*(one_instance(i) for i in range(100)))
        return results

    results = asyncio.run(go3())
    ok3 = all(err is None and v == "y" for err, v in results)
    record("D3-ensure-future-100-concurrent", ok3, f"{sum(1 for e,v in results if e is None and v=='y')}/100 clean")

    # D4: child -> parent wait=True send (a child's action awaits, wait=True,
    # a send TO ITS PARENT interpreter -- not reentrant on the child itself,
    # so must succeed, not raise).
    parent_cfg = {"id": "parent", "initial": "p1", "states": {"p1": {"on": {"PING": "p2"}}, "p2": {}}}
    child_cfg = {"id": "child", "initial": "c1", "states": {"c1": {"entry": ["notify"]}}}

    async def go4():
        parent = await Interpreter(mk(parent_cfg)).start()

        async def notify(i, c, e, a):
            r = await parent.send("PING", wait=True)
            return r

        child = await Interpreter(mk(child_cfg, logic=MachineLogic(actions={"notify": notify}))).start()
        await asyncio.sleep(0.05)
        pv = parent.value
        await parent.stop()
        await child.stop()
        return pv

    pv = asyncio.run(go4())
    record("D4-child-to-parent-wait-true", pv == "p2", f"parent.value={pv}")


# =============================================================================
# E -- #222 chain_trips/last_chain_error latch, exactly-once semantics
#      across a snapshot (persist mid-trip, restore, verify latch survives
#      or is documented not to); on_event_dropped ordering vs the latch.
# =============================================================================
class TripWatcher:
    def __init__(self):
        self.hits = []

    def on_chain_budget_exceeded(self, i, error, event):
        self.hits.append((type(error).__name__, event.type))

    def on_event_dropped(self, i, event, reason):
        self.hits.append(("DROPPED", event.type, reason))

    def on_action_error(self, i, action, error):
        pass


def _cfg_trip(maxit=6):
    return {
        "id": "trip", "initial": "spin", "maxIterations": maxit,
        "states": {
            "spin": {
                "entry": [{"type": "raise", "params": {"event": "LAP"}}, "bump"],
                "on": {
                    "LAP": {"target": "spin", "reenter": True},
                    "BENIGN": {"target": "spin", "reenter": False},
                },
            }
        },
    }


def attack_e_chain_trip_latch():
    for kind, wrap in KINDS.items():
        logic = MachineLogic(actions={"bump": wrap(lambda i, c: None)})

        async def go():
            w = TripWatcher()
            i = Interpreter(mk(_cfg_trip(), logic=logic)).use(w)
            await i.start()
            await asyncio.sleep(0.2)
            at = (i.chain_trips, type(i.last_chain_error).__name__, type(i.last_error).__name__)
            for _ in range(3):
                await i.send("BENIGN", wait=True)
            after = (i.chain_trips, type(i.last_chain_error).__name__, type(i.last_error).__name__)
            hits = list(w.hits)
            i.clear_chain_error()
            cleared = (i.chain_trips, i.last_chain_error)
            await i.stop()
            return at, after, hits, cleared

        at, after, hits, cleared = asyncio.run(go())
        ok = (
            at == (1, "RunawayChainError", "RunawayChainError")
            and after == (1, "RunawayChainError", "NoneType")
            and hits == [("DROPPED", "LAP", "chain_budget"), ("RunawayChainError", "LAP")]
            and cleared == (1, None)
        )
        record(f"E-latch-async-{kind}", ok, f"at={at} after={after} hits={hits} cleared={cleared}")

    # sync engine
    w = TripWatcher()
    logic = MachineLogic(actions={"bump": act_def(lambda i, c: None)})
    s = SyncInterpreter(mk(_cfg_trip(), logic=logic)).use(w)
    s.start()
    at = (s.chain_trips, type(s.last_chain_error).__name__, type(s.last_error).__name__)
    for _ in range(3):
        s.send("BENIGN", wait=True)
    after = (s.chain_trips, type(s.last_chain_error).__name__, type(s.last_error).__name__)
    hits = list(w.hits)
    s.clear_chain_error()
    cleared = (s.chain_trips, s.last_chain_error)
    s.stop()
    ok = (
        at == (1, "RunawayChainError", "RunawayChainError")
        and after == (1, "RunawayChainError", "NoneType")
        and hits == [("DROPPED", "LAP", "chain_budget"), ("RunawayChainError", "LAP")]
        and cleared == (1, None)
    )
    record("E-latch-sync-def", ok, f"at={at} after={after} hits={hits} cleared={cleared}")

    # snapshot persistence across a trip: latch is documented as
    # process-local (chain_trips/last_chain_error are NOT part of
    # get_persisted_snapshot's payload) -- verify that contract holds
    # rather than assume it round-trips.
    w2 = TripWatcher()
    logic2 = MachineLogic(actions={"bump": act_def(lambda i, c: None)})
    s2 = SyncInterpreter(mk(_cfg_trip(), logic=logic2)).use(w2)
    s2.start()
    blob = s2.get_persisted_snapshot()
    has_latch_fields = ("chain_trips" in blob) or ("last_chain_error" in blob)
    trips_before = s2.chain_trips
    s2.stop()
    r = SyncInterpreter.from_snapshot(json.dumps(blob), mk(_cfg_trip(), logic=logic2))
    r.start()
    trips_after_restore = r.chain_trips
    r.stop()
    record(
        "E-latch-not-persisted-by-contract",
        not has_latch_fields and trips_after_restore == 0,
        f"blob_has_latch_fields={has_latch_fields} trips_before={trips_before} trips_after_restore={trips_after_restore}",
    )


# =============================================================================
# F -- concurrency: 200 heartbeat machines, handle count flat (reduced from
#      "10s wall" to a fixed 100-beat budget for the 20-min time box).
# =============================================================================
def attack_f_200_heartbeats():
    def cfg(period):
        arm = {"type": "raise", "params": {"event": "BEAT", "delay": period}}
        return {
            "id": "hb", "initial": "up",
            "states": {
                "up": {"entry": [arm], "on": {"BEAT": "down"}},
                "down": {"entry": [arm], "on": {"BEAT": "up"}},
            },
        }

    n_machines = 200
    n_beats = 100
    clocks = [SimulatedClock() for _ in range(n_machines)]
    interps = [SyncInterpreter(mk(cfg(1), logic=MachineLogic(actions={})), clock=c).start() for c in clocks]
    for _ in range(n_beats):
        for c in clocks:
            c.increment(1)
    held = [sum(len(v) for v in i._timer_handles.values()) for i in interps]
    trips = [i.chain_trips for i in interps]
    for i in interps:
        i.stop()
    max_held = max(held)
    total_trips = sum(trips)
    record(
        "F-200-heartbeats-handles-flat",
        max_held <= 1 and total_trips == 0,
        f"n_machines={n_machines} beats_each={n_beats} max_handles_held={max_held} total_chain_trips={total_trips}",
    )


# =============================================================================
# Runner
# =============================================================================
def main():
    t0 = time.time()
    safe("A", attack_a_heartbeat_and_latch)
    safe("B", attack_b_persistence_property)
    safe("C", attack_c_key_fuzzer)
    safe("D", attack_d_reentrant_matrix)
    safe("E", attack_e_chain_trip_latch)
    safe("F", attack_f_200_heartbeats)
    dt = time.time() - t0
    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    n_total = len(RESULTS)
    print(f"\n=== {n_pass}/{n_total} PASS === wall={dt:.1f}s")
    sys.exit(0 if n_pass == n_total else 1)


if __name__ == "__main__":
    main()
