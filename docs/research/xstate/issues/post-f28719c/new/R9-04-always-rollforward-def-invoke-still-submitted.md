---
r9: R9-04
severity: High
verified: true
build: f28719c
relates_to: [193]
labels: [bug, severity/high, area/interpreter, actors, sync-interpreter, docs]
repro: new/repro/R9-04_always_rollforward_def_invoke_submitted.py
---

# A `def` service armed by a transition an `always` rolls forward is still submitted, contradicting #193 and `production-characteristics.md:97`

**Severity (ours):** High
**Relates to:** #193 — **one branch short**: the rollback half landed, the roll-forward half did not, and `SyncInterpreter` was not covered at all.

---

## Summary

#193 moved the `def`-service executor handoff into the engine-held task so that **rollback and roll-forward** both cancel before submission. **The rollback half landed on the async engine. The roll-forward half did not, on either engine, and `SyncInterpreter` leaks both halves.**

3 of 6 lanes call a live service from a state the machine never settles in.

The documentation states the opposite in so many words. `docs/_guide/production-characteristics.md:97`, verbatim, final sentence of the plain-`def` contract paragraph:

> Where the async engine *does* now match the coroutine lane: a `def` service armed by a transition that is then rolled back (`actionErrorPolicy: "rollback"`) or rolled forward (an `always` out of the state before it stabilises) is never submitted to the pool.

The leaking case-A rows below are verbatim the "rolled forward (an `always` out of the state before it stabilises)" clause of that sentence.

## Environment

