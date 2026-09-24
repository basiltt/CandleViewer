# Replacement body for meta issue #26

**Action:** replace the issue body (full replacement, not a comment)

---

> ## Status on `main` @ `3c527b0` (re-verified 2026-09-18, pre-0.8.1)
>
> **Identify this build by commit, not by version string.** `__version__` still reports `0.8.0` on this commit while `CHANGELOG.md` targets `0.8.1`. Any pin, CI assertion or baseline keyed on the version string will silently confuse the two.
>
> **PR #83 landed three good fixes and introduced three High defects on the persistence path.** #43, #79 and #80 all verify against their own acceptance criteria (7/7, 10/10, 8/8). No regression is visible at the gate, suite, benchmark or probe level. But two features that shipped together — provenance-based system events (#79) and `ErrorEvent` (#80) — each met the snapshot boundary (#47) without being taught about it, and neither interaction is covered by a test or mentioned in the CHANGELOG.
>
> **The adopting project's gate moved to DEFER** on the arithmetic of open High items (7, bar is ≤5), not on a judgement about quality. Fixing the two snapshot findings before 0.8.1 tags returns the count to 5 and the previous decision applies again.

## Gate result on this commit

```
Gate run 2026-09-18 - xstate-statemachine main @ 3c527b0 (unreleased 0.8.1)
DECISION: DEFER (was: ADOPT WITH CONSTRAINTS, CONDITIONAL)
          -- decision-table row 5: 7 High open (bar: <=5)
  verify (mandated config, blocking) : 33/34 pass  (was 32/34 -- #43 now PASS)
  repro  (defaults, informational)   : 13/34 pass
  probes                             : identical baseline, no new failures
  suite                              : 3242 passed, 13 skipped, 0 failed (was 3234/13/0)
  coverage                           : 90% (unchanged)
  benches                            : actor task budget children+1 CONFIRMED
                                       (1.0 tasks/child, was 2.0)
                                       order-path headroom with rollback armed
                                       still short of the adopting project's bar
  regressions                        : ONE -- provenance does not survive a snapshot
  high open                          : 7
  new findings                       : 24 canonical (6 High, 11 Medium, 7 Low)
```

## What landed, and it is worth saying plainly

**#43 is the best piece of work in this window.** `_ACTOR_POLL_INTERVAL` and the per-child manager task are gone; completion is pushed from the child's terminal listener. Independently reproduced: 50 idle children add exactly 50 tasks over baseline; zero stray `loop.call_later` in a 200 ms idle window with 20 children; `onDone` median latency 0.96 ms (was floored at ≥5 ms); 1 000 spawn/complete cycles leak nothing; teardown correct on parent `stop()` **and** on rollback of the entering transition; the exit-vs-completion race scanned in 1 ms steps across the window with a passing control, and no stale `onDone`/`onError` ever lands in a state the parent already left. The `production-characteristics.md` rewrite is accurate — we have revised our own capacity planning from `2 × children` to `children + 1`.

**#79 closes its reported defect properly.** A user-sent `done.review` is now matched by `"*"` and `"done.*"`, trips `onUnhandled: "error"`, and is rejected by `strict` — case variants included, because *neither* spelling is exempt any more. That retired a constraint on our side outright.

**#80 is a real ergonomics win.** We have replaced `event.type.startswith("error.")` string-matching with `isinstance(event, ErrorEvent)` / `event.error` throughout our own error handling.

## Per-issue status — every issue open before PR #82/#83

| # | Status on `3c527b0` | Action |
|---|---|---|
| #27 | FIXED-OPT-IN; only wording deviations remain | confirm closed |
| #31 | PARTIAL — engine parity under `strict_targets=False` unmet by code | **reopen** |
| #37 | FIXED | confirm closed |
| #39 | FIXED | confirm closed |
| #43 | **FIXED on this commit** — all 7 criteria | confirm closed |
| #44 | FIXED | confirm closed |
| #50 | FIXED | confirm closed |
| #51 | FIXED (strict itself FIXED-OPT-IN per the issue's own plan) | confirm closed |
| #52 | FIXED | confirm closed |
| #60 | FIXED behaviourally; the residual is architectural framing, not a criterion | confirm closed |
| #75 | FIXED — held at 500-way concurrency under three policies | confirm closed |
| #76 | FIXED | confirm closed |
| #77 | PARTIAL — overflow is still silent; the criteria asked for a raise | **reopen** |
| #78 | FIXED | confirm closed |
| #79 | Reported defect FIXED; criterion 8 (provenance not spoofable / not lost) unmet | **reopen** |
| #80 | **FIXED on this commit** — all 8 criteria, sync parity included | confirm closed |

**13 confirm closed · 3 reopen.** We only reopen where an acceptance criterion is unmet **by code** — not for wording, naming, test-file paths or architectural framing.

## Wave 3 — new issues filed against this commit

**High (6)**

