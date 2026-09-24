"""Fast, decisive oracle for the `start()` non-termination defect.

Instead of waiting for a timeout, we count `_select_transitions` calls and
abort via a sentinel exception once the count exceeds a threshold. A healthy
machine settles in a handful of calls; the defective one is unbounded. This
turns a 6-second timeout oracle into a ~0.05-second one, which is what makes
delta-debugging tractable.

Monkey-patching happens in OUR process on a method we do not modify on disk.
"""

from __future__ import annotations

import logging
import warnings

warnings.simplefilter("ignore")
logging.disable(logging.CRITICAL)

import xstate_statemachine.base_interpreter as _B
from xstate_statemachine import SyncInterpreter, create_machine


class Spin(Exception):
    """Raised once the select-transition budget is blown."""


_ORIG = _B.BaseInterpreter._select_transitions
_STATE = {"n": 0, "limit": 20000}


def _patched(self, ev):
    _STATE["n"] += 1
    if _STATE["n"] > _STATE["limit"]:
        raise Spin(f"{_STATE['n']} _select_transitions calls")
    return _ORIG(self, ev)


_B.BaseInterpreter._select_transitions = _patched


def spins(cfg, logic, limit: int = 20000):
    """True when start() blows the select budget (i.e. does not settle)."""
    _STATE["n"] = 0
    _STATE["limit"] = limit
    try:
        m = create_machine(cfg, logic=logic)
    except Exception:
        return False
    try:
        i = SyncInterpreter(m)
        i.start()
    except Spin:
        return True
    except Exception:
        return False
    return False


def selects(cfg, logic, limit: int = 20000):
    """Number of select calls start() needed, or None if it blew the budget."""
    _STATE["n"] = 0
    _STATE["limit"] = limit
    try:
        m = create_machine(cfg, logic=logic)
        i = SyncInterpreter(m)
        i.start()
    except Spin:
        return None
    return _STATE["n"]