- Library: `main` @ `f28719c` (merge of PR #202, unreleased 0.8.1; `__version__` still reports `0.8.0` — **key on the commit**)
- CPython 3.13.7, Windows 11 Pro 10.0.26200, fresh venv
- `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`
- Both service spellings (`def` and `async def`) and both engines (`Interpreter`, `SyncInterpreter`) exercised; `SimulatedClock` for determinism.

## The lane matrix — this is the finding

Re-run fresh at `f28719c`, all six lanes. Case A is the roll-forward (`always` with a true guard out of the invoking state); case B is the rollback (entry action raises under `actionErrorPolicy: "rollback"`). `SyncInterpreter` has no `async def` lane, so six lanes rather than eight.

| # | Case | Service | Engine | `service_calls` | Leak? |
|---|---|---|---|---|---|
| 1 | A — roll-forward | `async def` | async | `[]` | **no** |
| 2 | A — roll-forward | `def` | async | `['submit_child']` | **YES** |
| 3 | A — roll-forward | `def` | sync | `['submit_child']` | **YES** |
| 4 | B — rollback | `async def` | async | `[]` | **no** |
| 5 | B — rollback | `def` | async | `[]` | no — **this is #193 landing** |
| 6 | B — rollback | `def` | sync | `['submit_child']` | **YES** |

**3/6 lanes leaked the service call.** Every leaking lane is a `def` service; every `async def` lane is clean, which is consistent with #193's own account that a coroutine service becomes its own task and is cancelled on exit.

Lane 5 flipping LEAK→ok between `6db65d8` and `f28719c` is **#193 working**, and it is the more dangerous half in order-management terms. Credit for that — it is a real fix and we verified it independently rather than taking the CHANGELOG's word.

What #193 did not reach: the `always` roll-forward epilogue on either engine (lanes 2 and 3), and `SyncInterpreter` on either epilogue (lanes 3 and 6).

## Chart

No catalogue dependency, no external fixtures:

```
armed --GO--> submitting
submitting: entry [bump], invoke submit_child (onDone/onError -> armed),
            always -> armed   (case A only, guard constantly true)
```

Case B replaces the roll-forward with a `bump` that raises, under `actionErrorPolicy: "rollback"`.

## Minimal reproduction

Complete, standalone (stdlib + `xstate_statemachine` only, every helper inlined), run from a neutral cwd. Byte-identical to `repro/R9-04_always_rollforward_def_invoke_submitted.py`. **Exits 1 while any lane leaks, 0 once every lane is clean.**

```python
# -*- coding: utf-8 -*-
"""LD-01 (residual) @ f28719c -- STANDALONE (stdlib + xstate_statemachine).

A plain `def` service is still CALLED when an `always` transition rolls the
machine forward out of the invoking state before the invoke should ever run.

#193 moved the def-service executor handoff into the engine-held task so
that rollback AND roll-forward cancel before submission. The ROLLBACK half
is fixed (case B passes on the async engine). The ROLL-FORWARD half is NOT:
with `always` leaving the state, the plain callable is still submitted.

`SyncInterpreter` fails BOTH halves.

Chart (no catalogue dependency):

    armed --GO--> submitting
    submitting: entry [bump], invoke submit_child,
                always -> armed   (case A, guard true)

In an OMS `submit_child` places a live child order. A roll-forward exists
precisely to say "this slice is below minimum, do not send it".

Exit 0 = every lane clean. Exit 1 = at least one leak (the finding).
"""
from __future__ import annotations

import asyncio
import json

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    SyncInterpreter,
    create_machine,
)
from xstate_statemachine.clock import SimulatedClock

CALLS: list[str] = []
ROWS: list[dict] = []


def chart(case: str) -> dict:
    sub = {
        "entry": ["bump"],
        "invoke": {
            "id": "kid",
            "src": "submit_child",
            "onDone": {"target": "#m.armed"},
            "onError": {"target": "#m.armed"},
        },
    }
    if case == "A":
        sub["always"] = [{"target": "#m.armed", "guard": "roll_forward"}]
    return {
        "id": "m",
        "initial": "armed",
        "actionErrorPolicy": "rollback",
        "onUnhandled": "defer",
        "guardErrorPolicy": "raise",
        "strictTargets": True,
        "strict": True,
        "context": {"n": 0},
        "states": {
            "armed": {"on": {"GO": {"target": "#m.submitting"}}},
            "submitting": sub,
        },
    }


def logic(case: str, style: str) -> MachineLogic:
    def bump(i, ctx, e, ad):  # noqa: ANN001
        if case == "B":
            raise RuntimeError("entry action failed")
        ctx["n"] = ctx.get("n", 0) + 1

    def svc_def(i, ctx, e):  # noqa: ANN001
        CALLS.append("submit_child")
        return {"ok": True}

    async def svc_async(i, ctx, e):  # noqa: ANN001
        CALLS.append("submit_child")
        return {"ok": True}

    return MachineLogic(
        actions={"bump": bump},
        guards={"roll_forward": lambda ctx, e: True},
        services={"submit_child": svc_def if style == "def" else svc_async},
        strict=True,
    )


def record(case: str, style: str, engine: str, states, ctx) -> None:
    leaked = bool(CALLS)
    ROWS.append(
        {
            "case": case,
            "style": style,
            "engine": engine,
            "states": sorted(states),
            "context": dict(ctx),
            "service_calls": list(CALLS),
            "leaked": leaked,
        }
    )
    print(
        ("LEAK " if leaked else "ok   ")
        + "case %s | %-5s service | %-5s engine | states=%s ctx=%s calls=%s"
        % (case, style, engine, sorted(states), dict(ctx), CALLS),
        flush=True,
    )


async def run_async(case: str, style: str) -> None:
    CALLS.clear()
    m = create_machine(chart(case), logic=logic(case, style))
    i = Interpreter(
        m,
        clock=SimulatedClock(),
        max_queue_size=64,
        overflow_policy=OverflowPolicy.RAISE,
    )
    await i.start()
    await asyncio.sleep(0.05)
    try:
        await asyncio.wait_for(i.send("GO", wait=True), 5)
    except Exception as exc:  # noqa: BLE001
        print("   send raised:", repr(exc), flush=True)
    for _ in range(6):
        await asyncio.sleep(0.03)
    record(case, style, "async", i.current_state_ids, i.context)
    try:
        await asyncio.wait_for(i.stop(), 5)
    except Exception:  # noqa: BLE001
        pass


def run_sync(case: str) -> None:
    CALLS.clear()
    m = create_machine(chart(case), logic=logic(case, "def"))
    i = SyncInterpreter(m, clock=SimulatedClock())
    i.start()
    try:
        i.send("GO")
    except Exception as exc:  # noqa: BLE001
        print("   send raised:", repr(exc), flush=True)
    record(case, "def", "sync", i.current_state_ids, i.context)
    try:
        i.stop()
    except Exception:  # noqa: BLE001
        pass


async def main() -> int:
    for case in ("A", "B"):
        for style in ("async", "def"):
            await run_async(case, style)
        run_sync(case)
    leaks = [r for r in ROWS if r["leaked"]]
    print("\n%d/%d lanes leaked the service call" % (len(leaks), len(ROWS)))
    for r in leaks:
        print("  LEAK: case %s / %s service / %s engine"
              % (r["case"], r["style"], r["engine"]))
    print(json.dumps(ROWS, indent=1))
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

## Observed

Verbatim from a fresh run (cwd `<home>`, outside both the library tree and the audit tree). The interleaved library `ERROR`/`WARNING` logs are the case-B rollback machinery working as designed and are elided here for length; the lane verdict lines and the summary are verbatim:

```
ok   case A | async service | async engine | states=['m.armed'] ctx={'n': 1} calls=[]
LEAK case A | def   service | async engine | states=['m.armed'] ctx={'n': 1} calls=['submit_child']
LEAK case A | def   service | sync  engine | states=['m.armed'] ctx={'n': 1} calls=['submit_child']
ok   case B | async service | async engine | states=['m.armed'] ctx={'n': 0} calls=[]
ok   case B | def   service | async engine | states=['m.armed'] ctx={'n': 0} calls=[]
LEAK case B | def   service | sync  engine | states=['m.armed'] ctx={'n': 0} calls=['submit_child']

3/6 lanes leaked the service call
  LEAK: case A / def service / async engine
  LEAK: case A / def service / sync engine
  LEAK: case B / def service / sync engine
```

Exit code **1**. (The script also emits the full per-lane JSON, including `states` and `context`, for machine-readable diffing.)

Note the final configuration is `['m.armed']` in every lane — the machine correctly does **not** settle in `submitting`. The service ran anyway. That is precisely the shape of the defect: the state was never stabilised, but its side effect was performed.

Case B logs additionally show `💥 Transition on 'm.armed' failed; rolling back to the pre-transition configuration.` on all three lanes, so the rollback epilogue **is** running on `SyncInterpreter` (lane 6) — it simply does not cancel the already-submitted handoff there.

## Expected

**1. The library's own published contract.** `docs/_guide/production-characteristics.md:97`, quoted verbatim in the Summary above, promises that a `def` service "rolled forward (an `always` out of the state before it stabilises) is never submitted to the pool". Lanes 2 and 3 are that sentence's exact scenario, and they submit. This is not an outside expectation imported from a spec — it is the library's own documented behaviour, and it is the reason we rate this High.

**2. SCXML §6.1** states the *rationale* for the rule as well as the rule, and is unusually direct:

> Since an invocation will be canceled when the state machine leaves the invoking state, it does not make sense to start an invocation in a state that will be exited immediately. Therefore the `<invoke>` element is executed upon entry into the state, but only *after* checking for eventless transitions and…

An `always` transition **is** an eventless transition. SCXML orders the eventless check strictly *before* invocation precisely so that a state exited by an `always` never invokes.

**3. SCXML §6.4 / the Algorithm.** The normative pseudocode makes the same point mechanically. `enterStates` adds entered states to `statesToInvoke`; `exitStates` removes them again *before* invocation ever happens:

```
procedure exitStates(enabledTransitions):
    statesToExit = computeExitSet(enabledTransitions)
    for s in statesToExit:
        statesToInvoke.delete(s)
```

with the accompanying prose:

> Suppose macrostep M1 consists of microsteps m11 and m12. We may enter state s in m11 and exit it in m12. We will add s to `statesToInvoke` in m11, and **must remove it in m12**. In the subsequent macrostep M2, we will apply invoke processing to all states that were entered, **and not exited**, in M1.

And `mainEventLoop` only drains `statesToInvoke` after the internal queue is empty — i.e. after the macrostep, including all `always` microsteps, has completed:

```
for state in statesToInvoke.sort(entryOrder):
    for inv in state.invoke.sort(documentOrder):
        invoke(inv)
statesToInvoke.clear()
```

A state entered and left by an `always` within one macrostep is entered-and-exited in M1 and must therefore never appear in M2's invoke set. So the documented behaviour is also the specified behaviour; only the implementation diverges.

**4. `asyncio` is not the constraint.** The `async def` lanes already achieve the correct result on the async engine, so nothing about the runtime prevents it — the difference is purely that the coroutine becomes a cancellable task while the plain callable is handed to the executor synchronously.

## Root cause

Confirmed open on `main` @ `f28719c`.

- **`docs/_guide/production-characteristics.md:97`** — the claim, quoted verbatim above, is unqualified as to which epilogue and which engine. Present on this tree.

- **The `always` settle pass does not reach the invoke-cancelling path.** #196 moved `always` into the eventless settle pass. #193's cancellation was attached to the rollback epilogue, which is a different code path from the settle-pass exit, so a state left by an eventless transition does not take the branch that withdraws the executor handoff. This is why the case-A/`def` lane leaks on the async engine (lane 2) while the case-B/`def` lane no longer does (lane 5) — same service, same spelling, same engine, different epilogue.

- **`src/xstate_statemachine/sync_interpreter.py`** — #193's handoff change was made in the async engine only. `SyncInterpreter` runs a `def` service inline as part of the entering macrostep, with no interposed handoff object to withdraw, so *both* epilogues leak there (lanes 3 and 6). The rollback epilogue itself is reached on the sync engine — the traceback in our run goes through `sync_interpreter.py:1073` (`_run_user_action`) and the rollback WARNING fires — so the gap is specifically the absence of an invoke-cancellation step, not a missing rollback.

- **The behaviour is *pinned as the contract* by the test suite.** `tests/test_round8_findings.py:421`:

  ```python
  def test_always_rollforward_matches_sync(self) -> None:
      # An `always` out of the invoking state: both engines arm and
      # complete the plain service inside the step (SCXML lets the
      # invoke start once the state is entered); parity is the contract.
  ```

  The chart is ours in miniature (`idle --GO--> busy`, `busy: always -> out, invoke svc onDone -> done`), and the test asserts the service *is* called on both engines. So **the suite is green against the inverse of what `production-characteristics.md:97` and the CHANGELOG promise**, and the published claim has no test covering it at all.

  The comment's justification — "SCXML lets the invoke start once the state is entered" — is the point on which we respectfully disagree, and §6.1 is explicit the other way: `<invoke>` "is executed upon entry into the state, **but only after checking for eventless transitions**", with `exitStates` deleting the state from `statesToInvoke` in the same macrostep. Whichever way you resolve it, the test and the doc cannot both stand.

## Impact

**General.** An `always` roll-forward is the idiomatic way to express "this state's precondition does not hold — leave immediately, do not do the work". A leak converts that guard into a no-op for the one thing it exists to prevent: the side effect. Because the machine ends in the roll-forward target (`m.armed` in our run), there is also **no `onError` or compensation path attached** — the transition that would have handled a failure was rolled forward, so the service's effect is both performed and unobserved. Anything non-idempotent behind a `def` service inherits this: payment capture, email dispatch, file writes, external POSTs.

The severity is amplified by the doc mismatch. A user who reads `production-characteristics.md:97` will reasonably use an `always` guard *as* the safety interlock for exactly this purpose, because the documentation tells them it is one.

**In our adoption (order management).** `submit_child` places a **live child order** on an exchange. A roll-forward exists precisely to express "this slice is below the exchange minimum — do not send it", or "the parent was cancelled between arming and stabilising — stand down". A leak is a real child order submitted from a state the machine never settled in, against a venue that will fill it, with no compensating cancel wired up because the invoke's `onDone`/`onError` belong to a state we left. The reconciliation loop then sees a fill for an order the machine has no record of having sent.

**Our containment, for context.** We contain this with two constraints rather than waiting on a fix — `async def` services only on the async engine, and the order path never on `SyncInterpreter` — which makes all three leaking lanes unreachable for us. We mention it only so the severity is read correctly: High because of the published-claim mismatch and the live side effect, not because it is unmitigable.

## Proposed fix

**1. Cancel the executor handoff on the `always` roll-forward epilogue**, the same way #193 now does it on the rollback epilogue. #196 moved `always` into the eventless settle pass, which appears to have left the invoking state off the cancelling path; the settle pass needs the same withdraw-handoff step the rollback epilogue already performs. Equivalently, and closer to SCXML: defer the handoff until the settle pass has converged, and drop it for any state no longer in the configuration at that point — the `statesToInvoke` discipline of §6.1.

**2. Extend #193's handoff change to `SyncInterpreter`**, which currently leaks both epilogues. The sync engine runs `def` services inline, so the fix there is structural rather than a cancellation: arm the invocation as a *pending* record during the macrostep and only execute pending invocations for states still in the configuration once the settle pass converges. This is the `statesToInvoke` / `mainEventLoop` shape from the spec, and it fixes lanes 3 and 6 together.

**3. Reconcile the test and the doc — explicitly, either way.** `tests/test_round8_findings.py::test_always_rollforward_matches_sync` currently certifies the leaking behaviour. If you adopt fixes 1–2, that test must be inverted (and its comment's SCXML reading corrected). If you instead decide parity-with-sync-at-any-cost is the intended contract, then `production-characteristics.md:97` must lose the "or rolled forward (an `always` out of the state before it stabilises)" clause, and the CHANGELOG entry for #193 must be narrowed to the rollback epilogue on the async engine. **As it stands the green suite actively certifies the behaviour the doc says cannot happen**, which is the worst of the three outcomes — we would rather see it resolved in either direction than left divergent.

We prefer fixes 1–2: they make the implementation, the documentation and SCXML §6.1 agree, and they preserve engine parity by raising the sync engine to the documented behaviour rather than lowering the doc to the sync engine.

## Acceptance criteria

Named tests, parametrised over **both service spellings** (`def`, `async def`) and **both engines** (`Interpreter`, `SyncInterpreter`) wherever the lane exists. All use `SimulatedClock` and a call-recording service.

1. `test_always_rollforward_does_not_submit_def_service` — parametrised `[async_engine, sync_engine] × [def, async def]` (the sync/`async def` combination skipped). Chart: `armed --GO--> submitting`; `submitting` has `entry [bump]`, `invoke submit_child`, and `always -> armed` with a true guard. Assert `service_calls == []` in **every** lane and the final configuration is `{"m.armed"}`. This is lanes 1–3; lanes 2 and 3 fail today.

2. `test_rollback_does_not_submit_def_service_on_either_engine` — same parametrisation, case B (`entry` action raises under `actionErrorPolicy: "rollback"`). Assert `service_calls == []` and `context == {"n": 0}`. Lane 5 passes today and must be pinned so #193 does not regress; lane 6 fails today.

3. `test_always_rollforward_matches_sync` — **invert the existing test at `tests/test_round8_findings.py:421`** and correct its comment. It should assert the service is *not* called on either engine, with the SCXML §6.1 ordering rule (eventless check before `<invoke>`) cited in place of the current "SCXML lets the invoke start once the state is entered". Parity remains the contract; the parity point moves to *not called*.

4. `test_invoke_still_runs_when_always_guard_is_false` — the anti-regression guard, all four lanes. Identical chart with `roll_forward` returning `False`: the machine settles in `submitting` and the service **is** called exactly once, with `onDone` routing normally. Ensures the fix withdraws only handoffs whose state was actually exited.

5. `test_invoke_runs_when_no_always_present` — plain `invoke` with no eventless transition, all four lanes, service called once. Pins that the deferral in fix 1 does not silently drop ordinary invocations.

6. `test_production_characteristics_rollforward_claim_has_a_test` — a docs-contract test naming `production-characteristics.md:97`, so the published sentence is covered by an executable assertion rather than by prose alone. (Any mechanism is fine — the point is that this claim currently has no test at all.)

7. Every assertion checks the **call count is zero**, not merely that the machine ended in `armed`: every lane already ends in `armed` today, so a configuration-only assertion would pass on the broken build.

## Related

- **#193** — *A `def` service is uncancellable and is not unwound by rollback.* The fix is **one branch short**: it landed the rollback epilogue on the async engine (our lane 5, verified flipped to clean at `f28719c` — real and credited) but not the `always` roll-forward epilogue on either engine, and it did not extend to `SyncInterpreter` at all. The CHANGELOG and `production-characteristics.md:97` both describe the fix as covering rollback **and** roll-forward, so the claim is broader than what shipped. This issue is that residual.
- **#196** — moved `always` into the eventless settle pass. The most likely proximate cause: the settle-pass exit is a different path from the rollback epilogue #193 instrumented, so the invoking state never reaches the cancelling branch.
- **#116** — plain-`def` parity between the engines. The parity principle is right; this finding argues the parity point is currently set at the wrong value for the roll-forward case, and that `SyncInterpreter` breaks parity in the other direction on rollback.
- **`tests/test_round8_findings.py:421::test_always_rollforward_matches_sync`** — pins the leaking behaviour as the contract; must be reconciled with `production-characteristics.md:97` whichever way the semantics are resolved.
- **SCXML §6.1**, §3.13, and the `exitStates` / `mainEventLoop` pseudocode in the Algorithm appendix — the normative basis, quoted above.

## Verification

- **Date:** 2026-09-22
- **Library commit:** `f28719c555ef6e9315a71315945a5a4f2965af73` (`main`, merge of PR #202; `__version__` reports `0.8.0`)
- **Python:** CPython 3.13.7 (tags/v3.13.7:bcee1c3, Aug 14 2025) [MSC v.1944 64 bit (AMD64)], Windows 11 Pro 10.0.26200
- **Env:** `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`
- **cwd used:** `<home>` — a neutral directory outside both the library tree and the audit tree, proving the script is genuinely standalone (stdlib + `xstate_statemachine` only; every helper inlined, no harness import).
- **Script:** `repro/R9-04_always_rollforward_def_invoke_submitted.py`, byte-identical to the block embedded above.
- **Exit code:** `1` (defect present). **3/6 lanes leaked**: case A/`def`/async, case A/`def`/sync, case B/`def`/sync. Clean: case A/`async def`/async, case B/`async def`/async, case B/`def`/async (**#193 landing**). Returns `0` once every lane is clean.
- **Coverage of the required axes:** both service spellings run on the async engine for both cases; the sync engine runs `def` for both cases (it has no `async def` lane). No run approached the 90 s cap; no hang or watchdog timeout.
- **Source/doc anchors re-read on this tree:** `docs/_guide/production-characteristics.md:97`; `tests/test_round8_findings.py:421-470`; `src/xstate_statemachine/base_interpreter.py:3264`; `src/xstate_statemachine/interpreter.py:2054`; `src/xstate_statemachine/sync_interpreter.py:1073`.
- **Duplicate check:** `gh issue list -R basiltt/xstate-statemachine --state all --limit 260 --search "always roll-forward invoke"` and related searches. Nearest hits #193, #196, #116, #49 — all closed, none covering the roll-forward epilogue or the `SyncInterpreter` gap. **No duplicate.**
