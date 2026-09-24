---
lc: LC-47
title: "Improvement: target resolution writes `transition.target_str` on definition objects shared across every interpreter of a machine"
labels: [enhancement, severity/low, area/interpreter]
severity: Low
blocks_adoption: false
repro_script: repro/LC-47_target-str-mutation-shared-definition.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

Both engines write back to the machine *definition* during interpretation: after a successful `resolve_target_state`, `base_interpreter.py:1195` and `sync_interpreter.py:1478` execute `transition.target_str = tgt`. The `TransitionDefinition` being mutated lives on the `MachineNode`, which the library explicitly encourages sharing across many interpreters (creating one node is ~19× cheaper than one per actor). So an object documented as a shared, read-only definition is written to by every interpreter, from every thread, on every transition.

**This is a latent hazard, not a live bug.** The value written is currently always identical to the authored one, because the first resolution attempt (`(target_str, source)`) already succeeds for every target form the resolver accepts — the fallbacks that would write a *different* string are unreachable in practice. This report asks for the accidental memoisation to be moved off the shared definition, and records the evidence so the register row can be narrowed from "mutates" to "writes an idempotent value".

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7 (64-bit, CPython)
- OS: Windows 11 (x64)

## Minimal reproduction

```python
"""LC-47 repro: target resolution WRITES to `transition.target_str` on the
`TransitionDefinition` objects that live on the shared `MachineNode`.

`base_interpreter.py:1195` and `sync_interpreter.py:1478` both do
`transition.target_str = tgt` after a successful `resolve_target_state`,
turning the machine *definition* into an accidental memoisation cache. The
`MachineNode` is explicitly designed to be shared -- the documented pattern is
to `create_machine()` once and hand the same node to many interpreters -- so
every interpreter writes into state that all the others read.

This is a code-quality / latent-hazard report, not a live-failure report: the
value written is currently always identical to the authored one, because the
FIRST resolution attempt (`(target_str, source)`) already succeeds for every
target form the resolver accepts. So the observable state is unchanged; what
this script shows is that the write happens at all, on a shared object, from
many interpreters, including concurrently from threads.

`target_str` is installed as a watched property so every assignment is
counted. Exit code 1 if the shared definition object is written to during
interpretation.
"""

from __future__ import annotations

import logging
import sys
import threading

from xstate_statemachine import SyncInterpreter, create_machine

logging.disable(logging.CRITICAL)

CONFIG = {
    "id": "order",
    "initial": "idle",
    "states": {
        "idle": {"on": {"SUBMIT": "open"}},
        "open": {"on": {"CLOSE": "closed"}},
        "closed": {"type": "final"},
    },
}

# 🌳 ONE shared MachineNode -- the documented, 19x-cheaper pattern.
MACHINE = create_machine(CONFIG)
TRANSITION = MACHINE.states["idle"].on["SUBMIT"][0]

WRITES: list[tuple[str, str]] = []
LOCK = threading.Lock()


def watch(transition) -> None:
    """Replace `target_str` with a property that records every assignment."""
    stored = transition.__dict__.pop("target_str")
    transition.__dict__["_target_str"] = stored

    class Watched(type(transition)):
        @property
        def target_str(self):
            return self.__dict__["_target_str"]

        @target_str.setter
        def target_str(self, value):
            with LOCK:
                WRITES.append((threading.current_thread().name, value))
            self.__dict__["_target_str"] = value

    transition.__class__ = Watched


authored = TRANSITION.target_str
watch(TRANSITION)
print(f"OBSERVED target_str as authored in config  : {authored!r}")

# 1️⃣ A single interpreter writes to the shared definition object.
it1 = SyncInterpreter(MACHINE).start()
it1.send("SUBMIT")
print(f"OBSERVED writes after 1 interpreter, 1 event: {WRITES}")

# 2️⃣ A second interpreter over the SAME node writes to the same field.
it2 = SyncInterpreter(MACHINE).start()
it2.send("SUBMIT")
print(f"OBSERVED writes after a 2nd interpreter     : {len(WRITES)}")

# 3️⃣ Concurrent SyncInterpreters (whose `after` timers are real threads, so
#    nothing serialises them onto one loop) all write this shared field.
WRITES.clear()


def drive() -> None:
    it = SyncInterpreter(MACHINE).start()
    for _ in range(100):
        it.send("SUBMIT")
        it.send("CLOSE")


threads = [threading.Thread(target=drive, name=f"w{i}") for i in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join()
writers = sorted({name for name, _ in WRITES})
print(
    f"OBSERVED 8 threads x 100 cycles -> {len(WRITES)} writes to ONE shared "
    f"definition object from threads {writers}"
)
print(f"OBSERVED values written                     : "
      f"{sorted({v for _, v in WRITES})}")
print(f"OBSERVED final target_str                   : {TRANSITION.target_str!r}")
print(
    "EXPECTED zero writes: the machine definition should be immutable under "
    "interpretation, with resolution results memoised in a per-interpreter "
    "cache keyed by id(transition)"
)

sys.exit(0 if not WRITES else 1)
```

