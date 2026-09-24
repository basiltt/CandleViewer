---
lc: LC-06
title: "Bug: over-forgiving target resolution silently binds an unrelated state in another region"
labels: [bug, severity/high, area/interpreter, candleviewer]
severity: High
blocks_adoption: false
repro_script: repro/LC-06_overforgiving-target-resolution.py
library_version: 0.7.0 (commit 42612cf)
verified: true
python: 3.13.7
---

## Summary

`_resolve_target_state_node` tries four escalating fallbacks after standard resolution fails, ending in an **exhaustive walk of the entire machine tree that matches on the last segment of a state id**. A transition declaring `target: "filled"` inside `order`, where `order` has no `filled` child, therefore binds to `audit.archive.filled` — a node in a completely unrelated parallel region — and the machine transitions there. No error, no warning above `DEBUG`. Short leaf names like `filled`, `cancelled`, `failed`, `idle`, `done` recur in every non-trivial machine, so the fallback is very likely to find a wrong match rather than no match.

## Environment

- Library: `xstate-statemachine` 0.7.0, commit `42612cf`, local clone, installed with `pip install -e .`
- Python: 3.13.7
- OS: Windows 10/11 (x64)

## Minimal reproduction

```python
"""LC-06: over-forgiving target resolution silently binds an unrelated state.

`order.submitting` declares `target: "filled"`. There is no `filled` sibling in
`order` — the only node whose last id segment is `filled` lives in a completely
unrelated region, `audit.archive.filled`. A conforming engine must fail (XState
raises at machine-creation time for an unresolvable target). This library walks
the whole tree and binds the foreign node.
"""

from __future__ import annotations

import asyncio
import sys

from xstate_statemachine import Interpreter, MachineLogic, create_machine


async def main() -> int:
    cfg = {
        "id": "m",
        "type": "parallel",
        "context": {},
        "states": {
            "audit": {
                "initial": "archive",
                "states": {
                    "archive": {
                        "initial": "open",
                        "states": {"open": {}, "filled": {}},
                    }
                },
            },
            "order": {
                "initial": "submitting",
                "states": {
                    # ⚠️ `filled` does not exist inside `order`.
                    "submitting": {"on": {"FILL": "filled"}},
                    "done": {},
                },
            },
        },
    }
    interp = await Interpreter(
        create_machine(cfg, logic=MachineLogic())
    ).start()
    await interp.send("FILL")
    await asyncio.sleep(0.2)
    observed = sorted(interp.current_state_ids)
    await interp.stop()

    print("OBSERVED:", observed)
    print(
        "EXPECTED: create_machine() or send() to raise StateNotFoundError for "
        "unresolvable target 'filled'; never bind 'm.audit.archive.filled'"
    )
    bad = "m.audit.archive.filled" in observed
    print("BOUND_FOREIGN_STATE:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED: ['m.audit.archive.filled', 'm.order.submitting']
EXPECTED: create_machine() or send() to raise StateNotFoundError for unresolvable target 'filled'; never bind 'm.audit.archive.filled'
BOUND_FOREIGN_STATE: True
```

Exit code `1`. Note the damage precisely: the `order` region **did not move** (still `submitting`), while the unrelated `audit` region was yanked from `archive.open` to `archive.filled`. A single mistyped/underspecified target corrupted a region the transition has no business touching, and left the intended region stuck.

## Expected behaviour

XState v5 — https://stately.ai/docs/transitions:

> "Usually, transitions are between two sibling states. These transitions are defined by setting the `target` as the sibling state key."
>
> "**Any state by ID:** `{ target: '#specificState' }` — target any state in the machine by its unique ID"

Resolution in XState is lexically scoped: a bare target names a **sibling** of the source state; `#id` names a node by its explicit id; a leading `.` names a descendant. There is no "search the whole machine for something with a similar name" rule.

An unresolvable target is an error, raised while the machine is being formatted — not silently redirected. From XState v5 core (`packages/core/src/stateUtils.ts`), `getStateNode` throws:

```
Child state '<key>' does not exist on '<stateNode.id>'
```

which `resolveTarget` re-wraps as:

```
Invalid transition definition for state node '<stateNode.id>':
Child state '<key>' does not exist on '<parent.id>'
```

SCXML 1.0 §3.3 likewise requires every `target` to be the `id` of a state in the document, and §3.12.1 makes an unresolvable target a document-level error.

The key property being violated is *locality*: a transition must never be able to reach into a state it could not have named.

## Root cause analysis

`src/xstate_statemachine/base_interpreter.py:1164-1261`, `_resolve_target_state_node`. Standard resolution is correct and tries, in order, the source, the source's parent, the root, and the root-prefixed id (`:1183-1209`). When all four raise `StateNotFoundError`, three fallbacks follow:

- **Fallback 1** (`:1211-1218`) — `getattr(root, target_str)`: an arbitrary attribute lookup on the root node.
- **Fallback 2** (`:1220-1236`) — the root's `states` dict, first by exact key, then by *last id segment*:

  ```python
  for state in states_dict.values():
      if state.id.split(".")[-1] == target_str:
          return state
  ```

- **Fallback 3** (`:1238-1250`) — an exhaustive recursive `_walk(root)` over every node in the machine, matching the same way:

  ```python
  for candidate in _walk(root):
      if candidate.id.split(".")[-1] == target_str:
          logger.debug("✅ Resolved via full tree walk: '%s'", candidate.id)
          return candidate
  ```

Fallback 3 is what fires in the repro. Three further problems compound it:

