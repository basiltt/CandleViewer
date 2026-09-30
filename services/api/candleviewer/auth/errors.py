"""Domain errors for the auth module (M18)."""

from __future__ import annotations


class AuthError(Exception):
    """Base exception for the M18 `auth` module."""


class InvalidCredentials(AuthError):
    """Unknown user, wrong password, or a not-yet-known combination.

    Deliberately uniform (E09-S01 acceptance criterion "Unknown user is
    indistinguishable from a wrong password" / C-2.12 enumeration
    resistance): callers must render exactly the same HTTP status and
    message for every case this is raised, never branching on which case
    produced it.
    """


class AccountDisabled(AuthError):
    """Password verified but `users.status = 'disabled'`.

    Only ever raised *after* a successful Argon2id verification (the
    ticket's documented, deliberate trade-off: the caller already proved
    knowledge of the secret, so revealing the disabled state here does not
    aid enumeration)."""


class AccountLocked(AuthError):
    """`users.locked_until` is in the future. Carries the remaining seconds
    so the API/UI can render a countdown without a second query."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"account locked for another {retry_after_s}s")
        self.retry_after_s = retry_after_s


class AuthServiceUnavailable(AuthError):
    """The auth module has not been started with a real repository."""


class MfaChallengeInvalid(AuthError):
    """The `mfa_token` does not correspond to an open, unexpired challenge —
    unknown token, already-satisfied challenge, or an expired one (ticket
    "expired-challenge (returns to SCR-001)"). Deliberately uniform: the
    router must never reveal *which* of these applied."""


class MfaChallengeLocked(AuthError):
    """Five failed attempts against one challenge (ticket "locked after 5
    tries" / `mfa_challenges.attempts CHECK BETWEEN 0 AND 10` with this
    module enforcing the tighter 5-try business rule)."""


class MfaCodeInvalid(AuthError):
    """A syntactically valid TOTP/recovery code that did not verify.

    Raised only when the surrounding challenge is still open (an already
    exhausted challenge raises `MfaChallengeLocked` instead) — the caller
    still owes the failure an `auth.mfa_failed` audit record with
    `reason=invalid`."""


class MfaCodeReused(AuthError):
    """A TOTP code whose `time_step` was already accepted for this method
    (ticket "Reused code is rejected" — replay protection)."""


class MfaEnrollmentNotFound(AuthError):
    """`method_id` does not exist, is not `pending`, or does not belong to
    the authenticated user."""


class MfaLastMethodProtected(AuthError):
    """`DELETE /auth/mfa/methods/{methodId}` on the last active method while
    `users.mfa_required` is set (ticket "Security notes": "the last
    remaining method cannot be deleted while `users.mfa_required` is
    set")."""


class MfaReauthRequired(AuthError):
    """`DELETE /auth/mfa/methods/{methodId}` without a valid
    `X-Reauth-Password` header (ticket "Security notes")."""


class RecoveryCodeInvalid(AuthError):
    """An unknown or already-used recovery code."""


class RecoveryCodesExhausted(AuthError):
    """All recovery codes for this user are consumed (ticket "Recovery
    codes exhausted": "no session is created")."""
