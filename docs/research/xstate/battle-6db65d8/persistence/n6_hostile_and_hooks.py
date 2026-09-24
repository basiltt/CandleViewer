# -*- coding: utf-8 -*-
"""N6 -- persistence-adjacent hostile inputs and observability.

A. InvalidEventError (#113): a non-`str` event `type` must raise
   `InvalidEventError` (and be a `TypeError`) rather than escape the
   hierarchy -- tested on the live `send()` path AND on the RESTORE path,
   which is the persistence-relevant half: a hostile blob whose pending
   record carries a non-str `type` must not mint an un-typed event.

B. SnapshotSerializationError (#131): non-JSON pending data must raise a
   typed error at snapshot time rather than being stringified into the blob
   (silent data mutation across a restore).

C. Observability hook matrix over the persistence path: for each new error
   class, does the documented hook fire? Includes `on_plugin_error` /
   `last_plugin_error` (#127) with an `async def` hook on the sync-ish path,
   and `on_resolve_error` (#134).

D. Security: `LoggingInspector` redaction (#126) -- does a snapshot-shaped
   context with secret-looking keys get redacted in the log stream?

E. Exported provenance API surface (#137): the names the CHANGELOG says are
   public must be importable from the package root.
"""
from __future__ import annotations

import asyncio
import json
import logging

from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.clock import SimulatedClock
from xstate_statemachine.plugins import PluginBase

import order_machine

SIMPLE = {
    "id": "hx",
    "initial": "a",
    "context": {"n": 0, "password": "hunter2", "api_key": "sk-live-abc",
                "qty": 5},
    "states": {"a": {"on": {"GO": {"target": "b", "actions": ["bump"]}}},
               "b": {"on": {"BACK": {"target": "a"}}}},
}


def bump(i, ctx, e, ad): ctx["n"] += 1      # noqa: ANN001,E704


def build_simple():
    return create_machine(SIMPLE, logic=MachineLogic(actions={"bump": bump}))


async def test_a() -> None:
    print("=== A. InvalidEventError over hostile event types (#113) ===")
    from xstate_statemachine.exceptions import InvalidEventError
    i = Interpreter(build_simple(), clock=SimulatedClock())
    await i.start(); await asyncio.sleep(0.02)

    hostile = [42, None, 3.5, b"GO", ["GO"], {"type": "GO"}, object(),
               True, (1, 2)]
    live_ok = 0
    live_bad = []
    for h in hostile:
        try:
            await i.send(h)          # type: ignore[arg-type]
            live_bad.append(f"{h!r}: ACCEPTED")
        except InvalidEventError as exc:
            assert isinstance(exc, TypeError), "not also a TypeError"
            live_ok += 1
        except Exception as exc:  # noqa: BLE001
            live_bad.append(f"{type(h).__name__}: {type(exc).__name__}: {exc}")
    print(f"   live send(): typed {live_ok}/{len(hostile)}")
    for b in live_bad:
        print(f"      LEAK {b[:110]}")
    blob = i.get_snapshot()
    await i.stop()

    # restore path: a hostile pending record
    restore_bad = []
    restore_ok = 0
    for bad_type in (42, None, ["GO"], {"x": 1}, True):
        d = json.loads(blob)
        d["pending_events"] = [{"kind": "event", "type": bad_type,
                                "payload": {}}]
        try:
            j = Interpreter.from_snapshot(json.dumps(d), build_simple(),
                                          clock=SimulatedClock())
            await j.start(); await asyncio.sleep(0.03)
            restore_bad.append(
                f"type={bad_type!r}: ACCEPTED, status={j.status}")
            if j.status == "running":
                await j.stop()
        except (InvalidEventError,) as exc:
            restore_ok += 1
        except Exception as exc:  # noqa: BLE001
            from xstate_statemachine.exceptions import XStateMachineError
            if isinstance(exc, XStateMachineError):
                restore_ok += 1
            else:
                restore_bad.append(
                    f"type={bad_type!r}: RAW {type(exc).__name__}: {exc}")
    print(f"   restore path: typed/refused {restore_ok}/5")
    for b in restore_bad:
        print(f"      LEAK {b[:130]}")
    print(f"   VERDICT = {not live_bad and not restore_bad}")


async def test_b() -> None:
    print("\n=== B. SnapshotSerializationError for non-JSON pending (#131) ===")
    from xstate_statemachine.exceptions import SnapshotSerializationError
    i = Interpreter(build_simple(), clock=SimulatedClock())
    await i.start(); await asyncio.sleep(0.02)
    i._processing = True                 # hold the inbox
    await i.send("GO", payload_obj=object())
    await asyncio.sleep(0.02)
    i._processing = False
    try:
        blob = i.get_snapshot()
        d = json.loads(blob)
        recs = d.get("pending_events", [])
        stringified = any("object object at" in json.dumps(r) for r in recs)
        print(f"   snapshot SUCCEEDED; pending={json.dumps(recs)[:160]}")
        print(f"   silently stringified = {stringified}  <- must be False")
        ok = not stringified
    except SnapshotSerializationError as exc:
        print(f"   SnapshotSerializationError: {str(exc)[:160]}")
        ok = True
    except Exception as exc:  # noqa: BLE001
        print(f"   RAW {type(exc).__name__}: {str(exc)[:160]}")
        ok = False
    print(f"   VERDICT = {ok}")
    try:
        await i.stop()
    except Exception:  # noqa: BLE001
        pass


