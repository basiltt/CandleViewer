# Bug: `on_interpreter_start` never fires on a snapshot-restored interpreter - no working registration route, both engines

**NOT POSTED. Draft.**

**Severity (ours): Medium** - observability; an unbalanced lifecycle pair.
**Version:** `0.9.0` (tag `v0.9.0` = `91bd979`).
**Affects:** `Interpreter` and `SyncInterpreter`, via both `from_snapshot(plugins=[...])` and `.use()`.

## Summary

`Interpreter.start()` has two paths. The resume branch (`interpreter.py:588-624`) detects the restored shape (`status in ("running", "done", "error")` and `_event_loop_task is None`), logs `"Resuming restored interpreter"`, binds the loop, re-arms scheduled sends (#213), optionally re-drives invokes (#44) and `after` timers (#128), resumes child actors, and **`return self` at line 624**.

The plugin notification loop -

```python
for plugin in self._plugins:
    plugin.on_interpreter_start(self)
```

- sits at `interpreter.py:663-665`, **below that early return**, and is never reached on a restored interpreter. `SyncInterpreter.start()` has the identical shape (`sync_interpreter.py:311-347`, returning above its own hook loop at `:388`), which is why the sync engine fails the same way rather than via a separate bug.

`on_interpreter_stop` has only one path and **does** fire. So a lifecycle plugin attached to a restored actor observes a `stop` with no matching `start`.

## Reproduction

Standalone - stdlib plus `xstate_statemachine` only, every helper inlined, neutral working directory. Prints a control (fresh actor) and both restored registration routes.

```python
"""on_interpreter_start does not fire on a restored interpreter."""
import asyncio
import json

from xstate_statemachine import create_machine, Interpreter, PluginBase

CFG = {
    "id": "m",
    "initial": "a",
    "states": {"a": {"on": {"GO": "b"}}, "b": {}},
}


class Trace(PluginBase):
    def __init__(self):
        self.seen = []

    def on_interpreter_start(self, interpreter):
        self.seen.append("start")

    def on_transition(self, interpreter, from_state, to_state, event):
        self.seen.append("transition")

    def on_interpreter_stop(self, interpreter):
        self.seen.append("stop")


async def run(label, make):
    plugin = Trace()
    interp = await make(plugin)
    await interp.send("GO")
    await asyncio.sleep(0.05)
    await interp.stop()
    print(f"{label:<34}: {plugin.seen}")


async def main():
    machine = create_machine(CFG)

    # Control: a fresh interpreter.
    async def fresh(plugin):
        i = Interpreter(machine).use(plugin)
        await i.start()
        return i

    await run("CONTROL fresh .use()", fresh)

    # Produce a snapshot to restore from.
    src = Interpreter(machine)
    await src.start()
    blob = json.dumps(src.get_persisted_snapshot(), default=str)
    await src.stop()

    async def restored_kwarg(plugin):
        i = Interpreter.from_snapshot(blob, machine, plugins=[plugin])
        await i.start()
        return i

    async def restored_use(plugin):
        i = Interpreter.from_snapshot(blob, machine).use(plugin)
        await i.start()
        return i

    await run("RESTORED from_snapshot(plugins=)", restored_kwarg)
    await run("RESTORED .use() after restore", restored_use)


asyncio.run(asyncio.wait_for(main(), 25))
```

Output on `v0.9.0`:

```
CONTROL fresh .use()              : ['start', 'transition', 'transition', 'stop']
RESTORED from_snapshot(plugins=)  : ['transition', 'stop']
RESTORED .use() after restore     : ['transition', 'stop']
```

We measured the same result across 6/6 cells, `{async, sync} x {def, async def} x {plugins=, .use()}`, and independently at fleet scale in a chaos soak: 40/40 restores, `plugin_start_counts = [0]`.

## Expected

`on_interpreter_start` fires when `start()` is called, including on the resume path - ideally with a `restored=True` discriminator so a plugin can distinguish bring-up from resume, since the two usually want different telemetry.

## Why we think this is a defect rather than intended resume semantics

We argued the other side internally first and it did not hold up:

1. **The docs do not carve out resume.** `docs/_guide/plugins.md:175` says `on_interpreter_start` fires "**when `start()` is called**"; `docs/api/index.md:1919` says "`start()` begins". And `start()` is the library's own documented way to resume a restored actor - the architecture comment at `interpreter.py:582-587` says so explicitly. A reader following the documentation has no way to anticipate this.
2. **The pair is unbalanced, not merely absent.** Because `stop()` fires normally, a plugin sees a `stop` for an actor it never saw start. Anything holding a span, a correlation id, a latency clock, or an audit "actor came up" record either leaks or reports a negative/absent duration. An absent-on-both-ends hook would be easy to work around; an asymmetric one is a trap.
3. **There is no working route.** It is not `plugins=`-specific: `.use()` after `from_snapshot` is equally blind, so there is no way to observe this event on a restored actor at all. The 0.9.0 changelog states that `plugins=` has "the same effect as `.use()` on the result" - which is true here, but only vacuously.

This reads to us as the other half of the hook #230 just fixed: `plugins=` correctly delivers `on_invalid_event` at restore time (we verified exactly-once over 320 property cases), and the lifecycle hook simply has no route on the same path.

## Impact

Limited to observability - and we want to be clear about that, because the actor itself is entirely healthy. In all six cells `restored_machine_is_live = true`, and `on_transition`, `on_action_execute` and `on_interpreter_stop` all behave normally. It works; it just never announces itself. For a long-lived process that restores a large population of actors from snapshots after a restart, the practical effect is that the restart is invisible to lifecycle telemetry exactly when an operator most wants to see it.

## Suggested fix

Run the plugin notification loop on the resume branch as well, or hoist it above the early return in both engines. A test asserting `start`/`stop` balance on a restored interpreter would pin it on both engines at once.

## Workaround for others

Do not hang per-process bring-up work off `on_interpreter_start`. Do it at construction/restore time in your own wrapper, and treat `on_interpreter_stop` as possibly-unpaired.
