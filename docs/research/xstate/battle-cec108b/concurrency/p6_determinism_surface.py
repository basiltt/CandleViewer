"""P6 @cec108b -- determinism with executor services + hash-seed sweep,
and the exported-API / redaction surface delta vs 3ed3099.

A  50x identical traces on each engine for a machine whose invoke is a
   PLAIN def service now running on the #149 executor. Within-engine
   determinism must be exact; cross-engine agreement on the final states
   and context is reported (and the #116 ordering question is separated
   out into p1b).
B  Hash-seed sweep: the same trace under PYTHONHASHSEED in {0,1,2,...}
   is driven by a subprocess (see run_seed()) -- ordering must not depend
   on dict/set iteration order.
C  Exported API surface: names in `__all__` on this commit vs the
   documented round-5 additions (service_executor kwarg, Receipt.denied,
   RootTargetError, SnapshotCorruptError, QueueOverflowError, the new
   hooks) and a DEBUG-log redaction check for get_snapshot (#160).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time

from common import emit
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)

CFG = {
    "id": "det",
    "initial": "idle",
    "context": {"n": 0, "trace": []},
    "states": {
        "idle": {"on": {"GO": {"target": "work"}}},
        "work": {
            "invoke": {
                "id": "j",
                "src": "plain",
                "onDone": {"target": "idle", "actions": ["ok"]},
            },
            "on": {"CANCEL": {"target": "idle", "actions": ["cancel"]}},
        },
    },
}


def plain(i, ctx, e):  # noqa: ANN001
    return {"v": 1}


def ok(i, ctx, e, a):  # noqa: ANN001
    ctx["n"] += 1
    ctx["trace"].append("ok")


def cancel(i, ctx, e, a):  # noqa: ANN001
    ctx["trace"].append("cancel")


def mk():
    return create_machine(
        CFG,
        logic=MachineLogic(
            actions={"ok": ok, "cancel": cancel}, services={"plain": plain}
        ),
    )


class Tracer(PluginBase):
    def __init__(self) -> None:
        self.rows: list = []

    def on_transition(self, i, frm, to, t):  # noqa: ANN001
        self.rows.append((sorted(x.id for x in to), t.event))

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.rows, default=repr).encode()
        ).hexdigest()[:16]


SCRIPT = ["GO", "CANCEL", "GO", "GO", "CANCEL", "GO"]


async def async_run() -> tuple:
    t = Tracer()
    i = Interpreter(mk())
    i.use(t)
    await i.start()
    for ev in SCRIPT:
        await asyncio.wait_for(i.send(ev, wait=True), 5)
    out = (t.digest(), sorted(i.current_state_ids), dict(i.context))
    await i.stop()
    return out


def sync_run() -> tuple:
    t = Tracer()
    i = SyncInterpreter(mk())
    i.use(t)
    i.start()
    for ev in SCRIPT:
        i.send(ev)
    out = (t.digest(), sorted(i.current_state_ids), dict(i.context))
    i.stop()
    return out


async def a_determinism(reps: int = 50) -> dict:
    ad = set()
    a_last = None
    for _ in range(reps):
        a_last = await async_run()
        ad.add(a_last[0])
    sd = set()
    s_last = None
    for _ in range(reps):
        s_last = sync_run()
        sd.add(s_last[0])
    return {
        "reps": reps,
        "async_distinct_trace_hashes": len(ad),
        "sync_distinct_trace_hashes": len(sd),
        "async_final": {"states": a_last[1], "context": a_last[2]},
        "sync_final": {"states": s_last[1], "context": s_last[2]},
        "cross_engine_states_equal": a_last[1] == s_last[1],
        "cross_engine_context_equal": a_last[2] == s_last[2],
        "pass": len(ad) == 1 and len(sd) == 1,
    }


SEED_SNIPPET = (
    "import asyncio,sys;sys.path.insert(0,r'{here}');"
    "import p6_determinism_surface as m;"
    "print(asyncio.run(m.async_run())[0]);print(m.sync_run()[0])"
)


def b_hash_seed(seeds=(0, 1, 2, 7, 12345)) -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    outs = {}
    for s in seeds:
        env = dict(os.environ, PYTHONHASHSEED=str(s), PYTHONUTF8="1")
        r = subprocess.run(
            [sys.executable, "-c", SEED_SNIPPET.format(here=here)],
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )
        lines = [ln for ln in r.stdout.strip().splitlines() if ln]
        outs[str(s)] = lines[-2:] if len(lines) >= 2 else r.stderr[-160:]
    vals = [tuple(v) for v in outs.values() if isinstance(v, list)]
    return {
        "seeds": outs,
        "distinct": len(set(vals)),
        "pass": len(set(vals)) == 1 and len(vals) == len(outs),
    }


def c_surface() -> dict:
    import xstate_statemachine as X
    from xstate_statemachine import plugins as P

    required = [
        "RootTargetError",
        "SnapshotCorruptError",
        "QueueOverflowError",
        "SnapshotMidStepError",
        "InvalidEventError",
        "SnapshotSerializationError",
        "Receipt",
    ]
    missing = [n for n in required if not hasattr(X, n)]
    all_names = sorted(getattr(X, "__all__", []))
    hooks = [
        h
        for h in (
            "on_invalid_event",
            "on_snapshot_error",
            "on_plugin_error",
            "on_resolve_error",
            "on_guard_error",
            "on_unhandled_event",
            "on_event_dropped",
        )
        if not hasattr(P.PluginBase, h)
    ]
    import inspect

    sig = inspect.signature(Interpreter.__init__)
    has_exec = "service_executor" in sig.parameters
    r = X.Receipt(state_ids=frozenset(), changed=False, error=None)
    has_denied = hasattr(r, "denied")

    # #160: DEBUG log of get_snapshot must be redacted
    logs: list = []

    class H(logging.Handler):
        def emit(self, rec):  # noqa: ANN001
            logs.append(rec.getMessage())

    lg = logging.getLogger("xstate_statemachine")
    h = H()
    lg.addHandler(h)
    old = lg.level
    lg.setLevel(logging.DEBUG)
    secret = "IBAN-SECRET-9999"

    async def probe():
        cfg = {
            "id": "red",
            "initial": "a",
            "context": {"iban": secret, "plain": "visible"},
            "states": {"a": {}},
        }
        i = Interpreter(create_machine(cfg, logic=MachineLogic()))
        await i.start()
        i.get_snapshot()
        i.get_persisted_snapshot()
        await i.stop()

    asyncio.run(probe())
    lg.setLevel(old)
    lg.removeHandler(h)
    leaked = [m for m in logs if secret in m]
    return {
        "missing_exports": missing,
        "public_names_total": len(all_names),
        "missing_plugin_hooks": hooks,
        "Interpreter_has_service_executor": has_exec,
        "Receipt_has_denied": has_denied,
        "debug_log_lines": len(logs),
        "secret_leaks_in_logs": len(leaked),
        "leak_sample": leaked[:1],
        "pass": not missing
        and not hooks
        and has_exec
        and has_denied
        and not leaked,
    }


def main() -> int:
    res = {"a_determinism": asyncio.run(a_determinism())}
    res["b_hash_seed"] = b_hash_seed()
    res["c_surface"] = c_surface()
    res["result"] = (
        "PASS"
        if all(v["pass"] for v in res.values() if isinstance(v, dict))
        else "FAIL"
    )
    emit("p6_determinism_surface", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
