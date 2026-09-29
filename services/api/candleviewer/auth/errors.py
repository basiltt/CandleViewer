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
