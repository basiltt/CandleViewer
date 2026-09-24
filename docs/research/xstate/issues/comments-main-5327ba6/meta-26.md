# Draft update for meta issue #26 — NOT POSTED

Replacement text for the status block at the head of
*"Meta: CandleViewer adoption readiness — tracking issue for 34 filed defects"*.
Everything below is a drop-in replacement for the current `0.8.0` status block;
the rest of the meta issue body (purpose, families, contribution plan) is
unchanged.

---

## Status on `main` @ `5327ba6` (re-verified 2026-09-18, pre-0.8.1)

> **Identify this build by commit, not by version string.** `__version__` still
> reports `0.8.0` on this commit while `CHANGELOG.md` targets `0.8.1`.

**25 FIXED-DEFAULT · 5 FIXED-OPT-IN · 3 PARTIAL · 1 NOT-FIXED.**
All four filed Blockers remain closed — two of them (LC-01, LC-03) only by an
opt-in policy, so they count as closed for us only while our own linter mandates
that policy.

```
Gate run 2026-09-18 - xstate-statemachine main @ 5327ba6 (pre-0.8.1)
DECISION: ADOPT WITH CONSTRAINTS, CONDITIONAL
  verify (mandated config, blocking) : 32/34 pass  - FAILs: #43, #60/LC-52
  repro  (defaults, informational)   : 13/34 pass
  probes                             : 43/51-equivalent, identical baseline
  suite                              : 3234 passed, 13 skipped, 0 failed (was 3170)
  coverage                           : 90% (was 87% at 0.7.0)
  benches                            : BENCH-1 armed 2.43x (bar >=3.0x);
                                       BENCH-2, BENCH-6 still missed
  regressions                        : NONE
  new defects                        : 13 (3 High, 6 Medium, 3 Low, 0 Blocker)
```

**No regressions.** Every status delta against the 0.8.0 register moved in the
fixing direction. No test function was deleted and no skip/xfail was added
across the whole `v0.8.0..5327ba6` diff. The public API is additive only
(`SYSTEM_EVENT_PREFIXES`, `has_dormant_invocations`, `MachineLogic(strict=)`,
`Clock.set_timeout(sync=)`) and the snapshot format is unchanged.

### Per-issue dispositions on this commit

**Close (9):** `#27` (LC-01) · `#37` (LC-43) · `#39` (LC-42/N-1) · `#44` (LC-19) ·
`#50` (LC-38/N-2) · `#51` (LC-34/N-4) · `#52` (LC-37) · `#75` (N-1) · `#76` (N-2) ·
`#78` (N-4)

**Keep open (6):**

| GH# | Why it stays open |
|---|---|
| `#31` | Engine parity under the documented `strict_targets=False` opt-out is still unmet — `SyncInterpreter` raises `StateNotFoundError`, async `Interpreter` silently no-ops. Everything else in the issue is confirmed working. Suggest re-scoping to that one criterion. |
| `#43` | The poll→`wait_done()` half shipped and holds (`onDone` 0.58 ms, zero idle wakeups); the "collapse the second task" half did not — still a flat **2.0** asyncio tasks per invoked/spawned child at n=2/10/50. Suggest re-scoping so it does not read as a full regression next time. |
| `#60` | The shared-algorithm half landed; the `ErrorEvent` sub-claim did not. Consider closing and letting `#80` carry the remainder. |
| `#77` | The data-loss defect is genuinely fixed (1501/5000-event batches fully processed, 3000 independent one-deep raises all delivered, byte-identical sync/async traces). Overflow is still **silent** — the criteria asked for a raise. Three new defects in the same code path, filed separately. |
| `#79` | Documentation + a build-time `UserWarning` for reserved `on` keys shipped; the runtime silent-drop is unchanged and explicitly deferred to 0.9 ("provenance-tagged system events"). Suggest retagging for 0.9. |
| `#80` | `ErrorEvent` has not shipped; acceptance criteria apply verbatim. Correctly and visibly deferred. |

### New issues we intend to file against this commit (8, drafts only)

| Severity | Title |
|---|---|
| **High** | `send(wait=True)` resolves with `changed=False, error=None` for an event held by `onUnhandled: "defer"` |
| **High** | The sync `maxIterations` `tripped` flag is scoped to the drain, not the chain — one runaway starves later unrelated events in the same batch (#77) |
| **High** | The `sync=` compatibility shim treats a `**kwargs` clock as consent and feeds it an unexpected kwarg (#76) |
| Medium | `max_iterations` does not bound an action-side `send()` on the async engine; the #77 parity claim covers the `raise` built-in only |
| Medium | The alias-ambiguity guard does not fire for its own documented example |
| Medium | `resolve_aliases` mutates the caller's `MachineLogic` registry across `create_machine()` calls |
| Medium | The `logic_modules` normalised index uses `setdefault`, so duplicate snake/camel implementations resolve by iteration order |
| Medium | A `done.invoke` from a sync service is classed as self-generated; after a trip the completion is dropped and the machine parks (#77) |

### Before tagging 0.8.1 — what we would check

1. **`__version__` still reports `0.8.0`** on this commit. Bump it; consider a
   test tying it to the newest released CHANGELOG heading.
2. Fix at least the High item in `#77`'s own code path (sticky `tripped` flag)
   before shipping the fix it belongs to.
3. `#76`'s legacy-clock signature inspection should require `sync` by name, not
   accept a `**kwargs` catch-all.
4. Make `resolve_aliases` resolve into a per-machine copy rather than mutating
   the caller's registry.
5. Pin a `--cov-fail-under` floor now that coverage is at 90%.
6. Qualify the rollback claim: "≈0.98× of the default" holds only for
   transitions that run **no actions**; with actions it is 0.878×, and on a busy
   50 000-event burst armed rollback is 0.854×.
7. State the deliberate deferrals in the release notes (`#80`, `#79`'s runtime
   half, `#43`'s task-collapse half) so they are not read as omissions.

### Our remaining gap is ours, not yours

Nothing upstream blocks CandleViewer adoption on a non-order path. The
outstanding condition is our own machine-definition linter (`E29-T10`,
CV-LINT-XS1…XS12) and `tests/xstate_contract/` — required because the two
Blockers closed by opt-in policy are closed only for a caller that sets the
option, and an unenforced rule is not a mitigation for a silent failure. The
order path additionally waits on the deferred-receipt finding above, which is
the one new defect whose trigger is our *mandated* configuration rather than a
misuse of it.

Full write-up: `docs/research/xstate/22-verify-main-verdict.md`.
