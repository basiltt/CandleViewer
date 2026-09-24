# `post-cec108b/` — round-6 upstream drafts

**Nothing here has been posted.** No GitHub writes were made in this round. These are
drafts for review before anyone touches the tracker.

| Path | Contents |
|---|---|
| `comments/` | 26 files, one per verified issue. 24 comment+close, `122.md` comment+reopen (narrow), `157.md` comment+reopen on **narrower grounds** (our original claim was partly wrong and the draft says so), `144.md` comment only — a ride-along recording that the fix is sync-only. |
| `new/` | 10 new-issue drafts: 2 Blocker (R6-01, R6-03), 2 High (R6-02, R6-06), 6 Medium (R6-10…R6-15). |
| `meta-26.md` | Refresh comment for the adoption meta-issue: scorecard, the engine-parity pattern, the pre-tag checklist. |
| `manifest.json` | Machine-readable index, counts, labels, and the rationale for what was deliberately **not** filed. |
| `_gen.py`, `_gen_med.py` | Generators, so a regenerate is reproducible rather than hand-edited. |

## What is deliberately not filed as its own issue

The nine Low items (R6-04, R6-07, R6-08, R6-09, R6-16…R6-20) ride along in `meta-26.md`
rather than becoming nine separate issues — several of them are documentation fixes and
two are corrections to findings **we** got wrong. R6-05 is delivered as the narrowed
reopen on #157, because that is where the correction to our original claim belongs.

## House rules observed

- Build identified **by commit** (`cec108b`), never by `__version__` (still `0.8.0`).
- Every claim reproduced in a fresh process against a clean venv before it was written.
- No adopting-project name appears in any postable text.
- Refutation before filing: 6 of 10 Blocker/High candidates were downgraded on our own
  adversarial pass; corrections to our own errors are stated in the drafts themselves.
