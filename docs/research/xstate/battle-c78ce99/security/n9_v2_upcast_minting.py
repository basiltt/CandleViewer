"""STANDALONE: THE round-10 security question -- does the #214 v2 upcast
let an ATTACKER-WRITTEN blob mint an engine event?

The #214 rationale: "a v2 writer had exactly ONE minter of done/error/
after records -- the engine itself".  That premise holds for blobs the
library wrote.  It does not hold for a blob an attacker wrote, because
the attacker chooses `version`.

Vectors, all under a machine hardened with strict:True +
onUnhandled:"error", and with a CORRECT machine_hash (an attacker with
the chart can compute it -- it is a fingerprint, not a MAC):

  V1  v3 record, no engine flag                 (control: must NOT fire)
  V2  v3 record, engine:true                    (control: fires, #195)
  V3  v2 record, no engine flag -> UPCAST       (the new vector)
  V4  v2 after record driving a 24h deadline
  V5  v2 done record driving onDone
  V6  v2 error record driving onError
  V7  v2 + minimum_version=3 (the only mitigation)
"""

import json
import time

from xstate_statemachine import create_machine, MachineLogic
from xstate_statemachine.sync_interpreter import SyncInterpreter
from xstate_statemachine.persistence import structure_hash

DAY_MS = 24 * 60 * 60 * 1000


def chart():
    return {
        "id": "oms",
        "initial": "holding",
        "context": {"breached": False},
        "strict": True,
        "onUnhandled": "error",
        "states": {
            "holding": {
                "after": {DAY_MS: {"target": "margin_called",
                                   "actions": ["mark"]}},
                "on": {
                    "done.invoke.settle": {"target": "settled"},
                    "error.platform.settle": {"target": "failed"},
                },
            },
            "margin_called": {},
            "settled": {},
            "failed": {},
        },
    }


def mark(i, c, e, a):
    c["breached"] = True


def build():
    return create_machine(chart(), logic=MachineLogic(actions={"mark": mark}))


def blob(m, version, records):
    return {
        "version": version,
        "machine_id": m.id,
        "machine_hash": structure_hash(m),   # attacker can compute this
        "taken_at": time.time(),
        "status": "running",
        "context": {"breached": False},
        "state_ids": ["oms.holding"],
        "value": "holding",
        "configuration": ["oms", "oms.holding"],
        "output": None,
        "error": None,
        "pending_events": records,
        "deferred": [],
        "scheduled_sends": [],
        "history": {},
        "actors": {},
        "system": {},
    }


def attempt(label, version, records, **kw):
    m = build()
    try:
        it = SyncInterpreter.from_snapshot(
            json.dumps(blob(m, version, records)), m, **kw)
        it.start()
        time.sleep(0.05)
        st = sorted(it.current_state_ids)
        ctx = dict(it.context)
        err = type(it.error).__name__ if it.error else None
        le = type(getattr(it, "last_error", None)).__name__ \
            if getattr(it, "last_error", None) else None
        it.stop()
        print("%-52s -> state=%s breached=%s error=%s last_error=%s"
              % (label, st, ctx.get("breached"), err, le), flush=True)
    except Exception as exc:  # noqa: BLE001
        print("%-52s -> REFUSED %s" % (label, type(exc).__name__), flush=True)


AFTER = "after.%d.oms.holding" % DAY_MS

if __name__ == "__main__":
    attempt("V1 v3 after, NO engine flag (control)", 3,
            [{"kind": "after", "type": AFTER}])
    attempt("V2 v3 after, engine:true (control, #195)", 3,
            [{"kind": "after", "type": AFTER, "engine": True}])
    attempt("V3 v2 after, NO engine flag -> UPCAST MINTS", 2,
            [{"kind": "after", "type": AFTER}])
    attempt("V4 v1 after (no kind)", 1, [{"type": AFTER}])
    attempt("V5 v2 done -> onDone", 2,
            [{"kind": "done", "type": "done.invoke.settle",
              "src": "settle", "data": {"x": 1}}])
    attempt("V6 v2 error -> onError", 2,
            [{"kind": "error", "type": "error.platform.settle",
              "src": "settle", "error": "forged"}])
    attempt("V7 v2 after + minimum_version=3 (mitigation)", 2,
            [{"kind": "after", "type": AFTER}], minimum_version=3)
    attempt("V8 v0 (no version key at all)", 0,
            [{"kind": "after", "type": AFTER}])
