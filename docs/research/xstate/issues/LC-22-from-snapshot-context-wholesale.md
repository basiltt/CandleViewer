---
lc: LC-22
title: "Bug: `from_snapshot` assigns the restored context wholesale — machine defaults are not merged and the caller's dict is aliased"
labels: [bug, severity/high, area/persistence, candleviewer]
severity: High
blocks_adoption: false
repro_script: repro/LC-22_from_snapshot_context_wholesale.py
library_version: 0.7.0 (commit 42612cf)
python: 3.13.7
verified: true
---

## Summary

`BaseInterpreter.from_snapshot()` restores context with a single statement — `interpreter.context = snapshot["context"]` (`base_interpreter.py:872`). Two problems follow. First, the machine's own `context` defaults, already built by `__init__`, are discarded rather than merged: any key added to the machine definition *after* a snapshot was written is simply absent from the restored interpreter, so logic shipped with the new schema raises `KeyError` on live restored state. Second, the assignment is not a copy, so the dict the caller parsed out of storage becomes the live machine context — mutating the machine mutates the caller's object and vice versa.

Snapshots outlive deployments by definition. Any machine whose context schema evolves across releases will restore into a context that is missing its newest keys, and the failure surfaces as an exception inside an action on a real order, not at restore time.

## Environment

- Library: xstate-statemachine 0.7.0, commit `42612cf` (local clone, `pip install -e .`)
- Python: 3.13.7
- OS: Windows-11-10.0.26200-SP0
- Install method: editable install into a dedicated venv

## Minimal reproduction

