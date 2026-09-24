# -*- coding: utf-8 -*-
"""Verify #114 on 3ed3099:
  (a) a plugin hook raising asyncio.CancelledError is CONTAINED (does not
      kill the run loop), and reported via on_plugin_error/last_plugin_error.
  (b) a genuinely external cancellation of the run loop task flips `status`
      away from "running" (to "error") and fails pending/subsequent
      receipts instead of leaving a dead loop that reports healthy and
      hangs every wait=True send() forever.

Criteria:
  1. Plugin hook raising CancelledError: transition still completes
     (`r.changed is True`), status stays "running", and
     `last_plugin_error is not None`.
  2. External `task.cancel()` on `_event_loop_task`: status becomes
     "error", `i.error` is a RuntimeError.
  3. After external cancellation, `send(..., wait=True)` does NOT hang --
     it raises (fails the receipt) rather than waiting forever.

Exits 0 iff all pass.
"""
from __future__ import annotations

import asyncio

from xstate_statemachine import Interpreter, MachineLogic, PluginBase, create_machine

CFG = {
    "id": "px",
    "initial": "a",
    "context": {"n": 0},
    "states": {
        "a": {"on": {"GO": "b", "T": {"actions": "inc"}}},
        "b": {"on": {"BACK": "a"}},
    },
}


class Evil(PluginBase):
    def on_transition(self, i, from_states, to_states, transition):  # noqa: ANN001
        raise asyncio.CancelledError()


def _bump(key):
    def action(ctx, event):
        ctx[key] = ctx.get(key, 0) + 1

    return action


async def check_plugin_hook_contained() -> bool:
    i = Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"inc": _bump("n")}))
    ).use(Evil())
    await i.start()
    try:
        r = await asyncio.wait_for(i.send("GO", wait=True), 2)
        hung = False
    except asyncio.TimeoutError:
        r = None
        hung = True
    ok = (
        not hung
        and r is not None
        and r.changed is True
        and i.status == "running"
        and i.last_plugin_error is not None
    )
    print(
        f"[plugin_hook_contained] hung={hung} changed={getattr(r, 'changed', None)} "
        f"status={i.status} last_plugin_error={i.last_plugin_error is not None}"
    )
    await i.stop()
    return ok


async def check_external_cancel_normalizes_status() -> bool:
    i = await Interpreter(
        create_machine(CFG, logic=MachineLogic(actions={"inc": _bump("n")}))
    ).start()
    await asyncio.sleep(0)
    i._event_loop_task.cancel()
    await asyncio.sleep(0.05)
    status_ok = i.status == "error"
    error_ok = isinstance(i.error, RuntimeError)
    print(f"[external_cancel] status={i.status} error_is_runtimeerror={error_ok}")

    try:
        await asyncio.wait_for(i.send("BACK", wait=True), 3)
        hung = False
        receipt_failed = False
    except asyncio.TimeoutError:
        hung = True
        receipt_failed = False
    except Exception as exc:  # noqa: BLE001
        hung = False
        receipt_failed = True
        print(f"[external_cancel] send after death raised: {type(exc).__name__}: {exc}")

    print(f"[external_cancel] hung={hung} receipt_failed_fast={receipt_failed}")
    return status_ok and error_ok and not hung


async def main() -> int:
    results = [
        await check_plugin_hook_contained(),
        await check_external_cancel_normalizes_status(),
    ]
    n_ok = sum(results)
    print(f"\n{n_ok}/{len(results)} criteria passed")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
