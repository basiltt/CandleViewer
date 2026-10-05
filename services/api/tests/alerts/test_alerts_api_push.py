"""E40-T04: `push` is refused at the API with a clear message (Gherkin "Push is refused")."""

from __future__ import annotations

import pytest
from _alert_api_env import PRICE_CROSS, Env


@pytest.mark.parametrize("channels", [["push"], ["in_app", "push"]])
def test_push_channel_refused_with_clear_message(channels: list[str]) -> None:
    env = Env()
    r = env.c.post("/alerts", json=PRICE_CROSS | {"channels": channels})
    assert r.status_code == 422
    assert r.json()["detail"] == "Push delivery is not available in this deployment."
    assert r.json()["errors"][0]["field"] == "channels"
    assert not env.repo.rows and "alert.created" not in env.audit.actions()
