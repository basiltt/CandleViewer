---
lc: LC-16
title: "Bug: `sendTo` cannot address an actor by its `invoke` `id` or `systemId`; the event is silently dropped"
labels: [bug, severity/blocker, area/actors, candleviewer]
severity: Blocker
blocks_adoption: true
repro_script: repro/LC-16_sendto-invoke-id.py
library_version: 0.7.0 (commit 42612cf)
verified: true
python: 3.13.7
---

## Summary

An actor started with `invoke: {"id": "kid", "src": "child"}` can only be reached by `sendTo` under its **service key** (`"child"`), never under its declared `id` or its `systemId`. The id minted for an invoked actor is `f"{parent.id}:{invocation.src}:{uuid4()}"` — the declared `id` never enters the string, and `systemId` is not read at all on the `invoke` path. `_resolve_actor_target` then matches on `actor_id.split(":")[1:]`, i.e. the service key or the random uuid. The failure mode is a `logger.warning` plus a **dropped event**: no exception, no `onError`, nothing in the snapshot. Because the service key is the only working name, it is also ambiguous by construction when several children are invoked from one `src` — and the ambiguous case is likewise a warning + dropped event.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7
- OS: Windows 10/11 (x64)

## Minimal reproduction

```python
"""LC-16: `sendTo` cannot address an invoked actor by its `invoke` id/systemId.

Runs three identical parent machines that differ only in the name used as the
`send_to` target: the service key, the declared invoke `id`, and the declared
`systemId`. Only the service key delivers; the other two drop the event.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, Optional

from xstate_statemachine import Interpreter, MachineLogic, create_machine

CHILD = create_machine(
    {
        "id": "child",
        "initial": "idle",
        "context": {},
        "states": {
            "idle": {
                "on": {
                    "PING": {
                        "actions": [
                            {"type": "send_parent", "params": {"event": "PONG"}}
                        ]
                    }
                }
            }
        },
    },
    logic=MachineLogic(),
)


async def attempt(to: str, invoke: Dict[str, Any]) -> Optional[str]:
    seen: Dict[str, Any] = {}

    def cap(i, c, e, a):  # noqa: ANN001
        seen["reply"] = e.type

    cfg = {
        "id": "p",
        "initial": "run",
        "context": {},
        "states": {
            "run": {
                "invoke": invoke,
                "on": {
                    "POKE": {
                        "actions": [
                            {
                                "type": "send_to",
                                "params": {"to": to, "event": "PING"},
                            }
                        ]
                    },
                    "PONG": {"target": "got", "actions": ["cap"]},
                },
            },
            "got": {},
        },
    }
    logic = MachineLogic(actions={"cap": cap}, services={"child": CHILD})
    interp = await Interpreter(create_machine(cfg, logic=logic)).start()
    await asyncio.sleep(0.1)
    await interp.send("POKE")
    await asyncio.sleep(0.25)
    await interp.stop()
    return seen.get("reply")


async def main() -> int:
    observed = {
        "by_service_key": await attempt("child", {"id": "kid", "src": "child"}),
        "by_invoke_id": await attempt("kid", {"id": "kid", "src": "child"}),
        "by_system_id": await attempt(
            "kid", {"id": "kid", "src": "child", "systemId": "kid"}
        ),
    }
    expected = {k: "PONG" for k in observed}
    print("OBSERVED:", observed)
    print("EXPECTED:", expected)
    return 0 if observed == expected else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
WARNING:xstate_statemachine.interpreter:⚠️ sendTo could not resolve target 'kid'; event dropped.
WARNING:xstate_statemachine.interpreter:⚠️ Interpreter 'p:child:283679cd-3912-4fbb-b668-64e2afa450f5' is not running. Skipping stop.
WARNING:xstate_statemachine.interpreter:⚠️ sendTo could not resolve target 'kid'; event dropped.
WARNING:xstate_statemachine.interpreter:⚠️ Interpreter 'p:child:e14f5fbf-b22e-43df-9681-dd937659a028' is not running. Skipping stop.
OBSERVED: {'by_service_key': 'PONG', 'by_invoke_id': None, 'by_system_id': None}
EXPECTED: {'by_service_key': 'PONG', 'by_invoke_id': 'PONG', 'by_system_id': 'PONG'}
```

Exit code `1`. Note the uuid in the warning: the minted actor id is `p:child:<uuid>` — the declared `id` `kid` is nowhere in it.

## Expected behaviour

XState v5 — https://stately.ai/docs/invoke, https://stately.ai/docs/actions#send-to-action and https://stately.ai/docs/system:

From the `invoke` property API:

> "`id` - A string identifying the actor, unique within its parent machine."

