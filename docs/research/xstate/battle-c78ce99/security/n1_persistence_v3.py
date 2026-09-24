"""STANDALONE: v3 snapshot layout attacks (#213/#214).

Sections:
  A  v3 round-trip property, >=300 random machines with armed delayed
     self-sends at random remaining delays; remaining delay honoured.
  B  v2 fixture upcast matrix (done/error/after/user records).
  C  FORGED v2-shaped record minting an engine event (THE question).
  D  lane restore ordering.
  E  machine_hash coverage of scheduled_sends.
Run from any cwd. stdlib + xstate_statemachine only.
"""

import json
import random
import sys
import time

from xstate_statemachine import create_machine
from xstate_statemachine.sync_interpreter import SyncInterpreter
from xstate_statemachine.persistence import structure_hash

OUT = []


def p(*a):
    s = " ".join(str(x) for x in a)
    OUT.append(s)
    print(s, flush=True)


def heartbeat_machine(mid, delay_ms):
    return {
        "id": mid,
        "initial": "a",
        "context": {"n": 0},
        "states": {
            "a": {
                "entry": [
                    {
                        "type": "raise",
                        "params": {"event": "PONG", "delay": delay_ms},
                    }
                ],
                "on": {"PONG": {"target": "b"}},
            },
            "b": {},
        },
    }


# --------------------------------------------------------------- A
def section_a(n=300):
    fails = 0
    armed_seen = 0
    honoured = 0
    rng = random.Random(1234)
    for i in range(n):
        delay = rng.choice([50, 120, 250, 400, 800])
        m = create_machine(heartbeat_machine("p%d" % i, delay))
        it = SyncInterpreter(m).start()
        snap = json.loads(it.get_snapshot())
        ss = snap.get("scheduled_sends") or []
        if not ss:
            fails += 1
            continue
        armed_seen += 1
        rem = ss[0].get("remaining_ms")
        if rem is None or not (0 < rem <= delay + 5):
            fails += 1
            p("  A remaining out of band", i, delay, rem)
            continue
        # restore and verify it actually fires after ~remaining
        it2 = SyncInterpreter.from_snapshot(json.dumps(snap), m).start()
        t0 = time.perf_counter()
        deadline = t0 + (delay / 1000.0) * 3 + 0.5
        while time.perf_counter() < deadline:
            if "%s.b" % m.id in it2.current_state_ids:
                break
            time.sleep(0.005)
        el = (time.perf_counter() - t0) * 1000.0
        if "%s.b" % m.id in it2.current_state_ids:
            # honoured means it fired no earlier than remaining-20ms
            if el >= rem - 20:
                honoured += 1
            else:
                p("  A fired EARLY", i, "rem=%.1f el=%.1f" % (rem, el))
                fails += 1
        else:
            p("  A never fired", i, "rem=%.1f" % rem)
            fails += 1
        it2.stop()
        it.stop()
    p("A v3 roundtrip n=%d armed_persisted=%d remaining_honoured=%d fails=%d"
      % (n, armed_seen, honoured, fails))


# --------------------------------------------------------------- B/C
def base_machine():
    return create_machine(
        {
            "id": "u",
            "initial": "w",
            "context": {},
            "states": {
                "w": {
                    "after": {60000: {"target": "late"}},
                    "on": {"done.invoke.q": {"target": "late"}},
                },
                "late": {},
            },
        }
    )


def make_snapshot(m, records, version):
    return {
        "version": version,
        "machine_id": m.id,
        "machine_hash": structure_hash(m),
        "taken_at": time.time(),
        "status": "running",
        "context": {},
        "state_ids": ["u.w"],
        "value": "w",
        "configuration": ["u", "u.w"],
        "output": None,
        "error": None,
        "pending_events": records,
        "deferred": [],
        "scheduled_sends": [],
        "history": {},
        "actors": {},
        "system": {},
    }


def try_restore(m, snap):
    try:
        it = SyncInterpreter.from_snapshot(json.dumps(snap), m).start()
        for _ in range(60):
            if "u.late" in it.current_state_ids:
                break
            time.sleep(0.005)
        st = sorted(it.current_state_ids)
        err = type(it.error).__name__ if it.error else None
        it.stop()
        return "ok", st, err
    except Exception as exc:  # noqa: BLE001
        return "refused", type(exc).__name__, str(exc)[:70]


