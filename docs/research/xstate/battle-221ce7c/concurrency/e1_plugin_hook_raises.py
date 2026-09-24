"""(e) An exception raised inside a plugin hook.

A plugin is an OBSERVER. Nothing in `PluginBase`'s contract says a hook may
not raise -- a metrics push that times out, a JSON encode that chokes on a
payload, an audit write to a full disk. The question is what an observer's
failure does to the machine it is observing.

No hook dispatch site in the engine is wrapped in try/except; every one is
a bare `for plugin in self._plugins: plugin.on_x(...)`:

    base_interpreter.py:2544  on_action_execute
    base_interpreter.py:2610  on_action_error
    base_interpreter.py:3350  on_unhandled_event
    base_interpreter.py:3531  on_error
    base_interpreter.py:3559  on_done
    base_interpreter.py:4165  on_guard_error
    base_interpreter.py:4181  on_guard_evaluated
    interpreter.py:853        on_event_dropped (queue_full)
    interpreter.py:804        on_event_dropped (not_running)
    interpreter.py:1211/1240  on_event_received / chain_budget

For each hook this probe raises from exactly one plugin and records:
  * does the transition still commit?
  * is the configuration consistent afterwards (exactly one leaf)?
  * is the machine still `running` and able to process the NEXT event?
  * does a SECOND, innocent plugin still get its callback? (an observer
    must not be able to blind another observer)
  * is the failure visible to the application, or swallowed?
"""

from __future__ import annotations

import asyncio

from common import emit
from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine
from xstate_statemachine.models import OverflowPolicy


class Boom(RuntimeError):
    pass


class Exploder(PluginBase):
    """Raises from exactly one named hook; records which hooks it saw."""

    def __init__(self, hook: str):
        self.hook = hook
        self.seen: list[str] = []

    def _maybe(self, name: str):
        self.seen.append(name)
        if name == self.hook:
            raise Boom(f"plugin exploded in {name}")

    def on_interpreter_start(self, i):  # noqa: ANN001
        self._maybe("on_interpreter_start")

    def on_interpreter_stop(self, i):  # noqa: ANN001
        self._maybe("on_interpreter_stop")

    def on_event_received(self, i, e):  # noqa: ANN001
        self._maybe("on_event_received")

    def on_transition(self, i, f, t, tr):  # noqa: ANN001
        self._maybe("on_transition")

    def on_action_execute(self, i, a):  # noqa: ANN001
        self._maybe("on_action_execute")

    def on_action_error(self, i, a, exc):  # noqa: ANN001
        self._maybe("on_action_error")

    def on_guard_evaluated(self, i, g, e, r):  # noqa: ANN001
        self._maybe("on_guard_evaluated")

    def on_guard_error(self, i, g, e, exc):  # noqa: ANN001
        self._maybe("on_guard_error")

    def on_unhandled_event(self, i, e, a, d):  # noqa: ANN001
        self._maybe("on_unhandled_event")

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self._maybe("on_event_dropped")

    def on_error(self, i, err):  # noqa: ANN001
        self._maybe("on_error")

    def on_done(self, i, out):  # noqa: ANN001
        self._maybe("on_done")


class Innocent(PluginBase):
    """A well-behaved second observer registered AFTER the exploder."""

    def __init__(self):
        self.calls: dict[str, int] = {}

    def _c(self, n):
        self.calls[n] = self.calls.get(n, 0) + 1

    def on_event_received(self, i, e):  # noqa: ANN001
        self._c("on_event_received")

    def on_transition(self, i, f, t, tr):  # noqa: ANN001
        self._c("on_transition")

    def on_action_execute(self, i, a):  # noqa: ANN001
        self._c("on_action_execute")

    def on_guard_evaluated(self, i, g, e, r):  # noqa: ANN001
        self._c("on_guard_evaluated")

    def on_event_dropped(self, i, e, r):  # noqa: ANN001
        self._c("on_event_dropped")

    def on_unhandled_event(self, i, e, a, d):  # noqa: ANN001
        self._c("on_unhandled_event")

    def on_done(self, i, out):  # noqa: ANN001
        self._c("on_done")

    def on_error(self, i, err):  # noqa: ANN001
        self._c("on_error")


# --------------------------------------------------------------------------
CFG = {
    "id": "pl",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {
            "on": {
                "GO": {"target": "b", "actions": ["bump"], "guard": "yes"},
                "BADGUARD": {"target": "b", "guard": "raises"},
                "FINISH": {"target": "done_"},
            }
        },
        "b": {"on": {"BACK": {"target": "a"}, "FINISH": {"target": "done_"}}},
        "done_": {"type": "final"},
    },
}


