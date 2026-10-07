"""Fault vocabulary for the E08-Q03 fault-injecting harness.

A `Fault` is armed with `StubExchange.inject(fault)` and fires at the transport
seam (the stub socket / stub REST transport) - never by patching ingestion
internals - so the same catalogue can drive a future second adapter and the
E08-X02 hostile corpus (`replay(iter_hostile_frames())`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FaultKind(StrEnum):
    # ---- WS (public stream) ------------------------------------------------
    RESET = "reset"  # TCP reset: the next recv raises ConnectionResetError
    STALL = "stall"  # socket stays open, delivers nothing (until closed)
    DROP = "drop"  # the next `count` frames on `topic` are lost
    DUPLICATE = "duplicate"  # the next `count` frames on `topic` are delivered twice
    REORDER = "reorder"  # the next two frames on `topic` swap places
    REFUSE = "refuse"  # the next `count` connection attempts fail (OSError)
    BOMB = "bomb"  # one frame larger than the frame cap (decompressed-size bomb)
    DELIST = "delist"  # `symbol` stops trading: no more frames, catalogue says Closed
    # ---- REST -----------------------------------------------------------------
    HTTP_STATUS = "http_status"  # the next `count` REST calls return `status` (JSON {})
    HTML_502 = "html_502"  # the next `count` REST calls return a 502 HTML error page
    MALFORMED_JSON = "malformed_json"  # the next `count` REST calls return HTTP 200 + junk
    HOSTILE_JSON = "hostile_json"  # retCode 0 with an attacker-shaped row (SR-040b)
    RATE_LIMIT = "rate_limit"  # the next `count` REST calls return 10018 + reset headers
    # ---- host ---------------------------------------------------------------
    CLOCK_JUMP = "clock_jump"  # the host wall clock jumps by `seconds` (WSL sleep)
    VENUE_CLOCK_JUMP = "venue_clock_jump"  # venue time moves `seconds`; the host clock does not
    REJECT_SIGNED = "reject_signed"  # the next `count` signed calls get 10002 whatever the clock


WS_FAULTS = frozenset(
    {
        FaultKind.RESET,
        FaultKind.STALL,
        FaultKind.DROP,
        FaultKind.DUPLICATE,
        FaultKind.REORDER,
        FaultKind.REFUSE,
        FaultKind.BOMB,
        FaultKind.DELIST,
    }
)


@dataclass(frozen=True, slots=True)
class Fault:
    kind: FaultKind
    topic: str | None = None
    symbol: str | None = None
    count: int = 1
    status: int = 503
    seconds: float = 0.0
    reset_in_s: float = 0.0  # RATE_LIMIT: X-Bapi-Limit-Reset-Timestamp = now + this
    path: str | None = None  # REST faults: only this path (None = any)

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError("fault count must be >= 1")
