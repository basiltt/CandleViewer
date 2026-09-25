"""Board automation guards for CandleViewer (E01-T07).

Pure-function `evaluate()` guards live here; GitHub side effects (reopen,
comment, label) are in `scripts/gh/gh_adapter.py`. This split keeps the
acceptance-criteria matrix testable without a GitHub API.
"""
