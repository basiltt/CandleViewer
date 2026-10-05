"""Demo-only environment guard for the `exchange_smoke` suite (E08-T05).

The smoke suite is the only code under `tests/` allowed to reach Bybit. It is
opt-in (`CV_EXCHANGE_SMOKE=1`), demo-only, uses **no credentials**, and fails
closed: any live-looking configuration raises before a socket is opened
(security notes threat 2; C-2.11, C-13.5).
"""

from __future__ import annotations

from collections.abc import Mapping

#: Only these hosts may be dialled: the demo REST host and the public stream
#: demo uses (demo has no public feed of its own — public_ws.PUBLIC_WS_URLS).
DEMO_REST_URL = "https://api-demo.bybit.com"
DEMO_HOSTS = ("api-demo.bybit.com", "stream.bybit.com")
_OPT_IN = "CV_EXCHANGE_SMOKE"
#: Env vars that name the target environment; every one must be `demo` if set.
_ENV_VARS = ("CV_ENVIRONMENT", "CV_SMOKE_ENV", "CV_BYBIT_ENV")
_LIVE_HINTS = ("api.bybit.com", "api.bytick.com", "live", "mainnet", "prod")


class SmokeGuardError(RuntimeError):
    """The smoke suite refused to run against this configuration."""


def opted_in(env: Mapping[str, str]) -> bool:
    return env.get(_OPT_IN) == "1"


def assert_demo_only(env: Mapping[str, str]) -> None:
    """Raise `SmokeGuardError` unless the configuration is unambiguously demo."""
    for var in _ENV_VARS:
        value = env.get(var)
        if value is not None and value.strip().lower() != "demo":
            raise SmokeGuardError(
                f"exchange_smoke is demo-only: {var}={value!r} is not 'demo' - refusing to run"
            )
    base = env.get("CV_BYBIT_REST_BASE_URL")
    if base is not None and base.rstrip("/") != DEMO_REST_URL:
        raise SmokeGuardError(
            f"exchange_smoke is demo-only: CV_BYBIT_REST_BASE_URL={base!r} is not {DEMO_REST_URL}"
        )
    for key, value in env.items():
        upper = key.upper()
        if upper.startswith("CV_") and ("API_KEY" in upper or "API_SECRET" in upper) and value:
            raise SmokeGuardError(
                f"exchange_smoke uses no credentials: unset {key} before running the suite"
            )
        if upper.startswith("CV_BYBIT") and any(h in value.lower() for h in _LIVE_HINTS):
            raise SmokeGuardError(f"exchange_smoke is demo-only: {key} points at live")
