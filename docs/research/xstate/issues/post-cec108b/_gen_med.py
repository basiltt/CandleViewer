"""Generate the Medium-severity round-6 new-issue drafts. Run: python _gen_med.py"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

FM = """---
r6: {rid}
title: "{title}"
labels: [bug, severity/medium, {area}]
severity: Medium
engines: {engines}
repro_script: repro/{rid}_{slug}.py
commit: cec108b
python: 3.13.7
verified: true
---

"""

ITEMS = [
    dict(
        rid="R6-10", slug="denied_true_for_crashed_guard", area="area/receipts",
        engines="both",
        title="Bug: `Receipt.denied` is `True` for a guard that *crashed* under `guardErrorPolicy: \"raise\"`, "
              "mislabelling a third case into the bucket #153 exists to separate",
        body="""## Summary

A guard that **raises** under `guardErrorPolicy: "raise"` yields `Receipt.denied=True`,
because `_is_guard_satisfied` returns `False` on the raise path
(`base_interpreter.py:4834`) and that sets `_guard_denied_this_step`. Reproduced on both
engines.

The documentation says `denied` means the guard *"returned False"*
(`docs/api/index.md:1222`, `docs/_guide/interpreters.md:510`). A crash is a third,
never-enumerated case.

## Why we filed this at Medium rather than High

We tried hard to break it and it mostly held up:

- **#153's actual contract is intact.** Declared-but-refused vs undeclared still works;
  an undeclared event still gives `denied=False`. This is a third case mislabelled into
  the denial bucket, not a re-merge of the two #153 separates.
- **No information is lost.** `Receipt.error` is a documented first-class field on the
  same object, and `(denied, error is None)` totally discriminates all three cases in a
  single read. Being misled requires reading `denied` while ignoring a non-`None` `error`.
- **The plugin channel is clean.** A crashed guard under `"raise"` fires no
  `on_unhandled_event` at all, so the `"guard_denied"` disposition is un-conflated.

Note also that two harness errors of our own had to be corrected before this reproduced
at all (`logic_modules=[class]` is invalid; sync `send()` needs `wait=True` to return a
`Receipt`) — flagging that so the repro is read correctly.

## The `defer` half, stated accurately

Under `onUnhandled: "defer"` the receipt reports `denied=True` **and** `deferred=True`
together, so the denial is **not** shadowed where the caller reads it — only the
single-valued plugin disposition string has to pick one label. And a guard-denied event
entering the defer buffer and being replayed later against a changed world is `defer`
performing its documented function over "an event selected no transition"; scoping
`defer` machine-wide on a chart with business-rule guards is **our** configuration
choice to fix, not a library defect. We mention it only because the combination
surprised us.

XState v5 has neither `Receipt` nor `onUnhandled` and grants no authority either way.

## Ask

Either make `denied` `False` when the guard raised, or document `error is None` as the
discriminator. A one-line note that denied events enter the defer buffer and are
re-evaluated later would also have saved us an afternoon.""",
    ),
    dict(
        rid="R6-11", slug="start_returns_before_children_ready", area="area/interpreter",
        engines="async (SyncInterpreter is correct)",
        title="Bug: `await Interpreter.start()` returns before the initial entry set's `invoke` children are "
              "registered and before an initial plain-`def` service completes; `SyncInterpreter.start()` does both",
        body="""## Summary

`await Interpreter.start()` returns while the initial macrostep is still settling. Three
independently written probes land on one root cause.

```
async_completes_inside_start : false
sync_completes_inside_start  : true
engines_agree_on_start_completion : false

async: actors immediately after `await start()` : []
async: child actor became addressable 12.7 ms AFTER start() returned
async: first POKE -> drops: ['unresolved_target']
sync : actors immediately after start() : ['par:kid']   (0 lost in 10)
```

## Root cause

`interpreter.py:487,496`. `start()` enters the initial configuration via `_enter_states`
+ `_settle_transient_transitions` and **never calls `_await_inline_services()`**, which
is only reached from the run loop at `:1645`/`:1649`. So the executor handoff future
created at `:2417-2425` is first drained by the *first event's* macrostep, and
invoke-child registration lands after `start()` has returned.

## Why the existing pin does not catch it

The `(GO, CANCEL) x10` #116 parity oracle passes (`sync=ok10 async=ok10`), so the pinned
regression test is green while the engines disagree on what `start()` means.

## Mitigating, and why it is still worth fixing

The `sendTo` loss is **not silent** — `on_event_dropped(reason='unresolved_target')` plus
a soft step error fire, which is the #133 contract working correctly. But
`await start()` reads as *"the machine is up and its declared children exist"*, and the
two engines disagree about that for the same configuration.

## Ask

Either await the initial macrostep's inline services and actor registration inside async
`start()`, or expose an awaitable `children_ready()` and document that `start()` does not
imply it. We have implemented the latter as a wrapper on our side and would happily drop
it.""",
    ),
    dict(
        rid="R6-12", slug="threadsafe_self_send_counter_leak", area="area/interpreter",
        engines="async",
        title="Bug: `_threadsafe_self_sends_in_flight` is incremented on the calling thread and decremented "
              "inside `_deliver`, so it leaks permanently if `_deliver` never runs — and it gates the `_raise_depth` reset",
        body="""## Summary

```
in-flight counter after loop stop: 5   (expected 0)
```

Incremented at `interpreter.py:1132` on the **calling thread**, decremented at `:1136`
**inside `_deliver`**. There is no compensating path if `_deliver` never runs — a stopped
loop, a refused enqueue, a cancelled future. The leak is deterministic and reproduces
every run.

