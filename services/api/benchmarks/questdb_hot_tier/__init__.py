"""Perf regression harness for the QuestDB hot tier (E07-T03).

Re-runs shapes A-F from the `E07-K01` spike (`spikes/storage/bench.py`,
`docs/plan/spikes/S2-hot-tier.md`) against a *real* QuestDB instance and
compares the result to the committed `baseline.json` (a copy of the spike's
`results.json`, see `README.md` for provenance).

Per the ticket's Definition of Done: "Perf regression harness committed with
baseline numbers recorded (not yet gating, per R0 quality gates)" — this
package is a regression *reporter*, not a CI gate. `compare.py` always exits
0; it prints a table and flags shapes outside tolerance for a human to read.
"""