## Observed behaviour

```
OBSERVED target_str as authored in config  : 'open'
OBSERVED writes after 1 interpreter, 1 event: [('MainThread', 'open')]
OBSERVED writes after a 2nd interpreter     : 2
OBSERVED 8 threads x 100 cycles -> 8 writes to ONE shared definition object from threads ['w0', 'w1', 'w2', 'w3', 'w4', 'w5', 'w6', 'w7']
OBSERVED values written                     : ['open']
OBSERVED final target_str                   : 'open'
EXPECTED zero writes: the machine definition should be immutable under interpretation, with resolution results memoised in a per-interpreter cache keyed by id(transition)
EXIT=1
```

Reading this precisely:

- The write is **real and confirmed**: 8 independent `SyncInterpreter`s on 8 OS threads each wrote to the same `TransitionDefinition` instance.
- The written value is `'open'` — **identical to the authored value**, in every case. The definition is not corrupted, and no cross-talk is possible today.
- Only 8 writes occurred across 800 event cycles, not 800: after the first write the value is unchanged, but note that this is *not* because the code short-circuits — the write executes every time resolution runs; the count is 8 because `_resolve_target_state_robustly` itself is reached once per transition per interpreter here.

I probed the fallback paths deliberately to see whether a *different* value could ever be written — nested (`"b.inner"`), `#`-absolute (`"#o.b"`), and bubble-up-to-uncle (`"q"`) targets all resolve on attempt #1 and write back their own authored string unchanged. A root-prefixed form like `"o.b"` that would exercise the `f"{root.id}.{target_str}"` fallback instead raises `StateNotFoundError` before reaching it. So on the current resolver there appears to be no reachable input for which the write changes the value.

This is consistent with, and sharpens, a separate adversarial result from the same research (200 interpreters over one `MachineNode`, `E` sent to exactly 100 → 100/100 moved, 100/100 untouched, no cross-talk). That test showed no *observable* cross-talk; this script shows *why* — the write is value-idempotent — and confirms the write itself happens, which a black-box test could not see.

## Expected behaviour

