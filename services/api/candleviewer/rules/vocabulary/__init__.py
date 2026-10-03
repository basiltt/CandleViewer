"""Rule vocabulary: projection of the MetricRegistry + IR enums (E35-T03)."""

from __future__ import annotations

from candleviewer.rules.vocabulary.build import (
    VocabularyUnavailableError,
    build_vocabulary,
    etag_for,
    undescribed_metrics,
)
from candleviewer.rules.vocabulary.metrics import default_registry
from candleviewer.rules.vocabulary.registry import MetricDescriptor, MetricRegistry

__all__ = [
    "MetricDescriptor", "MetricRegistry", "VocabularyUnavailableError", "build_vocabulary",
    "default_registry", "etag_for", "undescribed_metrics",
]  # fmt: skip
