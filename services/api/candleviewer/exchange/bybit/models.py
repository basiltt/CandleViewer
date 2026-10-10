"""Domain models for the exchange.bybit module (M4).

Pydantic v2 response models for Bybit payloads. All parsing of raw Bybit JSON lives here
(C-2.2/C-2.3); other modules consume the normalised values these models expose.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from candleviewer.exchange.base.errors import UnknownStateError

_DIGITS_RE = re.compile(r"[0-9]{1,19}")
"""Strict decimal digits only: no sign, whitespace, underscore or non-ASCII digits."""
_MAX_NANO = 2**63
_SECOND_MIN = 1_577_836_800  # 2020-01-01T00:00:00Z
_SECOND_MAX = 4_102_444_800  # 2100-01-01T00:00:00Z


def _digits(value: object) -> str:
    """Accept a digit-only string (or a non-bool int, as a JSON number) as its digit string."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or _DIGITS_RE.fullmatch(value) is None:
        raise ValueError("time field must be 1-19 ASCII digits")
    return value


class ServerTime(BaseModel):
    """`result` of `GET /v5/market/time`.

    Bybit v5 returns `timeSecond` and `timeNano` as decimal strings. `time` (epoch ms) is
    accepted as a last-resort source for older API surfaces and recorded fixtures.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeSecond: str | None = None
    timeNano: str | None = None
    time: str | int | None = None

    @field_validator("timeSecond", "timeNano", "time", mode="before")
    @classmethod
    def _strict_digits(cls, value: object) -> str | None:
        return None if value is None else _digits(value)

    @field_validator("timeNano")
    @classmethod
    def _nano_in_range(cls, value: str | None) -> str | None:
        if value is not None and int(value) >= _MAX_NANO:
            raise ValueError("timeNano out of range")
        return value

    @field_validator("timeSecond")
    @classmethod
    def _second_plausible(cls, value: str | None) -> str | None:
        if value is not None and not _SECOND_MIN <= int(value) <= _SECOND_MAX:
            raise ValueError("timeSecond outside plausible window (2020..2100)")
        return value

    @model_validator(mode="after")
    def _has_a_time_field(self) -> ServerTime:
        if self.timeNano is None and self.timeSecond is None and self.time is None:
            raise ValueError("no usable time field (timeNano/timeSecond/time)")
        return self

    @property
    def time_us(self) -> int:
        """Server epoch time in microseconds, preferring the finest-resolution field."""
        if self.timeNano is not None:
            return int(self.timeNano) // 1_000
        if self.timeSecond is not None:
            return int(self.timeSecond) * 1_000_000
        return int(str(self.time)) * 1_000

    @classmethod
    def from_response(cls, response: dict[str, Any]) -> ServerTime:
        """Validate a full `/v5/market/time` response body; typed error, never `KeyError`."""
        try:
            result = response["result"]
            parsed = cls.model_validate(result)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise UnknownStateError(
                f"malformed /v5/market/time response: {type(exc).__name__}"
            ) from exc
        return parsed
