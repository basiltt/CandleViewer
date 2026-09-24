"""R7 - SECURITY: can user code forge the engine-completion marker?

#179/#180 make chain-budget accounting depend on ONE bit: was this event
minted by the engine (`_ENGINE_MARK` in `Event._provenance`, and the
`engine_completion=True` kwarg on `_deliver_priority`)? If user code can
set that bit, it can either (a) exempt its own flood from the budget or
(b) get its own traffic charged and shed as `chain_budget`.

Four forgery routes, plus redaction and the `__slots__` surface:
  F1  Event subclass that overrides `system` / sets `_provenance`
  F2  `dataclasses.replace()` on a genuine engine DoneEvent
  F3  `send_threadsafe(..., internal=True)` from outside
  F4  capture a real `DoneEvent` from a hook and `sendTo`/`send` it back
  F5  reach `_ENGINE_MARK` by name / pickle round-trip / copy
  F6  call the private `_deliver_priority(..., engine_completion=True)`

Every route is scored on what the ENGINE believed, not on whether the call
raised. Both service kinds.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import pickle

from common2 import (
    Interpreter,
    MachineLogic,
    PluginBase,
    create_machine,
    emit,
    make_service,
)
from xstate_statemachine import Event
from xstate_statemachine.events import DoneEvent, is_system_event

CFG = {
    "id": "r7",
    "initial": "a",
    "context": {"n": 0, "secret": "hunter2-TOPSECRET"},
    "states": {
        "a": {
            "invoke": {"src": "s", "onDone": {"target": "b"}},
            "on": {"X": {"actions": ["bump"]}},
        },
        "b": {"on": {"X": {"actions": ["bump"]}}},
    },
}


def bump(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] = ctx.get("n", 0) + 1


class Grab(PluginBase):
    def __init__(self) -> None:
        self.done = None

    def on_event_received(self, i, e):  # noqa: ANN001
        if isinstance(e, DoneEvent) and self.done is None:
            self.done = e


def mk(kind: str):
    return create_machine(
        CFG, logic=MachineLogic(actions={"bump": bump}, services={"s": make_service(kind)})
    )


async def case(kind: str) -> dict:
    g = Grab()
    itp = Interpreter(mk(kind)).use(g)
    await asyncio.wait_for(itp.start(), 10)
    await asyncio.sleep(0.2)
    out = {}

    # --- F1: Event subclass ---
    class Forged(Event):
        @property
        def system(self):  # noqa: ANN001
            return True

    try:
        f = Forged(type="done.invoke.s")
        out["F1_subclass_overrides_system_property"] = bool(f.system)
        out["F1_engine_believes_is_system_event"] = bool(is_system_event(f))
    except Exception as exc:  # noqa: BLE001
        out["F1_subclass"] = f"refused:{type(exc).__name__}"

    # F1b: write the private slot directly
    try:
        e = Event(type="done.invoke.s")
        object.__setattr__(e, "_provenance", "not-the-mark")
        out["F1b_arbitrary_provenance_accepted_as_system"] = bool(
            is_system_event(e)
        )
    except Exception as exc:  # noqa: BLE001
        out["F1b"] = f"refused:{type(exc).__name__}"

    # --- F2: dataclasses.replace on a genuine engine event ---
    genuine = g.done
    out["F2_captured_a_genuine_DoneEvent"] = genuine is not None
    if genuine is not None:
        out["F2_genuine_is_system"] = bool(is_system_event(genuine))
        try:
            r = dataclasses.replace(genuine, type="done.invoke.s")
            out["F2_replace_preserves_engine_status"] = bool(is_system_event(r))
        except Exception as exc:  # noqa: BLE001
            out["F2_replace"] = f"refused:{type(exc).__name__}"
        out["F2_copy_preserves"] = bool(is_system_event(copy.copy(genuine)))
        out["F2_deepcopy_preserves"] = bool(is_system_event(copy.deepcopy(genuine)))
        try:
            out["F2_pickle_roundtrip_preserves"] = bool(
                is_system_event(pickle.loads(pickle.dumps(genuine)))
            )
        except Exception as exc:  # noqa: BLE001
            out["F2_pickle"] = f"refused:{type(exc).__name__}"

    # --- F3: internal=True from outside ---
    depth0 = getattr(itp, "_raise_depth", None)
    try:
        itp.send_threadsafe("X", internal=True)
        await asyncio.sleep(0.15)
        out["F3_internal_true_accepted_from_outside"] = True
        out["F3_raise_depth_before_after"] = [depth0, getattr(itp, "_raise_depth", None)]
    except TypeError as exc:
        out["F3_internal_true"] = f"refused:{type(exc).__name__}"

    # --- F4: re-send a captured engine DoneEvent ---
    if genuine is not None:
        try:
            await asyncio.wait_for(itp.send(genuine, wait=True), 5)
            out["F4_resend_captured_DoneEvent"] = "ACCEPTED"
            out["F4_still_system_on_resend"] = bool(is_system_event(genuine))
        except Exception as exc:  # noqa: BLE001
            out["F4_resend_captured_DoneEvent"] = f"refused:{type(exc).__name__}"

    # --- F5: obtain the marker by name ---
    try:
        import xstate_statemachine.events as evmod

        mark = getattr(evmod, "_ENGINE_MARK")
        forged = Event(type="done.invoke.s")
        object.__setattr__(forged, "_provenance", mark)
        out["F5_marker_reachable_by_module_attribute"] = True
        out["F5_forged_with_real_marker_is_system"] = bool(is_system_event(forged))
        out["F5_marker_pickle_resolves_to_same_object"] = (
            pickle.loads(pickle.dumps(mark)) is mark
        )
    except Exception as exc:  # noqa: BLE001
        out["F5"] = f"refused:{type(exc).__name__}"

    # --- F6: call the private charged lane directly ---
    try:
        itp._deliver_priority(Event(type="X"), engine_completion=True)
        await asyncio.sleep(0.1)
        out["F6_private_charged_lane_callable"] = True
    except Exception as exc:  # noqa: BLE001
        out["F6_private_charged_lane_callable"] = f"refused:{type(exc).__name__}"

    # --- redaction / __slots__ surface ---
    out["secret_in_interpreter_repr"] = "hunter2" in repr(itp)
    out["secret_in_interpreter_str"] = "hunter2" in str(itp)
    blob = itp.get_persisted_snapshot()
    out["secret_in_snapshot"] = "hunter2" in str(blob)
    out["interpreter_has___dict__"] = hasattr(itp, "__dict__")
    try:
        itp._chain_owed = 999
        out["private_budget_counter_writable_from_outside"] = (
            getattr(itp, "_chain_owed") == 999
        )
        itp._chain_owed = 0
    except Exception as exc:  # noqa: BLE001
        out["private_budget_counter_writable_from_outside"] = (
            f"refused:{type(exc).__name__}"
        )

    await asyncio.wait_for(itp.stop(), 20)
    return {"service_kind": kind, **out}


async def main() -> int:
    rows = [await case(k) for k in ("def", "async def")]
    # A forgery SUCCEEDS if user code got `is_system_event` to say True for
    # an event the engine did not mint.
    forged = []
    for r in rows:
        for key in (
            "F1_engine_believes_is_system_event",
            "F1b_arbitrary_provenance_accepted_as_system",
            "F5_forged_with_real_marker_is_system",
        ):
            if r.get(key) is True:
                forged.append((r["service_kind"], key))
    leaks = [
        (r["service_kind"], k)
        for r in rows
        for k in ("secret_in_interpreter_repr", "secret_in_interpreter_str")
        if r.get(k) is True
    ]
    emit(
        "r7_engine_marker_forgery",
        {
            "rows": rows,
            "successful_forgeries": forged,
            "secret_leaks": leaks,
            "result": "FAIL" if forged or leaks else "PASS",
        },
    )
    return 1 if forged or leaks else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
