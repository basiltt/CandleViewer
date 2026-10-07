---
r9: R9-02
severity: High
verified: true
build: f28719c
relates_to: [195]
labels: [bug, severity/high, area/interpreter, events, persistence]
repro: new/repro/R9-02_after_matched_on_public_class.py
---

# `after` transitions are matched on the public `AfterEvent` class, so a forged snapshot record fires a 60-second timer instantly

**Severity (ours):** High
**Relates to:** #195 — **narrower than claimed**: that fix minted three engine subclasses but wired only two of the three into transition selection.

---

## Summary

#195 minted three private engine event subclasses — `_EngineDone`, `_EngineError` and `_EngineAfter` (`src/xstate_statemachine/events.py:567-590`) — and made provenance, not spelling, decide system status. Selection was then gated on provenance for the `done`/`error` families, but **not for `after`**.

`src/xstate_statemachine/base_interpreter.py:4523` still selects `after` transitions on a bare `isinstance(event, AfterEvent)` against the **public, package-root-exported** class, never consulting `is_system_event` / `_EngineAfter` — unlike the `DoneEvent`/`ErrorEvent` branch eight lines below it, which does call `_completion_is_for_live_invocation` (`base_interpreter.py:4536-4546`).

The consequence that matters: **a forged `pending_events` record restores and fires an `after` timer instantly, even with `strict=True`**, because a restored event never passes through the `send()`-time check.

## Environment

