"""Domain errors for the rules module (M15)."""

from __future__ import annotations


class RulesError(Exception):
    """Base exception for the M15 `rules` module."""


class FormUnrepresentableError(RulesError, ValueError):
    """The form editor cannot express this rule (E35-Q02: a lossy hop fails loudly).

    Subclasses ``ValueError`` so existing callers of ``to_form_model`` keep working.
    """

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("rule is not form-compatible: " + "; ".join(reasons))


class ScopeForbiddenError(RulesError):
    """403: absent and not-granted accounts are indistinguishable (no existence leak)."""

    message = "Forbidden"
