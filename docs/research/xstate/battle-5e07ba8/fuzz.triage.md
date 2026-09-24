# FUZZ track triage — `xstate-statemachine` @ `5e07ba8`

Re-verification pass over `docs/research/xstate/battle-5e07ba8/fuzz.md`.
Method: re-ran `fuzz/repros.py` fresh (single process, exit code = defects
reproducing), then read every cited library source location to confirm the
claimed root cause. No library source modified; no `git` run in this repo.

**Re-run result:** `9/9 defects reproduce on this build` (identical to the
document's claim; observed values differ slightly in scale — e.g. D-fuzz-1's
inbox length after 6 s was 125 249 vs. the doc's 36 050 at 4 s / run-to-run
variance — but the qualitative outcome is unchanged for every defect).

Source spot-checks performed: `sync_interpreter.py:796-845`
(`_process_transient_transitions`, confirms D-fuzz-1's per-pass microstep
limit that does not bound re-entry from a fresh macrostep), `:770-776`
(the `generated=0; tripped=False` reset on any queue-length decrease,
confirms the chain-budget-reset mechanism cited for D-fuzz-1/D-fuzz-9), and
`validation.py:132-151` (`_is_dead_always_loop`, confirms it only fires when
`target is t.source`, i.e. is blind to the cross-region/root-targeting
shapes in D-fuzz-1 and D-fuzz-2).

## Triage table

| ID | Re-repro | Kind | Severity (OMS-adjusted) | Reason |
|---|---|---|---|---|
| D-fuzz-1 | REPRODUCED (start() alive after 6s, inbox=125,249 and climbing) | LIBRARY-DEFECT | **Blocker** (unchanged) | Confirmed at `sync_interpreter.py:796-845`: the microstep limit (`limit = machine.max_iterations`, default 1000) bounds one pass of `_process_transient_transitions`, but each pass that re-arms an `invoke` completes with `iterations` reset to 0 on the *next* call from `_process_event_queue`. `_is_dead_always_loop` (`validation.py:132-151`) requires `target is t.source`, so a cross-region `always` targeting a *different* region's invoking state is structurally invisible to build-time validation. This is a genuine, silent, unbounded-memory hang on `start()` with no timeout and no way to interrupt on the sync engine — squarely a money-loss risk (process death / stuck order-placement thread) on an OMS order path. Severity unchanged from the register: Blocker. |
| D-fuzz-9 | REPRODUCED (orphan `m.b.b.a`; save1 config `['m','m.b.b.a']` vs save2 `['m','m.b','m.b.b','m.b.b.a']`) | LIBRARY-DEFECT | **High** (unchanged, arguably borderline Blocker) | Confirmed: the transient-settling budget break at `sync_interpreter.py:812-824` has no `last_transition_ok`/`last_error` reporting (contrast the event-chain budget at `:716-733`, which does set both). The ancestor-repair in `from_snapshot` (cited at `base_interpreter.py:1229-1234`) silently produces a different, still-illegal parallel state on restore. This is a live invariant violation (non-tree active configuration) reported as `status='running'`, `last_transition_ok=True` — the exact "silent state corruption" the register's Blocker bar names, but kept at High per the original doc because it requires the same rare cross-region+invoke shape as D-fuzz-1 and a tight `maxIterations`, and — unlike D-fuzz-1 — the process does not die, so an external watchdog/health-check (once instructed by CV-F08) can still catch it. Kept at High; flag for reconsideration if the catalogue cannot rule out the triggering shape. |
| D-fuzz-6 | REPRODUCED (8/8 mutations raised untyped `KeyError`/`AttributeError`/`TypeError`) | LIBRARY-DEFECT | **High** (unchanged) | Confirmed at `events.py` (`restore_event` indexing `record["type"]`/`record.get` with no shape check) and `base_interpreter.py` (`from_snapshot` iterating `configuration`/`history` without a type guard). `from_snapshot`'s stated contract (`except XStateMachineError`) is not met on untrusted wire input — this is precisely the boundary #45 was supposed to harden. High is correct: it's an untyped-exception boundary bug, not silent data corruption (the process does at least crash loudly, so an OMS can fail-fast rather than proceed on bad state) — this is the distinguishing factor vs. D-fuzz-7/9 which stay silent. |
| D-fuzz-7 | REPRODUCED (empty-configuration and non-str/int/list `status` all restored with no error) | LIBRARY-DEFECT | **High**, arguably should be raised to **Blocker** for the empty-configuration sub-case | `base_interpreter.py:1216` assigns `interpreter.status = snapshot["status"]` verbatim with no membership check, confirmed. This is silent state corruption surviving a restart with `status='running'`/`has_dormant_invocations=False` reported as healthy — the register's own Blocker definition ("silent state corruption on the order path") arguably applies directly to the empty-`configuration` sub-case, since a restored OMS interpreter that reports healthy while holding zero state and silently no-ops every subsequent event is worse than a crash. Recording as High per the document's own classification, but flagging this as a plausible upgrade candidate: the empty-configuration variant meets the Blocker bar as written and should probably be split out and upgraded, while the merely-undocumented-status-type variant is fairly High. |
| D-fuzz-2 | REPRODUCED (sync + async both `states=[]`, `status='running'`) | LIBRARY-DEFECT | **High** (unchanged) | Confirmed same-family silent-emptying bug as D-fuzz-1/9 but via a simpler, single-region path; both engines agree (no parity escape), `_is_dead_always_loop` doesn't fire because target is the root, not the source. Correctly High: it is discoverable by build-time lint (CV-F03) and does not require the invoke/parallel-region combination that makes D-fuzz-1 unrecoverable, so it's a design-around-able footgun rather than a Blocker. |
| D-fuzz-4 | REPRODUCED (`AttributeError`/`TypeError` on all 4 strict×payload combos) | LIBRARY-DEFECT | **High** (unchanged) | Confirmed: `_prepare_event` pops `type` from a dict event with no `isinstance(str)` check, and the `strict` rejection path itself (`UnknownEventError.__init__` → `difflib.get_close_matches`) also crashes on a non-str type — the error-handling code is itself unsafe. Correctly High: this is a wire-shaped ("dict from a queue/HTTP body") input crashing library internals uncatchably, exactly the untrusted-boundary criterion for High. |
| D-fuzz-3 | REPRODUCED (sync: no hooks fire on send to stopped/done machine; async fires `on_event_dropped`) | LIBRARY-DEFECT | **Medium** (unchanged) | Confirmed by the same repro; this is an engine-parity/observability gap, not silent state corruption (the interpreter's actual state doesn't change — the event is dropped, not mis-applied), and a workaround exists (check `.status` before every sync send, per CV-F07). Medium is right. |
| D-fuzz-5 | REPRODUCED (bare `TypeError` for all 5 non-event objects) | LIBRARY-DEFECT | **Medium** (unchanged, could be folded into D-fuzz-4 as the same class) | Confirmed: `_prepare_event`'s final `else` raises built-in `TypeError` by its own docstring's design ("Raises: TypeError"), so this is a *documented* library choice rather than a bug at a dict-shaped boundary. Kept at the document's severity; arguably slightly lower risk than D-fuzz-4 since it requires a caller to pass a wildly wrong type (not just a malformed dict), which is easier to guard against in a project-side type check before calling `send()`. Medium fits. |
| D-fuzz-8 | REPRODUCED (`RecursionError` on a self-referential config dict) | LIBRARY-DEFECT | **Low** (unchanged) | Confirmed unguarded recursion in `StateNode.__init__` walking `config["states"]`. Genuinely Low as filed: an aliased-dict cycle cannot be expressed in JSON, so any config loaded from a catalogue file (the normal OMS ingestion path) cannot trigger it — only a hand-built Python dict can. Low is right; not worth upgrading. |

