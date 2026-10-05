"""Domain errors for the alerts module (M22)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

#: `cv_alert_compile_rejected_total{reason}` label values (bounded set).
RejectReason = Literal[
    "action_node", "unknown_metric", "bad_trigger", "bad_template", "schema", "too_large"
]


class AlertsError(Exception):
    """Base exception for the M22 `alerts` module."""


@dataclass(frozen=True, slots=True)
class AlertIssue:
    """One plain-language problem, anchored to an IR node so the editor can jump to it."""

    field: str
    rule: str
    message: str
    node_id: str | None = None
    suggestions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"field": self.field, "rule": self.rule, "message": self.message}
        if self.node_id is not None:
            out["node_id"] = self.node_id
        if self.suggestions:
            out["suggestions"] = list(self.suggestions)
        return out


class AlertIrInvalid(AlertsError):
    """The alert condition (or its template) was refused; maps to HTTP 422."""

    def __init__(self, reason: RejectReason, issues: list[AlertIssue]) -> None:
        super().__init__(f"{len(issues)} problem(s) in the alert ({reason})")
        self.reason: RejectReason = reason
        self.issues = issues
