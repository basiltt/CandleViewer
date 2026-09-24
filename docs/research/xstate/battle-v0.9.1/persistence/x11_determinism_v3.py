# -*- coding: utf-8 -*-
"""X11 -- determinism: 50x traces, both engines, both kinds, incl. a
scheduled_sends restore; and PYTHONHASHSEED sensitivity.

STANDALONE. Neutral cwd.

A trace = (action order, transition order, final states, final context,
snapshot pending_events, snapshot scheduled_sends). 50 repeats of the same
scripted scenario must produce ONE distinct trace per lane, and the async
and sync lanes must agree with each other.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

KIND = os.environ.get("XS_SVC", "async")
REPS = int(os.environ.get("XS_REPS", "50"))


def attach_clock(interp, clock):
    from xstate_statemachine.base_interpreter import _accepts_kwarg

    interp.clock = clock
    interp._clock_accepts_sync = _accepts_kwarg(clock.set_timeout, "sync")
    clock._attach(interp._settle_for_clock)


class Trace(PluginBase):
    def __init__(self):
        self.a = []
        self.t = []

    def on_action_execute(self, i, action):  # noqa: ANN001
        self.a.append(action.type)

    def on_transition(self, i, frm, to, tr):  # noqa: ANN001
        self.t.append(f"{tr.event}->{sorted(n.id for n in to if not n.states)}")


SPEC = {
    "id": "det",
    "initial": "idle",
    "context": {"n": 0, "log": []},
    "states": {
        "idle": {"on": {"GO": "armed"}},
        "armed": {
            "entry": [{"type": "raise",
                       "params": {"event": "TICK", "delay": 100, "id": "hb"}},
                      "mark"],
            "on": {"TICK": {"target": "done_", "actions": "mark"},
                   "CANCEL": "idle"},
            "after": {"5000": "idle"},
        },
        "done_": {"type": "final"},
    },
}


def build():
    def mark(i, c, e, a):  # noqa: ANN001
        c["n"] += 1
        c["log"].append(e.type)

    return create_machine(json.loads(json.dumps(SPEC)),
                          logic=MachineLogic(actions={"mark": mark}))


def digest(parts):
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


async def run_async():
    tp = Trace()
    c = SimulatedClock()
    i = Interpreter(build(), clock=c)
    i.use(tp)
    await i.start()
    await i.send("GO")
    await asyncio.sleep(0)
    await c.increment(40)
    blob = i.get_snapshot()
    snap = json.loads(blob)
    await i.stop()
    ss = [(r["type"], r["remaining_ms"], r.get("send_id"))
          for r in snap.get("scheduled_sends") or []]
    pe = [(r["type"], r.get("kind"), r.get("lane")) for r in
          snap.get("pending_events") or []]
    # restore and complete
    tp2 = Trace()
    c2 = SimulatedClock()
    i2 = Interpreter.from_snapshot(blob, build(), clock=c2)
    i2.use(tp2)
    await i2.start()
    await c2.increment(100)
    await asyncio.sleep(0)
    out = (tp.a, tp.t, sorted(i.current_state_ids), ss, pe,
           tp2.a, sorted(i2.current_state_ids), i2.context["n"],
           i2.context["log"])
    if i2.status == "running":
        await i2.stop()
    return digest(out), out


def run_sync():
    tp = Trace()
    c = SimulatedClock()
    i = SyncInterpreter(build(), clock=c)
    i.use(tp)
    i.start()
    i.send("GO")
    c.increment(40)
    blob = i.get_snapshot()
    snap = json.loads(blob)
    i.stop()
    ss = [(r["type"], r["remaining_ms"], r.get("send_id"))
          for r in snap.get("scheduled_sends") or []]
    pe = [(r["type"], r.get("kind"), r.get("lane")) for r in
          snap.get("pending_events") or []]
    tp2 = Trace()
    c2 = SimulatedClock()
    i2 = SyncInterpreter.from_snapshot(blob, build(), clock=c2)
    i2.use(tp2)
    i2.start()
    c2.increment(100)
    out = (tp.a, tp.t, sorted(i.current_state_ids), ss, pe,
           tp2.a, sorted(i2.current_state_ids), i2.context["n"],
           i2.context["log"])
    if i2.status == "running":
        i2.stop()
    return digest(out), out


async def main():
    print(f"X11 kind={KIND} REPS={REPS}")
    ad = {}
    sample_a = None
    for _ in range(REPS):
        d, o = await run_async()
        ad[d] = ad.get(d, 0) + 1
        sample_a = o
    sd, sample_s = SYNC_OUT
    print(f"   async distinct traces = {len(ad)} {list(ad.items())[:3]}")
    print(f"   sync  distinct traces = {len(sd)} {list(sd.items())[:3]}")
    print(f"   sample scheduled_sends = {sample_a[3]}")
    print(f"   sample restored log    = {sample_a[8]} states={sample_a[6]}")
    agree = sample_a[3] == sample_s[3] and sample_a[6] == sample_s[6] \
        and sample_a[8] == sample_s[8]
    print(f"   async/sync agree on (scheduled_sends, restored states, log) "
          f"= {agree}")
    if not agree:
        print(f"     async: ss={sample_a[3]} st={sample_a[6]} log={sample_a[8]}")
        print(f"     sync : ss={sample_s[3]} st={sample_s[6]} log={sample_s[8]}")
    ok = len(ad) == 1 and len(sd) == 1 and agree
    print(f"   VERDICT determinism = {'PASS' if ok else 'FAIL'}")
    # hash-seed sensitivity
    if os.environ.get("XS_CHILD") != "1":
        digs = []
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed, XS_CHILD="1",
                       XS_REPS="3", PYTHONUTF8="1")
            r = subprocess.run([sys.executable, os.path.abspath(__file__)],
                               capture_output=True, text=True, env=env,
                               timeout=90)
            line = [ln for ln in r.stdout.splitlines()
                    if "async distinct" in ln]
            digs.append((seed, line[0].strip() if line else r.stdout[-80:]))
        print("   PYTHONHASHSEED sweep:")
        for s, ln in digs:
            print(f"     seed={s:6s} {ln}")
        uniq = {ln.split('=')[-1] for _, ln in digs}
        print(f"   VERDICT hash-seed independent = "
              f"{'PASS' if len(uniq) == 1 else 'FAIL'}")


# 📏 the sync engine + SimulatedClock idiom is OUTSIDE any running loop
SYNC_OUT = ({}, None)


def sync_pass():
    global SYNC_OUT
    sd, sample = {}, None
    for _ in range(REPS):
        d, o = run_sync()
        sd[d] = sd.get(d, 0) + 1
        sample = o
    SYNC_OUT = (sd, sample)


sync_pass()
asyncio.run(main())