class HookSpy(PluginBase):
    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    def _rec(self, name): self.calls[name] = self.calls.get(name, 0) + 1  # noqa: E704

    def on_plugin_error(self, *a, **k): self._rec("on_plugin_error")       # noqa: E704
    def on_resolve_error(self, *a, **k): self._rec("on_resolve_error")     # noqa: E704
    def on_event_dropped(self, *a, **k): self._rec("on_event_dropped")     # noqa: E704
    def on_transition(self, *a, **k): self._rec("on_transition")           # noqa: E704
    def on_action_execute(self, *a, **k): self._rec("on_action_execute")   # noqa: E704


class AsyncHook(PluginBase):
    """#127: an `async def` hook must be reported, not silently skipped."""
    def __init__(self) -> None:
        self.ran = 0

    async def on_transition(self, *a, **k):  # noqa: ANN001
        self.ran += 1


async def test_c() -> None:
    print("\n=== C. hook matrix on the persistence path (#127/#134) ===")
    spy = HookSpy()
    ah = AsyncHook()
    i = Interpreter(build_simple(), clock=SimulatedClock())
    i.use(spy); i.use(ah)
    await i.start(); await asyncio.sleep(0.02)
    await i.send("GO"); await asyncio.sleep(0.03)
    blob = i.get_snapshot()
    await i.stop()

    print(f"   async-def hook actually ran   : {ah.ran}")
    print(f"   on_plugin_error fired (#127)  : {spy.calls.get('on_plugin_error', 0)}")
    print(f"   last_plugin_error             : "
          f"{str(getattr(i, 'last_plugin_error', 'NO ATTR'))[:100]}")

    # restore, then drive the restored machine and check hooks still fire
    spy2 = HookSpy()
    j = Interpreter.from_snapshot(blob, build_simple(),
                                  clock=SimulatedClock())
    j.use(spy2)
    await j.start(); await asyncio.sleep(0.02)
    await j.send("BACK"); await asyncio.sleep(0.03)
    print(f"   hooks on the RESTORED machine : {dict(sorted(spy2.calls.items()))}")
    await j.stop()
    ok = (ah.ran == 0 and spy.calls.get("on_plugin_error", 0) > 0
          and spy2.calls.get("on_transition", 0) > 0) or ah.ran > 0
    print(f"   VERDICT async hook either runs or is reported = {ok}")


async def test_d() -> None:
    print("\n=== D. LoggingInspector redaction (#126) ===")
    from xstate_statemachine.plugins import LoggingInspector
    buf: list[str] = []

    class Cap(logging.Handler):
        def emit(self, record): buf.append(self.format(record))  # noqa: E704

    lg = logging.getLogger("xstate_statemachine")
    h = Cap(); h.setFormatter(logging.Formatter("%(message)s"))
    lg.addHandler(h); lg.setLevel(logging.DEBUG)
    try:
        i = Interpreter(build_simple(), clock=SimulatedClock())
        i.use(LoggingInspector())
        await i.start(); await asyncio.sleep(0.02)
        await i.send("GO", password="hunter2", api_key="sk-live-abc",
                     token="t0ps3cret", qty=9)
        await asyncio.sleep(0.03)
        await i.stop()
    finally:
        lg.removeHandler(h)
    text = "\n".join(buf)
    leaked = [s for s in ("hunter2", "sk-live-abc", "t0ps3cret")
              if s in text]
    print(f"   log lines captured : {len(buf)}")
    print(f"   secrets LEAKED     : {leaked}  <- must be []")
    print(f"   'qty' still visible: {'qty' in text} (redaction must be "
          "targeted, not blanket)")
    print(f"   VERDICT = {not leaked}")


def test_e() -> None:
    print("\n=== E. exported provenance API surface (#137) ===")
    import xstate_statemachine as pkg
    names = ["is_system_event", "system_event", "DoneEvent", "AfterEvent",
             "ErrorEvent", "Event", "ENGINE_EVENT_SHAPES",
             "SnapshotMidStepError", "SnapshotCorruptError",
             "SnapshotSerializationError", "InvalidEventError",
             "SnapshotDriftError", "SnapshotVersionError"]
    missing = [n for n in names if not hasattr(pkg, n)]
    not_in_all = [n for n in names
                  if n not in getattr(pkg, "__all__", []) and hasattr(pkg, n)]
    print(f"   importable from package root : {len(names) - len(missing)}/{len(names)}")
    if missing:
        print(f"   MISSING      : {missing}")
    if not_in_all:
        print(f"   not in __all__: {not_in_all}")
    print(f"   VERDICT = {not missing and not not_in_all}")


async def main() -> None:
    await test_a(); await test_b(); await test_c(); await test_d()
    test_e()


if __name__ == "__main__":
    asyncio.run(main())
