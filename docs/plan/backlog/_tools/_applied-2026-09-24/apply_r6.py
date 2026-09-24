"""Round-6 E50 backlog update (2026-09-20).

Applies the `39-r6-final-readiness-verdict.md` outcomes to docs/plan/backlog/E50.json:
  * chore status updates for upstream items verified at cec108b
  * E50-X01 round-6 verdict prepended to its Context
  * E50-T12 narrowed, E50-T13 root-target rule retired, E50-T16 re-scoped
  * new guard tickets for the constraints that replaced the retired ones

Idempotent: re-running detects the round-6 markers and does nothing.
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
E50 = os.path.join(HERE, "..", "E50.json")
MARK = "Round 6 input (2026-09-20, main @cec108b)"
SRC = "docs/research/xstate/39-r6-final-readiness-verdict.md"

BODY_TMPL = """## Context
{context}
Source: `{src}` §7, ADR-0016 Amendment 6.

## Scope / Deliverables
- Implementation under `services/api/candleviewer/statechart/` (factory / lint / gateway as named)
- Unit tests plus a contract test in `tests/xstate_contract/` that reproduces the upstream defect and proves the guard prevents it
- Lint rule registered in `tools/lint_statecharts.py` where the constraint is static
- Constraint id recorded in the machine registry so a reviewer can trace the rule to its finding

## Acceptance criteria
{accept}

