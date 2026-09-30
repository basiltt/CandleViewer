"""Boundary wrapper (`docs/plan/24-internal-schemas.md` §14.2 rule 1, ticket
acceptance criterion 4): every exception an adapter implementation raises
that is not already a member of the internal `ExchangeError` taxonomy is
re-raised as `UnknownStateError`, chaining the original as `__cause__`, and
increments `exchange_errors_total{class="UNKNOWN_STATE"}`.

Adapters (`exchange/bybit/`, future exchanges) call `translate_exchange_error`
from their own except-clauses once they have exhausted their retCode
mapping table; this module holds only the *fallback*, generic behaviour —
the Bybit-specific mapping table itself is out of scope for this ticket
(E08-T02).
"""

from __future__ import annotations

from candleviewer.observability.metrics import Counter

from .errors import ExchangeError, OmsErrorCode, UnknownStateError

__all__ = ["exchange_errors_total", "translate_exchange_error"]

exchange_errors_total = Counter(
    "exchange_errors_total",
    "Count of exchange errors by internal taxonomy class.",
    labelnames=("class",),
)


def translate_exchange_error(exc: BaseException) -> ExchangeError:
    """Return `exc` unchanged if it is already a taxonomy member (after
    incrementing its metric); otherwise wrap it as `UnknownStateError` with
    `exc` preserved as `__cause__` (acceptance criterion 4)."""
    if isinstance(exc, ExchangeError):
        exchange_errors_total.labels(**{"class": exc.code.value}).inc()
        return exc
    wrapped = UnknownStateError(f"unmapped exchange error: {exc.__class__.__name__}: {exc}")
    wrapped.__cause__ = exc
    exchange_errors_total.labels(**{"class": OmsErrorCode.UNKNOWN_STATE.value}).inc()
    return wrapped
