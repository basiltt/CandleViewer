"""tests/xstate_contract/test_b16.py — B16 `session` golden traces (E09-S03, QA #1634).

Drives the B16 contract (`machines/B16.session.machine.json`) only through
`cv.statechart.factory.build` (C-2.19). Transition names follow
28-statechart-catalogue.md B16.
"""

from __future__ import annotations

import pytest
from xstate_statemachine import Interpreter, SimulatedClock

from candleviewer.statechart import build
from candleviewer.statechart.bindings import b16_session  # noqa: F401  (registers "session")


async def _start(lane: str = "platform") -> Interpreter:
    result = await build("session", clock=SimulatedClock(), lane=lane)  # type: ignore[arg-type]
    return result.interpreter


async def _active() -> Interpreter:
    interp = await _start()
    await interp.send("MFA_OK", wait=True)
    await interp.drain_pending()
    return interp


async def test_b16_starts_pending_mfa_and_normal() -> None:
    interp = await _start()
    try:
        assert interp.matches("auth.pending_mfa")
        assert interp.matches("elevation.normal")
    finally:
        await interp.stop()


async def test_b16_mfa_ok_activates() -> None:
    interp = await _active()
    try:
        assert interp.matches("auth.active")
        assert interp.context["mfa_satisfied"] is True
    finally:
        await interp.stop()


async def test_b16_mfa_timeout_revokes_with_timeout_reason() -> None:
    interp = await _start()
    try:
        await interp.send("MFA_TIMEOUT", wait=True)
        await interp.drain_pending()
        assert interp.matches("auth.revoked")
        assert interp.context["revoke_reason"] == "timeout"
    finally:
        await interp.stop()


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        ("IDLE_DEADLINE", "idle"),
        ("ABSOLUTE_DEADLINE", "expired"),
        ("REVOKE", "admin"),
        ("LOGOUT", "logout"),
    ],
)
async def test_b16_terminal_events_revoke_with_reason_and_kill_elevation(
    event: str, reason: str
) -> None:
    interp = await _active()
    try:
        await interp.send(event, wait=True)
        await interp.drain_pending()
        assert interp.matches("auth.revoked")
        assert interp.matches("elevation.dead")
        assert interp.context["revoke_reason"] == reason
    finally:
        await interp.stop()


async def test_b16_mfa_attempts_exhausted_locks_after_cap() -> None:
    from candleviewer.statechart.bindings.b16_session import MFA_ATTEMPT_CAP

    interp = await _start()
    try:
        for _ in range(MFA_ATTEMPT_CAP + 1):
            await interp.send("MFA_FAILED", wait=True)
            await interp.drain_pending()
            if interp.matches("auth.revoked"):
                break
        assert interp.matches("auth.revoked")
        assert interp.context["revoke_reason"] == "locked"
    finally:
        await interp.stop()


async def test_b16_step_up_toggles_elevation() -> None:
    interp = await _active()
    try:
        await interp.send("STEP_UP_OK", wait=True)
        await interp.drain_pending()
        assert interp.matches("elevation.elevated")
        await interp.send("ELEVATION_DEADLINE", wait=True)
        await interp.drain_pending()
        assert interp.matches("elevation.normal")
    finally:
        await interp.stop()


async def test_b16_built_with_mandatory_strict_config() -> None:
    interp = await _start()
    try:
        assert interp.strict is True
    finally:
        await interp.stop()
