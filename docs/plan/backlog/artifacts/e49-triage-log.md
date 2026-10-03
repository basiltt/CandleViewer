# E49 triage log

One dated section per weekly ritual (see e49-triage-ritual.md).

## Debt sweep applied 2026-10-04 (E49-T01 AC4)

> The Grade column below is the grade at first-sweep time; rows shown UNSET were graded afterwards (see
> "Severity grading completed"). Verified live 2026-10-04: all 21 open type/bug issues carry a priority/*
> label, none carry needs-severity; each marker comment names @basiltt as owner.

Run: `python -m tools.triage.run sweep` (idempotent; adds labels + one marker comment per bug only).

| Issue | Grade | SLA due | Labels added |
|---|---|---|---|
| #1737 | UNSET | n/a | needs-dor,needs-severity,needs-area |
| #1652 | UNSET | n/a | needs-dor,needs-severity |
| #1646 | UNSET | n/a | needs-dor,needs-severity,needs-area |
| #1636 | UNSET | n/a | needs-dor,needs-severity |
| #1586 | UNSET | n/a | needs-dor,needs-severity |
| #1564 | P1 | 2026-09-29T17:00+01:00 | needs-dor |
| #1547 | UNSET | n/a | needs-dor,needs-severity |
| #1538 | P1 | 2026-09-29T15:25+01:00 | needs-dor |
| #1536 | P2 | 2026-10-01T15:24+01:00 | needs-dor |
| #1535 | P2 | 2026-10-01T15:23+01:00 | needs-dor |
| #1468 | UNSET | n/a | needs-dor,needs-severity,needs-area |
| #1462 | UNSET | n/a | needs-dor,needs-severity,needs-area |
| #1443 | P2 | 2026-09-30T17:00+01:00 | needs-dor,needs-area |
| #1442 | P2 | 2026-09-30T17:00+01:00 | needs-dor |
| #1386 | P2 | 2026-09-28T17:00+01:00 | needs-dor |
| #1385 | P2 | 2026-09-28T17:00+01:00 | needs-dor |
| #1384 | P2 | 2026-09-28T17:00+01:00 | needs-dor |
| #1363 | P2 | 2026-09-28T17:00+01:00 | needs-dor |
| #1339 | P2 | 2026-09-28T17:00+01:00 | needs-dor |
| #1338 | P1 | 2026-09-24T17:00+01:00 | needs-dor |
| #1337 | P0 | 2026-09-24T11:00+01:00 | needs-dor |

Sweep: graded 21 open bug(s); 21 fail DoR

## Severity grading completed (review fix)
The 8 bugs previously UNSET were graded and `needs-severity` removed: #1737, #1586 -> priority/p1-high
(security/supply-chain); #1652, #1646, #1636, #1547 -> priority/p2-medium; #1468, #1462 -> priority/p3
(docs/evidence). All open type/bug issues now carry a priority label.

## Required-check exception
`regression-guard` stays non-required: C-9.1 owns the required list, so promotion needs a C-16
amendment (raised on #1340). Owner-approved exception requested on the issue.

## Grading result (review fix 2)
21/21 open bugs graded (see table above), 0 defaulted,
none carry `needs-severity`. The sweep now defaults an ungradable bug to P1 (conservative) and keeps
`needs-dor` naming the missing Severity field, instead of leaving it UNSET.

## Evidence pointers (review fix 3)
Scratch-board e2e: `python -m tools.triage.scratch_e2e` ran against scratch issue #1764 (not the live board).
Projects v2 GraphQL: offline contract tests in tests/triage/test_triage.py; no docker/live board needed.
AC3 exception: requested from @basiltt on #1340 (C-9.1 owns the required list; C-16 amendment needed).