def bump(i, ctx, e, ad):  # noqa: ANN001
    ctx["n"] += 1


def yes(ctx, e):  # noqa: ANN001  (guards are (context, event))
    return True


def raises(ctx, e):  # noqa: ANN001  (guards are (context, event))
    raise ValueError("guard blew up")


def machine(policy="continue", guard_policy="raise"):
    cfg = dict(CFG)
    cfg["actionErrorPolicy"] = policy
    cfg["guardErrorPolicy"] = guard_policy
    return create_machine(
        cfg,
        logic=MachineLogic(
            actions={"bump": bump}, guards={"yes": yes, "raises": raises}
        ),
    )


async def probe(hook: str, trigger: str = "GO") -> dict:
    boom = Exploder(hook)
    good = Innocent()
    kw = {}
    if hook == "on_event_dropped":
        kw = dict(max_queue_size=1, overflow_policy=OverflowPolicy.DROP_NEWEST)
    i = Interpreter(machine(), **kw)
    i.use(boom)
    i.use(good)

    start_error = None
    try:
        await i.start()
    except Exception as exc:  # noqa: BLE001
        start_error = f"{type(exc).__name__}: {exc}"
        return {
            "hook": hook,
            "raised_from_start": start_error,
            "status": i.status,
            "states": sorted(i.current_state_ids),
        }

    send_error = None
    receipt = None
    try:
        if hook == "on_event_dropped":
            # Overfill the bounded inbox so DROP_NEWEST fires the hook.
            for _ in range(5):
                await i.send("GO")
            await asyncio.sleep(0.05)
        elif hook == "on_unhandled_event":
            r = await asyncio.wait_for(i.send("NOPE", wait=True), 5)
            receipt = (r.changed, repr(r.error))
        elif hook == "on_guard_error":
            r = await asyncio.wait_for(i.send("BADGUARD", wait=True), 5)
            receipt = (r.changed, repr(r.error))
        elif hook in ("on_done", "on_error"):
            r = await asyncio.wait_for(i.send("FINISH", wait=True), 5)
            receipt = (r.changed, repr(r.error))
        else:
            r = await asyncio.wait_for(i.send(trigger, wait=True), 5)
            receipt = (r.changed, repr(r.error))
    except Exception as exc:  # noqa: BLE001
        send_error = f"{type(exc).__name__}: {exc}"

    await asyncio.sleep(0.05)
    states_after = sorted(i.current_state_ids)
    status_after = i.status

    # Can the machine still work?
    next_ok = None
    next_err = None
    if status_after == "running":
        try:
            ev = "BACK" if "pl.b" in states_after else "GO"
            r2 = await asyncio.wait_for(i.send(ev, wait=True), 5)
            next_ok = (r2.changed, repr(r2.error))
        except Exception as exc:  # noqa: BLE001
            next_err = f"{type(exc).__name__}: {exc}"

    out = {
        "hook": hook,
        "raised_to_caller": send_error,
        "trigger_receipt": receipt,
        "states_after": states_after,
        "exactly_one_leaf": len(states_after) == 1,
        "status_after": status_after,
        "context_n": i.context["n"],
        "last_transition_ok": i.last_transition_ok,
        "last_error": repr(i.last_error),
        "next_event_receipt": next_ok,
        "next_event_exception": next_err,
        "second_plugin_still_called": dict(good.calls),
        "exploder_hooks_seen": sorted(set(boom.seen)),
    }
    try:
        await i.stop()
    except Exception as exc:  # noqa: BLE001
        out["raised_from_stop"] = f"{type(exc).__name__}: {exc}"
    return out


HOOKS = [
    "on_interpreter_start",
    "on_event_received",
    "on_transition",
    "on_action_execute",
    "on_guard_evaluated",
    "on_guard_error",
    "on_unhandled_event",
    "on_event_dropped",
    "on_done",
    "on_interpreter_stop",
]


async def main():
    res = {}
    for h in HOOKS:
        try:
            res[h] = await probe(h)
        except Exception as exc:  # noqa: BLE001
            res[h] = {"hook": h, "PROBE_CRASHED": f"{type(exc).__name__}: {exc}"}
    emit("e1_plugin_hook_raises", res)


if __name__ == "__main__":
    asyncio.run(main())
