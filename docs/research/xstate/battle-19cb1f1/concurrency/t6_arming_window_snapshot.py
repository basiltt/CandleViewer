"""t6 (@19cb1f1) -- STANDALONE. #204 moved invoke arming from state ENTRY
to the end of the eventless settle pass. That opens a new window: the
state is ENTERED and recorded in `_states_to_invoke`, but the service is
not yet submitted. What does a snapshot taken in that window say, and
does a restore arm the invoke EXACTLY ONCE?

  W1  snapshot while the invoke is armed-and-running (the normal case)
      -> restore static: dormant, pending names the invoke, 0 submits
      -> restore restart_services=True: exactly 1 submit
  W2  snapshot taken from an `always`-chain state whose settle is still
      running (many `always` hops before the invoking state) -- taken from
      a plugin hook so it lands mid-macrostep
  W3  the round-trip repeated 40x -- submits must be exactly 1 each time,
      never 0 and never 2

Both service kinds. Async engine (snapshot/restore of a running machine).

Run: python t6_arming_window_snapshot.py   (exit 1 == defect)
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
)


def emit(name: str, data: Dict[str, Any]) -> None:
    data = {"probe": name, "py": ".".join(map(str, sys.version_info[:3])), **data}
    txt = json.dumps(data, indent=2, default=str)
    with open(os.path.join(os.path.dirname(__file__), name + ".json"), "w") as fh:
        fh.write(txt)
    print(txt)


# W1/W3: plain invoking state, service sleeps so the snapshot lands while
# it is genuinely in flight.
PLAIN = {
    "id": "w", "initial": "idle", "context": {},
    "states": {
        "idle": {"on": {"GO": "work"}},
        "work": {"invoke": {"id": "job", "src": "svc",
                            "onDone": {"target": "done"}}},
        "done": {"type": "final"},
    },
}

# W2: a chain of `always` hops so the settle pass is multi-microstep and
# the invoking state is entered at the END of it.
CHAIN = {
    "id": "w", "initial": "idle", "context": {},
    "states": {
        "idle": {"on": {"GO": "h0"}},
        "h0": {"always": {"target": "h1"}},
        "h1": {"always": {"target": "h2"}},
        "h2": {"always": {"target": "work"}},
        "work": {"invoke": {"id": "job", "src": "svc",
                            "onDone": {"target": "done"}}},
        "done": {"type": "final"},
    },
}


def build(kind: str, sub: List[int]) -> MachineLogic:
    if kind == "def":

        def svc(i, c, e):  # noqa: ANN001
            sub[0] += 1
            import time

            time.sleep(0.4)
            return {"ok": 1}

    else:

        async def svc(i, c, e):  # noqa: ANN001
            sub[0] += 1
            await asyncio.sleep(0.4)
            return {"ok": 1}

    return MachineLogic(services={"svc": svc})


class Grab(PluginBase):
    """Snapshot from inside a transition hook -> mid-macrostep."""

    def __init__(self) -> None:
        self.blobs: List[Any] = []
        self.midstep_refusals = 0
        self.errors: List[str] = []

    def on_transition(self, itp, frm, to, ev):  # noqa: ANN001
        try:
            self.blobs.append(itp.get_persisted_snapshot())
        except Exception as exc:  # noqa: BLE001
            self.errors.append(type(exc).__name__)


async def take(cfgname: str, kind: str, from_hook: bool):
    cfg = copy.deepcopy(CHAIN if cfgname == "CHAIN" else PLAIN)
    sub = [0]
    itp = Interpreter(create_machine(cfg, logic=build(kind, sub)))
    grab = Grab()
    if from_hook:
        itp.use(grab)
    await itp.start()
    await itp.send("GO")
    await asyncio.sleep(0.05)  # inside the 0.4 s service
    # A plain `def` service blocks the loop (documented D8-concurrency-2),
    # so the snapshot can land mid-macrostep; retry until it settles and
    # RECORD how many refusals it took.
    blob, midstep = None, 0
    for _ in range(40):
        try:
            raw = itp.get_persisted_snapshot()
            # from_snapshot takes the JSON STRING form.
            blob = raw if isinstance(raw, str) else json.dumps(
                raw, default=str
            )
            break
        except Exception as exc:  # noqa: BLE001
            if type(exc).__name__ != "SnapshotMidStepError":
                raise
            midstep += 1
            await asyncio.sleep(0.05)
    live_state = sorted(itp.current_state_ids)
    await itp.stop()
    grab.midstep_refusals = midstep
    return blob, live_state, sub[0], grab


async def restore(blob, kind: str, restart: bool) -> Dict[str, Any]:
    sub = [0]
    cfg = copy.deepcopy(CHAIN if "h0" in blob else PLAIN)
    m = create_machine(cfg, logic=build(kind, sub))
    row: Dict[str, Any] = {"restart_services": restart}
    try:
        itp = Interpreter.from_snapshot(blob, m, restart_services=restart)
        if hasattr(itp, "__await__"):
            itp = await itp
        # `restart_services` is CONSUMED BY start()  (base_interpreter:1867
        # -> interpreter:560), so a restored interpreter must be started
        # for the re-arm to happen at all.
        await itp.start()
        await asyncio.sleep(0.6)
        row["state"] = sorted(itp.current_state_ids)
        row["dormant"] = bool(itp.has_dormant_invocations)
        row["pending"] = [str(p) for p in itp.pending_invocations()]
        await itp.stop()
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["submits"] = sub[0]
    return row


async def main() -> int:
    rows: List[Dict[str, Any]] = []
    viol: List[Any] = []

    for kind in ("def", "async def"):
        # W1
        blob, live, subs, _ = await take("PLAIN", kind, False)
        st = await restore(blob, kind, False)
        rs = await restore(blob, kind, True)
        rows.append({"case": "W1_plain", "kind": kind, "live_state": live,
                     "live_submits": subs, "static": st, "restarted": rs})
        if st.get("submits") != 0:
            viol.append((kind, "W1 static restore submitted a service",
                         st.get("submits")))
        if live == ["w.work"] and not st.get("dormant"):
            viol.append((kind, "W1 static restore not reported dormant"))
        if live == ["w.work"] and rs.get("submits") != 1:
            viol.append((kind, "W1 restart_services submits != 1",
                         rs.get("submits")))

        # W2 -- snapshot from a mid-settle transition hook
        blob2, live2, subs2, grab = await take("CHAIN", kind, True)
        hookrows = []
        for b in grab.blobs[-3:]:
            sb = b if isinstance(b, str) else json.dumps(b, default=str)
            hookrows.append(await restore(sb, kind, True))
        rows.append({"case": "W2_chain_hook", "kind": kind,
                     "live_state": live2, "live_submits": subs2,
                     "hook_blobs": len(grab.blobs),
                     "hook_snapshot_errors": grab.errors[:3],
                     "restores": hookrows})
        for h in hookrows:
            if h.get("submits", 0) > 1:
                viol.append((kind, "W2 hook-window restore armed twice",
                             h.get("submits")))

        # W3 -- 40 round-trips, exactly-once each
        c: Counter = Counter()
        for _ in range(40):
            r = await restore(blob, kind, True)
            c[r.get("submits", "err")] += 1
        rows.append({"case": "W3_x40", "kind": kind,
                     "submit_histogram": {str(k): v for k, v in c.items()}})
        if live == ["w.work"] and set(c) != {1}:
            viol.append((kind, "W3 not exactly-once over 40 restores",
                         {str(k): v for k, v in c.items()}))

    emit("t6_arming_window_snapshot",
         {"claim": "#204 arming window: a snapshot taken before the settle "
                   "arms the invoke restores and arms it exactly once",
          "rows": rows, "violations": viol,
          "result": "FAIL" if viol else "PASS"})
    return 1 if viol else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
