"""Single home of the E12 REST read caps (E12 STRIDE SR-E12-01/02/03, #398 scope addition).

`docs/security/threat-models/E12-bars.md` proposes these numbers; an assert test pins them so a
change is a reviewed diff, never a drive-by. Routes import from here, never restate a number.
"""

from __future__ import annotations

from typing import Final

#: `BarLimit` (22-api): rows per page.
MAX_LIMIT: Final = 5_000
DEFAULT_LIMIT: Final = 1_000
#: SR-E12-01: a page whose JSON body would exceed this is `422 response_too_large`, not truncated.
RESPONSE_MAX_BYTES: Final = 2 * 1024 * 1024
#: SR-E12-01: every storage read behind a bars/klines request is bounded by this.
QUERY_TIMEOUT_S: Final = 2.0
#: SR-E12-02: window caps. Time bars: <= 400 d; non-time bars: <= 31 d.
MAX_TIME_WINDOW_US: Final = 400 * 86_400 * 1_000_000
MAX_NON_TIME_WINDOW_US: Final = 31 * 86_400 * 1_000_000
MAX_WINDOW_BARS: Final = 250_000
#: SR-E12-03: param floors/ceilings per non-time bar type.
TICK_PARAM_RANGE: Final = (100, 1_000_000)
RANGE_TICKS_RANGE: Final = (2, 100_000)
QTY_PARAM_MAX: Final = 10**12

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MAX_NON_TIME_WINDOW_US",
    "MAX_TIME_WINDOW_US",
    "MAX_WINDOW_BARS",
    "QTY_PARAM_MAX",
    "QUERY_TIMEOUT_S",
    "RANGE_TICKS_RANGE",
    "RESPONSE_MAX_BYTES",
    "TICK_PARAM_RANGE",
]
