"""Domain models for the exchange.bybit module (M4).

Pydantic v2 response models for Bybit payloads. All parsing of raw Bybit JSON lives here
(C-2.2/C-2.3); other modules consume the normalised values these models expose.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from candleviewer.exchange.base.errors import UnknownStateError


class ServerTime(BaseModel):
    """`result` of `GET /v5/market/time`.

    Bybit v5 returns `timeSecond` and `timeNano` as decimal strings. `time` (epoch ms) is
    accepted as a last-resort source for older API surfaces and recorded fixtures.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeSecond: str | None = None
    timeNano: str | None = None
    time: str | int | None = None

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
            parsed.time_us  # noqa: B018 - surfaces non-numeric strings as ValueError here
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise UnknownStateError(
                f"malformed /v5/market/time response: {type(exc).__name__}"
            ) from exc
        return parsed
