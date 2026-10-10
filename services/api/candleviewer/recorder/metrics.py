"""Recorder policy metrics (E16-T02), via the observability facade."""

from __future__ import annotations

from candleviewer.observability.metrics import Counter

recorder_cap_refused_total = Counter(
    "recorder_cap_refused_total",
    "Recording starts refused by CV_RECORDER_MAX_SYMBOLS (queued, retried each tick).",
    ["reason"],
)
recorder_cap_preempted_total = Counter(
    "recorder_cap_preempted_total",
    "Chart-only recordings stopped to make room for an open position.",
)
recorder_b11_error_total = Counter(
    "recorder_b11_error_total",
    "B11 recording machines that entered `error` (retried with backoff).",
    ["env"],
)
