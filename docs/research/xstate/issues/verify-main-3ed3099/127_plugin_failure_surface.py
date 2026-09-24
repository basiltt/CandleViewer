# -*- coding: utf-8 -*-
"""Verify #127 on main@3ed3099: async-def plugin hook overrides are rejected
(not silently dropped), and a raising hook is exposed programmatically via
`last_plugin_error` / `on_plugin_error`, on both engines.
"""
from __future__ import annotations

import asyncio
import warnings

from xstate_statemachine import Interpreter, SyncInterpreter, create_machine
from xstate_statemachine.plugins import PluginBase

CFG = {"id": "m", "initial": "a", "states": {"a": {"on": {"T": "b"}}, "b": {}}}


class BadAsync(PluginBase):
    executed = False

    async def on_transition(self, i, s, t, tr):
        BadAsync.executed = True


class Raising(PluginBase):
    def on_transition(self, i, s, t, tr):
        raise ValueError("boom")


class Watch(PluginBase):
    def __init__(self):
        self.seen = []

    def on_plugin_error(self, i, plugin, hook, err):
        self.seen.append((type(plugin).__name__, hook, type(err).__name__))


def crit_async_def_hook_sync_engine() -> bool:
    BadAsync.executed = False
    w = Watch()
    i = SyncInterpreter(create_machine(CFG)).use(BadAsync()).use(w)
    i.start()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        i.send("T")
        # force GC of any dangling coroutine to see if RuntimeWarning appears
        import gc

        gc.collect()
    never_awaited = any("never awaited" in str(x.message) for x in caught)
    hook, err_type = i.last_plugin_error[1], type(i.last_plugin_error[2]).__name__
    i.stop()
    ok = (
        BadAsync.executed is False
        and not never_awaited
        and hook == "on_transition"
        and err_type == "TypeError"
        and ("BadAsync", "on_transition", "TypeError") in w.seen
    )
    print(
        f"  [sync] executed={BadAsync.executed} never_awaited_warning={never_awaited} "
        f"last_plugin_error=({hook},{err_type}) watch.seen={w.seen}"
    )
    return ok


async def crit_async_def_hook_async_engine() -> bool:
    BadAsync.executed = False
    w = Watch()
    i = Interpreter(create_machine(CFG)).use(BadAsync()).use(w)
    await i.start()
    await i.send("T", wait=True)
    hook, err_type = i.last_plugin_error[1], type(i.last_plugin_error[2]).__name__
    await i.stop()
    ok = (
        BadAsync.executed is False
        and hook == "on_transition"
        and err_type == "TypeError"
        and ("BadAsync", "on_transition", "TypeError") in w.seen
    )
    print(
        f"  [async] executed={BadAsync.executed} last_plugin_error=({hook},{err_type}) "
        f"watch.seen={w.seen}"
    )
    return ok


def crit_raising_hook_exposed_sync() -> bool:
    w = Watch()
    i = SyncInterpreter(create_machine(CFG)).use(Raising()).use(w)
    i.start()
    r = i.send("T", wait=True)
    hook, err_type = i.last_plugin_error[1], type(i.last_plugin_error[2]).__name__
    i.stop()
    ok = (
        r.changed is True  # machine still transitions despite plugin failure
        and r.error is None
        and hook == "on_transition"
        and err_type == "ValueError"
        and ("Raising", "on_transition", "ValueError") in w.seen
    )
    print(
        f"  [sync raising] receipt={r} last_plugin_error=({hook},{err_type}) "
        f"watch.seen={w.seen}"
    )
    return ok


async def crit_raising_hook_exposed_async() -> bool:
    w = Watch()
    i = Interpreter(create_machine(CFG)).use(Raising()).use(w)
    await i.start()
    r = await i.send("T", wait=True)
    hook, err_type = i.last_plugin_error[1], type(i.last_plugin_error[2]).__name__
    await i.stop()
    ok = (
        r.changed is True
        and r.error is None
        and hook == "on_transition"
        and err_type == "ValueError"
        and ("Raising", "on_transition", "ValueError") in w.seen
    )
    print(
        f"  [async raising] receipt={r} last_plugin_error=({hook},{err_type}) "
        f"watch.seen={w.seen}"
    )
    return ok


async def main() -> int:
    r1 = crit_async_def_hook_sync_engine()
    r2 = await crit_async_def_hook_async_engine()
    r3 = crit_raising_hook_exposed_sync()
    r4 = await crit_raising_hook_exposed_async()
    for name, r in [
        ("crit_async_def_hook_sync_engine", r1),
        ("crit_async_def_hook_async_engine", r2),
        ("crit_raising_hook_exposed_sync", r3),
        ("crit_raising_hook_exposed_async", r4),
    ]:
        print(f"{name}: {'PASS' if r else 'FAIL'}")
    ok = r1 and r2 and r3 and r4
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