- Library: `main` @ `f28719c` (merge of PR #202, unreleased 0.8.1; `__version__` still reports `0.8.0` — **key on the commit**, not the version string)
- CPython 3.13.7, Windows 11 Pro 10.0.26200, fresh venv
- `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`
- No service/action is involved in this finding (it is pure event-selection and restore), so the `def` / `async def` axis does not apply; the repro nonetheless exercises both the async `send()` path and the `from_snapshot()` restore path.

## What is and is not affected — stated precisely

We re-ran both vectors rather than inheriting them, and **one half of our own first characterisation was wrong**. Our findings register overstated the send-side half; to be fair to #195, we correct it here:

| Vector | `strict=True` | `strict=False` (the default) |
|---|---|---|
| **A** — hand-built `AfterEvent` passed to `send()` | **correctly refused** (`UnknownEventError`) | **fires the 60 s timer** |
| **B** — forged `pending_events` record, **no `"engine"` flag**, via `from_snapshot()` | **fires the 60 s timer** | fires the 60 s timer |

**To be explicit: the send-side vector under `strict=True` IS correctly refused.** The gate #195 built at `base_interpreter.py:2134` does cover hand-built `AfterEvent`s, and our register was wrong to imply otherwise. Vector B is the live defect: `_enqueue_restored` (called at `base_interpreter.py:1768`) puts the restored event straight on the inbox, so `strict` is never consulted on that path at all.

Vector A at the **default** `strict=False` remains a real (if lesser) issue, because it shows the privilege is attached to the exported class rather than to provenance — which is exactly the property #195 set out to remove.

## The discriminating control

This rules out the benign explanation "the `after.*` namespace is simply open, and any event of that name matches". At the default `strict=False`:

```
AfterEvent("after.60000.m.work")  ->  ['m.expired']     # fires a 60s timer instantly
Event("after.60000.m.work")       ->  ['m.work']        # SAME NAME, plain class: ignored
"after.60000.m.work" (bare str)   ->  ['m.work']        # ignored
```

Same name, three classes, different outcomes. **It is the class that is privileged, not the namespace** — and that class is exported from the package root (`__init__.py`).

## Minimal reproduction

Complete, standalone (stdlib + `xstate_statemachine` only, every helper inlined), run from a neutral cwd. Byte-identical to `repro/R9-02_after_matched_on_public_class.py`. **Exits 1 while the defect is present, 0 once it is fixed.**

```python
"""R9-02 — STANDALONE repro.

`after` transitions are selected on the PUBLIC exported `AfterEvent` class,
never on the private `_EngineAfter` minted by #195. Two consequences:

  (A) A hand-built `AfterEvent` fires a 60-second timer instantly.
      A plain `Event` of the SAME NAME does not -- so it is the CLASS that is
      privileged, not the `after.*` namespace. (This control refutes the
      "open namespace" explanation.)

  (B) The decisive vector needs no API call at all, and so never meets the
      `send()`-time `strict` check: a forged `pending_events` record with NO
      "engine" flag restores as user traffic (correct per #195) and is then
      handed straight to the inbox by `_enqueue_restored`. With strict=True
      the machine still reaches `m.expired`.

Exits 1 if either vector fires the timer. Exits 0 when both are refused.

stdlib + xstate_statemachine only. Verified against main @ f28719c.
"""
import asyncio
import json
import sys

from xstate_statemachine import (
    AfterEvent,
    Event,
    Interpreter,
    MachineLogic,
    create_machine,
)

CFG = {
    "id": "m",
    "initial": "work",
    "states": {
        "work": {"after": {60000: "expired"}, "on": {"GO": "other"}},
        "expired": {},
        "other": {},
    },
}


def build():
    # Fresh definition each time: the loader mutates target strings in place.
    return create_machine(json.loads(json.dumps(CFG)), logic=MachineLogic())


async def vector_a(strict):
    """Hand-built AfterEvent vs a plain Event of the same name."""
    results = {}
    for label, ev in (
        ("AfterEvent", AfterEvent("after.60000.m.work")),
        ("Event(same name)", Event("after.60000.m.work")),
        ("bare str", "after.60000.m.work"),
    ):
        i = Interpreter(build())
        i.strict = strict
        await i.start()
        await asyncio.sleep(0.02)
        try:
            await i.send(ev)
        except Exception as e:  # strict may refuse -- that is the good path
            results[label] = "refused:" + type(e).__name__
            await i.stop()
            continue
        await asyncio.sleep(0.05)
        results[label] = sorted(i.current_state_ids)
        await i.stop()
    return results


async def vector_b():
    """Forged pending_events record, no 'engine' flag, via from_snapshot."""
    i = Interpreter(build())
    i.strict = True
    await i.start()
    await asyncio.sleep(0.02)
    snap = i.get_snapshot()
    await i.stop()

    snap = json.loads(snap) if isinstance(snap, str) else snap
    snap.setdefault("pending_events", []).append(
        {"kind": "after", "type": "after.60000.m.work"}
    )
    try:
        j = Interpreter.from_snapshot(json.dumps(snap), build())
    except Exception as e:
        return "restore refused:" + type(e).__name__
    j.strict = True
    await j.start()
    await asyncio.sleep(0.1)
    out = sorted(j.current_state_ids)
    await j.stop()
    return out


async def main():
    a_strict = await vector_a(True)
    a_default = await vector_a(False)
    b = await vector_b()

    print("VECTOR A -- hand-built event, strict=True (send-side check)")
    for k, v in a_strict.items():
        print("  %-18s -> %s" % (k, v))
    print("VECTOR A -- hand-built event, strict=False (THE DEFAULT)")
    for k, v in a_default.items():
        print("  %-18s -> %s" % (k, v))
    print("VECTOR B -- forged snapshot record (no 'engine' flag), strict=True")
    print("  restored states   -> %s" % (b,))

    bad = []
    if a_default.get("AfterEvent") == ["m.expired"]:
        bad.append(
            "A: at the DEFAULT strict=False, a hand-built AfterEvent fired "
            "the 60s timer"
        )
    if b == ["m.expired"]:
        bad.append(
            "B: a forged snapshot record fired the 60s timer EVEN AT "
            "strict=True (never meets the send()-time check)"
        )

    # Discriminator: if a plain Event of the same name also moves the machine,
    # the `after.*` namespace is merely open and the finding is weaker. If it
    # does NOT move while AfterEvent does, the CLASS itself is privileged.
    ctrl = a_default.get("Event(same name)")
    if a_default.get("AfterEvent") == ["m.expired"] and ctrl == ["m.work"]:
        print()
        print(
            "DISCRIMINATOR: plain Event of the same name stayed in %s while "
            "AfterEvent moved to ['m.expired'] -> the CLASS is privileged, "
            "not the namespace." % (ctrl,)
        )

    print()
    if bad:
        for line in bad:
            print("DEFECT:", line)
        print("VERDICT: FAIL (%d/2 vectors fired a 60-second timer)" % len(bad))
        return 1
    print("VERDICT: ok -- both vectors refused")
    return 0


sys.exit(asyncio.run(main()))
```

## Observed

Verbatim stdout from a fresh run (cwd `<home>`, i.e. outside both the library tree and the audit tree):

```
VECTOR A -- hand-built event, strict=True (send-side check)
  AfterEvent         -> refused:UnknownEventError
  Event(same name)   -> refused:UnknownEventError
  bare str           -> refused:UnknownEventError
VECTOR A -- hand-built event, strict=False (THE DEFAULT)
  AfterEvent         -> ['m.expired']
  Event(same name)   -> ['m.work']
  bare str           -> ['m.work']
VECTOR B -- forged snapshot record (no 'engine' flag), strict=True
  restored states   -> ['m.expired']

DISCRIMINATOR: plain Event of the same name stayed in ['m.work'] while AfterEvent moved to ['m.expired'] -> the CLASS is privileged, not the namespace.

DEFECT: A: at the DEFAULT strict=False, a hand-built AfterEvent fired the 60s timer
DEFECT: B: a forged snapshot record fired the 60s timer EVEN AT strict=True (never meets the send()-time check)
VERDICT: FAIL (2/2 vectors fired a 60-second timer)
```

Exit code **1**.

## Expected

**1. The library's own contract.** `src/xstate_statemachine/events.py:272-287`, the docstring of `is_system_event`, states the rule this branch does not follow:

> ``True`` for events the ENGINE synthesised (#79).
>
> Provenance, not spelling -- and not public type either (#195). A `DoneEvent` / `ErrorEvent` / **`AfterEvent`** the engine minted is an instance of a private subclass (`engine_done` / `engine_error` / **`engine_after`**); one built by hand from the public class is USER traffic, subject to `strict` and `onUnhandled` like any other event.

And `events.py:326-331`, in the persistence writer, makes the restore-side intent explicit:

> 🏷️ #195: an engine-minted completion persists its provenance so the round-trip restores it as engine-minted (and a record without the flag -- hand-written, or from a pre-#195 writer -- **restores as the PUBLIC class, i.e. user traffic**).

So the library already classifies a flagless restored `after` record as *user traffic* — and then, because selection tests the public class, drives an engine-only transition with it anyway. The two halves of #195 disagree with each other; this is not us importing an outside expectation.

**2. XState v5.** `after` is not an open event channel. In `packages/core/src/stateUtils.ts::getDelayedTransitions`, the event is minted by the engine and both raised and cancelled by compiler-inserted entry/exit actions:

```ts
const mutateEntryExit = (delay: string | number) => {
  const afterEvent = createAfterEvent(delay, stateNode.id);
  const eventType = afterEvent.type;
  stateNode.entry.push(raise(afterEvent, { id: eventType, delay }));
  stateNode.exit.push(cancel(eventType));
  return eventType;
};
```

The `xstate.after(...)` event exists only as an internally `raise`d event tied to a scheduled, cancellable timer — there is no supported path by which external traffic supplies one. Matching it on a user-constructible public class has no XState counterpart.

**3. SCXML.** §3.13 requires that exiting a state *cancel* what that state scheduled. An `after` event that can be injected — from the API at the default `strict`, or from a snapshot record at any `strict` — is a timer firing that was never scheduled, and so can never have been cancelled by the exit that should have pre-empted it.

## Root cause

Confirmed open on `main` @ `f28719c`:

- **`src/xstate_statemachine/base_interpreter.py:4523`** — the `after` selection branch:

  ```python
  # ⏰ `after` transitions for timed events.
  if isinstance(event, AfterEvent):
      for transitions in current.after.values():
          for t in transitions:
              if t.event == event.type and _passes(t):
                  eligible.append(t)
  ```

  A bare `isinstance` against the **public** class. Compare the sibling branch at **`base_interpreter.py:4531-4546`**, which after `isinstance(event, (DoneEvent, ErrorEvent))` immediately narrows with `_completion_is_for_live_invocation(...)` under an explicit `# 🛡️ #195` comment. The `after` branch has no such narrowing and never calls `is_system_event`.

- **`src/xstate_statemachine/base_interpreter.py:1768`** — the restore path:

  ```python
  for record in snapshot.get("pending_events") or []:
      interpreter._enqueue_restored(restore_event(record))
  ```

  `_enqueue_restored` (declared `base_interpreter.py:2022`) goes to the queue directly. The `strict` / schema gate lives in the `send()` path (`base_interpreter.py:2128-2142`) and is therefore structurally unreachable for restored events. That is why vector B defeats `strict=True` while vector A does not.

- **`src/xstate_statemachine/events.py:331`** — `if kind in ("done", "error", "after") and is_system_event(event): rec["engine"] = True`. The `after` kind is handled correctly *here*; the asymmetry is entirely at the selection site.

## Impact

**General.** A snapshot is untrusted input from the process's point of view — it comes off disk, a cache or a store, and may have been written by an older library version or another writer entirely. Vector B means whoever can write a snapshot record can fire **any** `after` transition anywhere in the chart, immediately, at an arbitrary point in the machine's life, with `strict=True` and without making a single API call. That is a control-flow primitive, not data corruption: it does not merely set a wrong value, it takes a transition the chart reserves for the passage of time.

It also breaks the invariant that a timeout branch is reachable *only* after its delay has elapsed. Every chart that uses `after` as a deadline — retry backoff, circuit-breaker cool-down, lease expiry, session timeout — becomes instantly reachable.

Vector A matters less but is not nothing: at the shipped default (`strict=False`) any code holding the package-root-exported `AfterEvent` can do the same thing through the ordinary `send()` API, and that class is exported precisely so users can type-annotate and `isinstance`-branch on it.

**In our adoption (order management).** We run order-management machines where `after` is the escalation timeout — "if the exchange has not acknowledged in 60 seconds, cancel-replace and escalate". Firing that transition instantly means a live order is cancel-replaced while the original is still working and still acknowledgeable, from a state the machine reached in under a millisecond of wall-clock. The escalation path also carries a notification and a risk-desk hand-off, so the blast radius is not confined to the state machine.

We recognise that #185 established snapshot writers as a trust boundary, and we are not asking you to re-litigate that. The difference is that **#198 in this same release now refuses forged `configuration` payloads** — so "a record writer already controls the state anyway" no longer holds uniformly. The library has started defending this boundary; this is a gap in that defence rather than a place where no defence was ever claimed.

## Proposed fix

**1. Gate selection on provenance (the one-line core).** At `base_interpreter.py:4523`, narrow exactly as the sibling branch does. The mechanism already exists in the file — `is_system_event` is imported at `base_interpreter.py:66`:

```python
# ⏰ `after` transitions for timed events.
# 🛡️ #195: only an ENGINE-minted `_EngineAfter` is a timer firing; a
#    hand-built or restored public `AfterEvent` is user traffic.
if isinstance(event, AfterEvent) and is_system_event(event):
    ...
```

This closes vector A at every `strict` setting and vector B as well, since a flagless record already restores as the public class by design (`events.py:326-331`).

**2. Make `strict` reachable on the restore path (defence in depth).** Route `_enqueue_restored` through the same validation `send()` uses, or validate each record in the loop at `base_interpreter.py:1768` before enqueueing. Even with fix 1 in place, a restored event is currently the only way user-classified traffic enters the machine without ever meeting `strict` — worth closing on its own terms. (We have filed this separately as a Low.)

**3. The generalisation, offered constructively.** #195 is a good mechanism that shipped covering two of the three families it minted a class for. A small meta-test asserting that **every** `isinstance(event, <public engine class>)` site in `base_interpreter.py` is paired with a provenance check would have caught this at authoring time, and would also catch the `done.state.*` relative (an unreserved namespace for compound/parallel `onDone`, filed separately as a Low). That generalises better than fixing the `after` branch alone.

## Acceptance criteria

Named tests, all asserting the state does **not** advance to the timer target. No service or action participates in this path, so the `def`/`async def` axis is not applicable; the engine axis is, since both engines share `_select_eligible_transitions` in `base_interpreter.py` but have separate `send()` and `_enqueue_restored` implementations.

1. `test_after_hand_built_afterevent_is_not_privileged` — parametrised over `strict in (True, False)` **and** over `(Interpreter, SyncInterpreter)`. Send a hand-built `AfterEvent("after.60000.m.work")` into a machine sitting in `work` with a 60 s `after`. Assert: under `strict=True` it raises `UnknownEventError` (today's correct behaviour — pin it so the fix does not regress it); under `strict=False` the configuration stays `{"m.work"}` and never reaches `m.expired`.

2. `test_after_class_is_not_privileged_over_same_named_event` — the discriminator, at `strict=False`, both engines. Assert `AfterEvent("after.60000.m.work")`, `Event("after.60000.m.work")` and the bare string `"after.60000.m.work"` all produce the *same* outcome (`{"m.work"}`). Today the first diverges; this is the test that states the invariant rather than the symptom.

3. `test_forged_pending_events_after_record_does_not_fire_timer` — parametrised over `strict in (True, False)` and both engines. Snapshot a machine in `work`, append `{"kind": "after", "type": "after.60000.m.work"}` (**no `"engine"` key**) to `pending_events`, restore and start. Assert the configuration is `{"m.work"}`. Optionally also assert the record is *refused* at restore, if fix 2 is adopted.

4. `test_engine_minted_after_still_fires` — the anti-regression guard. Drive a real timer (via `SimulatedClock`) on both engines and assert `m.expired` is reached, so the provenance gate does not break genuine timers.

5. `test_engine_flagged_pending_events_after_record_still_fires` — round-trip an *engine-minted* `_EngineAfter` through `get_snapshot()` / `from_snapshot()` (the record carries `"engine": true` per `events.py:331`) and assert it still fires on restore. This pins that the fix distinguishes forged from genuine records rather than disabling restored timers wholesale — the regression #107 and #154 exist to prevent.

6. `test_every_public_engine_event_isinstance_site_checks_provenance` — the meta-test from fix 3. Walk the AST of `base_interpreter.py` for `isinstance(..., (AfterEvent|DoneEvent|ErrorEvent))` tests inside transition selection and assert each is conjoined with, or immediately narrowed by, a provenance check.

## Related

- **#195** — *DoneEvent/AfterEvent carry no provenance marker and are exempt from strict.* The fix is **narrower than claimed**: it minted `_EngineDone`, `_EngineError` **and** `_EngineAfter`, and wired provenance into the `done`/`error` selection branch and into the `send()`-time gate, but the `after` selection branch at `base_interpreter.py:4523` was left on the public class. The title names `AfterEvent` explicitly, so the `after` family was in scope; it is one branch short. We have also **corrected our own round-8 overstatement** above: the `send()`-side gate #195 built does work under `strict=True`.
- **#107** — persisting the priority/timer lane. Establishes that restored `after` records are a supported, load-bearing path, which is why the forged-record vector is reachable at all and why acceptance criterion 5 matters.
- **#118** — `AfterEvent` lateness telemetry across a round-trip. Same serialisation site (`events.py:340-345`).
- **#198** — refusal of forged `configuration` payloads. The precedent that the library now defends the snapshot boundary rather than treating every writer as fully trusted.
- **#185** — snapshot writers as a trust boundary. The framing this finding is deliberately scoped against.
- **#79 / #162** — the original name-prefix-vs-provenance line of work that #195 concluded.
- Filed separately by us, both Low: `strict` not gating restored `pending_events` at all (the delivery mechanism for vector B), and `done.state.*` as an unreserved namespace for compound/parallel `onDone`.

## Verification

- **Date:** 2026-09-22
- **Library commit:** `f28719c555ef6e9315a71315945a5a4f2965af73` (`main`, merge of PR #202; `__version__` reports `0.8.0`)
- **Python:** CPython 3.13.7 (tags/v3.13.7:bcee1c3, Aug 14 2025) [MSC v.1944 64 bit (AMD64)], Windows 11 Pro 10.0.26200
- **Env:** `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`
- **cwd used:** `<home>` — a neutral directory outside both the library tree and the audit tree, proving the script is genuinely standalone (stdlib + `xstate_statemachine` only, no harness or helper module on the path).
- **Script:** `repro/R9-02_after_matched_on_public_class.py`, byte-identical to the block embedded above.
- **Exit codes:** `1` (defect present) — both vectors fired. Vector A `strict=True`: refused, `UnknownEventError` (correct). Vector A `strict=False`: `['m.expired']` (defect). Vector B `strict=True`: `['m.expired']` (defect). The script returns `0` once both vectors are refused.
- **Source anchors re-read on this tree:** `base_interpreter.py:4523`, `:4531-4546`, `:1768`, `:2022`, `:2128-2142`, `:66`; `events.py:272-287`, `:326-331`, `:567-590`, `:610`.
- **Duplicate check:** `gh issue list -R basiltt/xstate-statemachine --state all --limit 260 --search` run for `AfterEvent`, `after forged snapshot`, `is_system_event`. Nearest hits are #195, #118, #107, #162, #79, #186 — all closed and none covering the `after` selection branch or the forged-`pending_events` vector. **No duplicate.**
