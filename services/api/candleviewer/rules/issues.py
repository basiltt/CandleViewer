"""Validation / compile issue model shared by the compiler and validator (E35-T04).

Every issue carries a stable machine ``code`` (editors key inline messages and jump-to-node off it,
never the prose) and a human message that names the row/node in words.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Severity = Literal["error", "warning"]
IssueClass = Literal["syntax", "semantics", "safety", "performance"]


@dataclass(frozen=True, slots=True)
class Issue:
    path: str
    code: str
    message: str
    severity: Severity = "error"
    klass: IssueClass = "semantics"
    node_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "class": self.klass,
        }
        if self.node_ids:
            out["node_ids"] = list(self.node_ids)
        return out


class RuleCompileError(Exception):
    """Structural compile failure: no IR is produced (maps to 422 ``rule_ir_invalid``)."""

    def __init__(self, issues: list[Issue]) -> None:
        first = issues[0].message if issues else "invalid rule model"
        super().__init__(f"{len(issues)} error(s) compiling the rule model: {first}")
        self.issues = issues
