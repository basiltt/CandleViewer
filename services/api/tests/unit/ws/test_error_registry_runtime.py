"""E17-T05: the runtime assertion - an uncatalogued WS error code can never be emitted (S10)."""

from __future__ import annotations

import pytest

from candleviewer.ws._generated.error_codes import WS_ERROR_CODES, ErrorCode
from candleviewer.ws.errors import UnknownErrorCode, build_ws_error


def test_build_ws_error_unknown_code_raises() -> None:
    with pytest.raises(UnknownErrorCode):
        build_ws_error("totally_made_up")


def test_build_ws_error_rest_only_code_raises() -> None:
    with pytest.raises(UnknownErrorCode):
        build_ws_error("validation_failed")


def test_build_ws_error_known_code_builds_frame() -> None:
    frame = build_ws_error("not_authenticated", id="c-1")
    assert frame["t"] == "err" and frame["id"] == "c-1"
    assert frame["p"]["code"] == "not_authenticated" and frame["p"]["retryable"] is False


def test_internal_error_never_carries_message() -> None:
    frame = build_ws_error("internal_error", message="boom: SELECT *", request_id="urn:x")
    assert "message" not in frame["p"] and frame["p"]["request_id"] == "urn:x"


def test_catalogue_has_28_codes() -> None:
    assert len(WS_ERROR_CODES) == 28 and ErrorCode.FORBIDDEN in WS_ERROR_CODES
