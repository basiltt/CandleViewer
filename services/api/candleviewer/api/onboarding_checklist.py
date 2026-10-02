"""Server-evaluated first-run checklist (E09-S06, US-ONB-007).

Pure assembly logic: every step state comes from a read-only probe run with a
250 ms budget. A probe that times out or raises yields `error` for that step
only; a step whose owning epic has not shipped has no probe and renders
`pending` with a feature-flag reason. Nothing here trusts client input.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal

StepState = Literal["ok", "pending", "blocked", "error"]
PROBE_TIMEOUT_S: Final = 0.25
STEP_ORDER: Final = (
    "tailscale",
    "totp",
    "sub_account",
    "api_key",
    "profile_limits",
    "demo_session",
)
ACTION_ROUTES: Final[Mapping[str, str]] = {
    "tailscale": "/settings/help",
    "totp": "/login/2fa/enroll",
    "sub_account": "/settings/accounts",
    "api_key": "/settings/accounts",
    "profile_limits": "/settings/accounts",
    "demo_session": "/settings/accounts",
}
BYBIT_KEY_RESTRICTION: Final = (
    "Bybit blocks API-key creation for 48 hours after a sub-account is created."
)
_COMING_SOON: Final = "Coming soon in this environment."
BYBIT_RESTRICTION_HOURS: Final = 48


@dataclass(frozen=True)
class StepResult:
    state: StepState
    reason: str | None = None
    unblock_at: datetime | None = None


Probe = Callable[[uuid.UUID], Awaitable[StepResult]]


def bybit_key_restriction(created_at: datetime, now: datetime) -> StepResult | None:
    """`blocked` with the UTC unblock time while inside the 48 h window, else None."""
    from datetime import timedelta

    unblock = created_at.astimezone(UTC) + timedelta(hours=BYBIT_RESTRICTION_HOURS)
    if now < unblock:
        return StepResult("blocked", BYBIT_KEY_RESTRICTION, unblock)
    return None


async def _run(probe: Probe | None, user_id: uuid.UUID, flag_on: bool) -> tuple[StepResult, bool]:
    """Returns (result, timed_out)."""
    if probe is None or not flag_on:
        return StepResult("pending", _COMING_SOON), False
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_S):
            return await probe(user_id), False
    except TimeoutError:
        return StepResult("error", "This check timed out. Retry."), True
    except Exception:  # a failing dependency must never fail the whole card
        return StepResult("error", "This check is unavailable. Retry."), False


async def assemble(
    user_id: uuid.UUID,
    probes: Mapping[str, Probe],
    flags: Mapping[str, bool],
    *,
    dismissed: bool,
) -> tuple[list[dict[str, object]], bool, list[tuple[str, StepResult, bool]]]:
    keys = list(STEP_ORDER)
    results = await asyncio.gather(
        *(_run(probes.get(k), user_id, flags.get(k, True)) for k in keys)
    )
    items: list[dict[str, object]] = []
    raw: list[tuple[str, StepResult, bool]] = []
    for key, (res, timed_out) in zip(keys, results, strict=True):
        raw.append((key, res, timed_out))
        items.append(
            {
                "key": key,
                "state": res.state,
                "reason": res.reason,
                "unblock_at": res.unblock_at.isoformat() if res.unblock_at else None,
                "action_route": ACTION_ROUTES[key],
            }
        )
    complete = all(i["state"] == "ok" for i in items)
    return items, complete, raw