## Why it matters beyond tidiness

The counter gates the `_raise_depth` reset at `interpreter.py:1513`. A permanently
non-zero value means the chain budget can never reset, so a long-lived machine would
eventually trip `RunawayChainError` on entirely legitimate work.

## Honest scoping

We could **not** drive that trip. `p10_counter_leak.py` failed to produce one, because
external events do not increment `_raise_depth` in the first place. So the consequence is
**latent, not demonstrated** — we are filing the leak, which is certain, and flagging the
consequence, which is a reading of the code rather than an observation.

## Suggested fix

Decrement in a done-callback attached to the returned future, so every terminal outcome
of the send — delivered, refused, cancelled, loop gone — balances the increment.""",
    ),
    dict(
        rid="R6-13", slug="service_executor_hardcoded_pool", area="area/services",
        engines="async",
        title="Feature/bug: `_get_service_executor()` hard-codes `ThreadPoolExecutor(max_workers=4)` with no public "
              "`service_pool_size=`, so >4 concurrent plain-`def` services serialise in waves",
        body="""## Summary

`interpreter.py:2360` constructs `ThreadPoolExecutor(max_workers=4)`. The limit is not
on the public surface and is not documented. Concurrency shows a clean step function at
multiples of 4:

```
n <= 4   : 0.22 s
n = 5-8  : 0.41 s
n = 12   : 0.62 s
```

Worse, it compounds: 9 x 0.2 s services took **5.01 s** against an ideal of 0.2 s and a
fully serialised 1.8 s — i.e. **worse than serial**, because each wave also blocks a
macrostep.

## Scoping

Medium, not High, because a workaround exists and works: passing an explicit
`service_executor=` overrides the pool entirely. We now set it unconditionally.

## Ask

A `service_pool_size=` argument, and a documented statement of the default limit and its
interaction with macrostep blocking. Right now a user who never reads the source has no
way to know that the fifth concurrent service waits.""",
    ),
    dict(
        rid="R6-14", slug="after_lateness_unbounded_under_load", area="area/timers",
        engines="both",
        title="Regression: `after` timer lateness is 88-92 ms against a 50 ms budget under a busy loop — "
              "the per-macrostep settle budget bounds iterations but not lateness",
        body="""## Summary

**Regression against `5e07ba8`**, reproduced 5/5 deterministically.

The `AfterEvent` timestamp *fields* are correctly populated (#118 is genuinely fixed —
we have confirmed that separately and asked for #118 to be closed). What regressed is
the lateness itself: under a 100-iteration busy loop, observed lateness is **88-92 ms**
against a 50 ms budget.

The round-5 CHANGELOG describes a *"per-macrostep settle budget"*, which we read as
bounding the delay a timer can suffer. It bounds iterations per macrostep, but not
lateness under load.

## Note on severity

Medium for us because we already constrain `after` to coarse, non-critical timeouts and
drive all latency-sensitive timing from an external monotonic scheduler — a constraint
we adopted for an earlier finding. For a user who takes `after` at face value for, say,
a 50 ms heartbeat, the observed behaviour is a doubling.

## Related

A second, independent probe (`after.100` firing at 0.528 s while a 0.5 s plain-`def`
service is in flight, ~428 ms late) shows the same class from the services direction.
That one is arguably by design given the documented macrostep semantics, but it is not
documented as a timing consequence anywhere we could find.""",
    ),
    dict(
        rid="R6-15", slug="stop_leaves_duplicate_receipts_unresolved", area="area/interpreter",
        engines="async",
        title="Regression: `stop()` does not resolve every outstanding duplicate-`Event`-instance receipt with "
              "`InterpreterStoppedError` — some racing events settle as ordinary success receipts",
        body="""## Summary

**Regression against `5e07ba8`**, reproduced 5/5 deterministically.

Cases A, B and C of the original duplicate-`Event`-instance collision bug are
**genuinely fixed** — fresh and reused-instance concurrent `send()` / `send_threadsafe`
all now resolve correctly, and we are glad to see it.

Case D regressed: `stop()` no longer resolves *every* outstanding duplicate-instance
receipt with `InterpreterStoppedError`. Some events that raced the stop land as ordinary
`Receipt(changed=True, ...)`.

## Why it matters

A caller awaiting a receipt across a shutdown cannot distinguish "this was applied" from
"this was abandoned" for the racing window. For an order submission that is the wrong
kind of ambiguity: the safe reading of a stopped interpreter is that nothing after the
stop happened, and a success receipt asserts the opposite.

## Ask

Resolve all outstanding receipts at `stop()`, including duplicate `Event` instances, with
`InterpreterStoppedError`. A pinned test for case D specifically — the existing coverage
passes on A/B/C.""",
    ),
]

FOOT = """

---

*Filed as part of adoption audit #26, round 6, against `main` @ `cec108b` (unreleased
0.8.1 — `__version__` still reports `0.8.0`, so this is keyed on the commit). Reproduced
in a fresh process against a clean venv before filing. CPython 3.13.7, Windows 11.*
"""


def main() -> None:
    d = os.path.join(HERE, "new")
    os.makedirs(d, exist_ok=True)
    out = []
    for it in ITEMS:
        name = f"{it['rid']}-{it['slug'].replace('_', '-')}.md"
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write(FM.format(**it) + it["body"].strip() + FOOT)
        out.append({"file": f"new/{name}", "r6": it["rid"], "title": it["title"],
                    "labels": ["bug", "severity/medium"], "severity": "Medium"})
    with open(os.path.join(HERE, "_new_medium.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"medium new-issue drafts: {len(out)}")


if __name__ == "__main__":
    main()
