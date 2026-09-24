# New issue drafts — `xstate-statemachine` @ `main` commit `5327ba6` (pre-0.8.1)

**Nothing in this directory has been filed.** These are drafts only, written in
the same front-matter format as `../new-0.8.0/`, each with a runnable repro in
`repro/`.

**Build:** `basiltt/xstate-statemachine`, branch `main`, commit
`5327ba69fb735cfe24c7b3772050dac0a71a7b3d`. CHANGELOG `[Unreleased] — targeting
0.8.1`; `__version__` still reports `0.8.0` — **identify this build by commit,
never by version string.**

**Environment for every repro:** CPython 3.13.7, Windows 11 Pro 10.0.26200,
run with
`_ref/xstate-statemachine/.venv-main/Scripts/python` and
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

| Draft | Severity | Related | One-line |
|---|---|---|---|
| `M-1-deferred-event-receipt-false-negative.md` | **High** | #28, #39/#75 | A deferred event's `wait=True` receipt resolves `changed=False, error=None` — a confident false negative |
| `F-1-sync-tripped-flag-starves-later-events.md` | **High** | #77 | The overflow `tripped` flag is scoped to the drain, not the chain; one runaway starves every later unrelated event in the batch |
| `F-2-kwargs-clock-receives-unexpected-sync.md` | **High** | #76, #50 | The compatibility shim treats a `**kwargs` clock as consent and hands it `sync=` |
| `M-2-async-action-self-send-unbounded.md` | Medium | #77 | `max_iterations` does not bound an action-side `send()` on the async engine; the parity claim covers `raise` only |
| `M-3-alias-ambiguity-guard-misses-documented-example.md` | Medium | alias feature | The ambiguity guard does not fire for the CHANGELOG's own example; the config side is undefended |
| `M-4-resolve-aliases-mutates-caller-registry.md` | Medium | alias feature | `create_machine()` mutates the caller's `MachineLogic`, self-suppressing the guard and retroactively rebinding |
| `F-5-logic-modules-setdefault-order-dependent.md` | Medium | alias feature | `logic_modules` resolves duplicates by iteration order; the documented rejection never reaches this path |
| `F-6-done-invoke-dropped-after-trip.md` | Medium | #77 | A `done.invoke` from a sync service is dropped after a trip; the machine parks permanently |

**Rides along on existing issues instead of a new filing** (drafted in
`../comments-main-5327ba6/`): F-7 → #27 · M-5 / F-8 → #79 · M-6 → #78 ·
F-9 → #77 · F-10 → #31.

**Full context:** `../../22-verify-main-verdict.md` §2.

---

## Re-test on `main@3c527b0` (2026-09-18, after PR #83)

All 8 drafts in this directory were re-tested against `main@3c527b0` (merge of
PR #83 — `ErrorEvent` #80, provenance system events #79, one task per invoked
child #43). **All 8 are STILL-PRESENT**; front-matter now carries
`status: still-present`, `retested_on:` and `library_version: main@3c527b0`,
and each has a **Re-test on `main@3c527b0`** section with refreshed Observed
output. No draft became obsolete; none was deleted.

Of the 13 findings in the `5327ba6` register, the only one that moved is **M-5**
(a ride-along on #79, never a draft here): its premise was removed by #79 and its
residual is re-expressed in `../../23-verify-3c527b0-findings.md` §3. The
`../comments-main-5327ba6/79.md` draft comment is marked **SUPERSEDED** and must
be rewritten before posting.

**M-1 caveat:** the `deferred_count` mitigation proposed in
`22-verify-main-verdict.md` is **not sound as specified** — at the caller's
`await` point it reads `0` for both the deferred and the true-negative case.
See `23-verify-3c527b0-findings.md` §2.3 item 4.

Still nothing filed.