- [ ] `send(event, wait=True)` resolves `changed=False, error=None` for an event held by `onUnhandled: "defer"`
- [ ] `Event(system=True)` is user-settable and bypasses `strict`, `onUnhandled` and `"*"` on both engines
- [ ] Event provenance does not survive a snapshot; restored engine events become user traffic *(regression introduced by this release)*
- [ ] A pending `ErrorEvent` / `DoneEvent` is silently dropped by `get_persisted_snapshot()`
- [ ] The sync `maxIterations` `tripped` flag is scoped to the drain, not the chain (#77)
- [ ] The `sync=` compatibility shim treats a `**kwargs` clock as consent (#76)

**Medium (10)**

- [ ] `max_iterations` does not bound an action-side `send()` on the async engine (#77)
- [ ] The alias-ambiguity guard does not fire for its own documented example
- [ ] `resolve_aliases` mutates the caller's `MachineLogic` registry
- [ ] The `logic_modules` normalised index uses `setdefault`; duplicates resolve by iteration order
- [ ] A sync `done.invoke` is classed self-generated; after a trip the completion is dropped (#77)
- [ ] The library trips its own `ErrorEvent.data` `DeprecationWarning` (#80)
- [ ] `_resolve_event_spec` builds an `Event` whose `payload` is the exception (#80)
- [ ] `escalate` is the one failure path not converted to `ErrorEvent` (#80)
- [ ] Strict mode still exempts by name via `ENGINE_EVENT_SHAPES` (#79/#51)
- [ ] `SyncInterpreter` never delivers `onError` for a failed invoked child machine

**Low (8) — filed as ride-along comments rather than issues:** the rollback checkpoint-skip predicate (#27) · `send_threadsafe` error precedence (#78) · the silent per-chain cut and the sync/async off-by-one (#77) · `_SIBLING_FALLBACKS_WARNED` unbounded module-global (#31) · the untracked completion-delivery task (#43) · dead `_SYSTEM_EVENT_PREFIXES` with a now-false comment, missing tests for the new provenance attack surface, and the undocumented/unexported provenance API (all #79).

## Adoption decision

**DEFER, on the library-adoption half only.** To be explicit about what that does and does not mean:

- It is **arithmetic, not a verdict on quality**. The decision table is applied in order and the row that matches is "all Blockers closed; more than 5 High open". Seven are open: the engine-parity residual on #31, the deferred-receipt false negative, the sticky sync `tripped` flag, the `**kwargs` clock shim, and the three new ones from this PR.
- **All four originally-filed Blockers remain closed.** Nothing has regressed into Blocker territory.
- **This is a pre-release build.** Fixing the two snapshot findings before 0.8.1 tags returns the count to 5 and the previous "adopt with constraints" decision applies again. That is the outcome we expect and would prefer.
- The adopting project's own execution path (an in-house interpreter over the same statechart JSON) is unaffected and continues. Nothing here changes the plan to adopt once the count comes back under the bar.

**One finding still gates our order path specifically**, and it got harder rather than easier: the deferred-receipt false negative. The two settings that path is mandated to use together — `onUnhandled: "defer"` and `send(wait=True)` — compose into a receipt that says "nothing happened, nothing went wrong" for an event that is parked and about to drive its transition. We had proposed reading `deferred_count` alongside the receipt as our own mitigation; re-testing on this commit shows that does not work — at the caller's `await` point it reads `0` for both the deferred case and the genuine no-op. There is currently no in-band way for a caller to tell them apart.

## Release-readiness summary — what we would fix before tagging 0.8.1

**Blocking, in our reading:**

1. **Provenance does not survive a snapshot.** A restored `escalate` event fails a machine configured `onUnhandled: "error"` where the live one does not. Under the old name rule the answer was the same either side of a restore. This is #79 meeting #47, and it is the one item in this window we would call a regression.
2. **A pending `ErrorEvent` is silently dropped by the snapshot.** #47 exists so a crash between accept and process cannot lose an event; #80 routed *every* service and child failure through a class that falls through the filter. A machine restores believing the invoke never failed and no `onError` ever fires. Even a `logger.warning` would have surfaced it.
3. **`__version__` still reports `0.8.0`** on a tree whose CHANGELOG describes 0.8.1 — two reviews running. Consider a test tying it to the newest released CHANGELOG heading.

**Strongly recommended:**

4. **`Event.system` is a public, user-settable field.** The name rule this PR removed was at least hard to hit by accident.
5. **The sticky sync `tripped` flag** (#77): one self-feeding event starves five later unrelated events in the same `send_events()` batch — a data-starvation bug on the engine the fix was written for.
6. **The `**kwargs` clock shim** (#76): require the `sync` parameter by name, not via a catch-all.
7. **`resolve_aliases` mutating the caller's registry**: the one alias-feature item with cross-machine blast radius. Resolve into a per-machine copy.
8. **The alias-ambiguity guard** missing its own documented example, and not reaching `logic_modules` at all. Fixing it after release is a behaviour break.
9. **The library tripping its own deprecation warning**: `-W error::DeprecationWarning` CI now fails on code the user cannot change.
10. **Pin a `--cov-fail-under` floor at 88–90** while coverage is at its 90% high-water mark.

**Worth a release-note line rather than a fix:** qualify the rollback checkpoint-skip's "≈0.98× of the default" with *"on transitions that run no actions"* (with actions it is 0.878×; on a busy 50 000-event burst, armed rollback is 0.854× and `rollback_and_defer` 0.774×) · the checkpoint-skip predicate not modelling `always`/`on` on the target · the `ErrorEvent` edge cases in #80 · the strict-by-name residual · the sync/async child-failure parity gap · the untracked delivery task · the three #79 housekeeping items.

Every item above is reproduced by a script we can share; nothing in this list is a hunch.
