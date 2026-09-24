"""N6 -- observability & security surface for the round-4 additions.

O1  Hook matrix: does every new error class reach a plugin hook, or only an
    exception at the call site? An OMS's audit log is built from hooks; an
    error that raises but emits nothing is invisible to the log.
      - SnapshotMidStepError, SnapshotCorruptError, SnapshotSerializationError,
        InvalidEventError, RootTargetError/InvalidConfigError, RunawayChainError
O2  on_plugin_error: an `async def` hook on the sync engine, and a hook that
    raises (including CancelledError), must be reported -- not silently skipped.
O3  on_resolve_error: a `sendTo` to an unresolvable target.
S1  LoggingInspector redaction: sensitive keys must not appear in log output.
S2  Exported API surface: every name promised by #137 is importable and every
    new error class is in __all__.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import xstate_statemachine as xsm  # noqa: E402
from xstate_statemachine import (  # noqa: E402
    Interpreter,
    LoggingInspector,
    MachineLogic,
    PluginBase,
    SyncInterpreter,
    create_machine,
)


class Spy(PluginBase):
    """Records every `on_*` hook PluginBase declares.

    NOTE: `__getattr__` does NOT work here -- PluginBase defines the hooks as
    real (no-op) methods, so attribute lookup never falls through. The hooks
    must be bound explicitly, which is done below the class body.
    """

    def __init__(self):
        self.calls = []


def _bind_spy_hooks():
    names = [
        n
        for n in dir(PluginBase)
        if n.startswith("on_") and callable(getattr(PluginBase, n))
    ]

    def make(name):
        def hook(self, *a, **kw):
            # 🧯 `reason` is passed POSITIONALLY by the library
            #    (base_interpreter.py:2956), so kwargs-only inspection
            #    reports None. Record both.
            self.calls.append(
                (name, kw.get("reason"), str(a)[:400], str(kw)[:80])
            )

        return hook

    for n in names:
        setattr(Spy, n, make(n))
    return names


SPY_HOOKS = _bind_spy_hooks()


class AsyncHookPlugin(PluginBase):
    def __init__(self):
        self.ran = False

    async def on_transition(self, *a, **kw):  # wrong: async on sync engine
        self.ran = True


class RaisingPlugin(PluginBase):
    def __init__(self, exc):
        self.exc = exc

    def on_transition(self, *a, **kw):
        raise self.exc


SIMPLE = {
    "id": "ob",
    "initial": "a",
    "context": {"n": 0},
    "states": {"a": {"on": {"GO": "b"}}, "b": {"on": {"GO": "a"}}},
}


def mk():
    return create_machine(SIMPLE, logic=MachineLogic())


# ------------------------------------------------------------------- O1
def o1_midstep():
    """Snapshot inside an action: does any hook see the refusal?"""
    spy = Spy()
    res = {}

    def grab(i, c, e, a):
        try:
            i.get_persisted_snapshot()
            res["raise"] = "NO-RAISE"
        except Exception as ex:  # noqa: BLE001
            res["raise"] = type(ex).__name__

    cfg = {
        "id": "ms",
        "initial": "a",
        "states": {
            "a": {"on": {"GO": {"target": "b", "actions": ["grab"]}}},
            "b": {},
        },
    }
    m = create_machine(cfg, logic=MachineLogic(actions={"grab": grab}))
    i = SyncInterpreter(m)
    i.use(spy)
    i.start()
    i.send("GO")
    i.stop()
    res["hooks_seen"] = sorted({c[0] for c in spy.calls})
    res["error_hook_fired"] = any(
        "error" in c[0] or "failed" in c[0] or "dropped" in c[0]
        for c in spy.calls
    )
    return res


def o1_invalid_event():
    spy = Spy()
    i = SyncInterpreter(mk())
    i.use(spy)
    i.start()
    out = {}
    try:
        i.send(42)
        out["raise"] = "NO-RAISE"
    except Exception as e:  # noqa: BLE001
        out["raise"] = type(e).__name__
    i.stop()
    out["hooks_seen"] = sorted({c[0] for c in spy.calls})
    out["error_hook_fired"] = any(
        "error" in c[0] or "dropped" in c[0] or "failed" in c[0]
        for c in spy.calls
    )
    return out


def o1_corrupt_snapshot():
    spy = Spy()
    out = {}
    try:
        SyncInterpreter.from_snapshot('{"status": "bogus"}', mk())
        out["raise"] = "NO-RAISE"
    except Exception as e:  # noqa: BLE001
        out["raise"] = type(e).__name__
    out["note"] = "from_snapshot is a classmethod: no interpreter exists yet, so no hook can fire by construction"
    return out


def o1_serialization():
    """Non-JSON pending payload -> SnapshotSerializationError (#131)."""
    out = {}

    class Unser:
        pass

    cfg = {
        "id": "ser",
        "initial": "a",
        "onUnhandled": "defer",
        "states": {"a": {"on": {"GO": "a"}}},
    }
    i = SyncInterpreter(create_machine(cfg, logic=MachineLogic()))
    spy = Spy()
    i.use(spy)
    i.start()
    try:
        i.send("NOPE", blob=Unser())
    except Exception as e:  # noqa: BLE001
        out["send_raise"] = type(e).__name__
    try:
        i.get_persisted_snapshot()
        out["snapshot_raise"] = "NO-RAISE"
    except Exception as e:  # noqa: BLE001
        out["snapshot_raise"] = type(e).__name__
    i.stop()
    out["hooks_seen"] = sorted({c[0] for c in spy.calls})
    return out


# ------------------------------------------------------------------- O2
def o2_plugin_errors():
    out = {}
    # async hook on the sync engine (#127)
    p = AsyncHookPlugin()
    i = SyncInterpreter(mk())
    i.use(p)
    i.start()
    i.send("GO")
    out["async_hook_ran"] = p.ran
    out["last_plugin_error"] = repr(getattr(i, "last_plugin_error", "ATTR-MISSING"))[:140]
    i.stop()

    # a hook that raises, incl. CancelledError (#114)
    for label, exc in (
        ("ValueError", ValueError("boom")),
        ("CancelledError", asyncio.CancelledError()),
    ):
        spy = Spy()
        j = SyncInterpreter(mk())
        j.use(RaisingPlugin(exc))
        j.use(spy)
        try:
            j.start()
            j.send("GO")
            out[f"{label}_contained"] = True
        except BaseException as e:  # noqa: BLE001
            out[f"{label}_contained"] = False
            out[f"{label}_escaped_as"] = type(e).__name__
        out[f"{label}_status"] = j.status
        out[f"{label}_last_plugin_error"] = repr(
            getattr(j, "last_plugin_error", "ATTR-MISSING")
        )[:120]
        out[f"{label}_on_plugin_error_fired"] = any(
            c[0] == "on_plugin_error" for c in spy.calls
        )
        try:
            j.stop()
        except Exception:  # noqa: BLE001
            pass
    return out


# ------------------------------------------------------------------- O3
def o3_resolve_error():
    cfg = {
        "id": "re",
        "initial": "a",
        "states": {
            "a": {
                "on": {
                    "GO": {
                        "actions": [
                            {
                                "type": "sendTo",
                                "params": {"to": "ghost", "event": "X"},
                            }
                        ]
                    }
                }
            }
        },
    }
    spy = Spy()
    i = SyncInterpreter(create_machine(cfg, logic=MachineLogic()))
    i.use(spy)
    i.start()
    i.send("GO")
    i.stop()
    return {
        "hooks_seen": sorted({c[0] for c in spy.calls}),
        "on_resolve_error_fired": any(
            c[0] == "on_resolve_error" for c in spy.calls
        ),
        "on_event_dropped_fired": any(
            c[0] == "on_event_dropped" for c in spy.calls
        ),
        "drop_reasons": [
            (c[1], c[2]) for c in spy.calls if c[0] == "on_event_dropped"
        ],
        "unresolved_target_reported": any(
            c[0] == "on_event_dropped"
            and ("unresolved_target" in str(c[1]) or "unresolved_target" in c[2])
            for c in spy.calls
        ),
    }


# ------------------------------------------------------------------- S1
SECRET_KEYS = [
    "password",
    "api_key",
    "apiKey",
    "token",
    "secret",
    "authorization",
    "access_token",
    "client_secret",
    "private_key",
    "ssn",
    "card_number",
    "cvv",
]


def s1_redaction():
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    root = logging.getLogger("xstate_statemachine")
    prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    root.setLevel(logging.DEBUG)
    root.addHandler(h)

    payload = {k: f"LEAK-{k}-VALUE" for k in SECRET_KEYS}
    payload["benign"] = "VISIBLE-OK"

    i = SyncInterpreter(mk())
    i.use(LoggingInspector())
    i.start()
    i.send("GO", **payload)
    i.stop()

    root.removeHandler(h)
    logging.disable(prev_disable)
    text = buf.getvalue()
    leaked = [k for k in SECRET_KEYS if f"LEAK-{k}-VALUE" in text]
    return {
        "log_chars": len(text),
        "benign_value_present": "VISIBLE-OK" in text,
        "leaked_keys": leaked,
        "redacted_keys": [k for k in SECRET_KEYS if k not in leaked],
        "OK": not leaked,
    }


# ------------------------------------------------------------------- S2
PROMISED = [
    "is_system_event",
    "system_event",
    "DoneEvent",
    "AfterEvent",
    "ENGINE_EVENT_SHAPES",
    "SYSTEM_EVENT_PREFIXES",
    "ErrorEvent",
    "SnapshotMidStepError",
    "SnapshotCorruptError",
    "SnapshotSerializationError",
    "InvalidEventError",
    "RootTargetError",
    "RunawayChainError",
    "OverflowPolicy",
    "Receipt",
    "PendingInvocation",
    "SimulatedClock",
]


def s2_api():
    rows = {}
    for name in PROMISED:
        rows[name] = {
            "importable": hasattr(xsm, name),
            "in___all__": name in getattr(xsm, "__all__", []),
        }
    missing = [k for k, v in rows.items() if not v["importable"]]
    not_all = [k for k, v in rows.items() if not v["in___all__"]]
    return {
        "checked": len(PROMISED),
        "not_importable": missing,
        "not_in___all__": not_all,
        "version_string": xsm.__version__,
        "OK": not missing and not not_all,
    }


def main():
    logging.disable(logging.CRITICAL)
    res = {
        "spy_hooks_bound": SPY_HOOKS,
        "O1_midstep": o1_midstep(),
        "O1_invalid_event": o1_invalid_event(),
        "O1_corrupt_snapshot": o1_corrupt_snapshot(),
        "O1_serialization": o1_serialization(),
        "O2_plugin_errors": o2_plugin_errors(),
        "O3_resolve_error": o3_resolve_error(),
        "S1_redaction": s1_redaction(),
        "S2_api_surface": s2_api(),
    }
    for k, v in res.items():
        print(f"\n== {k} ==")
        if not isinstance(v, dict):
            print(f"   {v}")
            continue
        for kk, vv in v.items():
            print(f"   {kk:32s}: {vv}")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "n6_observability.json"), "w") as f:
        json.dump(res, f, indent=2, default=str)
    print("\nwrote out/n6_observability.json")


if __name__ == "__main__":
    main()
