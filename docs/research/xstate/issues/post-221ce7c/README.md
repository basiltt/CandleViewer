# `post-221ce7c/` — round-7 upstream drafts

**Nothing here has been posted.** No GitHub writes were made in this round. These
are drafts for review before anyone touches the tracker.

| Path | Contents |
|---|---|
| `comments/` | 12 files, one per verified issue. 7 comment+close (#157, #166, #169, #170, #171, #172, #173); `167.md` / `168.md` comment+reopen narrowly on the coroutine-service path only; `122.md` comment+close-as-designed **withdrawing our own previous reopen**; `174.md` comment only, leaving the issue open as a documented limitation; `175.md` comment+reopen on Case D. |
| `new/` | 12 new-issue drafts: 2 Blocker (R7-01, R7-02), 4 High (R7-03, R7-05, R7-07, R7-08), 6 Medium (R7-06, R7-09, R7-10, R7-11, R7-12, R7-13). |
| `new/repro/` | Standalone, library-only repro scripts for both Blockers. Each exits **1** when the defect is observed and **0** when it is fixed, and each carries its own control run. |
| `meta-26.md` | Refresh comment for the adoption meta-issue: the 12-issue table, post-refutation counts, the one-sentence pattern of the round, the two asks, and the pre-tag checklist. |
| `manifest.json` | Machine-readable index, counts, and the rationale for what was deliberately **not** filed. |

## Verified repro output (fresh process, `221ce7c`)

```
R7-01_async_service_lane_uncharged.py                      -> exit 1
  def       : service calls=23      status=running  last_error=RunawayChainError
  async def : service calls=28108   status=running  last_error=None

R7-02_external_priority_charged_to_chain_budget.py         -> exit 1
  priority=True  : sent=1500 processed=749 dropped=751 reasons=['chain_budget']
  priority=False : sent=1500 processed=883 dropped=0   reasons={}
```

## What is deliberately not filed as its own issue

The eight Low items (the R7-04 residual, R7-14…R7-20) ride along in `meta-26.md`
rather than becoming eight separate issues — several are documentation or export
fixes, and **the R7-04 entry is a correction to a finding we got wrong**: our
budget-renewal causal claim was refuted by our own follow-up evidence (a budget
sweep, our own control burning 4.5× the laps with zero starvation, and a cause
isolation showing the discriminating variable is `def` vs `async def`). Only a
narrower, already-documented residual survives. We would rather record that in
full than quietly drop it.

The five DESIGN-CONSTRAINT items (DC-1…DC-5) are wrapper obligations on our side,
not library defects, and are not filed. Likewise our own catalogue defects —
including two that are Blockers on any runtime — are ours, not the library's.

## House rules observed

- Build identified **by commit** (`221ce7c`), never by `__version__` (still `0.8.0`).
- Every claim reproduced in a fresh process against a clean venv before it was written.
- No adopting-project name appears in any postable text.
- Refutation before filing: three of eight Blocker/High candidates were moved
  **down** by our own adversarial pass and one was refuted outright. None moved up.