1. The walk is **order-dependent** — it returns the first match in declaration order. With two `filled` nodes the binding depends on dict ordering in the config, so the same logical machine can resolve differently depending on how the config was assembled.
2. The successful fallback logs at `DEBUG` only (`:1247-1249`). At default log level a wrong binding is completely silent; only the total-failure path logs at `ERROR` (`:1252-1260`).
3. Resolution happens **per transition attempt at runtime**, not once at `create_machine()`, so there is no build-time surface where the problem could be caught (this is LC-08's root too).

## Impact

**General:** the fallback converts a class of errors that should be loud build-time failures into silent runtime misbehaviour, and it does so *most* aggressively exactly where machines are most likely to reuse leaf names — status-like terminal states. It also defeats encapsulation of parallel regions: any region can be forced into any state by a typo elsewhere. Because the wrong binding is deterministic and logged only at DEBUG, it presents as "the machine sometimes ends up in a weird state" with no diagnostic trail.

**CandleViewer (trading OMS):** `filled`, `cancelled` and `failed` appear as leaf names in our Order machine, our Leg machine and every algo machine — by design, since they model the same lifecycle vocabulary. A relative `target: "filled"` written inside the Order machine and later refactored (the parent renamed, the leaf moved one level down) stops resolving locally and silently starts binding a *leg's* `filled` state in a parallel region. The result is a leg that reports filled while the order stays `submitting`: the position-reconciliation sweep sees a filled leg with no fill event, the order machine never fires `onDone`, and the OMS holds an exchange position it believes is still pending. Our rule engine generates some of these targets programmatically, so this is not a typo a reviewer can catch.

## Proposed fix

1. **Add `strict_targets: bool = True` to `create_machine()` / the machine node.** Under strict mode, resolution stops after the four standard attempts and raises `StateNotFoundError` naming the target, the source state and the candidate scopes tried.
2. **Validate targets at build time.** Walk every transition in `create_machine()` and resolve its target once, exactly as unknown action names are already validated (`ImplementationMissingError`). This removes the runtime failure surface entirely and fixes LC-08 at the same time. Cache the resolved `StateNode` on the `TransitionDefinition` so the runtime path becomes a lookup, which is also a small perf win.
3. **Keep the fallbacks only under `strict_targets=False`**, and when a fallback beyond standard resolution succeeds, log at **WARNING** with the full resolved id and the fallback stage, e.g. `⚠️ target 'filled' from 'm.order.submitting' resolved via full-tree-walk to 'm.audit.archive.filled' — this is not standard XState scoping and will be removed; use '#m.audit.archive.filled'`.
4. **Make an ambiguous fallback an error even in lenient mode.** If the tree walk finds more than one last-segment match, raise rather than silently picking the first; that removes the declaration-order dependence.
5. **Never treat `None` as "no transition".** The callers of `_resolve_target_state_node` currently swallow `None` (this is the LC-07 silent-no-op mechanism); a `None` must propagate as `StateNotFoundError`.

Migration: ship (3) + (4) + build-time **warnings** in 0.7.x with `strict_targets` defaulting to `False`; flip the default to `True` in 0.8.0 and document `strict_targets=False` as a deprecated escape hatch. Anyone relying on the fallbacks gets a full release cycle of warnings naming the exact `#id` replacement.

## Acceptance criteria

- [ ] The repro machine raises `StateNotFoundError` (at `create_machine()` under build-time validation) instead of binding `m.audit.archive.filled`.
- [ ] `audit` is never moved by a transition declared in `order`.
- [ ] Standard resolution is unchanged: sibling names, `#machine.full.id`, and root-relative ids all still resolve.
- [ ] With `strict_targets=False`, a fallback resolution emits a `WARNING` naming the stage and the resolved id.
- [ ] An ambiguous last-segment match raises in both modes.
- [ ] `repro/LC-06_overforgiving-target-resolution.py` exits 0.
- [ ] Tests added: `tests/test_target_resolution.py::test_unresolvable_target_raises_at_build_time`, `::test_foreign_region_never_bound_by_leaf_name`, `::test_sibling_and_hash_id_targets_still_resolve`, `::test_lenient_fallback_warns`, `::test_ambiguous_leaf_name_raises`.

## Related

- LC-07 (leading-dot `.child` targets are a silent no-op) — same `None`-swallowing caller. Filed separately.
- LC-08 (unknown target never validated) — fixed by the same build-time validation pass. Filed separately.

## Verification

Independently re-verified on **2026-09-15**.

- Python 3.13.7, `xstate-statemachine` 0.7.0, commit `42612cf`, editable install.
- `repro/LC-06_overforgiving-target-resolution.py` run in a fresh process: **exit code 1**.
  Observed `['m.audit.archive.filled', 'm.order.submitting']`, `BOUND_FOREIGN_STATE: True` — matches the Observed section verbatim.
- Root cause confirmed against source: `_resolve_target_state_node` at `base_interpreter.py:1164`; standard attempts `:1183-1209`; Fallback 1 `:1211`, Fallback 2 `:1220`, Fallback 3 (exhaustive `_walk`, last-segment match, `logger.debug` on success) `:1238-1250`; ERROR only on total failure `:1252-1260`. Line citations in the draft were off by a few lines and have been corrected.
- Expected behaviour re-checked against https://stately.ai/docs/transitions and XState v5 core `packages/core/src/stateUtils.ts`. The draft's doc quote was a paraphrase; it is replaced with the verbatim docs text plus the real upstream error templates (`Child state '<key>' does not exist on '<id>'`, re-wrapped as `Invalid transition definition for state node '<id>': …`). Substance of the claim holds.
- No duplicate: the upstream tracker has one issue total (#17, closed, unrelated).
