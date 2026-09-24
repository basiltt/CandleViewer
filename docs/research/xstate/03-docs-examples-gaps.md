# STUDY 3 — Docs & Examples Audit: `xstate-statemachine`

Version at time of study: **0.7.0** (pyproject.toml). README claims 2,800+ tests, 88% coverage,
zero runtime deps, Python 3.9–3.14. `docs/FEATURE_GAP_ANALYSIS.md` is dated 2026-08-07 against
v0.5.1 and is **explicitly marked RESOLVED as of v0.6.0** (2026-08-08) — it is a historical
record, not a current gap list. Current gaps (if any) must be found empirically in Study
4/5-style probing, not read off that document as-is.

Site fetch attempt (`https://basiltt.github.io/xstate-statemachine/`) **failed** in this
environment (WebFetch tool errored: "400 output_config.effort ... model claude-haiku-4.5 does
not support reasoning effort" — an infra/tool problem, not a library problem). Docs-vs-code
comparison below is therefore based on **repo docs vs repo source/CHANGELOG**, not the live
site render. Flagged as a methodology gap, not swept under the rug.

---

## 1. Documented Feature Inventory (recipe names as given in docs)

| Area | Doc file | Recipes / named features |
|---|---|---|
| Core | `core-concepts.md` | atomic/compound/parallel/final states, `initial`, `entry`/`exit`, context |
| Hierarchical | `hierarchical.md` | nested states, `id`/`#id` targets, dotted-path collision rejection |
| Parallel | `parallel.md` | concurrent regions, one-state-per-region invariant |
| Guards | `guards.md` | named predicates, `cond` (v4 alias), object-form guards, `and`/`or`/`not`, `stateIn` |
| Actions | `actions.md` | `assign`, `raise`, `sendTo`, `sendParent`, `forwardTo`, `escalate`, `log`, `cancel`, `stopChild`, `spawnChild`, `emit`, `enqueueActions` |
| Delayed transitions | `delayed-transitions.md` | `after` (integer + named/expression delays), timer cancellation on exit |
| Services / invoke | `services.md` | `invoke` + `onDone`/`onError`, sync vs async services, `NotSupportedError` guardrail |
| Actors | `actors.md` | `spawn_<key>` convention, `spawn_blocking_<key>`, factory-function actors, `spawnChild`/`systemId`/`system.get()`/`system.get_all()`, `sendTo`/`sendParent`/`stopChild`/`forwardTo`/`escalate`/`cancel` |
| Final states | `final-states.md` | `type: final`, `output`/done-data, `status == "done"` |
| Snapshots | `snapshots.md` | `get_snapshot()`/`from_snapshot()`, file + SQLite persistence recipes, explicit **limitations list** (no entry re-run, no service restart, no timer resume, JSON-only context) |
| Interpreters | `interpreters.md` | `Interpreter` (async) vs `SyncInterpreter`, lifecycle (`start`/`stop`/`status`) |
| Plugins | `plugins.md` | `PluginBase` hooks (`on_interpreter_start/stop`, `on_event_received`, `on_transition`, `on_guard_evaluated`, `on_action_execute`, `on_action_error`, `on_service_start/done/error`), built-in `LoggingInspector` |
| Testing / pure API | `testing-and-pure-api.md` | `initial_transition`, `pure_transition`, `get_next_snapshot`, `PureSnapshot` (`.state_ids/.context/.status/.output/.configuration/.matches()`), `wait_for`/`wait_for_sync`, `to_promise` |
| Diagrams | `diagrams.md` | `to_mermaid()`, `to_plantuml()` (no graphviz) |
| CLI codegen | `cli.md`, `cli-templates.md`, `cli-hierarchy.md` | `xsm generate-template` (`gt`), 5 templates (`pythonic-class/builder/functional`, `class-json`, `function-json`), `--check`/`--diff` self-verification, `--file-count`, `-jp/-jc` hierarchy composition, `LogicLoader` auto-discovery |
| Pythonic API | `pythonic-api.md` | `StateMachine`/decorators, `MachineBuilder` fluent, functional `State`+`build_machine()` |
| Context | `context.md` | context mutation patterns, `MachineLogic` |
| FAQ / troubleshooting | `faq.md`, `troubleshooting.md` | contained action-error semantics, timer-vs-snapshot caveat, "is this production ready" |

---

## 2. FEATURE_GAP_ANALYSIS Table — Reproduced + Impact Assessment for CandleViewer's OMS/Rule Engine

Status per the doc itself: **all 73 items closed in v0.6.0** (current is 0.7.0). Table reproduced
with our own impact read, because "closed" in the library's changelog still deserves scrutiny —
e.g. is it closed *correctly*, and does the underlying design choice still matter for us even
after the bug is fixed.

| # | Gap (as researched pre-0.6.0) | Severity (lib's own) | Status now (0.7.0) | CandleViewer impact if it recurred/if design choice remains relevant |
|---|---|---|---|---|
| 1 | `cond` fires unconditionally (v4 spelling ignored) | CRITICAL | Fixed — `cond` aliased to `guard` | Would have been catastrophic for OMS guards (e.g. "only cancel if not already filled") — silent bypass of safety predicate. Worth a regression test in our suite pinning this, since a future upstream regression would be a live-trading risk. |
| 2 | Object-form guards (`{"type":...,"params":...}`) unhashable, kills async interpreter | CRITICAL | Fixed | Directly relevant: our rule engine IR (24-internal-schemas.md) plans parameterised guards. This crash class — async task exception swallowed, `status` still "running" — is exactly the failure mode we must not tolerate in a live OMS interpreter. Confirms need for our own watchdog/heartbeat on any interpreter task, independent of upstream fixes. |
| 3 | History states strand the machine | HIGH | Fixed | We may want history semantics for algo pause/resume (e.g. chase algo resuming into last sub-state). Verify with our own test once integrated — don't trust the changelog blindly for a feature this specific to our OMS. |
| 4 | Child actors dropped from snapshot (data loss) | CRITICAL | Fixed (0.7.0 changelog claims persistence fixed in 0.6.0 tier-3 work — verify empirically) | **This is our single biggest integration risk.** OMS order-group fan-out and paper-matcher sub-actors are exactly the "parent with live spawned children" shape called out as the CRITICAL example. Must be independently re-verified (Study 4/5), not accepted on trust — this was the worst data-loss bug found. |
| 5 | Silently dropped keys (`tags`, `meta`, `always`, `output`, `delimiter`, wildcards, forbidden transitions, dynamic params, context-as-factory) | Mix HIGH/MEDIUM | Fixed, now loud or supported | `tags` mapped to `has_tag()` is genuinely useful for us — OMS/order UI states ("working", "terminal", "needs_attention") map well to tags. Wildcard event descriptors (`mouse.*`) map naturally to our order-flow event taxonomy (`order.*`, `fill.*`). |
| 6 | No action creators (`raise`/`sendTo`/`sendParent`/`forwardTo`/`escalate`/`log`/`cancel`/`stopChild`/`spawnChild`/`emit`/`enqueueActions`) | CRITICAL | Added | This is the backbone we'd use for OMS-parent ↔ algo-child ↔ paper-matcher messaging. `sendTo`+`systemId` gives us addressable actors without home-rolling a registry — good fit for trade-group fan-out. |
| 7 | Guards: no `and`/`or`/`not`/`stateIn`, no parameterised/dynamic guards | CRITICAL | Added | Needed for rule engine IR compound conditions; confirms the library can now express boolean guard composition natively instead of us pre-compiling it. |
| 8 | No `input`/`output` at actor level, context-as-factory broken | CRITICAL | Added | Relevant for spawning a per-order algo actor parameterised by order params (`input`) and collecting a fill summary at completion (`output`). |
| 9 | No actor system (`systemId`, `system.get/get_all`) | HIGH | Added | Matches our need to address a spawned iceberg/TWAP child by client-order-id from the parent OMS machine. |
| 10 | Actor logic creators (`fromPromise` partial, `fromCallback` partial, `fromTransition`/`fromObservable` missing) | HIGH | Partially addressed per docs (services.md still shows plain callables, no explicit `fromObservable`) — **treat as still-partial**, verify | Our order-flow/book engines are push/streaming in nature (closer to `fromObservable`/`fromEventObservable`). Docs show no such creator; services.md only documents plain sync/async callables via `invoke`. This is a real remaining gap for us: streaming market-data actors don't map cleanly onto invoke-once/onDone-once semantics. |
| 11 | No error snapshot (`status` never "error") | CRITICAL | Docs still show `status` as `'running'`, `'stopped'`, and `PureSnapshot.status` as `'running'/'done'/'error'` — **inconsistent between real interpreter and pure API**, see §4 | For OMS this matters: a "machine is broken and needs paging" state must be first-class and distinguishable from "running with a swallowed action error" (which is the documented *contained-action* semantics — see below). |
| 12 | No `subscribe/matches/hasTag/can/toPromise/waitFor` | HIGH | Added (`matches`, `can`, `has_tag`, `wait_for`/`wait_for_sync`, `to_promise` all documented) | Good — these map directly onto health/monitoring hooks we'd want in admin UI (query "is this OMS machine in a terminal/error tag"). |

**Overall assessment:** the analysis is credible and unusually self-critical for a project's own
docs (explicitly logs its own CLI template bugs, its own silent-failure classes, with reproduction
snippets). That itself is a signal of quality-of-process, but it also means the library had, as
recently as 3–5 weeks before this study (per dates in the doc), **multiple classes of behavior
that would have caused undetected wrong behavior or data loss in exactly the shapes CandleViewer
needs** (guarded order-cancel transitions, spawned actor persistence, async task death). None of
these are hypothetical for us — they map onto real OMS/rule-engine constructs. Recommendation:
do not treat "fixed in 0.6.0" as closed for our purposes until Study 4/5 empirically reproduces
the OMS-shaped scenarios (parent+child actor snapshot round-trip; guard object-form under load;
async interpreter task-death visibility) against the actual 0.7.0 code, because this project's
own history shows previously-"fixed" and even previously-tested code paths (2,647 passing tests)
still contained release-blocking defects found only by "adversarial battle testing" — the same
posture we've been asked to take.

---

## 3. Docs-vs-Code Discrepancies Found

1. **Error status inconsistency (real finding, not from the gap doc):** `snapshots.md` states a
   snapshot's `status` is "the interpreter's lifecycle status (`\"running\"`, `\"stopped\"`, etc.)".
   `testing-and-pure-api.md` documents `PureSnapshot.status` as `'running'`, `'done'` or `'error'`.
   The FAQ says action failures are "logged and contained" (never surfaced as machine status), while
   the CHANGELOG for 0.6.0 claims "closes all 73 gaps," including gap #11 "no error snapshot —
   `status` never `error`". The **pure API** clearly got an `'error'` status; whether the **live
   interpreter's** `status`/`get_snapshot()` also now reports `'error'` is not shown by any example
   in `snapshots.md` or `interpreters.md` — those two guides never mention `'error'` as a possible
   `status` value, only `'running'`/`'stopped'`. This is either an omission in `snapshots.md` or a
   real asymmetry between the pure and stateful APIs. **Needs an empirical probe** (Study 4) —
   flagged as a docs gap either way.
2. **CLI template maturity vs README claim:** README's comparison table and "Verified codegen"
   pitch imply all 5 templates are solid, but `CHANGELOG.md` [0.7.0] reveals that **all three
   `pythonic-*` templates were broken in every meaningful way** (zero transitions generated,
   dropped nested states, wrong initial-state count) as of 0.6.0, fixed only in 0.7.0, and the
   *previous* CLI test suite asserted on generated string literals in a way that pinned the bug as
   "correct" for the library's entire life up to that point. `docs/_guide/cli-templates.md` should
   be read with this history in mind — it now documents post-fix behavior, but is a reminder that
   generated-code correctness for this library has a recent track record of silent, long-lived
   breakage that its own test suite failed to catch. Any codegen path we adopt (`class-json`/
   `function-json`, which load JSON at runtime rather than baking it into Python, and were **not**
   in the broken set) is the lower-risk choice for us if codegen is used at all.
3. **`from_snapshot()` limitations are honestly documented** (no entry re-run, no service restart,
   no timer resume) — this is good, and directly informs our recorder/replay design: any OMS state
   restored from a snapshot after a restart must re-derive timer deadlines from context (as the doc
   itself recommends: store a wall-clock `deadline` in context rather than relying on `after`). This
   is a real constraint on our reconciliation/failover module (20-architecture.md), not just a docs
   nuance — a restarted OMS process resuming from a snapshot will **not** automatically re-arm
   things like TWAP slice timers or child-actor invocations; our failover logic must explicitly
   recompute/re-issue any such live state on resume.
4. **Website not independently verified.** The live docs-site fetch failed in this session (tool
   infra error, not a 404/content issue) — so "docs = code" could only be checked at the repo level
   (guide markdown vs CHANGELOG/source), not confirmed to be the same content the public site
   serves. Recommend re-running the fetch in a follow-up session before treating the site as
   validated.

---

## 4. Example Patterns Relevant to Us

All under `examples/{async,sync,hybrid}/...`, organized by difficulty × (class/functional) ×
(with/without `LogicLoader`).

- **Persistence:** no example dedicated purely to snapshot persistence beyond what's in
  `snapshots.md` itself (file + SQLite recipes). No example demonstrates snapshotting a machine
  *with live spawned actors* — i.e., the exact CRITICAL scenario (#4 above) that matters most for
  our OMS is **not covered by any example**, only asserted fixed in the changelog. Gap for us to
  fill with our own test before relying on it.
- **Actors:** `examples/async/super_complex/.../smart_home/` (parent + `light_bulb_actor.json`),
  `.../warehouse_robot/` (parent + `pathfinder_actor.json`), `.../flight_booking/` (parent +
  `ancillary_service_actor.json`), `.../collaborative_editor_*` (parent + `collaborator_cursor_actor.json`)
  — these are the most OMS-relevant: multi-actor systems with a coordinating parent, most closely
  resembling "OMS parent + per-order algo child" or "trade-group fan-out parent + per-leg child."
  Worth walking through `warehouse_robot` and `flight_booking` in Study 4/5 as structural templates.
- **Async services:** `examples/async/intermediate/.../api_fetcher`, `.../file_processor`,
  `.../video_transcoder` show `invoke` with async services and `LogicLoader`; directly analogous to
  our exchange REST-call services (place/cancel/amend order) inside OMS states.
- **Timers:** `stopwatch` (both sync and async variants) and `session_timeout` are the canonical
  `after`-timer examples — relevant to OCO/iceberg/TWAP slice timing and to session/auth expiry.
- **Plugins:** no example directory names a plugin demo explicitly; plugin usage is documented only
  in `plugins.md` narrative form (`LoggingInspector`, custom `PluginBase` subclass for metrics). For
  our purposes (structured audit logging into the recorder, Sentry-style `on_action_error` routing)
  the doc's own `Metrics`/`on_action_error` snippet is the template to copy.
- **Testing pure API:** no example under `examples/` uses `pure_transition`/`initial_transition`
  directly — only documented in `testing-and-pure-api.md`. This is a real testing pattern we'd
  want for the rule engine (compute "what would this rule set do to this order" without running
  side effects) but it exists only as documentation, not as a runnable example we can diff against.
- **CLI codegen JSON→typed Python:** no worked example under `examples/` shows CLI-generated
  output being kept in a repo (no `--check`/`--diff` CI-usage example). `cli-hierarchy.md` covers
  the `-jp`/`-jc` multi-file composition flow (parent + child JSON → codegen), relevant if we want
  to author OMS + per-algo-child machines as separate JSON files and generate typed stubs, but there
  is no example directory demonstrating this end-to-end — only the guide's narrative CLI invocations.
- **Hybrid example** (`examples/hybrid/manufacturing_line/`): one async JSON machine + one sync
  JSON machine composed together in a single Python driver (`hybrid_manufacturing.py`) — useful
  reference if any part of our stack needs a sync sub-machine (e.g. a CLI/admin tool) alongside the
  primarily-async OMS.

---

## 5. Stately.ai Interop Story — What It Buys CandleViewer

Per README and `json-config.md`: the pitch is that a JSON file exported from the Stately.ai visual
editor is loaded **unmodified** by `create_machine()`, with 103/104 real-world exported machines
in the test corpus parsing without changes (the 1 exclusion has no `states` key at all and is
rejected by `create_machine()` too, i.e., not really a counter-example). JS/TS action
*implementations* do not transfer — only the shape of the machine (states/events/guards/actions-
as-names) is portable; Python-side behavior is supplied via `MachineLogic`.

**What this concretely gives CandleViewer**, if adopted:

1. **A single source of truth for OMS/rule-engine state shape**, authored visually at stately.ai
   (or hand-written JSON), consumed identically by:
   - the Python backend (`create_machine()` + `MachineLogic` with our real order-management side
     effects), and
   - our React admin/trading UI, which could load the *same JSON* into `@xstate/react` purely for
     **visualization** (Stately's built-in state-chart diagram rendering, or `@statelyai/inspect`)
     — i.e., a live or replayed picture of "which OMS state is this order in, right now" and
     "which rule-engine state fired this action," without hand-maintaining a second diagram that
     drifts from the real state machine.
2. **Diagram generation without a JS toolchain on the Python side**: `to_mermaid()`/`to_plantuml()`
   let us render the same machine as a static diagram for docs/runbooks even without shipping the
   JSON to the frontend.
3. **Caveat, stated plainly by the library itself in its own FAQ**: this interop is *structural
   only*. Our OMS side-effects (exchange calls, DB writes, risk checks) are Python-native and will
   never be expressed in the shared JSON — nor should they be. The "same JSON, two runtimes" value
   is for the *shape* of the OMS/rule-engine state graph (states, events, guards-by-name,
   actions-by-name), which is exactly what we'd want a trading-ops person or reviewer to be able to
   inspect visually against the live backend's actual states, not full behavioral parity across
   languages.
4. **Risk to flag honestly**: this interop story is currently **untested by us** — it rests on the
   library's own 103/104 corpus claim, and depends on whichever subset of XState features
   (`tags`, `guards`, `wildcards`, `history`) our real OMS machine ends up using being covered by
   the "closed in 0.6.0" set, which per §2 we have not yet independently re-verified against 0.7.0
   for the specific shapes CandleViewer needs (spawned-actor persistence, streaming/observable
   actors). Recommend a Study 4/5 step that authors one real OMS sub-machine both in the Stately
   visual editor and by hand, diffs the JSON, and round-trips it through both `create_machine()`
   and a minimal React/`@xstate/react` loader before relying on this pitch operationally.

---

## 6. Summary Verdict for This Study

- Docs are thorough, example coverage is broad (100+ example programs across difficulty tiers and
  API styles), and the project is unusually transparent about its own defect history (gap analysis,
  CHANGELOG "silent wrongness" sections). That transparency is itself useful signal — but it is
  also a track record: two consecutive minor releases (0.6.0, 0.7.0) each disclose CRITICAL,
  silent-wrongness defects that survived thousands of pre-existing passing tests. For a trading OMS
  this means: **do not adopt any single behavior on the strength of documentation or changelog
  claims alone** — every OMS/rule-engine-relevant behavior (guarded transitions, actor snapshot
  persistence, async task-death visibility, error-status surfacing) needs its own reproduction in
  our own test harness before we depend on it in a live-trading path.
- The single most consequential open question for us, not fully resolved by docs: whether
  **child-actor persistence** (historically the worst CRITICAL/data-loss defect found) is now
  correct for a shape like ours (parent OMS + multiple concurrently spawned per-order/per-leg
  actors, not just the single-child examples shown), and whether **error status** is surfaced
  identically between the live interpreter and the pure API. Both are concrete, testable claims —
  next study should verify them directly against 0.7.0 rather than trusting the "RESOLVED" banner.
