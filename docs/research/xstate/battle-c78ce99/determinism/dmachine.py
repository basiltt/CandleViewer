"""Shared replay fixture for the DETERMINISM battle-test track.

One machine definition + one deterministic event script, runnable on BOTH
engines (async `Interpreter` and `SyncInterpreter`) against a `SimulatedClock`.

Design constraints so the two engines can run byte-identical work:
  * every service is a PLAIN SYNC callable (the sync engine refuses `async def`);
  * every delay is driven by `SimulatedClock`, never wall clock;
  * the event script is generated from a seeded `random.Random`, so the same
    seed yields the same script in every process, independent of PYTHONHASHSEED.

The machine deliberately exercises the ordering lanes the track is about:
  external inbox, `raise` (internal queue), `sendTo` (actor mailbox),
  `after` (timer priority lane), invoke completions (`done.invoke` /
  `error.platform`), and `onUnhandled: "defer"` replay.
"""

from __future__ import annotations

import json
import logging
import random
import sys

logging.disable(logging.CRITICAL)

LIB = "<workspace>/_ref/xstate-statemachine/src"
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from xstate_statemachine import (  # noqa: E402
    Event,
    MachineLogic,
    PluginBase,
    create_machine,
)

# -----------------------------------------------------------------------------
# 📜 Machine config
# -----------------------------------------------------------------------------
# A small order-management shape: a parallel root with a `trading` region that
# does the work and a `risk` region that runs in lockstep, plus an invoked
# child machine addressable by `sendTo`.

CHILD = {
    "id": "child",
    "initial": "up",
    "context": {"seen": 0},
    "states": {
        "up": {
            "on": {
                "PING": {"actions": ["child_seen"]},
                "FINISH": {"target": "done"},
            }
        },
        "done": {"type": "final"},
    },
}

CFG = {
    "id": "oms",
    "type": "parallel",
    "onUnhandled": "defer",
    "context": {
        "fills": 0,
        "risk": 0,
        "raised": 0,
        "timers": 0,
        "svc_ok": 0,
        "svc_err": 0,
        "log": [],
    },
    "states": {
        # --- region A: trading -------------------------------------------
        "trading": {
            "initial": "idle",
            "states": {
                "idle": {
                    "entry": ["enter_idle"],
                    "on": {
                        "ORDER": {"target": "pending", "actions": ["note"]},
                        "FILL": [
                            {
                                "target": "pending",
                                "guard": "g_even",
                                "actions": ["note", "bump_fills"],
                            },
                            {
                                "guard": "g_odd",
                                "actions": ["note", "g_odd_path"],
                            },
                            {"actions": ["note"]},
                        ],
                    },
                },
                "pending": {
                    "entry": [
                        "enter_pending",
                        {"type": "raise", "params": {"event": "SETTLE"}},
                    ],
                    "invoke": {
                        "id": "pricer",
                        "src": "price",
                        "onDone": {
                            "target": "idle",
                            "actions": ["svc_done"],
                        },
                        "onError": {
                            "target": "idle",
                            "actions": ["svc_fail"],
                        },
                    },
                    "after": {"50": {"target": "idle", "actions": ["timer"]}},
                    "on": {
                        "SETTLE": {"actions": ["bump_raised"]},
                        "CANCEL": {"target": "idle", "actions": ["note"]},
                        "PING_CHILD": {
                            "actions": [
                                {
                                    "type": "sendTo",
                                    "params": {
                                        "to": "kid",
                                        "event": "PING",
                                    },
                                }
                            ]
                        },
                    },
                },
            },
        },
        # --- region B: risk ----------------------------------------------
        "risk": {
            "initial": "green",
            "states": {
                "green": {
                    "entry": ["enter_green"],
                    "on": {
                        "FILL": {"actions": ["bump_risk"]},
                        "BREACH": {"target": "amber", "actions": ["note"]},
                    },
                },
                "amber": {
                    "entry": ["enter_amber"],
                    "on": {"CLEAR": {"target": "green", "actions": ["note"]}},
                },
            },
        },
        # --- region C: a permanently-live child for `sendTo` -------------
        "actors": {
            "initial": "hosting",
            "states": {
                "hosting": {
                    "invoke": {
                        "id": "kid",
                        "systemId": "kid",
                        "src": "childMachine",
                    }
                }
            },
        },
    },
}


