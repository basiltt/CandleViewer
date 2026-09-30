"""Revoking a session closes its sockets with 4401 (US-ONB-009, QA #1634)."""

from __future__ import annotations

from typing import Any

from candleviewer.ws.revocation import CLOSE_TOKEN_EXPIRED, RevocationHub


async def test_revoke_sends_bye_and_closes_4401_only_for_that_session() -> None:
    hub = RevocationHub()
    got: list[tuple[dict[str, Any], int]] = []
    other: list[int] = []

    async def closer(frame: dict[str, Any], code: int) -> None:
        got.append((frame, code))

    async def other_closer(frame: dict[str, Any], code: int) -> None:
        other.append(code)

    hub.register("s1", closer)
    hub.register("s2", other_closer)
    assert await hub.revoke("s1", "session_revoked") == 1
    assert got[0][1] == CLOSE_TOKEN_EXPIRED == 4401
    assert got[0][0]["t"] == "bye"
    assert got[0][0]["p"]["reconnect"] is False
    assert other == []


async def test_a_failing_socket_does_not_block_the_rest() -> None:
    hub = RevocationHub()
    closed: list[int] = []

    async def bad(frame: dict[str, Any], code: int) -> None:
        raise RuntimeError("socket gone")

    async def good(frame: dict[str, Any], code: int) -> None:
        closed.append(code)

    hub.register("s", bad)
    hub.register("s", good)
    await hub.revoke("s")
    assert closed == [4401]


async def test_unregistered_session_is_a_noop() -> None:
    assert await RevocationHub().revoke("nope") == 0
