# E07-Q02 deviation / waiver request

AC1 (90-minute sessions on a scratch compose stack) and AC5 (full epic exploratory pass) could not be met by the
authoring agent: no docker, no human timebox, and E07-D01/D02 are not in the repo. Sessions were ~20-minute
scripted probes on in-memory ports; the probes are committed as tests (test_exploratory_promoted.py).

Requested: owner approval of this deviation, with these follow-ups kept open on E07-Q02:
1. Re-run charters 1-3 against the real QuestDB/Parquet stack (concurrent drop, mid-scan boundary, hot_retention change, two racing reapers, pin removal, journal trade, manual compaction).
2. Run charter 4 once E07-D01/D02 exist.
Findings: BUG-A #1696 (P2), BUG-B #1698 (P3), BUG-C #1697 (P2, audit integrity, copied to E07-X02/Security), BUG-D #1699 (P3). No P0 (no pinned-data deletion path found); no P0/P1 outstanding.

## Unexercised per charter (AC5 / DoD)
- Charter 1: concurrent drop, mid-scan boundary move, `hot_retention` change on a live stack (in-memory ports only).
- Charter 2: two-symbol interleaved replay; re-ingest of rows older than the retention horizon (needs QuestDB).
- Charter 3: two racing reapers on the real engine, pin removal mid-run, journal trade, manual compaction.
- Charter 4: operator model beyond the event surface; blocked on E07-D01/D02.

## Sign-off status
No P0/P1 are open, but BUG-A #1696 and BUG-C #1697 (P2) remain open against E07-T05, so no QA sign-off
contribution to E07-T05 is recorded. It stays pending until those are fixed or accepted by the owner.
BUG-C was copied to E07-X02 (#276) and Security.
