"""`RetentionRepository` — the Protocol only; retention *logic* is E07-T05.

Ticket "Out of scope": "Retention *logic* — E07-T05 (this task defines only
the Protocol)." Implementations decide what a "policy" is; this Protocol
only fixes the three-verb shape (`policies` / `plan` / `apply`) every
implementation and the E07-T05 router must expose.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from candleviewer.storage.models import RetentionDecision


@runtime_checkable
class RetentionRepository(Protocol):
    """Roll-off/delete planning and execution across the hot/cold boundary."""

    def policies(self) -> list[Any]:
        """Return the currently configured retention policies (shape owned
        by E07-T05 — this Protocol does not constrain it beyond `list[Any]`
        so this ticket does not have to invent retention policy semantics it
        is explicitly out of scope for)."""
        ...

    async def plan(self, dry_run: bool = True) -> list[RetentionDecision]:
        """Compute what would happen if retention ran now.

        `dry_run=True` (the default) never mutates storage — every decision
        is a preview. `dry_run=False` still only *plans*; use `apply` to
        execute. A decision with `action="skip"` and a non-empty `reason`
        signals a `RetentionPin` or an in-flight export blocking that range.
        """
        ...

    async def apply(self, plan: list[RetentionDecision]) -> None:
        """Execute a previously computed plan. Raises
        `StorageRetentionBlockedByPin` if any non-`skip` decision in `plan`
        now conflicts with a pin that was added after `plan()` returned
        (plans are not re-validated automatically — callers must re-`plan()`
        if a meaningful delay elapsed)."""
        ...