# -----------------------------------------------------------------------------
# 🎬 Recorder: the full observable trace
# -----------------------------------------------------------------------------
class Recorder:
    """Collects everything the track compares between runs."""

    def __init__(self) -> None:
        self.actions: list = []  # user-action call order
        self.hooks: list = []  # plugin hook order
        self.transitions: list = []  # (from, event, to)
        self.receipts: list = []  # per-send receipt fields
        self.snapshots: list = []  # (checkpoint, canonical json bytes)

    # -- comparison surface ------------------------------------------------
    def digest(self) -> dict:
        return {
            "actions": self.actions,
            "hooks": self.hooks,
            "transitions": self.transitions,
            "receipts": self.receipts,
            "snapshots": [s for _, s in self.snapshots],
        }


class TracePlugin(PluginBase):
    """Records the hook order. Only hooks both engines can fire."""

    def __init__(self, rec: Recorder) -> None:
        self.rec = rec

    def on_event_received(self, interp, event):
        self.rec.hooks.append(("recv", event.type))

    def on_transition(self, interp, from_states, to_states, transition):
        self.rec.hooks.append(
            (
                "trans",
                transition.event,
                tuple(sorted(s.id for s in from_states)),
                tuple(sorted(s.id for s in to_states)),
            )
        )
        self.rec.transitions.append(
            (
                tuple(sorted(s.id for s in from_states)),
                transition.event,
                tuple(sorted(s.id for s in to_states)),
            )
        )

    def on_action_execute(self, interp, action):
        self.rec.hooks.append(("act", action.type))

    def on_guard_evaluated(self, interp, guard_name, event, result):
        self.rec.hooks.append(("guard", guard_name, event.type, bool(result)))

    def on_transition_failed(self, interp, transition, failed_actions):
        self.rec.hooks.append(
            (
                "tfail",
                transition.event,
                tuple(type(e).__name__ for _, e in failed_actions),
            )
        )

    def on_unhandled_event(self, interp, event, active_state_ids, disposition):
        self.rec.hooks.append(("unhandled", event.type, disposition))

    def on_event_dropped(self, interp, event, reason):
        self.rec.hooks.append(("dropped", getattr(event, "type", "?"), reason))

    def on_service_start(self, interp, invocation):
        self.rec.hooks.append(("svc_start", invocation.id))

    def on_service_done(self, interp, invocation, result):
        self.rec.hooks.append(("svc_done", invocation.id, repr(result)))

    def on_service_error(self, interp, invocation, error):
        self.rec.hooks.append(("svc_err", invocation.id, type(error).__name__))