## Out of scope
- Fixing the upstream defect itself. These are our guards; the upstream work is tracked by the `E50-C*` chores.
"""

NEW_TICKETS = [
    dict(
        key="E50-T17",
        title="Linter: no `always` into an invoked child, no `always` to an ancestor (CV-C35)",
        context=(
            "Upstream **R6-01 (Blocker)**: on the async engine, an event re-entering a compound state "
            "whose `always` descends into a child carrying an `invoke` livelocks the run loop once that "
            "invoke completes — `await send(wait=True)` never resolves, a core is pegged, and the machine "
            "reports `status=\"running\"` with `error is None`. `SyncInterpreter` returns in 0.04 s on the "
            "identical config. Unwrappable at runtime (there is nothing observable to watch), so the only "
            "mitigation is to make the shape unrepresentable in our catalogue at build time.\n"
            "Also covers **R6-02 (High)**, the same root cause seen as an unbounded silent invoke cycle."
        ),
        accept=(
            "- [ ] `CV-LINT-XS17`: a machine is rejected if any `always` transition targets a state that is, "
            "or contains, a state carrying an `invoke`\n"
            "- [ ] `CV-LINT-XS18`: a machine is rejected if any `always` targets an ancestor of its own source\n"
            "- [ ] All 20 catalogue contracts pass both rules (or are corrected until they do)\n"
            "- [ ] Contract test reproduces the upstream livelock on the bare library and shows the lint "
            "rejects that JSON before it can be built\n"
            "- [ ] Rules are retired, with the contract test flipped to an expect-pass, once upstream R6-01/R6-02 close"
        ),
        priority="P0 Critical",
        sprint="Sprint 08",
        estimate=3,
    ),
    dict(
        key="E50-T18",
        title="Gateway: every send_threadsafe future is read; refusals are counted and paged (CV-C36)",
        context=(
            "Upstream **R6-05 (Medium)**. Our original filing (#157: the inbox bound is bypassed and events "
            "are accepted then lost) was **refuted by our own corrected repro** — `_enqueue()` on the loop is "
            "authoritative and refuses correctly, max observed depth 0 against a bound of 3. What survives is "
            "narrower and still ours to handle: while the loop is busy — the only time backpressure matters — "
            "the refusal lands on exactly the future a fire-and-forget producer never reads, and the RAISE "
            "branch emits no log and no `on_event_dropped`. Correct load shedding with a **hidden shed rate**."
        ),
        accept=(
            "- [ ] The gateway's cross-thread submit API cannot be called in a way that discards the result "
            "(no bare fire-and-forget overload exists)\n"
            "- [ ] Every refusal increments a `statechart_events_shed_total` counter labelled by machine\n"
            "- [ ] A sustained shed rate above threshold pages, rather than being visible only in a log\n"
            "- [ ] Contract test: flood a busy loop and assert shed count equals sends minus enqueued, with "
            "zero silent losses\n"
            "- [ ] `CV-LINT-XS19`: direct `interp.send_threadsafe` outside the gateway is rejected"
        ),
        priority="P1 High",
        sprint="Sprint 09",
        estimate=2,
    ),
    dict(
        key="E50-T19",
        title="Factory: children_ready() barrier — `await start()` is not \"the machine is up\" (CV-C37)",
        context=(
            "Upstream **R6-11 (Medium)**. `await Interpreter.start()` returns ~13 ms before the initial entry "
            "set's `invoke` children are registered and before an initial plain-`def` service completes; "
            "`SyncInterpreter.start()` does both before returning, so the engines disagree on what `start()` "
            "means. A `sendTo` issued in that window is dropped — not silently (`on_event_dropped("
            "reason='unresolved_target')` fires, which is #133 working), but dropped. Root cause: "
            "`interpreter.py:487,496` never calls `_await_inline_services()`."
        ),
        accept=(
            "- [ ] `cv.statechart.factory.start()` does not return a usable handle until every `invoke.id` "
            "declared on the initial configuration is present in `interpreter.actors`\n"
            "- [ ] Bounded wait with an explicit timeout and a typed `CvStartTimeout`, never an unbounded poll\n"
            "- [ ] Contract test: reproduce the dropped `sendTo` on the bare library, then show zero drops "
            "through the factory across 100 starts\n"
            "- [ ] Retired when upstream `start()` settles the initial macrostep or ships `children_ready()`"
        ),
        priority="P2 Medium",
        sprint="Sprint 09",
        estimate=2,
    ),
]


def main() -> None:
    path = os.path.normpath(E50)
    data = json.load(open(path, encoding="utf-8"))
    by = {t["key"]: t for t in data}
    if MARK in by["E50-X01"]["body"]:
        print("already applied; nothing to do")
        return

    # --- E50-X01: prepend the round-6 verdict -------------------------------
    x = by["E50-X01"]
    x["body"] = x["body"].replace(
        "## Context\n",
        "## Context\n"
        f"> **{MARK}:** **DEFER (order path) / GO (non-order paths)** — unchanged in "
        "direction, much narrower in cause. 26 issues verified (24 closed, 1 partial #122, "
        "1 not-fixed #157); 3 Medium regressions; suite 3399/0 at **92.77 %** coverage "
        "(new 90 % floor). Post-refutation **2 Blocker · 2 High · 7 Medium · 9 Low** — "
        "refutation moved 6 of 10 Blocker/High candidates *down*, none up. Both Blockers "
        "(R6-01 async `always`+completed-`invoke` livelock; R6-03 `rollback`+`invoke.onDone` "
        "re-invoking ~1400/s silently) are **async-only**, with the sync engine provably "
        "correct, and **one upstream change closes both plus R6-02**: give "
        "`interpreter.py` the sync engine's chain/macrostep termination accounting "
        "(`:1427` exemption + porting #144's rule to `_run_event_loop`). Absent them, "
        "open-High is 2 — inside the bar of 5, both mechanically mitigated — i.e. decision "
        "row 6, ADOPT WITH CONSTRAINTS. Non-order machines B10–B17/B19/B20 move to the "
        "library now under CV-C01–C37 (they drove **zero** new library defects this round); "
        "order path stays on the shim. **Do not pin a 0.8.1 tag cut at `cec108b`.** "
        f"Exit condition: `{SRC}` §9. Shim-retirement ladder: §10.6. ADR-0016 Amendment 6.\n",
        1,
    )

    # --- chores verified at cec108b ----------------------------------------
    chore_updates = {
        "E50-C03": ("[VERIFIED FIXED main@cec108b]",
                    "#145 closes the last live piece: `actionErrorPolicy:\"fail\"` halts with "
                    "`status=\"stopped\"` and a cleared configuration, retains `TransitionFailedError`, "
                    "round-trips through a snapshot, and the halted blob is refused by `from_snapshot`. "
                    "Symmetric on both engines. The `\"rollback\"` path is separately confirmed, with the "
                    "caveat now tracked as R6-03. **Note:** the `plugins.py:201-202` docstring still says "
                    "`status == \"error\"`; the code and CHANGELOG say `\"stopped\"` (R6-20, doc-only)."),
        "E50-C05": ("[VERIFIED FIXED main@cec108b]",
                    "#153 lands `Receipt.denied` plus `on_unhandled_event(disposition=\"guard_denied\")`, "
                    "so guard-refused and truly-undeclared events are distinguishable at the call site. "
                    "Residual R6-10 (Medium): a guard that *crashes* under `guardErrorPolicy:\"raise\"` also "
                    "sets `denied=True` — read `(denied, error is None)`, per CV-C06/W-04."),
        "E50-C11": ("[VERIFIED FIXED main@cec108b]",
                    "#152 closes the previous round's ship-blocker: `guardErrorPolicy:\"raise\"` now cancels "
                    "only the *failing* candidate, so the unguarded fallback is still taken, with "
                    "`last_error`/`receipt.error` set. Verified on both engines."),
        "E50-C08": ("[VERIFIED FIXED main@cec108b]",
                    "The persistence class this chore tracks is closed at the root. #142/#143 enforce one "
                    "legality predicate — exactly one leaf per region — on **both** the snapshot write side "
                    "and the read side, with the read side provably reusing the write-side function. Torn "
                    "parallel snapshots 27.4 % → **0 %**; 2000/2000 quiescent snapshot/restore cycles; 1 217 "
                    "snapshots over 350 random parallel machines with zero illegal configurations. #146/#158 "
                    "type every hostile field. Residuals are Low: R6-16 (`configuration` not cross-validated "
                    "against `state_ids`) and R6-06 (High, the entry/exit-action window — a *different* "
                    "predicate bug, tracked with E50-T10)."),
        "E50-C15": ("[VERIFIED FIXED main@cec108b]",
                    "#150 charges `send_threadsafe` self-sends to `maxIterations` on both the flag and the "
                    "contextvars-inherited route. Residuals: R6-05 (Medium, loop-side RAISE refusals are "
                    "silent → E50-T18) and R6-12 (Medium, the in-flight counter leaks)."),
        "E50-C09": ("[PARTIAL main@cec108b]",
                    "#118 fixes the `AfterEvent` telemetry fields (`scheduled_for`/`fired_at` restore as "
                    "`None`, never `0.0`; `lateness_ms` is `None` when unknown) and #154 attaches the clock "
                    "on both sync early-return paths. But **R6-14 is a regression**: `after` lateness is "
                    "88–92 ms against a 50 ms budget under a busy loop, 5/5 deterministic. The per-macrostep "
                    "settle budget bounds iterations, not lateness. BENCH-6 remains unmet, so the standing "
                    "constraint (external `MonotonicScheduler` for all algo timing) stands."),
        "E50-C10": ("[VERIFIED FIXED main@cec108b]",
                    "#147 raises a **non-downgradable** `RootTargetError` at build time under *both* "
                    "`strict_targets` settings (8/8 combinations), while genuine unresolvable targets still "
                    "only warn. #133/#134 add `on_event_dropped(reason=\"unresolved_target\")` and "
                    "`on_resolve_error` on both engines. This retires the CV-C29 lint and E50-T13's "
                    "root-target rule."),
        "E50-C12": ("[VERIFIED FIXED main@cec108b]",
                    "The observability and backpressure gaps this chore tracks are closed: #159 adds "
                    "`on_invalid_event`/`on_snapshot_error`, #160 redacts the `get_snapshot()` DEBUG log and "
                    "extends `DEFAULT_REDACT_KEYS` to 17/17 of the keys we listed, `on_event_dropped` fires "
                    "for events abandoned at `stop()` (5/5), and the bounded inbox with "
                    "`OverflowPolicy.RAISE` holds under 16-thread contention. Residuals are Low/Medium: "
                    "R6-08 (the `onUnhandled:\"error\"` receipt is unpopulated for one event) and R6-05."),
    }
    for key, (tag, note) in chore_updates.items():
        t = by[key]
        if "[VERIFIED FIXED main@cec108b]" in t["title"] or "[PARTIAL main@cec108b]" in t["title"]:
            continue
        base = t["title"].split(":", 1)
        t["title"] = f"{base[0]} {tag}:{base[1]}" if len(base) == 2 else f"{t['title']} {tag}"
        t["body"] = t["body"].replace(
            "## Context\n",
            f"## Context\n> **Round-6 re-verification (2026-09-20, `main` @ `cec108b`).** {note} "
            f"Evidence: `{SRC}` §1/§5.\n\n",
            1,
        )
        labels = t.setdefault("labels", [])
        for stale in ("status/partially-verified", "status/unverified"):
            if stale in labels:
                labels.remove(stale)
        marker = "status/verified-fixed" if tag.startswith("[VERIFIED") else "status/partially-verified"
        if marker not in labels:
            labels.append(marker)

    # --- retire / narrow / re-scope existing guard tickets ------------------
    t12 = by["E50-T12"]
    t12["title"] = "Restore legality check before start() — NARROWED to state_ids ⊆ configuration (CV-C27′)"
    t12["body"] = t12["body"].replace(
        "## Context\n",
        "## Context\n> **NARROWED, round 6 (2026-09-20).** Upstream #142/#143 now enforce configuration "
        "legality on the **read** side using the identical predicate as the write side, so the general "
        "obligation this ticket carried (CV-C27) is **retired** — 5 000 mutations produce 0 raw builtins "
        "and 0 restored `running`-with-no-leaf machines. One hole remains (R6-16, Low): `configuration` "
        "can be emptied alone with `state_ids` intact and still restores live, because the check keys on "
        "`state_ids` and never cross-validates the two copies. Scope shrinks to **one assertion**: "
        f"`set(state_ids) ⊆ set(configuration)` before `start()`, raising `CvRestoreError`. Source: `{SRC}` §7.\n\n",
        1,
    )
    t12["estimate"] = 1
    t12["priority"] = "P2 Medium"

    t13 = by["E50-T13"]
    t13["title"] = "Linter rules: no child output reliance, no BLOCK policy (CV-C05) — root-target rule RETIRED"
    t13["body"] = t13["body"].replace(
        "## Context\n",
        "## Context\n> **PARTIALLY RETIRED, round 6 (2026-09-20).** `CV-LINT-XS14` (no `always` → machine "
        "root) is **retired**: upstream #147 raises a non-downgradable `RootTargetError` at build time under "
        "both `strict_targets` settings (8/8 combinations verified), so the lint is genuinely redundant "
        "rather than belt-and-braces. XS15 and XS16 stand. **Note the replacement is not this ticket:** the "
        "new `always` rules (no descent into an invoked child, no ancestor target — CV-C35) are a different "
        f"and more dangerous shape and live in `E50-T17`. Source: `{SRC}` §7.\n\n",
        1,
    )
    t13["estimate"] = 2

    t16 = by["E50-T16"]
    t16["title"] = "Mandatory config round 6: re-permit \"fail\", guard \"rollback\" on invoke states, write the missing halted states (CV-C31′)"
    t16["body"] = t16["body"].replace(
        "## Context\n",
        "## Context\n> **RE-SCOPED AND INVERTED, round 6 (2026-09-20).** R5-12 is **fixed** (#145 verified on "
        "both engines: `\"fail\"` halts with `status=\"stopped\"`, configuration cleared, "
        "`TransitionFailedError` retained, halted blob refused by `from_snapshot`), so **CV-C31's blanket ban "
        "on `\"fail\"` is retired**. The danger has moved: upstream **R6-03 (Blocker)** makes `\"rollback\"` "
        "an unbounded, silent re-invocation loop (~1400 calls/s, `status=\"running\"`, `error=None`) on any "
        "state carrying an `invoke` whose `onDone` target has a raisable entry action — which is a shape four "
        "of five machines in one of our groups carry. **CV-C31′:** those states use `\"fail\"`; `\"rollback\"` "
        "remains the default everywhere else. Independently, the explicit `halted` states CV-C31 promised for "
        "B16–B20 were **never actually written** (defect C-07), so a failed `locked` entry currently rolls B20 "
        f"back to `clear` (tag `trading_allowed`) with no record and no sink to page from. Source: `{SRC}` §7.\n\n",
        1,
    )
    t16["estimate"] = 5

    t10 = by["E50-T10"]
    t10["body"] = t10["body"].replace(
        "## Context\n",
        "## Context\n> **STILL LOAD-BEARING, round 6 (2026-09-20) — and for a new reason.** R4-01 is fixed, "
        "but upstream **R6-06 (High)** shows the library's in-flight guard uses the wrong predicate: "
        "`base_interpreter.py:1306` tests `_step_in_flight() and not _configuration_is_legal()`, and inside "
        "an **entry or exit action** the configuration is perfectly legal while context is half-applied. So "
        "the guard is **inert for every action window in a non-parallel machine**, on both engines, and a "
        "torn snapshot (new leaf + stale context) is accepted with `last_transition_ok=True`. Quiescence-only "
        f"snapshotting is now our primary defence, not a belt-and-braces one. Source: `{SRC}` §5/§7.\n\n",
        1,
    )
    t10["priority"] = "P0 Critical"

    # --- new tickets --------------------------------------------------------
    proto = by["E50-T12"]
    for spec in NEW_TICKETS:
        if spec["key"] in by:
            continue
        t = {k: v for k, v in proto.items()}
        t.update(
            key=spec["key"],
            kind="Task",
            title=spec["title"],
            labels=["type/feature", "area/backend-platform", "statechart",
                    "priority/p0" if spec["priority"].startswith("P0") else "priority/p1"],
            sprint=spec["sprint"],
            priority=spec["priority"],
            estimate=spec["estimate"],
            blocked_by=["E50-T07"],
            parent="E50",
            perspective="Development",
            body=BODY_TMPL.format(context=spec["context"], accept=spec["accept"], src=SRC),
        )
        data.append(t)

    json.dump(data, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"E50.json updated: {len(data)} items; added {[s['key'] for s in NEW_TICKETS]}")


if __name__ == "__main__":
    main()
