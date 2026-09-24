# -*- coding: utf-8 -*-
"""R6 -- snapshot-from-every-hook property WITH invoked children and services,
over both service kinds. Strengthens `q1` (which had no `invoke` at all).

Each generated machine has:
  * 1-3 parallel regions, each a compound state with 2-3 children;
  * an `invoke` on one region's initial child, whose `src` is either a plain
    `def` service, an `async def` service or a child MACHINE (whose own entry
    action mutates its context -- the #183 harvest target);
  * `after` timers and an `onUnhandled` policy.

Every action mutates context, so an accepted mid-action blob is detectable:
its context predates the mutation. Snapshots are attempted from
`on_transition`, every `on_action_execute` (classified by window, incl. the
`start()` descent and the child's own entry) and `on_unhandled_event`.

An attempt may be REFUSED (legal) or ACCEPTED. An ACCEPTED blob must:
  1. restore without raising,
  2. restore to a region-legal configuration,
  3. round-trip byte-identical,
  4. carry the context the machine actually held at that instant, and
  5. carry no child actor whose context is half-written.

    usage: r6_child_hook_property.py [N_MACHINES] [SEED]
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import traceback
from collections import Counter

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.exceptions import SnapshotMidStepError
from xstate_statemachine.plugins import PluginBase

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 11

ST = Counter()
TORN: list[str] = []
RAW: list[str] = []
MISMATCH: list[str] = []
HALF: list[str] = []
WINDOWS = Counter()
TORN_WINDOWS = Counter()

HALF_MARK = "__HALF__"


def _strip(o):
    """Drop every `taken_at` at ANY depth.

    A child actor's record nests its own snapshot, with its own wall-clock
    `taken_at`; stripping only the top-level one makes every parent-with-child
    blob "differ" on a timestamp. Verified as an artefact in
    `r7_child_actor_restore.py` (field-level diff: all fields equal).
    """
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k != "taken_at"}
    if isinstance(o, list):
        return [_strip(x) for x in o]
    return o


def canon(b: dict) -> str:
    return json.dumps(_strip(b), sort_keys=True, default=str)


def build(rnd: random.Random, kind: str):
    """Generate one machine; returns (machine, alphabet)."""
    nreg = rnd.randint(1, 3)
    regions, alphabet = {}, set()
    for r in range(nreg):
        nkids = rnd.randint(2, 3)
        kids = {}
        for k in range(nkids):
            ev = f"E{r}_{k}"
            alphabet.add(ev)
            nxt = f"s{(k + 1) % nkids}"
            node = {
                "entry": [f"en_{r}_{k}"],
                "exit": [f"ex_{r}_{k}"],
                "on": {ev: nxt},
            }
            if k == 0 and rnd.random() < 0.6:
                node["after"] = {rnd.choice([30, 60]): f"s{(k+1)%nkids}"}
            kids[f"s{k}"] = node
        # the invoke goes on the first region's initial child
        if r == 0:
            kids["s0"]["invoke"] = [{"id": "kid", "src": "svc"}]
        regions[f"r{r}"] = {
            "initial": "s0",
            "states": kids,
        }
    spec = {
        "id": "gen",
        "type": "parallel",
        "onUnhandled": rnd.choice(["defer", "ignore"]),
        "states": regions,
    }

    actions = {}
    for r in range(nreg):
        for k in range(rnd.randint(2, 3)):
            for pre in ("en", "ex"):
                nm = f"{pre}_{r}_{k}"

                def act(i, c, e, a, nm=nm):  # noqa: ANN001
                    c["n"] = c.get("n", 0) + 1
                    c["last"] = nm

                actions[nm] = act
    for r in range(nreg):
        for k in range(3):
            actions.setdefault(f"en_{r}_{k}", actions[next(iter(actions))])
            actions.setdefault(f"ex_{r}_{k}", actions[next(iter(actions))])

    # --- the invoked src: def service / async service / child machine ---
    def svc_def(i, c, e):  # noqa: ANN001
        return {"ok": 1}

    async def svc_async(i, c, e):  # noqa: ANN001
        await asyncio.sleep(0)
        return {"ok": 1}

    def kid_entry(i, c, e, a):  # noqa: ANN001
        c["half"] = HALF_MARK
        c["half"] = "complete"

    async def kid_entry_async(i, c, e, a):  # noqa: ANN001
        c["half"] = HALF_MARK
        await asyncio.sleep(0)
        c["half"] = "complete"

    pick = rnd.random()
    if pick < 0.34:
        src = svc_def if kind == "def" else svc_async
    else:
        src = create_machine(
            {"id": "kid", "initial": "s", "states": {"s": {"entry": ["ke"]}}},
            logic=MachineLogic(
                actions={"ke": kid_entry if kind == "def" else kid_entry_async}
            ),
        )
    m = create_machine(
        spec, logic=MachineLogic(actions=actions, services={"svc": src})
    )
    return m, sorted(alphabet)


class Snapper(PluginBase):
    """Attempts a snapshot from every hook and validates the result."""

    def __init__(self, interp_box: dict, tag: str):
        self.box = interp_box
        self.tag = tag
        self.started = False

    # -- the validator ------------------------------------------------
    def attempt(self, interp, window: str) -> None:
        w = window if self.started else window + "@start"
        WINDOWS[w] += 1
        ctx_now = json.loads(json.dumps(interp.context, default=str))
        try:
            blob = interp.get_persisted_snapshot()
        except SnapshotMidStepError:
            ST["refused"] += 1
            return
        except Exception as exc:  # noqa: BLE001
            ST["raw"] += 1
            RAW.append(f"{self.tag}/{w}: {type(exc).__name__}: {exc}")
            return
        ST["accepted"] += 1

        # (5) no child actor caught half-written (#183)
        for aid, rec in (blob.get("actors") or {}).items():
            if isinstance(rec, dict) and \
                    (rec.get("context") or {}).get("half") == HALF_MARK:
                HALF.append(f"{self.tag}/{w}: child {aid} half-written")
                TORN_WINDOWS[w] += 1

        # (4) context must match what the machine held at this instant
        if blob.get("context") != ctx_now:
            TORN.append(f"{self.tag}/{w}: context drift {blob.get('context')!r} "
                        f"vs {ctx_now!r}")
            TORN_WINDOWS[w] += 1

        # (1)(2)(3) restore, legality, round-trip
        txt = json.dumps(blob, default=str)
        try:
            r = Interpreter.from_snapshot(txt, self.box["machine"])
        except Exception as exc:  # noqa: BLE001
            TORN.append(f"{self.tag}/{w}: write-accepted but READ-REFUSED "
                        f"{type(exc).__name__}: {str(exc)[:90]}")
            TORN_WINDOWS[w] += 1
            return
        if not r._configuration_is_legal():
            TORN.append(f"{self.tag}/{w}: restored configuration ILLEGAL")
            TORN_WINDOWS[w] += 1
            return
        try:
            again = r.get_persisted_snapshot()
        except Exception as exc:  # noqa: BLE001
            MISMATCH.append(f"{self.tag}/{w}: re-snapshot raised {type(exc).__name__}")
            return
        if canon(again) != canon(blob):
            a, b = json.loads(canon(blob)), json.loads(canon(again))
            diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            MISMATCH.append(
                f"{self.tag}/{w}: round-trip differs on {diff}: "
                + "; ".join(f"{k}: {a.get(k)!r} -> {b.get(k)!r}"
                            for k in diff)[:220]
            )

    # -- hooks ---------------------------------------------------------
    def on_transition(self, interp, frm, to, t):  # noqa: ANN001
        self.attempt(interp, "on_transition")

    def on_action_execute(self, interp, action):  # noqa: ANN001
        ty = getattr(action, "type", "")
        if ty.startswith("en_"):
            win = "entry"
        elif ty.startswith("ex_"):
            win = "exit"
        elif ty == "ke":
            win = "child_entry"
        else:
            win = "on_action"
        self.attempt(interp, win)

    def on_unhandled_event(self, interp, event, ids, disposition):  # noqa: ANN001
        self.attempt(interp, "unhandled")


async def run_one(rnd: random.Random, kind: str, idx: int) -> None:
    m, alphabet = build(rnd, kind)
    box = {"machine": m}
    plug = Snapper(box, f"{kind}#{idx}")
    clock = SimulatedClock()
    i = Interpreter(m, clock=clock)
    i.use(plug)
    # Plugins are per-interpreter; propagate to child actors as they
    # register so the CHILD's own entry window is observed too.
    try:
        await i.start(children_timeout=1.0)
    except Exception as exc:  # noqa: BLE001
        RAW.append(f"{kind}#{idx}: start() raised {type(exc).__name__}: {exc}")
        return
    plug.started = True
    for child in list(getattr(i, "_actors", {}).values()):
        try:
            child.use(Snapper(box, f"{kind}#{idx}/child"))
        except Exception:  # noqa: BLE001
            pass
    for _ in range(rnd.randint(3, 6)):
        ev = rnd.choice(alphabet + ["UNDECLARED"])
        try:
            await i.send(ev)
        except Exception as exc:  # noqa: BLE001
            RAW.append(f"{kind}#{idx}: send raised {type(exc).__name__}: {exc}")
            break
        if rnd.random() < 0.5:
            await clock.increment(rnd.choice([40, 80]))
        await asyncio.sleep(0.005)
    # quiescent snapshot must always succeed
    try:
        plug.attempt(i, "quiescent")
    except Exception as exc:  # noqa: BLE001
        RAW.append(f"{kind}#{idx}: quiescent {type(exc).__name__}: {exc}")
    await i.stop()


async def main() -> None:
    per = N // 2
    for kind in ("def", "async"):
        rnd = random.Random(SEED)
        for idx in range(per):
            try:
                await run_one(rnd, kind, idx)
            except Exception:  # noqa: BLE001
                RAW.append(f"{kind}#{idx}: harness {traceback.format_exc()[-160:]}")
    print("machines               : %d  (%d per service kind, seed %d)"
          % (per * 2, per, SEED))
    print("snapshot attempts      : %d" % sum(WINDOWS.values()))
    print("  refused (legal)      : %d" % ST["refused"])
    print("  accepted             : %d" % ST["accepted"])
    print("TORN / inconsistent    : %d   <- must be 0" % len(TORN))
    print("half-written child     : %d   <- must be 0" % len(HALF))
    print("round-trip mismatches  : %d   <- must be 0" % len(MISMATCH))
    print("RAW exceptions         : %d   <- must be 0" % len(RAW))
    print("windows exercised      :")
    for w, c in sorted(WINDOWS.items()):
        print("    %-24s %d" % (w, c))
    print("TORN by window         : %s" % dict(TORN_WINDOWS))
    for label, lst in (("TORN", TORN), ("HALF", HALF),
                       ("MISMATCH", MISMATCH), ("RAW", RAW)):
        for s in lst[:5]:
            print("  %s: %s" % (label, s))
    ok = not (TORN or HALF or MISMATCH or RAW)
    print("VERDICT:", "PASS" if ok else "FAIL")


asyncio.run(main())