From the send-to action:

> "The `sendTo(...)` action is a special action that sends an event to a specific actor." … "The destination actor can be the actor ID or the actor reference itself"

From Systems / Actor registration:

> "Actors can be registered with the system so that any other actor in the system can obtain a reference to it. Invoked actors are registered with a system-wide `systemId` in the `invoke` object"

with the documented retrieval being `system.get('notifier')`.

The declared `id` is the actor's canonical address within its parent, and `sendTo` accepts exactly that id; `systemId` is its canonical global address. Both must resolve exactly. Deriving the address from `src` is not part of the spec at all — it is at best a convenience alias, and it is unusable when several actors share one `src` (which XState explicitly supports: `invoke` may be an array of actors).

Additionally, a target name that cannot be resolved, or resolves ambiguously, must surface as an error. Silently dropping an event addressed to a named actor has no analogue in XState.

## Root cause analysis

1. `src/xstate_statemachine/interpreter.py:1189` — `_spawn_and_manage_actor` mints the id for an **invoked** actor:

   ```python
   actor_id = f"{self.id}:{invocation.src}:{uuid.uuid4()}"
   ```

   `invocation.id` is never used, and `systemId` is never registered — in fact `InvokeDefinition.__init__` (`models.py:445-472`) does not read a `systemId` key from the invoke config at all, so the value is discarded at parse time. Contrast the `spawn` path (`interpreter.py:957-979`), which does honour an explicit `id` (`f"{self.id}:{explicit_id}"`, `:959-963`) and does call `self._register_in_system(spawn_params.get("systemId"), ...)` (`:972-974`). So the two ways of creating a child disagree on addressing.

   Note also that `self._actor_sources[actor_id] = ...` is populated **only** on the spawn path (`interpreter.py:979`); the invoke path never records it, so the `_actor_sources` fallback inside `_resolve_actor_target` is dead for invoked actors.

2. `src/xstate_statemachine/base_interpreter.py:1329-1391` — `_resolve_actor_target` looks up, in order: the system registry, `self._actors` keyed by full id, then a **segment match**:

   ```python
   matches = [
       actor
       for actor_id, actor in self._actors.items()
       if spec in actor_id.split(":")[1:]
   ]
   if len(matches) == 1:
       return matches[0]
   if len(matches) > 1:
       logger.warning("⚠️ Actor key '%s' is ambiguous (%d matches) … event dropped.", ...)
       return None
   ```

   With the id shape from (1) the only matchable segments are `src` and the uuid, so `"kid"` matches nothing → `None` → the caller (`interpreter.py:738`, and `sync_interpreter.py:944` for the sync engine) logs "could not resolve target … event dropped" and returns. With N children invoked from one `src`, `"child"` matches N → the ambiguity branch → also dropped.

Both the "unresolved" and the "ambiguous" outcomes return `None`, and every caller of `_resolve_actor_target` treats `None` as "log and move on".

## Impact

**General:** any request/response pattern between a parent and a named invoked child is unreachable except via the `src` alias, and any fan-out of several children from one `src` is unaddressable altogether. Failures are invisible at runtime — no exception, no state change, nothing persisted — so a machine that has lost an event looks perfectly healthy.

**CandleViewer (trading OMS):** our trade-group design invokes one `leg` machine per leg of a trade group, all from a single `src: "leg"`, each with its own `id`/`systemId` (`leg-0`, `leg-1`, …). The group machine addresses legs individually — `sendTo("leg-1", {"type": "CANCEL"})` when the group hits its risk limit. Today that event is dropped with a warning: the exchange keeps working leg 1 while the group machine believes it has been cancelled, leaving an unhedged live position that no state in the model represents. There is no upstream-free fix; our workaround is an application-owned `dict[leg_id → Interpreter]` with restore-time rehydration, which duplicates the actor registry the library already maintains.

## Proposed fix

1. **Mint invoked-actor ids from the declared `id`.** In `interpreter.py:_spawn_and_manage_actor`, mirror the `spawn` path:

   ```python
   actor_id = (
       f"{self.id}:{invocation.id}"
       if invocation.id
       else f"{self.id}:{invocation.src}:{uuid.uuid4()}"
   )
   ```

   ⚠️ Note the existing default: `models.py:946` sets `invoke_id = i_config.get("id", self.id)`, i.e. an omitted `id` falls back to the **hosting state's id**, which is shared by every anonymous invoke in that state. So `invocation.id` is not safe to use unconditionally — mint `f"{self.id}:{invocation.id}"` only when `id` was *explicitly* declared in the config, and keep the uuid suffix for the anonymous case so two anonymous children of one state stay distinct. (That means `InvokeDefinition` should also record whether `id` was explicit.)

