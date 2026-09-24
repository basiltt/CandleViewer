# New issue drafts against xstate-statemachine 0.8.0

**These are drafts. Nothing here has been filed.** Same format as the original
0.7.0 filings in `../LC-*.md`: YAML front-matter, Summary, Environment, Minimal
reproduction, Observed, Expected, Root cause, Impact, Suggested fix, Acceptance
criteria, Related, Verification.

Runnable repros are in `repro/`. Each **exits 1 while the defect is present and
0 once it is fixed**, matching the convention `gate/run_gate.py` expects, so they
drop straight into the gate on the next release.

| Draft | Title | Severity |
|---|---|---|
| `N-01-send-wait-receipt-id-collision.md` | `send(event, wait=True)` hangs forever on a reused `Event` instance | High |
| `N-02-sync-timer-unreachable-in-loop.md` | `SyncInterpreter` `after` deadlines unreachable by `tick()` inside a running loop | High |
| `N-03-sync-macrostep-budget-clears-queue.md` | `SyncInterpreter` macrostep budget still discards legitimate external events | Medium |
| `N-04-send-threadsafe-bypasses-strict.md` | `send_threadsafe()` bypasses `strict` mode and `event_schemas` | Medium |
| `N-08-error-done-namespace-invisible.md` | User events named `error.*` / `done.*` are invisible to `"*"` and exempt from `onUnhandled: "error"` | Medium |