The machine definition should be immutable under interpretation. XState draws this line explicitly: a `StateMachine` in v5 is an immutable definition object and `createActor(machine)` may be called any number of times over one machine, with all mutable state living on the actor (see https://stately.ai/docs/machines — "The machine is a static definition… actors are created from machines"). Target resolution results belong in a per-actor cache, not written back into the definition.

This library makes the same promise implicitly by recommending shared `MachineNode`s for memory reasons, so the promise should hold structurally rather than by the accident that the memoised value happens to equal the original.

## Root cause analysis

Two sites, one pattern.

`src/xstate_statemachine/base_interpreter.py:1186-1197`, inside `_resolve_target_state_node`:

```python
for tgt, ref in filter(None, resolution_attempts):
    try:
        target_state = resolve_target_state(tgt, ref)
        # This side effect is important for logging and debugging.
        transition.target_str = tgt
        logger.debug("✅ Resolved via standard method: '%s'", target_state.id)
        break
    except StateNotFoundError:
        ...
```

`src/xstate_statemachine/sync_interpreter.py:1471-1481`, inside `_resolve_target_state_robustly`:

```python
for tgt, ref in filter(None, attempts):
    try:
        state = resolve_target_state(tgt, ref)
        logger.debug("✅ Resolved '%s' via standard method from '%s'.", tgt, ref.id)
        # ‼️ CRITICAL: This mutation logic is restored from the original code.
        transition.target_str = tgt
        return state
    except StateNotFoundError:
        continue
```

The comments are revealing. The async site justifies the write as being "important for logging and debugging" — but the very next statement logs `target_state.id`, which is derived from the resolved node and does not need the write. The sync site marks it "CRITICAL… restored from the original code", i.e. it was removed at some point, something broke, and it was put back without the root cause being identified. Neither comment describes a mechanism by which a later read of `target_str` depends on the write.

`transition.target_str` is read in several places that walk the definition rather than the interpreter — `models.py:892`, `:1243`, `:1294`, `:1305`, `:1350`, `:1360` — which is presumably where the "critical" behaviour was felt. Those readers are the ones that need auditing before the write is removed.

The attempt list is ordered `(target_str, source)`, `(target_str, parent)`, `(target_str, root)`, `(f"{root.id}.{target_str}", root)`. Only the last entry constructs a *different* string; the first three write back `target_str` to itself, which is why the write is a no-op in practice. `resolve_target_state` (`resolver.py:105-235`) already bubbles up the hierarchy internally in its plain-ID strategy, which is why attempt #1 subsumes attempts #2 and #3 and the fourth is never reached.

The structural risk is that the safety here rests on an invariant nobody stated: *the first attempt always wins*. Any future change to the resolver or the attempt ordering — for example, making attempt #1 stricter so that root-prefixed targets fall through to attempt #4 — would turn this into a real shared-mutable-state bug, and the async engine's serialisation onto one event loop would not protect `SyncInterpreter`, whose `after` timers run on genuine OS threads (LC-38).

## Impact

**General users.** No user-visible failure today. The cost is design integrity and future safety: an object the documentation invites you to share is silently written to, so any reader reasoning about thread-safety has to prove the idempotence argument above for themselves before trusting it — and any contributor touching `resolver.py` can invalidate it without realising. There is also a small per-transition attribute-write cost on a hot path (LC-45).

**CandleViewer (trading OMS).** CandleViewer is the downstream application this research was conducted for: an order-management system that runs hundreds of concurrent order-lifecycle interpreters. To get the ~19× construction saving, our design mandates one shared `MachineNode` per machine family across all of those interpreters, and several run under `SyncInterpreter` with threaded `after` timers for order-timeout logic. The current code is safe for us, and a separate 200-interpreter adversarial test confirmed no observable cross-talk. But we are relying on an undocumented invariant in a dependency rather than on a structural guarantee: if a future release changes resolution ordering, two order machines resolving the same shared transition from different threads could observe a torn `target_str`, and the symptom would be an order transitioning to the wrong state under load — the class of bug that is effectively impossible to reproduce after the fact. We would rather the guarantee be structural before we scale the shared-node pattern further.

## Proposed fix

**Move the memoisation off the definition and onto the interpreter.**

Add a per-interpreter cache in `BaseInterpreter.__init__`:

```python
self._target_cache: Dict[int, StateNode] = {}   # id(transition) -> resolved node
```

and rewrite both resolution loops to consult and populate it instead of writing to the definition:

```python
cached = self._target_cache.get(id(transition))
if cached is not None:
    return cached
for tgt, ref in filter(None, attempts):
    try:
        state = resolve_target_state(tgt, ref)
        logger.debug("✅ Resolved '%s' to '%s'", tgt, state.id)
        self._target_cache[id(transition)] = state
        return state
    except StateNotFoundError:
        continue
```

Keying on `id(transition)` is safe because the interpreter holds a reference to the `MachineNode` for its whole lifetime, so the definition objects cannot be collected and their ids cannot be reused. This is strictly better than the current arrangement: it caches the resolved `StateNode` rather than a string that still has to be re-resolved, so it removes work from the hot path as well (a win for LC-45).

**Before removing the write, audit the `target_str` readers.** The sync-engine comment says the write was once removed and something regressed. The readers at `models.py:892`, `:1243`, `:1294`, `:1305`, `:1350`, `:1360` are definition-level walks (validation, `on_done` wiring, graph export). Each needs checking for whether it depends on seeing a *resolved* string rather than the authored one. If any does, the correct fix is to give `TransitionDefinition` a separate read-only `resolved_target_id` populated once at machine-construction time — never during interpretation — rather than reinstating the write.

**Backwards compatibility.** `target_str` is a public attribute on a public model class. After this change it always holds the string as authored in the config. Anyone who was (accidentally) depending on reading a post-resolution value would see a behaviour change; given that the post-resolution value is currently always equal to the authored value, no real dependency can exist. Worth a CHANGELOG note under "Fixed" regardless. No deprecation cycle needed.

**Optional hardening.** Once the write is gone, consider `__slots__` plus a `_frozen` flag on `TransitionDefinition`, or a `__setattr__` that raises after `create_machine()` returns, so any future accidental write to a definition object fails loudly in tests rather than silently at runtime.

## Acceptance criteria

- [ ] `tests/test_definition_immutability.py::test_interpretation_does_not_write_to_transition_definition` — the watched-property technique from the repro script, asserting zero writes to `target_str` after driving both a `SyncInterpreter` and an async `Interpreter` through every transition of a machine covering plain, nested, `#`-absolute and bubble-up targets.
- [ ] `tests/test_definition_immutability.py::test_shared_machine_node_unchanged_after_many_interpreters` — `create_machine()` once, run 50 interpreters to completion, assert every `TransitionDefinition.target_str` in the node still equals the value authored in the config dict.
- [ ] `tests/test_definition_immutability.py::test_target_resolution_cached_per_interpreter` — a second transition over the same definition hits `_target_cache` (assert via a counter patched onto `resolve_target_state`) and two interpreters maintain independent caches.
- [ ] `tests/test_resolver.py` — existing target-resolution tests pass unchanged for plain, `.relative`, `.`-parent, `#absolute` and nested-dotted targets, confirming no resolution regression from removing the write.
- [ ] A regression test covering whatever the sync engine's "restored from the original code" comment was protecting, added as part of the reader audit, so the write cannot be silently reinstated.
- [ ] `repro/LC-47_target-str-mutation-shared-definition.py` exits 0.

## Related

- **LC-38** — `SyncInterpreter` timer threads: the reason the idempotence argument is load-bearing rather than academic, since it removes the "one event loop serialises everything" defence.
- **LC-45** — hot-path cost; the proposed per-interpreter cache of resolved `StateNode`s removes work rather than adding it.
- **LC-06 / LC-08** — over-forgiving target resolution and unvalidated unknown targets; all three touch the same `resolve_target_state` attempt ladder and would sensibly be addressed together.
## Verification

- Date: 2026-09-15
- Python: 3.13.7 (CPython, 64-bit, Windows 11 x64)
- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, editable install
- Repro exit code: **1** (fails today), reproduced in a fresh process with output matching the Observed section exactly, including the 8-writes-from-8-threads result
- Findings: this report needed the fewest corrections of the three. Its central claim is accurate and its self-limiting framing ("latent hazard, not a live bug") is correct and well-evidenced.
  - Both root-cause citations confirmed exact: `base_interpreter.py:1195` and `sync_interpreter.py:1478` are both `transition.target_str = tgt`, with the quoted surrounding comments present verbatim.
  - The `target_str` reader list was re-checked against `models.py`; all cited lines (`:892`, `:1243`, `:1294`, `:1305`, `:1350`, `:1360`) exist and read `target_str` as claimed. Note that `:375` and `:660` are the *writes* that set it from config, which the reader audit should also account for.
  - XState claim checked against https://stately.ai/docs/machines and confirmed: machines are static definitions and `createActor(machine)` may be called any number of times, with mutable state living on the actor.
  - Removed the `candleviewer` label, the internal `adv07` codename, the internal "A8 decision" reference, and the trailing internal-doc pointers, so the report stands alone for a maintainer.
  - Duplicate check: `gh issue list --repo basiltt/xstate-statemachine --state all` returns exactly one issue (#17, camelCase/snake_case logic auto-discovery, closed). Not a duplicate.
