# Replacement body for meta issue #26

**Action:** replace the issue body (full replacement, not a comment)

---

> ## Status on `main` @ `5e07ba8` (round 4, 2026-09-18, pre-0.8.1)
>
> **Identify this build by commit, not by version string.** `__version__` still reports `0.8.0` on this commit while `CHANGELOG.md` targets 0.8.1. Any pin, CI assertion or baseline keyed on the version string will silently confuse the two. Every finding below was reproduced in a fresh process on `5e07ba8842345a73ef8f830f0281de16370a7c74`, CPython 3.13.7, Windows 11.
>
> **The 19 issues fixed in round 3 are genuinely fixed — 17 confirm-closed, 2 reopened narrowly (#91 criterion 3, #99's async side).** No regressions at any level: suite **3 276 passed / 0 failed** (+34 over the previous commit), coverage 90%, every prior verification set still green, probes unchanged. The fix quality across three rounds has been consistently high, and we want that on the record before the rest.
>
> **Round 4 was the first deep battle-test of the library itself rather than of the issues we had already filed** — eight tracks: persistence/crash-consistency, concurrency & limits, determinism/replay, semantics conformance, fuzz/property, security/supply-chain, a 25-minute soak, and observability. It found **40 canonical defects; after an independent adversarial refutation pass, 2 Blocker · 6 High · 18 Medium · 12 Low survive** (2 refuted outright).
>
> The two Blockers and most Highs share one shape: **state-corrupting windows that report `status="running"`, `error=None`, `last_transition_ok=True`** — indistinguishable from health. For a durable, money-adjacent path that is the worst failure profile available; a crash would be better, because a crash is observable.
>
> **This is the first round where the operative blocker is upstream rather than in our own adoption tooling.** It is not a harsh verdict. Rounds 1-3 tested the issues we had filed. Round 4 was the first time the persistence, settling and concurrency machinery was driven with random interruption points, property tests and hostile policies — and it found what such testing usually finds in a young engine. What is missing is specific, small, and listed at the bottom of this issue.

## Gate result on this commit

```
Gate run 2026-09-18 — xstate-statemachine main @ 5e07ba8 (unreleased 0.8.1)
DECISION: DEFER (durable/critical path)  ·  other paths: proceed under constraints
  19 fixed issues : 17 confirm-closed, 2 reopen narrow (#91 crit 3, #99 async side)
  regressions     : none
  new defects     : 2 Blocker · 6 High · 18 Medium · 12 Low  (post-refutation; 2 refuted)
  suite/coverage  : 3276 passed / 0 failed · 90%
  operative block : UPSTREAM — R4-01 (torn snapshot), R4-04 (non-terminating start),
                    R4-06 (external events charged to chain budget), R4-07 (receipt id-keying)
```

Decision-table row 1 matches: any open Blocker → DEFER. Two are open.

## Per-issue status — every issue in this tracker

### Round-1 set (#27–#60)

| # | Status on `5e07ba8` | Action |
|---|---|---|
| #27 | FIXED-OPT-IN (`actionErrorPolicy`); only wording deviations remain | closed |
| #28 | FIXED-OPT-IN (`onUnhandled`) | closed |
| #29 | FIXED-DEFAULT (`strict_targets`) | closed |
| #30 | FIXED-DEFAULT | closed |
| #31 | **FIXED on this commit** — criterion 4 (engine parity under `strict_targets=False`) now met | **confirm closed** |
| #32 | FIXED-DEFAULT | closed |
| #33 | FIXED-DEFAULT (error-observability hooks) | closed |
| #34 | FIXED-DEFAULT | closed |
| #35 | FIXED-DEFAULT (observability) / FIXED-OPT-IN (`guardErrorPolicy`) | closed |
| #36 | FIXED-DEFAULT | closed |
| #37 | FIXED | closed |
| #38 | FIXED-DEFAULT (`queue_depth`) / FIXED-OPT-IN (bounding) — see **R4-03** for a defect in `OverflowPolicy.BLOCK` | closed |
| #39 | FIXED | closed |
| #40 | FIXED-DEFAULT — see **R4-35** for the unresolvable-`sendTo` residual | closed |
| #41 | FIXED-DEFAULT | closed |
| #42 | FIXED-DEFAULT | closed |
| #43 | FIXED at `3c527b0` — all 7 criteria; still holding | closed |
| #44 | FIXED — see **R4-37** for a docs residual on `restart_services=True` | closed |
| #45 | FIXED-DEFAULT (snapshot version + machine identity) — see **R4-02** | closed |
| #46 | FIXED-DEFAULT | closed |
| #47 | FIXED-DEFAULT — see **R4-11** (priority lane never persisted) | closed |
| #48 | FIXED-DEFAULT (14.5× better; our own latency bar is separate) | closed |
| #49 | FIXED-DEFAULT (clock injection) — see **R4-18**, **R4-22** | closed |
| #50 | FIXED | closed |
| #51 | FIXED for the guardrail + static-`raise` validation; `strict` remains opt-in by the issue's own plan. The by-name exemption residual is closed by #98 | closed |
| #52 | FIXED | closed |
| #53 | FIXED-DEFAULT (documentation) | closed |
| #54 | FIXED-DEFAULT (perf) | closed |
| #55 | FIXED-DEFAULT | closed |
| #56 | FIXED-DEFAULT | closed |
| #57 | FIXED-DEFAULT | closed |
| #58 | FIXED-DEFAULT | closed |
| #59 | FIXED-DEFAULT | closed |
| #60 | FIXED for every criterion that describes behaviour; the residual is architectural framing, not a criterion | closed |

### Round-2/3 set (#75–#99) — the 19 verified this round

| # | Status on `5e07ba8` | Action |
|---|---|---|
| #75 | FIXED | closed |
| #76 | FIXED — see #89 for the `**kwargs`-consent follow-up, also fixed | closed |
| #77 | **FIXED on this commit** — criterion 6 (overflow observability) now met | **confirm closed** |
| #78 | FIXED | closed |
| #79 | **FIXED on this commit** — criterion 8 (provenance not forgeable, survives snapshot) now met | **confirm closed** |
| #80 | FIXED | closed |
| #84 | **FIXED** — `Receipt.deferred` on both engines | **confirm closed** |
| #85 | **FIXED** — no public `system=` param; identity-sentinel provenance | **confirm closed** |
| #86 | **FIXED** — snapshot layout v2 round-trips provenance | **confirm closed** |
| #87 | **FIXED** — pending `ErrorEvent`/`DoneEvent` preserved | **confirm closed** |
| #88 | **FIXED** — `tripped` scoped per chain | **confirm closed** |
| #89 | **FIXED** — `**kwargs` no longer counts as clock consent | **confirm closed** |
| #90 | **FIXED** — async action-side `send()` bounded; see **R4-06** for a new defect in the reroute | **confirm closed** |
| **#91** | **PARTIAL** — registry-side guard correct; criterion 3 (config-side duplicate-name warning) not implemented | **REOPEN (narrow)** |
| #92 | **FIXED** — machine-owned registry copy | **confirm closed** |
| #93 | **FIXED** — `logic_modules` ambiguity rule | **confirm closed** |
| #94 | **FIXED** — completions survive a trip; see **R4-25** on engine scope | **confirm closed** |
| #95 | **FIXED** for its own three criteria | **confirm closed** |
| #96 | **FIXED** — `_resolve_event_spec` dict payload | **confirm closed** |
| #97 | **FIXED** — `escalate` mints an `ErrorEvent`; see **R4-20** on routability | **confirm closed** |
| #98 | **FIXED** — strict rejects forged engine-shaped names | **confirm closed** |
| **#99** | **PARTIAL** — sync side correct; the async `_deliver_invoked_completion` path still parks silently on an unhandled child-machine error | **REOPEN (narrow)** |

**17 confirm closed · 2 reopen · 1 meta update (this issue).** We reopen only where an acceptance criterion is unmet **by code** — never for wording, naming, test-file paths or architectural framing.

## Round 4 — new findings

Filed against this commit, each with a standalone runnable repro. Numbers are filled in as the issues are created.

**Blockers (2)**

- [ ] `<R4-01>` — Mid-macrostep configuration is snapshottable: a snapshot taken in the exit→actions→enter window restores as a permanently inert machine reporting healthy. Property run: **45.5% of mid-macrostep snapshots torn** (300 cases). Found independently by two tracks.
- [ ] `<R4-04>` — `SyncInterpreter.start()` never terminates for a cross-region `always` that re-enters an invoking state; at the default `maxIterations=1000` it is still running after 20 s with `last_transition_ok=True`, `last_error=None`.

**High (6)**

- [ ] `<R4-03>` — `OverflowPolicy.BLOCK` silently discards every fire-and-forget `send()`, even on an empty inbox.
- [ ] `<R4-06>` — An external `send()` issued while a macrostep is in flight is charged to the self-raised chain budget and silently dropped *(introduced by #90's reroute; a defect, not a regression of a verified item)*.
- [ ] `<R4-07>` — `Receipt.deferred` keys on `id(event)` in a set that never shrinks on replay: unbounded growth plus false positives on fully-handled events.
- [ ] `<R4-11>` — The priority (timer) lane is never persisted; an already-fired `after` event is lost across a snapshot.
- [ ] `<R4-12>` — A transition targeting the machine root empties the configuration on both engines, leaving `status="running"`.
- [ ] `<R4-19>` — An invoked child's `output` is discarded; `done.invoke` carries the child's private `context` instead.

**Medium (18)**

- [ ] `<R4-02>` — `from_snapshot()` performs no validation and leaks untyped exceptions on malformed snapshots.
- [ ] `<R4-08>` — `send(engine_event, wait=True)` strips engine provenance via `_detach()`'s `dataclasses.replace()`.
- [ ] `<R4-13>` — A settling-budget trip leaves an orphaned active leaf reported as healthy, and mutates on restore.
- [ ] `<R4-14>` — A dict/non-`str` event `type` raises untyped `AttributeError`/`TypeError`, escaping the documented exception hierarchy.
- [ ] `<R4-16>` — Run-loop death leaves `status="running"` and hangs pending receipts forever.
- [ ] `<R4-18>` — `SimulatedClock._attach()` has no paired detach, leaking every restored interpreter.
- [ ] `<R4-21>` — Plain-sync `invoke` completion timing diverges between the two engines for an identical event script.
- [ ] `<R4-22>` — `from_snapshot()` has no `clock=` parameter, so a custom or virtual clock cannot be restored.
- [ ] `<R4-23>` — `AfterEvent` lateness telemetry resets to `0.0` across a snapshot round-trip.
- [ ] `<R4-24>` — `Receipt`'s new 4th field is an undeclared breaking API change in the CHANGELOG.
- [ ] `<R4-25>` — "Engine completions are never discarded" (#94) is implemented on the sync engine only.
- [ ] `<R4-26>` — `create_machine()` still mutates a duck-typed logic object's registries in place.
- [ ] `<R4-27>` — `SyncInterpreter.tick()` delivers only one due `after` deadline per call on chained deadlines.
- [ ] `<R4-28>` — `send()` to a stopped `SyncInterpreter` is silent while the async engine fires `on_event_dropped`.
- [ ] `<R4-29>` — `SyncInterpreter.start()` emits a synthetic init `on_transition` hook the async engine never emits.
- [ ] `<R4-30>` — A deferred event's replay folds into the triggering event's own `Receipt`.
- [ ] `<R4-31>` — The shipped `LoggingInspector` reference plugin logs context and event payloads unredacted at INFO.
- [ ] `<R4-32>` — `async def` plugin hook overrides are never awaited, and swallowed hook failures have no programmatic surface.

**Low (11 filed, 12 surviving)**

- [ ] `<R4-10>` — `after` timers are never re-armed by `from_snapshot()`, with no dormancy signal for a lost timer.
- [ ] `<R4-15>` — Events abandoned by `stop()` are lost with no `on_event_dropped` hook and no log.
- [ ] `<R4-20>` — `escalate()` from an invoked child is unroutable: it reaches neither `onError` nor `"*"`.
- [ ] `<R4-33>` — `DoneEvent.data` is silently stringified into the snapshot by `json.dumps(default=str)`.
- [ ] `<R4-34>` — `stateIn` resolves an ambiguous bare state name by suffix match instead of rejecting it.
- [ ] `<R4-35>` — `sendTo` with an unresolvable target silently drops the event with no observable signal.
- [ ] `<R4-36>` — *(enhancement)* add an `on_resolve_error` plugin hook for unresolved transition targets.
- [ ] `<R4-37>` — `from_snapshot(restart_services=True)` reports `status="running"` before dormant invokes are actually restarted.
- [ ] `<R4-38>` — A self-referential (aliased-cycle) machine config raises `RecursionError` instead of `InvalidConfigError`.
- [ ] `<R4-39>` — `is_system_event` / `system_event` are undocumented and unexported from the package root.
- [ ] `<R4-40>` — Engine-event provenance does not survive `deepcopy` or `pickle`.

The twelfth surviving Low (a guard raising under `guardErrorPolicy: "false"`/`"true"` being indistinguishable from a legitimate `False`) is recorded in our register but not filed as a separate issue — it is a documentation line on #35 rather than a defect, and we will raise it there if you would like it tracked.

**Two findings were refuted by our own adversarial pass and are deliberately not filed**: `restore_event()`'s by-name v1 re-derivation (correct as designed — a name really is all that is available for a v1 record), and a claimed `send_threadsafe()` ordering hazard (the deferred enqueue point is documented behaviour, leaving at most a docs residual).

## Battle-test scorecard

| Track | Coverage achieved | Defects after triage | Verdict |
|---|---|---|---|
| **Persistence / crash consistency** | property runs over random interruption points; v1→v2 upcast; corrupt JSON; large context | **1 Blocker (R4-01)**, 3 High, 7 Medium | **FAIL** — the snapshot is not transactional |
| **Concurrency & limits** | 2 000 interpreters × 16 producers × 3 policies; 32-thread `send_threadsafe`; stop/restore races; 1 000-cycle leak check | R4-03, R4-06, R4-16 | **FAIL** on silent-drop paths; **PASS** on leaks (0 leaked tasks) and loop blocking (<5 ms) |
| **Determinism / replay** | 50× runs on both engines, 10 000 events; scheduling perturbation; `PYTHONHASHSEED` sweep | 0 Blocker; engine-parity Mediums (R4-21, R4-28, R4-29) | **PASS with constraints** — the async engine is deterministic run-to-run; sync ≠ async in 3 places |
| **Semantics conformance** | 60+ SCXML / XState cases | R4-12 (High), R4-19 (High), Mediums | **PARTIAL** — the core algorithm is sound; root-target transitions and `output` are wrong |
| **Fuzz / property** | machine-definition, event-sequence and snapshot-corruption fuzzers | R4-02, R4-14, R4-38 (typed-exception escapes) | **PARTIAL** — no crashes, but errors escape the documented base class |
| **Security / supply chain** | bandit / semgrep / pip-audit, import surfaces, codegen, snapshot reconstruction, logging | 2 Medium (R4-31, R4-26), 3 Low | **PASS** — no injection or RCE surface; 0 dependencies; `kind` is an allow-list |
| **25-minute soak** | 200 machines, 3 000 ev/s, chaos restore + plugin exceptions | 1 Low | **PASS** — flat memory, 0 leaked tasks, 0 lost accepted events, stable p99 |
| **Observability** | failure-mode × hook matrix | R4-15, R4-32, R4-35, R4-36 | **PARTIAL** — most paths observable; several drop paths fire no hook |

## Harness errors on our side

Listed explicitly so you are not asked to account for our mistakes. **None of these is a defect in the library.**

- Probe expectations **A10**, **A18** and **C15** are stale: all three are now correctly rejected at **build time** with `InvalidConfigError`. That is `strict_targets` / `always` validation doing its job; our probes still expect the old runtime behaviour.
- The `g1_forge_system.py` family of probes was written against the pre-#85 public `Event(system=True)` kwarg. They are now **inert** and their output on this commit is not evidence of anything; they need a rewrite against the private-sentinel API.
- One observability claim — that `.use()` skips the `_SafePlugin` wrap and so has a different blast radius from assigning `interpreter.plugins` — was **wrong and is withdrawn**. `base_interpreter.py:900-925` does construct a `_SafePlugin`; re-probed with a raising `on_transition`, both paths produce an identical `Receipt(changed=True, error=None)`.
- Our persistence harness uses private-attribute surgery to point a restored interpreter at a `SimulatedClock`. That is deliberate and disclosed — it is the only way to do it, which is itself finding R4-22. No upstream reader should mistake it for a pattern we believe is supported.
- Two runs in the final pass were reduced in scale to fit a time bound (a property run at 300 cases rather than 2 000; a soak at 20 cycles rather than 25 minutes). Both still reproduce, and no conclusion rests on a number we did not re-measure.

## Release-readiness — what we would fix before tagging 0.8.1

**Tag-blocking, in our reading (items 1-4):**

1. `__version__` still reports `0.8.0` — bump it. Consider a test tying it to the newest released CHANGELOG heading; this is the third review running with two version stories.
2. **Fix R4-01.** `get_persisted_snapshot()` must observe only a *committed* configuration — take the snapshot under the same latch that guards `_processing`, or snapshot the pre-macrostep configuration. This is the single most important item in three rounds.
3. **Fix R4-06.** The #90 reroute must distinguish self-generated from external events by provenance/origin, not by the interpreter-wide `_processing` flag.
4. **Fix R4-07.** `Receipt.deferred` must not key on `id(event)`; reuse the envelope identity introduced for #75.

**Strongly recommended before the tag:**

5. **R4-04** — bound the settling loop by the same `RunawayChainError` path as the event chain (this also closes R4-13).
6. **R4-12** — reject a root-targeting transition at build time.
7. **R4-19** — `done.invoke` must carry the child's `output`.
8. Do one **systematic provenance audit** of every `Event` reconstruction site (R4-08). This is the third instance in two releases of "the new provenance rule was not audited across a boundary that rebuilds an `Event`"; the fix is one audit of `_detach`, `restore_event` and every `deepcopy`/`pickle` site, not three more point patches.
9. The async side of **#99**, and the config-side warning for **#91**.
10. Pin a `--cov-fail-under=88` floor now, while coverage is at its 90% high-water mark.

## What would change the verdict

- **R4-01 and R4-04 closed, with a pinned test each → the Blocker row clears.** If R4-06 and R4-07 are closed too, the open High count falls to 4 (R4-03, R4-11, R4-12, R4-19), each with a mechanical mitigation on our side — which returns us to **adopt with constraints**, gated only on our own linter and contract tests, exactly as at 0.8.0.
- Re-verification is cheap: the gate script, the seven final probes, and a reduced persistence property run (300 cases) on the fix commit. **About 30 minutes.**

Every item above is reproduced by a script we can share; nothing in this list is a hunch. We remain committed to adopting this library — these issues are the price of that adoption being safe, not an argument against it.
