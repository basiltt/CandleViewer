# Postable artefacts — `xstate-statemachine` @ `main` commit `3c527b0`

**Nothing in this directory has been posted.** These are the finalised bodies
for the Post phase, which is the only phase authorised to write to GitHub.

**Build:** `main` @ `3c527b0d04c0d2d0ebb565af7e9e905f7178f620` (merge of PR #83,
unreleased 0.8.1). `__version__` still reports `0.8.0` — **identify this build
by commit, never by version string.**

**Environment for every repro:** CPython 3.13.7, Windows 11 Pro 10.0.26200,
run with the project's `.venv-main` interpreter and
`PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.

## Contents

| Path | What it is |
|---|---|
| `<GH#>.md` × 16 | One verification comment per pre-#82/#83 issue: #27 #31 #37 #39 #43 #44 #50 #51 #52 #60 #75 #76 #77 #78 #79 #80. Each opens "Verified on main @ 3c527b0 (pre-0.8.1)", carries a criteria ✓/✗ table, and states an explicit disposition. |
| `<1..16>.md` | The 16 new-issue bodies, front-matter format, ready to file. |
| `meta-26.md` | Full replacement body for meta issue #26. |
| `manifest.json` | The posting plan: which comment goes where, which issues are reopened, which new issues are filed with which labels. |
| `repro/` | Every referenced repro script, runnable standalone. |

## Posting rules the Post phase must follow

1. **Labels only from:** `bug`, `enhancement`, `documentation`, `performance`,
   `severity/*`, `area/*`. **No `candleviewer` label**, on anything.
2. **Never name the adopting project.** Say "the adopting project" or
   "our adoption audit (#26)". All bodies here already comply — verified by
   a scan for the project name, `CV-C*` constraint ids and commit `5327ba6`.
3. **`comment+reopen`** in `manifest.json` means: post the comment, then reopen
   the issue if the maintainer has closed it. Three issues carry it: **#31**,
   **#77**, **#79**. Reopen is justified only where an acceptance criterion is
   unmet **by code** — not by wording, naming, test-file paths or architectural
   framing.
4. **`meta-26.md` replaces the issue body**; it is not a comment.

## Verdict

`../../26-verify-3c527b0-verdict.md` — per-issue dispositions, the consolidated
24-finding set, the single regression, the gate decision (DEFER, row 5), the
constraint delta, and the release-readiness note this material is drawn from.