# -----------------------------------------------------------------------------
# 🔧 Logic
# -----------------------------------------------------------------------------
def build_logic(rec: Recorder, child_machine, *, jitter=None):
    """Return a `MachineLogic`. `jitter` is an optional async yield hook."""

    def _rec(name, event):
        rec.actions.append((name, event.type))

    def note(i, c, e, a):
        _rec("note", e)
        c["log"].append(e.type)
        if len(c["log"]) > 8:
            del c["log"][0]

    def bump_fills(i, c, e, a):
        _rec("bump_fills", e)
        c["fills"] += 1

    def g_odd_path(i, c, e, a):
        _rec("g_odd_path", e)

    def bump_risk(i, c, e, a):
        _rec("bump_risk", e)
        c["risk"] += 1

    def bump_raised(i, c, e, a):
        _rec("bump_raised", e)
        c["raised"] += 1

    def timer(i, c, e, a):
        _rec("timer", e)
        c["timers"] += 1

    def svc_done(i, c, e, a):
        _rec("svc_done", e)
        c["svc_ok"] += 1

    def svc_fail(i, c, e, a):
        _rec("svc_fail", e)
        c["svc_err"] += 1

    def enter_idle(i, c, e, a):
        _rec("enter_idle", e)

    def enter_pending(i, c, e, a):
        _rec("enter_pending", e)

    def enter_green(i, c, e, a):
        _rec("enter_green", e)

    def enter_amber(i, c, e, a):
        _rec("enter_amber", e)

    def child_seen(i, c, e, a):
        _rec("child_seen", e)
        c["seen"] += 1

    # guards -- two of them fire on the SAME event so evaluation order is
    # observable.
    def g_even(c, e):
        rec.actions.append(("GUARD:g_even", e.type))
        return c["fills"] % 2 == 0

    def g_odd(c, e):
        rec.actions.append(("GUARD:g_odd", e.type))
        return c["fills"] % 2 == 1

    # A SYNC service so both engines can run it. Deterministic success/failure
    # keyed on context, never on time or randomness.
    def price(i, c, e):
        n = c["fills"] + c["raised"]
        if n % 7 == 3:
            raise ValueError(f"price-fail-{n % 7}")
        return {"px": n % 13}

    return MachineLogic(
        actions={
            "note": note,
            "bump_fills": bump_fills,
            "g_odd_path": g_odd_path,
            "bump_risk": bump_risk,
            "bump_raised": bump_raised,
            "timer": timer,
            "svc_done": svc_done,
            "svc_fail": svc_fail,
            "enter_idle": enter_idle,
            "enter_pending": enter_pending,
            "enter_green": enter_green,
            "enter_amber": enter_amber,
            "child_seen": child_seen,
        },
        guards={"g_even": g_even, "g_odd": g_odd},
        services={"price": price, "childMachine": child_machine},
    )


def build(rec: Recorder):
    child_logic = MachineLogic(
        actions={
            "child_seen": lambda i, c, e, a: (
                rec.actions.append(("child_seen", e.type)),
                c.__setitem__("seen", c["seen"] + 1),
            )[0]
        }
    )
    child = create_machine(CHILD, logic=child_logic)
    return create_machine(CFG, logic=build_logic(rec, child))


# -----------------------------------------------------------------------------
# 🎲 Event script
# -----------------------------------------------------------------------------
EVENT_POOL = [
    "ORDER",
    "FILL",
    "FILL",
    "CANCEL",
    "SETTLE",
    "BREACH",
    "CLEAR",
    "PING_CHILD",
    "NOPE",  # never declared anywhere -> onUnhandled: defer
]


def make_script(n: int, seed: int = 20260918) -> list:
    """A deterministic script of ``n`` steps.

    Each step is ``("send", type, payload)`` or ``("tick", ms)``. Timer ticks
    are interleaved so `after`/invoke completions land amid external traffic.
    """
    rng = random.Random(seed)
    script = []
    for k in range(n):
        if k % 37 == 36:
            script.append(("tick", rng.choice([10, 25, 60, 120])))
        else:
            t = EVENT_POOL[rng.randrange(len(EVENT_POOL))]
            script.append(("send", t, {"i": k, "v": rng.randrange(1000)}))
    return script


# -----------------------------------------------------------------------------
# 🧊 Canonical snapshot bytes
# -----------------------------------------------------------------------------
_VOLATILE = ("taken_at",)


def canon_snapshot(snap) -> str:
    """JSON with volatile fields removed, sorted keys -- comparable bytes."""

    def strip(o):
        if isinstance(o, dict):
            return {
                k: strip(v) for k, v in o.items() if k not in _VOLATILE
            }
        if isinstance(o, (list, tuple)):
            return [strip(x) for x in o]
        return o

    return json.dumps(strip(snap), sort_keys=True, default=repr)
