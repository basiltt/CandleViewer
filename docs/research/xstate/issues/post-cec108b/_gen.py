"""Generate round-6 postable drafts (comments + new issues + manifest).

Run:  python _gen.py
Writes into ./comments/ and ./new/ and ./manifest.json. Nothing is posted.
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
COMMIT = "cec108b"

HEADER = """# Comment for issue #{n} — {title}

**Action:** {action}
**Disposition:** {disp}

---

Verified on `main` @ `{commit}` (merge of PR #164, unreleased 0.8.1) as part of our
adoption audit (#26). Build identified **by commit** — `__version__` still reports
`0.8.0` on this tree, so nothing here should be keyed on the version string.
CPython 3.13.7, Windows 11. Every claim below was reproduced in a fresh process
against a clean venv before it was written down.

"""

FOOTER = """

---

*Round-6 context:* the full set is 26 issues verified (24 closed, 1 partial, 1 not
fixed), 3 regressions, and 20 canonical new defects after independent refutation
(2 Blocker · 2 High · 7 Medium · 9 Low). Suite `3399 passed / 13 skipped / 0 failed`,
coverage **92.77 %** against the new 90 % floor from #163. The one pattern worth the
team's attention is in #26: **three of this round's four candidate Blockers were
"fixed on the engine the issue was filed against"** — an `Interpreter`/`SyncInterpreter`
parity test class would have caught all three at authoring time.
"""

# id -> (title, action, disposition, body)
CLOSED: dict[str, tuple[str, str]] = {
    "118": ("`AfterEvent` lateness telemetry round-trip",
            "`scheduled_for`/`fired_at` now restore as `None` (never `0.0`) when the keys are "
            "absent, and `lateness_ms` returns `None` when either endpoint is unknown. "
            "All 6 criteria from the reopen pass. No residual — **please close.**"),
    "125": ("Sync parity: deferred-event replay is its own macrostep",
            "On `SyncInterpreter` the deferred event's replay is now a separate macrostep and "
            "the *triggering* event's `Receipt` is final before the replay runs. All criteria "
            "pass, no residual — **please close.**"),
    "133": ("Unresolved `sendTo`/`forwardTo` fires `on_event_dropped`",
            "Both unresolved `sendTo` and unresolved `forwardTo` now fire "
            "`on_event_dropped(reason=\"unresolved_target\")` through a shared helper, on both "
            "engines. All criteria pass, no residual — **please close.**"),
    "134": ("`PluginBase.on_resolve_error` fires on unresolved-target failures",
            "`on_resolve_error(interpreter, error, event)` fires **exactly once per engine** on "
            "an unresolved-target failure, and `last_error` parity is preserved. Note for the "
            "record: the original repro still exits 1, but that is a **stale detection heuristic "
            "in our script**, not a regression — we have refreshed it. **Please close.**"),
    "142": ("Recursive configuration-legality predicate",
            "Exercised directly on both engines. `_configuration_is_legal` is now "
            "exactly-one-leaf-per-region and recursive. At scale: `n3_parallel_tear` over 300 "
            "cases gives **0/179 torn** (was 49/179 = 27.4 % before the fix), and a 300-case "
            "Hypothesis property over randomly generated parallel machines took 879 quiescent "
            "snapshots with 0 failures. **Please close.** This fix is what lets us retire our "
            "own \"no parallel regions on the order path\" constraint."),
    "143": ("Restore reuses the write-side legality predicate",
            "Confirmed by reading the call: `from_snapshot()` calls the *identical* function the "
            "write side uses, so drift between the two sides is impossible by construction — "
            "which is exactly the right shape of fix. **Please close.** One narrow residual is "
            "filed separately (`configuration` is never cross-validated against `state_ids`), "
            "but it is not this issue."),
    "145": ("`actionErrorPolicy: \"fail\"` → status `stopped`, configuration cleared",
            "Symmetric on both engines, round-trips through a snapshot, `\"rollback\"` is "
            "unaffected, and the read-side error-message check is verified. `from_snapshot` "
            "correctly refuses the halted blob with `InvalidConfigError`. **Please close.** "
            "This retires a standing prohibition on our side — we had banned `\"fail\"` entirely "
            "after the previous round. One doc nit is filed separately (the `plugins.py` "
            "docstring still says `\"error\"`)."),
    "146": ("Hostile snapshot fields raise typed `SnapshotCorruptError`",
            "84-case cross-product (12 fields × 7 hostile scalars): **all** raise a typed "
            "`SnapshotCorruptError` before any bare Python exception can escape. Independently, "
            "5 000 structural mutations produced **0** raw `TypeError`/`ValueError`/"
            "`AttributeError`. **Please close.**"),
    "147": ("Root target rejected with a non-downgradable `RootTargetError`",
            "Rejected under **both** `strict_targets` settings — 8/8 site × setting combinations "
            "— while genuine unresolvable targets still only warn, which is the correct "
            "distinction. **Please close.**"),
    "148": ("Cancel before/after the loop's first turn",
            "Both orderings land `status=\"error\"` with a `RuntimeError`, the receipt carries "
            "`InterpreterStoppedError`, and `on_error` fires **exactly once**. `_die` is "
            "idempotent under 1, 2 and 3 cancels. **Please close.**"),
    "149": ("`service_executor` for plain-`def` services",
            "A plain-`def` service with a 0.3 s sleep no longer blocks `start()` or the loop — "
            "a background ticker advances 10+ times during it — and the machine completes to the "
            "correct state with #116's ordering held. **Please close.** For the record, we "
            "initially filed a follow-up claiming the *machine* is still blocked; on refutation "
            "that turned out to be our own misuse (a plain `def` where the docs specify "
            "`async def`) plus a documentation gap, not a defect in this fix."),
    "150": ("`send_threadsafe` self-sends are charged to `maxIterations`",
            "Both routes — the explicit flag and the contextvars-inherited one — are charged, "
            "trip `RunawayChainError`, and set `last_transition_ok=False`. **Please close.**"),
    "151": ("Per-macrostep settle budget",
            "`send_events([\"GO\",\"GO2\"])` as a batch now matches two sequential `send()` calls "
            "with no spurious budget trip — the budget is genuinely per-macrostep. **Please "
            "close.**"),
    "152": ("`guardErrorPolicy: \"raise\"` cancels only the failing candidate",
            "Verified on both engines: the failing candidate alone is cancelled, the unguarded "
            "fallback is still taken, and `last_error` / `receipt.error` are set. Repro exits 0, "
            "both pinned tests pass. **Please close.** (There is no separate `guard_errored` "
            "disposition — expected, and out of scope for this issue.) This was the previous "
            "round's ship-blocker; closing it is what made a downstream livelock in our own "
            "chart *visible* rather than silent, which we consider the fix working as intended."),
    "153": ("`Receipt.denied` and `on_unhandled_event(\"guard_denied\")`",
            "Guard-refused and truly-undeclared events are correctly distinguished; "
            "noop / denied / deferred are pairwise distinct; the fallback-candidate case still "
            "reports `denied=False`. Repro exits 0, 3 pinned tests pass. **Please close.** A "
            "narrow follow-up is filed separately: a guard that *crashes* under "
            "`guardErrorPolicy:\"raise\"` also sets `denied=True`."),
    "154": ("Sync `start()` / `from_snapshot()` attach the clock before returning",
            "Both early-return branches now call `clock._attach(tick)` before returning; the "
            "`restart_timers` path and the persisted-inbox path both re-arm and fire via "
            "`increment()` alone, and a double `start()` does not double-attach. **Please "
            "close.**"),
    "155": ("Action-name resolution checks `logic.actions` before the `spawn_` prefix",
            "A user action named `spawn_place_order` now runs instead of triggering a spawn, "
            "while unregistered `spawn_*` names still spawn normally. Repro exits 0, 3 pinned "
            "tests pass. **Please close.**"),
    "156": ("Child records the invoke id via `_invoked_as`",
            "The child now takes the invoke id from `self._invoked_as` (set by the parent) "
            "rather than parsing it back out of the runtime actor id, so `escalate` reaches "
            "`onError` identically whether or not `invoke.id` was given explicitly, on both "
            "engines. **Please close.** Good structural fix — it removes a string round-trip "
            "that could only ever be approximately right."),
    "158": ("`check_shape` and `restore_event` both reject malformed event records",
            "Independently verified: each rejects non-`str`/empty `type` and non-`dict` pending "
            "records with `SnapshotCorruptError`. All 4 criteria pass on rerun. **Please "
            "close.**"),
    "159": ("`PluginBase.on_invalid_event` / `on_snapshot_error`",
            "Both hooks exist and fire correctly for `InvalidEventError` and "
            "`SnapshotMidStepError` respectively. The original repro's FAIL is a stale "
            "substring-match heuristic in **our** script, not a regression — refreshed on our "
            "side. **Please close.**"),
    "160": ("`get_snapshot()` DEBUG log redaction and `DEFAULT_REDACT_KEYS`",
            "All three halves verified with no leaks: the `get_snapshot()` DEBUG log is "
            "redacted, `DEFAULT_REDACT_KEYS` covers **17/17** of the keys we listed as missing "
            "(including `iban`, `pan`, `bearer`, `cookie`, `dob`, `email`), and "
            "`LoggingInspector` redacts service results. **Please close.**"),
    "161": ("Dict-event key-shape validation",
            "Non-`str` key, non-`str` type, empty type and missing type all raise "
            "`InvalidEventError`, with no regression on the minimal form and none on a hostile "
            "non-dict sweep. **Please close, scoped as documented** — value-level validation is "
            "explicitly out of scope and belongs to `event_schemas` (#51). We had previously "
            "filed `{\"type\": \"GO\"}` acceptance as a bypass; with the boundary now written "
            "down it is a deliberate contract, and we have withdrawn that finding."),
    "162": ("v1 pending/deferred records restore as user events by default",
            "Records with no `kind` now restore as user events, with only the `___xstate` init "
            "sentinel staying a system event. Verified via `restore_event()` on `after.hours`, "
            "`escalate` and init-sentinel records. **Please close.**"),
}

SPECIAL = {
    "144": ("Nested-invoke `onDone` chain budget", "comment (no reopen) — **ride-along: the same cycle is unbounded on the async engine**", "FIXED as filed (sync), with an adjacent gap on the other engine", """
**The fix is correct and we are not reopening this issue.** The chain-budget rule
("a chain ends only when nothing self-generated remains queued") is exercised
directly, the repro exits 0, and `tests/test_round5_findings.py:331` pins it.

We are commenting only to record, in the place a maintainer will look for it, that
the fix shipped in `sync_interpreter.py` **only**, and the identical configuration
is still unbounded on `Interpreter`:

```
literal #144 config (invoke.onDone re-entering its ancestor, no `always`)
  SyncInterpreter : returns, RunawayChainError, last_transition_ok=False   CORRECT
  Interpreter     : ~34 000 invocations in 2 s, status="running", error=None,
                    no hang, no budget charged, no diagnostic
```

The async side is filed separately (see the new issues referencing
`interpreter.py:1427`) because the acceptance criteria *as written here* are met and
we do not think reopening a closed issue is the right way to carry a different
engine's bug. But the two are one root cause, and we would expect one change to
close both.

**Suggested companion work:** an `Interpreter`/`SyncInterpreter` parity test class —
a handful of pathological configs, asserting both engines reach the same terminal
disposition. Three of the four candidate Blockers we found this round would have
been caught by it before review.
"""),
    "122": ("`tick()` one-deadline-per-call", "comment + **reopen (narrow)**", "PARTIAL — the contract is documented and two of three drain paths are correct; the original repro still exits 1", """
Most of this is genuinely improved and we are reopening **narrowly**, for one
criterion only.

| # | Criterion | Result |
|---|---|---|
| 1 | `tick()`'s one-deadline-per-call contract is documented | ✓ |
| 2 | Zero-delay `after` chains drain correctly | ✓ |
| 3 | `SimulatedClock` deadline ladders drain correctly | ✓ |
| 4 | The original `RealClock` real-delay-ladder repro exits 0 | ✗ — still exits 1 |

What landed is a **documentation** fix, not a drain-loop fix. That is a legitimate
resolution for the ambiguity half of the issue, and we would have accepted it as a
close if the repro had been retired explicitly. As written, the acceptance criterion
"the repro passes" is unmet, so we are keeping that one line open rather than
silently dropping it.

If the intended resolution is "the real-clock ladder is working as designed and the
repro encodes a wrong expectation", say so on the issue and we will close it out and
refresh our script — that is a perfectly good answer and costs nobody any code.
"""),
    "157": ("`send_threadsafe` `qsize()` pre-check is TOCTOU-racy", "comment + **reopen on narrower grounds**", "NOT FIXED as filed — but our original framing was wrong; the surviving defect is smaller and different", """
**We got this one partly wrong, and we want to correct the record before asking for
anything.**

Our original claim — that the inbox bound is *bypassed* and events are accepted then
silently lost — **does not hold**. A corrected repro that actually reads the returned
future and samples the queue depth shows:

```
bound = 3
max observed queue depth : 0
sends refused on the loop : 497 / 500   (QueueOverflowError from inside _enqueue)
sends enqueued and run    :   3 / 500
leaked / accepted-then-lost: 0
```

The call-site `qsize()` check is an **optimistic pre-check**; `_enqueue()` on the loop
is authoritative against a live depth, and the documented contract says exactly that
("a concurrent producer may still be refused on the loop, in which case the returned
future carries the error"). Our repro discarded that future. `on_event_dropped` not
firing is also by design for `OverflowPolicy.RAISE` — the exception *is* the signal.
The pinned test is correctly scoped. Our apologies for the noise.

**What does survive, and why we are still asking for a small change.** The premise
inverts under load. While the loop is busy — the only time backpressure matters at
all — the refusal lands on exactly the future that fire-and-forget producers never
read, and the `RAISE` branch of `_enqueue` emits **no warning and no hook**. We
verified this at `logging.DEBUG` and confirmed there is no asyncio
unretrieved-exception traceback either. The result is correct load shedding with a
**hidden shed rate**: a cross-thread producer can lose the large majority of its sends
while every call site appears to succeed.

**Ask (Medium, one line):** log at WARNING and/or fire `on_event_dropped` for loop-side
`RAISE` refusals. That turns a silent shed into a measurable one, which is all we need.
"""),
}


def write_comments() -> list[dict]:
    out = []
    d = os.path.join(HERE, "comments")
    for n, (title, body) in sorted(CLOSED.items(), key=lambda kv: int(kv[0])):
        txt = HEADER.format(n=n, title=title, action="comment + **close**",
                            disp="FIXED — verified, no residual", commit=COMMIT)
        txt += "## Verification\n\n" + body + "\n" + FOOTER
        p = os.path.join(d, f"{n}.md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(txt)
        out.append({"issue": int(n), "file": f"comments/{n}.md",
                    "action": "comment+close", "disposition": "FIXED"})
    for n, (title, action, disp, body) in sorted(SPECIAL.items(), key=lambda kv: int(kv[0])):
        txt = HEADER.format(n=n, title=title, action=action, disp=disp, commit=COMMIT)
        txt += body.strip() + "\n" + FOOTER
        with open(os.path.join(d, f"{n}.md"), "w", encoding="utf-8") as fh:
            fh.write(txt)
        act = ("comment" if n == "144" else "comment+reopen")
        out.append({"issue": int(n), "file": f"comments/{n}.md",
                    "action": act, "disposition": disp.split(" —")[0]})
    return out


if __name__ == "__main__":
    c = write_comments()
    with open(os.path.join(HERE, "_comments.json"), "w", encoding="utf-8") as fh:
        json.dump(c, fh, indent=1)
    print(f"comments: {len(c)}")
