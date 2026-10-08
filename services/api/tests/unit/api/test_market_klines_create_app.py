"""#2087 security follow-up: `/market/klines` through the REAL app factory (`create_app`, fake
storage backend), so the app-wide `install_error_redaction` handler is in the path. The S1 leak
slipped past tests built on a bare `FastAPI()`; this pins the production behaviour.

Out-of-range `limit` fires in FastAPI before the handler -> the redaction handler's 422 Problem.
The garbage cursor: `create_app` wires no principal resolver for `/market/klines` yet, so it
fails closed (501 Problem) before `decode_cursor`; either way no response may echo the value.
The 400 `invalid_cursor` decode path is pinned in `tests/contract/test_market_klines_contract.py`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import Problem
from candleviewer.app import create_app
from candleviewer.settings import Settings

_LIMIT = "987654321"
_CURSOR = "GARBAGE-cursor-" + "Z" * 140


def test_out_of_range_limit_and_garbage_cursor_are_problems_without_echo() -> None:
    app = create_app(Settings(git_sha="test", version="0.0.0-test"))
    client = TestClient(app, client=("127.0.0.1", 50000))  # on-mesh peer (MeshOnlyMiddleware)
    base = {"symbol": "BTCUSDT", "interval": "1", "from": "2023-11-14T22:00:00Z",
            "to": "2023-11-15T06:00:00Z"}  # fmt: skip
    for params, needle in (
        ({**base, "limit": _LIMIT}, _LIMIT),
        ({**base, "cursor": _CURSOR}, _CURSOR),
    ):
        resp = client.get("/market/klines", params=params)
        assert 400 <= resp.status_code < 600, resp.text
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        Problem.model_validate(body)
        assert "input" not in resp.text and needle not in resp.text, resp.text
