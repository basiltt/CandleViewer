"""`MfaService` — the M18 core for E09-S02 (US-ONB-002/003): TOTP
verification, enrolment, and recovery-code lifecycle.

Every Gherkin scenario in the ticket maps to a method here:

- `verify()` — "Valid code creates a session" / "Reused code is rejected" /
  "Clock drift within one step is tolerated".
- `enroll()` + `confirm_enrollment()` — "First-login enrolment".
- `recover()` — "Recovery code use forces re-enrolment" /
  "Recovery codes exhausted".
- `regenerate_recovery_codes()` — `POST /auth/mfa/recovery`'s sibling
  regeneration path from SCR-112.

As with `LoginService`, audit emission is the router's job (`auth` may not
import `audit` — `forbidden-M18` import-linter contract); this module
raises typed errors and returns typed results only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import (
    MfaChallengeInvalid,
    MfaChallengeLocked,
    MfaCodeInvalid,
    MfaCodeReused,
    MfaEnrollmentNotFound,
    RecoveryCodeInvalid,
    RecoveryCodesExhausted,
)
from candleviewer.auth.mfa_repository import MfaRepository
from candleviewer.auth.models import (
    MfaChallengeRecord,
    MfaEnrollRequest,
    MfaEnrollResult,
    MfaMethodKind,
    MfaVerifiedResult,
    MfaVerifyRequest,
    RecoveryCodesRegenerated,
)
from candleviewer.auth.recovery_codes import generate_recovery_codes, hash_recovery_code
from candleviewer.auth.totp import generate_secret, otpauth_uri, secret_to_base32, verify_code

#: Ticket "Technical notes": "attempts capped at 5" (tighter than the
#: schema's own `mfa_ch_attempts CHECK BETWEEN 0 AND 10`, which is a wider
#: sanity bound the migration shares with `step_up`/`enroll` purposes).
CHALLENGE_ATTEMPT_CAP = 5

#: Ticket "Technical notes": "expires_at 5 min".
CHALLENGE_TTL = timedelta(minutes=5)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _hash_token(token: str) -> str:
    """Never persist a bearer `mfa_token` in the clear (mirrors
    `sessions.refresh_token_hash`'s own pattern, and `LoginService`'s
    `MfaChallengeResult.mfa_token` docstring)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class MfaService:
    def __init__(
        self,
        repository: MfaRepository,
        encryptor: TotpEncryptor,
        *,
        clock: Clock = _utc_now,
        issuer: str = "CandleViewer",
    ) -> None:
        self._repository = repository
        self._encryptor = encryptor
        self._clock = clock
        self._issuer = issuer

    # -- verification (login step 2) --------------------------------------

    async def verify(self, request: MfaVerifyRequest, *, account_name: str) -> MfaVerifiedResult:
        """`POST /auth/mfa/verify`. `account_name` (the username) is passed
        in only for symmetry with `enroll()`'s `otpauth_uri` — verification
        never needs it beyond that, since the challenge row already carries
        `user_id`.

        Raises `MfaChallengeInvalid`, `MfaChallengeLocked`, `MfaCodeInvalid`,
        or `MfaCodeReused`."""
        if request.method is not MfaMethodKind.TOTP:
            # WebAuthn is out of scope (ticket "Out of scope"); recovery
            # codes go through `recover()` / `/auth/mfa/recovery` instead
            # (`MfaVerifyRequest.method` is `totp | webauthn | recovery_code`
            # per the OpenAPI enum, but this service only implements the
            # `totp` arm of it).
            raise MfaCodeInvalid("only method=totp is implemented by this endpoint")

        challenge = await self._open_challenge_or_raise(request.mfa_token, purpose="login")
        methods = await self._repository.find_active_totp_methods(str(challenge.user_id))
        if not methods:
            raise MfaCodeInvalid("no active TOTP method enrolled")

        now = self._clock()
        accepted_step: int | None = None
        matched_method_id: str | None = None
        for method in methods:
            if method.secret_enc is None:
                continue  # mfa_totp_shape CHECK should prevent this; defend anyway
            seed = self._encryptor.decrypt(method.secret_enc)
            step = verify_code(seed, request.code, unix_time=now.timestamp())
            if step is not None:
                accepted_step = step
                matched_method_id = str(method.id)
                break

        if accepted_step is None or matched_method_id is None:
            await self._record_failed_attempt(challenge)
            raise MfaCodeInvalid("invalid TOTP code")

        replay_ok = await self._repository.record_time_step(
            matched_method_id, time_step=accepted_step
        )
        if not replay_ok:
            await self._record_failed_attempt(challenge)
            raise MfaCodeReused("this code has already been used")

        await self._repository.touch_method_used(matched_method_id, now=now)
        await self._repository.satisfy_challenge(str(challenge.id), now=now)
        return MfaVerifiedResult(user_id=challenge.user_id)

    async def _open_challenge_or_raise(self, mfa_token: str, *, purpose: str) -> MfaChallengeRecord:
        token_hash = _hash_token(mfa_token)
        challenge = await self._repository.find_open_challenge_by_token_hash(token_hash)
        if challenge is None or challenge.purpose != purpose:
            raise MfaChallengeInvalid("no open challenge for this token")
        if challenge.expires_at <= self._clock():
            raise MfaChallengeInvalid("challenge expired")
        if challenge.attempts >= CHALLENGE_ATTEMPT_CAP:
            raise MfaChallengeLocked("too many failed attempts")
        return challenge

    async def _record_failed_attempt(self, challenge: MfaChallengeRecord) -> None:
        new_count = await self._repository.record_challenge_attempt(str(challenge.id))
        if new_count >= CHALLENGE_ATTEMPT_CAP:
            raise MfaChallengeLocked("too many failed attempts")

    # -- enrolment ---------------------------------------------------------

    async def enroll(
        self, user_id: str, request: MfaEnrollRequest, *, account_name: str
    ) -> MfaEnrollResult:
        """`POST /auth/mfa/enroll`. WebAuthn is out of scope (ticket "Out of
        scope") — only `method=totp` is implemented."""
        if request.method is not MfaMethodKind.TOTP:
            raise MfaCodeInvalid("only method=totp enrolment is implemented")

        seed = generate_secret()
        secret_enc = self._encryptor.encrypt(seed)
        method = await self._repository.create_pending_method(
            user_id,
            secret_enc=secret_enc,
            secret_key_ref=self._encryptor.key_ref,
            label=request.label,
        )
        uri = otpauth_uri(secret=seed, account_name=account_name, issuer=self._issuer)
        return MfaEnrollResult(
            method_id=method.id,
            method=MfaMethodKind.TOTP,
            otpauth_uri=uri,
            secret_base32=secret_to_base32(seed),
        )

    async def confirm_enrollment(
        self, user_id: str, *, method_id: str, code: str
    ) -> tuple[MfaMethodKind, tuple[str, ...]]:
        """`POST /auth/mfa/enroll/confirm`. Returns `(method_kind,
        recovery_codes)` — recovery codes are (re)generated on TOTP
        confirmation whenever the user has none yet (first enrolment,
        ticket "First-login enrolment": "TOTP is enabled and 10 single-use
        recovery codes are displayed once").

        Raises `MfaEnrollmentNotFound` or `MfaCodeInvalid`."""
        method = await self._repository.find_pending_method(method_id, user_id)
        if method is None:
            raise MfaEnrollmentNotFound("no pending enrolment for this method_id")
        if method.secret_enc is None:  # mfa_totp_shape CHECK should prevent this
            raise MfaEnrollmentNotFound("pending method has no TOTP secret")

        seed = self._encryptor.decrypt(method.secret_enc)
        now = self._clock()
        accepted_step = verify_code(seed, code, unix_time=now.timestamp())
        if accepted_step is None:
            raise MfaCodeInvalid("invalid TOTP code")

        confirmed = await self._repository.confirm_method(method_id, now=now)
        await self._repository.record_time_step(method_id, time_step=accepted_step)

        recovery_codes: tuple[str, ...] = ()
        if await self._repository.count_unused_recovery_codes(user_id) == 0:
            recovery_codes = await self._issue_recovery_codes(user_id)
        return confirmed.kind, recovery_codes

    async def _issue_recovery_codes(self, user_id: str) -> tuple[str, ...]:
        plaintext_codes = generate_recovery_codes()
        hashes = tuple(hash_recovery_code(c) for c in plaintext_codes)
        await self._repository.replace_recovery_codes(user_id, code_hashes=hashes)
        return tuple(plaintext_codes)

    # -- recovery ------------------------------------------------------------

    async def recover(self, mfa_token: str, recovery_code: str) -> MfaVerifiedResult:
        """`POST /auth/mfa/recovery`. Raises `MfaChallengeInvalid`,
        `MfaChallengeLocked`, `RecoveryCodeInvalid`, or
        `RecoveryCodesExhausted`.

        Constant-time against the hashed set (ticket "Technical notes":
        "constant-time against the hashed set") is delivered by hashing the
        candidate once and doing an equality-indexed lookup — the DB index
        lookup itself is not a timing side-channel on the *code value*
        because it operates on the SHA-256 digest, not the code."""
        challenge = await self._open_challenge_or_raise(mfa_token, purpose="login")
        if await self._repository.count_unused_recovery_codes(str(challenge.user_id)) == 0:
            # Ticket "Recovery codes exhausted": "I am told to contact the
            # owner and no session is created" — distinct from a merely
            # wrong/reused code so the router can render the
            # contact-the-owner message (US-ONB-010 path) rather than the
            # generic invalid-code message.
            raise RecoveryCodesExhausted("all recovery codes have been used")

        code_hash = hash_recovery_code(recovery_code)
        code_id = await self._repository.find_unused_recovery_code(
            str(challenge.user_id), code_hash=code_hash
        )
        if code_id is None:
            await self._record_failed_attempt(challenge)
            raise RecoveryCodeInvalid("invalid or already-used recovery code")

        now = self._clock()
        await self._repository.consume_recovery_code(code_id, now=now)
        await self._repository.satisfy_challenge(str(challenge.id), now=now)

        # Ticket "Recovery code use forces re-enrolment" (unconditional —
        # the OpenAPI note's "<3 remaining" threshold is a *login-response*
        # UX detail owned by a later ticket's screen work, not a security
        # gate this service may loosen).
        await self._repository.set_mfa_required_reenroll(str(challenge.user_id))
        return MfaVerifiedResult(user_id=challenge.user_id, forced_totp_reenroll=True)

    async def regenerate_recovery_codes(self, user_id: str) -> RecoveryCodesRegenerated:
        """`POST /auth/mfa/recovery`'s SCR-112 regeneration sibling (ticket
        "Scope / Deliverables": "regenerates codes, hard-deleting unused
        ones")."""
        codes = await self._issue_recovery_codes(user_id)
        return RecoveryCodesRegenerated(recovery_codes=codes)