## Summary

All nine defects re-reproduced in a fresh process on this pass, matching the
document's `9/9` result. All nine are genuine **LIBRARY-DEFECT**s — none are
harness errors, none are documented design constraints, and none are
duplicates of a previously catalogued LC/N/F/G/H id (the doc's own §4 cross-
references the closest related items — #29/#30/#34/#45/#77/#79/#94/#98 — and
correctly distinguishes each defect's shape from what those fixes actually
cover; I did not find a closer match in this pass). Severity assessment
mostly agrees with the original register:

- **D-fuzz-1 stays Blocker** — confirmed root cause, unbounded hang with no
  workaround on the sync engine, satisfies the register's money-loss/silent-
  corruption bar directly.
- **D-fuzz-9 and D-fuzz-7 are the two candidates for reconsideration.** Both
  are silent, live state corruption reported as healthy (`status='running'`,
  `last_transition_ok=True`) — arguably meeting the Blocker bar as literally
  defined ("silent state corruption on the order path"). I have left them at
  High per the original document's classification since (a) they require a
  narrower trigger shape than D-fuzz-1's plain hang, and (b) a project-side
  post-transition/post-restore legality assertion (CV-F08/CV-F09, which the
  document already prescribes) fully closes the gap — but flag this as a
  judgment call the adopting team should revisit; a stricter reviewer could
  reasonably file D-fuzz-7's empty-configuration sub-case as Blocker.
- All other severities (D-fuzz-2 High, D-fuzz-3/5 Medium, D-fuzz-4 High,
  D-fuzz-6 High, D-fuzz-8 Low) are confirmed appropriate on re-review; no
  downgrades warranted.