2. **Read and register `systemId` on the invoke path.** `InvokeDefinition.__init__` currently never reads `systemId` from the config; add `self.system_id = config.get("systemId")`, then call `self._register_in_system(invocation.system_id, child_interpreter)` immediately after constructing the child, exactly as `spawn` does.

3. **Record `_actor_sources` on the invoke path too** (`self._actor_sources[actor_id] = invocation.src`), so the existing src-alias fallback in `_resolve_actor_target` actually covers invoked actors rather than only spawned ones.

4. **Make exact names first-class in `_resolve_actor_target`.** Before the segment scan, try (a) the system registry, (b) `f"{self.id}:{spec}"` in `self._actors`, (c) a match on the declared `invocation.id`. Keep the `src`-segment scan as a last-resort alias.

5. **Never drop a named event silently.** Unresolved or ambiguous targets should raise `ActorSpawningError` (or a new `ActorNotFoundError`). If raising is judged too breaking for 0.7.x, gate it behind an interpreter flag `strict_actor_targets=True` that becomes the default in 0.8.0, and meanwhile escalate the ambiguity warning to `logger.error`.

Backwards compatibility: (1)–(4) are additive — existing code addressing by `src` keeps working via the retained alias scan. Only (5) changes observable behaviour, hence the flag and the deprecation window. This also relates to LC-13 (duplicate `systemId`): `_register_in_system` (`base_interpreter.py:1417-1437`) today logs a warning and lets the new actor **replace** the old one; making it raise on a duplicate key would fix both.

## Acceptance criteria

- [ ] An actor started with `invoke: {"id": "kid", "src": "child"}` is reachable as `sendTo("kid", …)`.
- [ ] An actor started with `invoke: {"id": "kid", "src": "child", "systemId": "sys-kid"}` is reachable as `sendTo("sys-kid", …)` and via `system.get("sys-kid")`.
- [ ] Addressing by the bare `src` still works when exactly one child was invoked from that `src` (no regression).
- [ ] N children invoked from one `src` under distinct `id`s are each individually addressable, and events reach exactly the addressed child.
- [ ] An unresolvable or ambiguous `sendTo` target raises instead of dropping the event (under the strict flag, at minimum).
- [ ] `repro/LC-16_sendto-invoke-id.py` exits 0.
- [ ] Tests added: `tests/test_actor_addressing.py::test_send_to_by_invoke_id`, `::test_send_to_by_system_id`, `::test_send_to_by_src_alias_still_works`, `::test_fanout_same_src_distinct_ids`, `::test_unresolved_target_raises_in_strict_mode`.

## Related

- LC-02 (actor lifecycle/addressing) and LC-13 (duplicate `systemId` silently overwrites — same `_register_in_system` code path, worth fixing together). Filed separately.

## Verification

Independently re-verified on **2026-09-15**.

- Python 3.13.7, `xstate-statemachine` 0.7.0, commit `42612cf`, editable install.
- `repro/LC-16_sendto-invoke-id.py` run in a fresh process: **exit code 1**.
  Observed `{'by_service_key': 'PONG', 'by_invoke_id': None, 'by_system_id': None}`, with the two `sendTo could not resolve target 'kid'; event dropped.` warnings — matches the Observed section (uuids differ per run, as expected).
- Root cause confirmed against source: invoked-actor id minted at `interpreter.py:1189` as `f"{self.id}:{invocation.src}:{uuid.uuid4()}"`; spawn path honours explicit `id` and calls `_register_in_system` at `:957-979`; `_resolve_actor_target` segment match at `base_interpreter.py:1329-1391`; drop site `interpreter.py:738` (and `sync_interpreter.py:944`).
- Additional findings folded into the draft: `InvokeDefinition.__init__` (`models.py:445-472`) never reads `systemId` at all, so it is discarded at *parse* time, not merely unregistered; `_actor_sources` is written only on the spawn path (`:979`), making that fallback dead for invoked actors; and `invoke_id` defaults to the **hosting state's id** (`models.py:946`), so the draft's proposed fix was corrected to only use `invocation.id` when explicitly declared.
- Expected behaviour re-checked against https://stately.ai/docs/invoke, https://stately.ai/docs/actions#send-to-action and https://stately.ai/docs/system; both original quotes were paraphrases and are replaced with verbatim docs text. Substance of the claim holds.
- LC-13 cross-reference softened: `_register_in_system` (`base_interpreter.py:1417-1437`) warns and replaces on duplicate `systemId` — the draft claimed this issue's fix resolves it, which it does not by itself.
- No duplicate: the upstream tracker has one issue total (#17, closed, unrelated).