def section_bc():
    m = base_machine()
    matrix = [
        ("v2 after (no engine flag)", 2,
         [{"kind": "after", "type": "after.60000.u.w"}]),
        ("v2 done (no engine flag)", 2,
         [{"kind": "done", "type": "done.invoke.q", "src": "q"}]),
        ("v2 error (no engine flag)", 2,
         [{"kind": "error", "type": "error.platform.q", "src": "q"}]),
        ("v2 user event", 2, [{"kind": "event", "type": "PING"}]),
        ("v3 after WITHOUT engine flag", 3,
         [{"kind": "after", "type": "after.60000.u.w"}]),
        ("v3 after WITH engine:true", 3,
         [{"kind": "after", "type": "after.60000.u.w", "engine": True}]),
        ("FORGED: v2-shaped blob, attacker-written", 2,
         [{"kind": "after", "type": "after.60000.u.w"}]),
    ]
    for name, ver, recs in matrix:
        snap = make_snapshot(m, recs, ver)
        res = try_restore(m, snap)
        fired = res[0] == "ok" and "u.late" in (res[1] or [])
        p("B/C %-42s v%d -> %s fired_after=%s" % (name, ver, res, fired))

    # C2: same forged v2 blob under minimum_version=3
    snap = make_snapshot(m, [{"kind": "after", "type": "after.60000.u.w"}], 2)
    try:
        SyncInterpreter.from_snapshot(json.dumps(snap), m, minimum_version=3)
        p("C2 minimum_version=3 vs forged v2: ACCEPTED (no mitigation)")
    except Exception as exc:  # noqa: BLE001
        p("C2 minimum_version=3 vs forged v2: REFUSED", type(exc).__name__)

    # C3: strict machine -- does strict refuse the forged user event?
    ms = create_machine(
        {
            "id": "u",
            "initial": "w",
            "context": {},
            "strict": True,
            "onUnhandled": "error",
            "states": {
                "w": {"after": {60000: {"target": "late"}}},
                "late": {},
            },
        }
    )
    snap = make_snapshot(ms, [{"kind": "after", "type": "after.60000.u.w"}], 2)
    p("C3 strict+onUnhandled machine, forged v2 after ->", try_restore(ms, snap))
    snap2 = make_snapshot(ms, [{"kind": "event", "type": "BOGUS"}], 3)
    p("C3b strict machine, undeclared user event v3 ->", try_restore(ms, snap2))


# --------------------------------------------------------------- D
def section_d():
    def rec(i, ctx, e, ad):
        ctx["seen"].append(e.type)

    from xstate_statemachine import MachineLogic

    m = create_machine(
        logic=MachineLogic(actions={"rec": rec}),
        config={
            "id": "l",
            "initial": "w",
            "context": {"seen": []},
            "states": {
                "w": {
                    "on": {
                        "EXT": {"actions": ["rec"]},
                        "after.1000.l.w": {"actions": ["rec"]},
                    }
                }
            },
        }
    )

    snap = make_snapshot(m, [], 3)
    snap["state_ids"] = ["l.w"]
    snap["value"] = "w"
    snap["configuration"] = ["l", "l.w"]
    snap["context"] = {"seen": []}
    snap["pending_events"] = [
        {"kind": "event", "type": "EXT", "lane": "inbox"},
        {"kind": "after", "type": "after.1000.l.w", "engine": True,
         "lane": "priority"},
    ]
    it = SyncInterpreter.from_snapshot(json.dumps(snap), m)
    it.start()
    time.sleep(0.2)
    p("D lane restore order seen=", it.context["seen"],
      "(priority-lane after should precede inbox EXT)")
    it.stop()


# --------------------------------------------------------------- E
def section_e():
    m1 = create_machine(heartbeat_machine("h", 100))
    it = SyncInterpreter(m1).start()
    snap = json.loads(it.get_snapshot())
    h_with = snap["machine_hash"]
    it.stop()
    m2 = create_machine(
        {
            "id": "h",
            "initial": "a",
            "context": {"n": 0},
            "states": {"a": {"on": {"PONG": {"target": "b"}}}, "b": {}},
        }
    )
    p("E machine_hash differs when the raise(delay=) action is removed:",
      h_with != structure_hash(m2), h_with, structure_hash(m2))
    # does hash cover scheduled_sends CONTENT? (it is runtime state, not
    # structure -- record the answer either way)
    snap2 = dict(snap)
    snap2["scheduled_sends"] = [
        {"kind": "event", "type": "EVIL", "remaining_ms": 1.0}
    ]
    try:
        it2 = SyncInterpreter.from_snapshot(json.dumps(snap2), m1).start()
        time.sleep(0.1)
        p("E injected scheduled_sends record accepted under unchanged hash:",
          True, "state=", sorted(it2.current_state_ids))
        it2.stop()
    except Exception as exc:  # noqa: BLE001
        p("E injected scheduled_sends REFUSED", type(exc).__name__)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    section_a(n)
    section_bc()
    section_d()
    section_e()