```python
"""LC-22 repro: `from_snapshot` assigns the restored context wholesale.

`base_interpreter.py:872` does `interpreter.context = snapshot["context"]`.
Context keys added to the machine definition after a snapshot was written
are therefore MISSING from the restored interpreter: the machine's own
default context is never merged underneath the persisted one. An action
shipped with the new schema then raises KeyError on live restored state.

Exit code 1 on failure.
"""

from __future__ import annotations

import asyncio
import json
import logging

from xstate_statemachine import Interpreter, MachineLogic, create_machine

logging.disable(logging.CRITICAL)

V1 = {
    "id": "order",
    "initial": "submitting",
    "context": {"order_id": "A-1", "qty": 10},
    "states": {
        "submitting": {"on": {"FILL": {"target": "filled"}}},
        "filled": {},
    },
}
# v2 of the same machine: two context keys added by a later release.
V2 = json.loads(json.dumps(V1))
V2["context"] = {"order_id": "A-1", "qty": 10, "cum_qty": 0, "venue": "X"}
V2["states"]["submitting"]["on"]["FILL"]["actions"] = ["book"]

ERRORS: list[str] = []


def book(i, c, e, a):  # noqa: ANN001
    # Written against the v2 schema, where `cum_qty` always exists.
    try:
        c["cum_qty"] = c["cum_qty"] + 1
    except KeyError as exc:
        ERRORS.append(f"KeyError: {exc}")


async def main() -> int:
    ok = True
    i1 = await Interpreter(create_machine(V1)).start()
    snap = i1.get_snapshot()
    await i1.stop()

    m2 = create_machine(V2, logic=MachineLogic(actions={"book": book}))
    i2 = Interpreter.from_snapshot(snap, m2)
    missing = sorted({"cum_qty", "venue"} - set(i2.context))
    print(f"OBSERVED restored context     = {i2.context}")
    print("EXPECTED restored context     = "
          "{'order_id': 'A-1', 'qty': 10, 'cum_qty': 0, 'venue': 'X'}")
    print(f"OBSERVED missing default keys = {missing}")
    print("EXPECTED missing default keys = []")
    if missing:
        ok = False

    # The missing keys are not cosmetic: v2 logic fails on restored state.
    await i2.start()
    await i2.send("FILL")
    await asyncio.sleep(0.1)
    await i2.stop()
    print(f"OBSERVED action errors        = {ERRORS}")
    print("EXPECTED action errors        = []")
    if ERRORS:
        ok = False

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed behaviour

```
OBSERVED restored context     = {'order_id': 'A-1', 'qty': 10}
EXPECTED restored context     = {'order_id': 'A-1', 'qty': 10, 'cum_qty': 0, 'venue': 'X'}
OBSERVED missing default keys = ['cum_qty', 'venue']
EXPECTED missing default keys = []
OBSERVED action errors        = ["KeyError: 'cum_qty'"]
EXPECTED action errors        = []
RESULT: FAIL
```

Exit code `1`.

## Expected behaviour

Two distinct claims, with different strengths of evidence. The second is a plain defect; the first is a design gap.

**Aliasing (defect).** `get_persisted_snapshot()` already deep-copies on the way *out* (`base_interpreter.py:721`, with an explicit comment that returning the live dict let later execution retroactively rewrite an already-taken snapshot). The identical hazard exists on the way *in* and is not handled: after `from_snapshot`, the caller's parsed dict *is* the live machine context. XState is explicit that context must not be shared or mutated across actors — <https://stately.ai/docs/context>: "Do not mutate the `context` object... If you mutate the `context` object, you may get unexpected behavior, such as mutating the `context` of other actors." Restoring two interpreters from one parsed dict does exactly that. This half needs no interpretation: the library already knows the rule and applies it in one direction only.

**Schema drift (design gap — note this goes beyond what XState specifies).** We want to be straight with you here: XState's docs do **not** state that a restored snapshot's context is merged over the machine's current `context` defaults, and as far as we can tell XState v5 also restores the persisted context as-is. <https://stately.ai/docs/persistence> says only "You can restore an actor to a persisted state by passing the persisted state into the `state` option of the second argument of `createActor(logic, { snapshot: restoredState })`", and <https://stately.ai/docs/context> says "The object you pass to `context` will be the initial `context` value for any actor created from this machine" — which describes creation, not restoration. So this is **not** a "you diverge from XState" report; it is a "restoring a snapshot written by an older version of your own machine definition silently produces a context that violates the machine's declared shape, and the library offers nothing to detect or survive that."

XState arguably gets away with it because it pairs persistence with a typed `context` and a TypeScript compiler that makes the drift visible at build time. This library is untyped at runtime and the drift surfaces as a `KeyError` inside an action on live state. Something has to close that gap: merging defaults (proposed below), or a loud error at restore time (LC-21's schema version), or at minimum a documented warning on the persistence page that context shape is the caller's problem across releases. Today there is none of the three.

## Root cause analysis

`src/xstate_statemachine/base_interpreter.py`:

- `:871` — `interpreter = cls(machine)` constructs the interpreter, which runs `self.context = self._build_initial_context(machine, input)` (`:294`) and therefore *does* have a correct, fully-populated default context at this moment.
- `:872` — `interpreter.context = snapshot["context"]` throws that default away. The freshly built default context is discarded in its entirety and replaced by the JSON-decoded dict, by reference.

There is no merge and no copy. Everything else in `from_snapshot` is careful about forward/backward compatibility (`snapshot.get("configuration") or snapshot["state_ids"]` falls back for older snapshots at `:879`; `snapshot.get("output")` at `:901`, `snapshot.get("history") or {}` at `:913`, `snapshot.get("actors") or {}` at `:925` all tolerate missing fields). Context is the one field restored with no tolerance for definition drift at all — and it is the field most likely to drift.

Note that the same line is inherited by `SyncInterpreter`, and by the recursive child-actor restore at `:937`, so every actor in a restored hierarchy has the same two defects.

## Impact

**General users.** Any project that persists snapshots across releases — the entire point of persistence — will eventually restore a v1 snapshot into a v2 machine. The restored actor reports `status == "running"` and a correct state configuration, so every health check passes; the failure appears later as a `KeyError` inside an action, at whatever moment the new key is first touched. The aliasing defect is subtler and worse in review: application code that keeps the parsed snapshot dict around (for logging, for a retry, for a diff) is silently holding a live handle on machine context, and writes through it bypass the machine entirely.

**CandleViewer (trading OMS).** CandleViewer is a trading order-management system we are evaluating this library for. Its order machine's context gains fields as the venue integration matures — `cum_qty`, `venue`, `avg_px`, `client_order_id` were each added in a different release. A process restarts after a deploy, restores an order that was `submitting` when the old build died, and the first `FILL` from the exchange runs the new `book` action, which does `c["cum_qty"] + 1` and raises `KeyError`. Because an action that raises does not roll back its transition (reported separately as LC-01), the machine advances to `filled` with **no fill booked**: the position exists on the exchange, the OMS believes the order filled for zero quantity, and the reconciliation sweep compares two numbers that disagree with no record of why. Rewriting the action defensively as `c.get("cum_qty", 0)` is what most teams reach for and it is worse — it silently substitutes a default for a value that may legitimately have been non-zero, turning a loud crash into a wrong position.

## Proposed fix

**Location.** `src/xstate_statemachine/base_interpreter.py`, `from_snapshot`, replacing line 872.

**Design.**

```python
# 🧊 Layer the persisted context over the machine's current defaults, and
#    deep-copy so the caller's parsed dict does not alias live state.
restored_context = copy.deepcopy(snapshot["context"])
if isinstance(interpreter.context, dict) and isinstance(restored_context, dict):
    merged = {**interpreter.context, **restored_context}
else:
    merged = restored_context
