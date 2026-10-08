"""CVWB encode metrics (E17-T02 follow-up, docs/plan/20-architecture.md section 12.1).

Module-level series (the encoder is a pure function with no facade); `export_cvwb_metrics()`
serves them on the scraped registry. ``body_kind`` is the bounded 1-6 enum of section 3.4, so
children are pre-bound once and the encoder does two dict-free increments per frame.
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import CollectorRegistry, Counter, ReexportCollector
from candleviewer.ws._generated.cvwb_layout import KINDS

cvwb_frames_encoded_total = Counter(
    "cvwb_frames_encoded_total", "CVWB frames encoded.", labelnames=("body_kind",)
)
cvwb_bytes_encoded_total = Counter(
    "cvwb_bytes_encoded_total", "CVWB bytes encoded (header + body).", labelnames=("body_kind",)
)

EXPORTED_NAMES: Final[frozenset[str]] = frozenset(
    {"cvwb_frames_encoded_total", "cvwb_bytes_encoded_total"}
)

#: body_kind -> (frames child, bytes child); fixed at import, never grows.
ENCODED: Final = {
    k: (
        cvwb_frames_encoded_total.labels(body_kind=str(k)),
        cvwb_bytes_encoded_total.labels(body_kind=str(k)),
    )
    for k in KINDS
}


def export_cvwb_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the CVWB encode series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})
