"""Shared scaffolding for the battle-test FUZZ track against
xstate-statemachine @ main = 5e07ba8 (unreleased 0.8.1).

Nothing here modifies library source. Everything is import-only.

Conventions
-----------
* ``ALLOWED_BUILD_ERRORS``   -- the typed errors ``create_machine`` is
  permitted to raise. Anything else is a defect.
* ``ALLOWED_SEND_ERRORS``    -- the typed errors a ``send`` path may raise.
* ``ALLOWED_RESTORE_ERRORS`` -- the typed errors ``from_snapshot`` may raise.
* ``Defect``                 -- one recorded failure, JSON-serialisable.
* ``Recorder``               -- dedupes defects by (kind, signature) and
  keeps the SMALLEST repro seen for each, measured by ``size_hint``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Tuple

# 🔇 The library logs heavily at INFO/WARNING; a 20k-case run is unreadable
#    otherwise. Disabling does NOT change behaviour under test.
logging.disable(logging.CRITICAL)

from xstate_statemachine import (  # noqa: E402
    ActorSpawningError,
    ImplementationMissingError,
    InterpreterStoppedError,
    InvalidConfigError,
    InvalidEventPayloadError,
    NotSupportedError,
    QueueOverflowError,
    RestoredError,
    RunawayChainError,
    SnapshotDriftError,
    SnapshotVersionError,
    StateNotFoundError,
    TransitionFailedError,
    UnhandledEventError,
    UnknownEventError,
    WrongThreadError,
    XStateMachineError,
)
# 🔄 3ed3099: new typed error classes introduced by round-4 (#110,#113,#102,
#    #131,#108). Added to the oracle sets so the harness scores the CURRENT
#    contract, not 5e07ba8's.
from xstate_statemachine import (  # noqa: E402
    InvalidEventError,
    RootTargetError,
    SnapshotCorruptError,
    SnapshotMidStepError,
    SnapshotSerializationError,
)

# -----------------------------------------------------------------------------
# 🎯 Oracles: which exception types are CONTRACTUAL at each boundary
# -----------------------------------------------------------------------------
# create_machine's documented Raises: InvalidConfigError,
# ImplementationMissingError. StateNotFoundError is added because #29/#30
# build-time target validation raises it through the same call.
ALLOWED_BUILD_ERRORS: Tuple[type, ...] = (
    InvalidConfigError,
    ImplementationMissingError,
    StateNotFoundError,
    NotSupportedError,
    RootTargetError,
)

ALLOWED_SEND_ERRORS: Tuple[type, ...] = (
    UnknownEventError,
    InvalidEventPayloadError,
    QueueOverflowError,
    InterpreterStoppedError,
    UnhandledEventError,
    TransitionFailedError,
    WrongThreadError,
    StateNotFoundError,
    RunawayChainError,
    InvalidEventError,
    SnapshotMidStepError,
    SnapshotSerializationError,
)

ALLOWED_RESTORE_ERRORS: Tuple[type, ...] = (
    InvalidConfigError,
    SnapshotVersionError,
    SnapshotDriftError,
    StateNotFoundError,
    RestoredError,
    NotSupportedError,
    ImplementationMissingError,
    SnapshotCorruptError,
)


def exc_sig(exc: BaseException) -> str:
    """A stable, value-free signature for an exception.

    The message often embeds generated state names; those would defeat
    dedupe. We keep the type plus the deepest library frame.
    """
    tb = exc.__traceback__
    site = "?"
    while tb is not None:
        fn = tb.tb_frame.f_code.co_filename
        if "xstate_statemachine" in fn.replace("\\", "/"):
            site = f"{os.path.basename(fn)}:{tb.tb_lineno}"
        tb = tb.tb_next
    return f"{type(exc).__name__}@{site}"


def lib_frame(exc: BaseException) -> str:
    """Deepest library frame as ``file:line  <source>`` for root-cause cites."""
    tb = exc.__traceback__
    best = None
    while tb is not None:
        fn = tb.tb_frame.f_code.co_filename
        if "xstate_statemachine" in fn.replace("\\", "/"):
            best = (fn, tb.tb_lineno, tb.tb_frame.f_code.co_name)
        tb = tb.tb_next
    if best is None:
        return "(no library frame)"
    fn, line, name = best
    rel = "src/xstate_statemachine/" + os.path.basename(fn)
    return f"{rel}:{line} ({name})"


# -----------------------------------------------------------------------------
# 📋 Defect recording, with minimal-case retention
# -----------------------------------------------------------------------------
@dataclass
class Defect:
    kind: str  # short slug, e.g. "build-wrong-exception"
    signature: str  # dedupe key detail
    detail: str  # human-readable one-liner
    repro: Any  # the minimal input that triggers it (JSON-able)
    frame: str = ""
    tb: str = ""
    size: int = 1 << 30
    hits: int = 0


class Recorder:
    """Collects defects, keeping the smallest repro per (kind, signature)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._by_key: Dict[Tuple[str, str], Defect] = {}
        self.cases = 0
        self.counters: Dict[str, int] = {}

    def bump(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n

    def record(
        self,
        kind: str,
        signature: str,
        detail: str,
        repro: Any,
        size: int,
        exc: Optional[BaseException] = None,
    ) -> None:
        key = (kind, signature)
        prev = self._by_key.get(key)
        if prev is None:
            prev = Defect(
                kind=kind, signature=signature, detail=detail, repro=repro
            )
            self._by_key[key] = prev
        prev.hits += 1
        if size < prev.size:
            prev.size = size
            prev.repro = repro
            prev.detail = detail
            if exc is not None:
                prev.frame = lib_frame(exc)
                prev.tb = "".join(
                    traceback.format_exception(
                        type(exc), exc, exc.__traceback__
                    )
                )[-1500:]

    @property
    def defects(self) -> List[Defect]:
        return sorted(
            self._by_key.values(), key=lambda d: (-d.hits, d.kind, d.signature)
        )

    def dump(self, path: str) -> Dict[str, Any]:
        payload = {
            "fuzzer": self.name,
            "cases": self.cases,
            "counters": self.counters,
            "defect_classes": len(self._by_key),
            "defects": [asdict(d) for d in self.defects],
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        return payload

    def report(self) -> None:
        print(f"\n=== {self.name}: {self.cases} cases ===")
        for k in sorted(self.counters):
            print(f"  {k:<44} {self.counters[k]}")
        if not self._by_key:
            print("  NO DEFECTS")
            return
        print(f"  DEFECT CLASSES: {len(self._by_key)}")
        for d in self.defects:
            print(f"\n  [{d.kind}] {d.signature}  (hits={d.hits})")
            print(f"    {d.detail}")
            print(f"    frame: {d.frame}")
            print(f"    repro: {json.dumps(d.repro, default=str)[:1400]}")


OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
