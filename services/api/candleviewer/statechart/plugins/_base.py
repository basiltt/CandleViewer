"""Shared plumbing for the E50-T60 plugins: hook containment + pager seam."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, Literal, Protocol

import structlog


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.statechart.plugins")


Severity = Literal["page", "alert"]


class Pager(Protocol):
    """Out-of-band escalation seam (Alertmanager in production, E04).

    Must be synchronous and non-blocking: hooks run inside the interpreter's
    step and may not await."""

    def raise_alert(self, severity: Severity, summary: str, *, machine_kind: str) -> None: ...


class LogPager:
    """Default pager: a structured CRITICAL/ERROR log line that the
    log-based alert rules key on (`cv_page=true`)."""

    def raise_alert(self, severity: Severity, summary: str, *, machine_kind: str) -> None:
        log = logger().critical if severity == "page" else logger().error
        log("statechart_alert", cv_page=severity == "page", summary=summary, kind=machine_kind)


class HookFailureCounter:
    """Counts exceptions swallowed by `contained` hooks (never re-raised)."""

    def __init__(self) -> None:
        self.hook_errors = 0


def contained[**P, R](fn: Callable[P, R | None]) -> Callable[P, R | None]:
    """Decorate a plugin hook so it logs and counts instead of raising
    into the interpreter (ticket Technical notes). The library's
    `_SafePlugin` also contains hooks; this is our own, testable layer."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # observability must never break the machine
            self_obj: Any = args[0] if args else None
            if isinstance(self_obj, HookFailureCounter):
                self_obj.hook_errors += 1
            logger().error(
                "statechart_plugin_hook_failed", hook=fn.__name__, error=type(exc).__name__
            )
            return None

    return wrapper


def event_type(event: Any) -> str:
    return str(getattr(event, "type", "") or "")


def state_ids(states: Any) -> list[str]:
    return sorted(str(getattr(s, "id", s)) for s in (states or ()))