interpreter.context = merged
```

`copy` is already imported (used at `:721`). The shallow `{**defaults, **persisted}` merge is deliberate: persisted values win for every key present, defaults fill only keys the snapshot has never heard of. A deep/recursive merge is *not* proposed — it would resurrect nested keys the application intentionally deleted and is far harder to reason about.

**Backwards compatibility.** Additive and safe for the overwhelming majority of callers:

- Snapshots whose context matches the machine definition restore byte-identically (the merge is a no-op when key sets agree).
- Snapshots missing keys gain them at their machine-default values — which is what a reader of the docs already expects.
- The only behavioural regression risk is a caller who *relies* on a restored key being absent (e.g. `if "venue" not in ctx`). That is already a latent bug rather than a supported pattern, but it justifies mentioning the merge in the changelog under "behaviour changes" rather than "fixes".
- The deep copy changes aliasing, which no documented API promises. It costs one `deepcopy` per restore, negligible next to JSON decoding.

**Optional follow-up** (separate issue, related to LC-21): a `strict_context=True` flag that *raises* when the persisted context has keys the machine does not declare, so schema drift is detectable rather than merely survivable. Out of scope here; the merge is the correctness fix.

If you would rather not change restore semantics at all, the aliasing half stands on its own and should be fixed regardless — `interpreter.context = copy.deepcopy(snapshot["context"])` is a one-line change with no behavioural surface beyond removing the shared reference.

## Acceptance criteria

- [ ] `from_snapshot` merges the machine's default context underneath the persisted context, persisted values winning per key.
- [ ] `from_snapshot` deep-copies the persisted context; mutating the dict passed in (or the dict obtained by `json.loads` of the snapshot string) does not affect the restored interpreter, and vice versa.
- [ ] The same behaviour applies to `SyncInterpreter` and to recursively restored child actors (`base_interpreter.py:937`).
- [ ] `repro/LC-22_from_snapshot_context_wholesale.py` exits `0`.
- [ ] Tests added under `tests/`:
  - `tests/test_persistence_context_merge.py::test_from_snapshot_merges_new_machine_default_keys`
  - `tests/test_persistence_context_merge.py::test_from_snapshot_persisted_values_win_over_defaults`
  - `tests/test_persistence_context_merge.py::test_from_snapshot_deep_copies_context_no_aliasing`
  - `tests/test_persistence_context_merge.py::test_from_snapshot_child_actor_context_is_merged_and_copied`
  - `tests/test_persistence_context_merge.py::test_sync_interpreter_from_snapshot_merges_defaults`
- [ ] Docstring of `from_snapshot` states the merge rule explicitly, alongside the existing note about entry actions and timers not being re-run.

## Related

These are sibling reports from the same evaluation; each is self-contained and can be read independently.

- **LC-21** — no schema version or machine identity in the snapshot; this issue is the concrete damage that absence permits. Fixing both together gives detectable drift *and* survivable drift.
- **LC-19** and **LC-20** — restore does not restart invokes, and does not resume pending `after` timers: the other two "restore is not a faithful resume" defects.
- **LC-01** — an action that raises still commits its transition, which is why the `KeyError` this bug produces is silent corruption rather than a clean failure.
- **LC-24** — pending queued events are also absent from the snapshot.

## Verification

- Verified: 2026-09-15
- Python: 3.13.7, Windows-11-10.0.26200-SP0
- Library commit: `42612cf`, version 0.7.0 (editable install)
- Command: `python repro/LC-22_from_snapshot_context_wholesale.py`
- Exit code: `1` (fails against the library as shipped); Observed block matches real output byte for byte.
- Root-cause lines re-checked against source: `base_interpreter.py:294` (`self.context = self._build_initial_context(...)`), `:721` (`"context": copy.deepcopy(self.context)` plus the comment quoted), `:871` (`interpreter = cls(machine)`), `:872` (`interpreter.context = snapshot["context"]`), `:879` (`snapshot.get("configuration") or snapshot["state_ids"]`), `:901`/`:913`/`:925` (tolerant `.get` for output/history/actors), `:937` (recursive child restore), `import copy` at `:28`. All confirmed. Two line numbers in the draft were off by one and have been corrected (`:870`→`:871`, `:878`→`:879`).
- Expected-behaviour claims re-checked against <https://stately.ai/docs/persistence> and <https://stately.ai/docs/context>. **Corrected:** the draft claimed XState merges persisted context over machine defaults. The docs do not say this and XState does not appear to do it. The Expected section has been rewritten to separate the aliasing defect (well supported, including by the library's own code) from the schema-drift gap (a design argument, now labelled as such rather than as an XState-conformance claim). Severity left at High on the strength of the impact, but a maintainer may reasonably scope the fix to the deep-copy alone.
- Duplicate check: `gh issue list --state all` on the upstream repo returns one issue (#17, camelCase action auto-discovery, closed). Not a duplicate.
