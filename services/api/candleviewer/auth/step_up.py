"""`StepUpService` (E09-S04, US-ONB-005/010): step-up re-authentication and
owner-initiated TOTP reset.

Policy numbers mirror the B16 `session` chart's elevation sub-state
(`statechart/bindings/b16_session.py`; a parity test pins them). Per C-2.21
the statechart records and this synchronous code enforces: the check in
`require_elevation()` is a dict lookup on per-session state keyed by
`session_id` - never a token claim, so a client cannot forge or replay it on
another session. Audit emission is the router's job (`auth` may not import
`audit`).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from candleviewer.auth.errors import (
    SessionReadOnly,
    StepUpCodeInvalid,
    StepUpRequired,
    UnknownActionClass,
)
from candleviewer.auth.mfa_repository import MfaRepository
from candleviewer.auth.session_repository import SessionRepository
from candleviewer.auth.totp import verify_code

#: Ticket: "a 5-minute grace per action class".
GRACE_WINDOW = timedelta(minutes=5)
#: Ticket: three invalid codes abandon the action.
FAILURE_CAP = 3
#: Ticket: read-only downgrade lasts 5 minutes.
READONLY_WINDOW = timedelta(minutes=5)
ACTION_CLASSES = frozenset({"keys", "users", "live_enablement", "killswitch", "risk_caps"})
#: Ticket "No-grace list": always a fresh code.
NO_GRACE_ACTION_CLASSES = frozenset({"live_enablement", "killswitch"})
_MAX_TRACKED_SESSIONS = 10_000

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Decrypter(Protocol):
    def decrypt(self, blob: bytes) -> bytes: ...


class PositionStateProvider(Protocol):
    """Read-only view of a user's open-position state (OMS read model)."""

    async def open_position_count(self, user_id: str) -> int: ...


@dataclass
class _SessionState:
    classes: dict[str, datetime] = field(default_factory=dict)
    failures: int = 0
    readonly_until: datetime | None = None


@dataclass(frozen=True)
class StepUpGrant:
    action_class: str
    elevated_until: datetime
    #: True for no-grace classes: no window is opened; the grant authorises
    #: exactly the one action it was obtained for.
    single_use: bool


@dataclass(frozen=True)
class ResetPreview:
    target_user_id: uuid.UUID
    open_position_count: int
    message: str


@dataclass(frozen=True)
class ResetResult:
    """Deliberately no secret / recovery-code field (ticket "Reset reveals
    nothing")."""

    target_user_id: uuid.UUID
    methods_revoked: int
    sessions_revoked: int


class StepUpService:
    def __init__(
        self,
        mfa_repository: MfaRepository,
        session_repository: SessionRepository,
        encryptor: Decrypter,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._mfa = mfa_repository
        self._sessions = session_repository
        self._encryptor = encryptor
        self._clock = clock
        self._state: dict[str, _SessionState] = {}

    def _get(self, session_id: str) -> _SessionState:
        state = self._state.get(session_id)
        if state is None:
            if len(self._state) >= _MAX_TRACKED_SESSIONS:  # C-2.18: bounded
                self._state.pop(next(iter(self._state)))
            state = self._state[session_id] = _SessionState()
        return state

    # -- read-only downgrade ---------------------------------------------

    def assert_writable(self, session_id: str) -> None:
        """Every write route calls this; raises `SessionReadOnly` during the
        downgrade window."""
        state = self._state.get(session_id)
        if state is None or state.readonly_until is None:
            return
        if self._clock() < state.readonly_until:
            raise SessionReadOnly(state.readonly_until)
        state.readonly_until = None
        state.failures = 0

    # -- step-up -----------------------------------------------------------

    async def step_up(
        self, user_id: str, session_id: str, action_class: str, code: str
    ) -> StepUpGrant:
        if action_class not in ACTION_CLASSES:
            raise UnknownActionClass(action_class)
        self.assert_writable(session_id)
        state = self._get(session_id)
        now = self._clock()
        if not await self._verify(user_id, code, now):
            state.failures += 1
            if state.failures >= FAILURE_CAP:
                state.readonly_until = now + READONLY_WINDOW
                state.classes.clear()
                raise SessionReadOnly(state.readonly_until)
            raise StepUpCodeInvalid(FAILURE_CAP - state.failures)
        state.failures = 0
        until = now + GRACE_WINDOW
        if action_class in NO_GRACE_ACTION_CLASSES:
            return StepUpGrant(action_class, until, single_use=True)
        state.classes[action_class] = until
        return StepUpGrant(action_class, until, single_use=False)

    async def _verify(self, user_id: str, code: str, now: datetime) -> bool:
        for method in await self._mfa.find_active_totp_methods(user_id):
            if method.secret_enc is None:
                continue
            seed = self._encryptor.decrypt(method.secret_enc)
            step = verify_code(seed, code, unix_time=now.timestamp())
            if step is None:
                continue
            # Same replay protection as login codes (ticket Security notes).
            return await self._mfa.record_time_step(str(method.id), time_step=step)
        return False

    def remaining_grace(self, session_id: str, action_class: str) -> timedelta | None:
        """Remaining window for the dialog text; None if none / no-grace."""
        if action_class in NO_GRACE_ACTION_CLASSES:
            return None
        state = self._state.get(session_id)
        until = state.classes.get(action_class) if state else None
        now = self._clock()
        if until is None or until <= now:
            return None
        return until - now

    def require_elevation(self, session_id: str, action_class: str) -> None:
        """Server-side gate for `is_dangerous` routes (the E09-T03 decision
        point calls this). No-grace classes always raise: those actions must
        carry a fresh code (`step_up()` -> `StepUpGrant.single_use`)."""
        self.assert_writable(session_id)
        if action_class not in ACTION_CLASSES:
            raise StepUpRequired(action_class)
        if self.remaining_grace(session_id, action_class) is None:
            raise StepUpRequired(action_class)

    # -- owner TOTP reset ----------------------------------------------------

    async def preview_reset(
        self, target_user_id: str, positions: PositionStateProvider
    ) -> ResetPreview:
        """State shown to the owner *before* confirming."""
        count = await positions.open_position_count(target_user_id)
        msg = (
            f"Target has {count} open position(s). Resetting does NOT cancel "
            "orders or flatten positions."
        )
        return ResetPreview(uuid.UUID(target_user_id), count, msg)

    async def reset_totp(
        self, *, actor_session_id: str, actor_user_id: str, target_user_id: str
    ) -> ResetResult:
        """Owner reset: revoke the target's methods and all their sessions,
        nothing else. Requires a live `users` elevation; touches no OMS
        surface and returns no secret. Self-reset is refused."""
        self.require_elevation(actor_session_id, "users")
        if actor_user_id == target_user_id:
            raise StepUpRequired("users")
        now = self._clock()
        methods = await self._mfa.find_active_methods(target_user_id)
        for method in methods:
            await self._mfa.revoke_method(str(method.id), now=now)
        revoked = await self._sessions.revoke_all_for_user(
            target_user_id, reason="mfa_reset_by_owner", now=now
        )
        for session in revoked:
            self._state.pop(str(session.id), None)
        return ResetResult(uuid.UUID(target_user_id), len(methods), len(revoked))
