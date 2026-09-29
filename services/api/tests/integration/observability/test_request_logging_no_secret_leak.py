"""Integration test: request with an Authorization header + body never leaks (E04-T01).

Uses `starlette.testclient.TestClient` against a small app wired the same way
`configure_logging()` is wired in `candleviewer/main.py` — no real network
socket, no live exchange call (C-13.5), but exercises the full request path
through a stdlib logger the way a real deployment would.
"""

from __future__ import annotations

import io
import json
import logging
from contextlib import redirect_stdout

from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from candleviewer.observability.logging import configure_logging

_CANARY_TOKEN = (
    "Bearer CANARYBYBITKEY0123456789ABCDEF"  # noqa: S105 - test fixture, not a real secret
)
_CANARY_BODY_FIELD = "CANARY-BODY-FIELD-VALUE"


def _build_app() -> FastAPI:
    app = FastAPI()
    logger = logging.getLogger("candleviewer.test_integration")

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, str]:
        body = await request.body()
        # A call site logging a header + the raw body via a plain stdlib
        # logger — exactly the "new call site cannot bypass redaction" shape,
        # run end-to-end through the ASGI stack.
        logger.info(
            "request received: authorization=%s body=%s",
            request.headers.get("authorization"),
            body.decode(),
        )
        return {"ok": "true"}

    return app


def test_request_with_authorization_header_never_appears_in_captured_stdout() -> None:
    from candleviewer.observability import logging as logging_mod

    buf = io.StringIO()
    with redirect_stdout(buf):
        configure_logging(env="test", level="info", fmt="json")
        app = _build_app()
        client = TestClient(app)
        response = client.post(
            "/echo",
            headers={"Authorization": _CANARY_TOKEN},
            json={"field": _CANARY_BODY_FIELD},
        )
        assert response.status_code == 200
        listener = logging_mod._listener
        assert listener is not None
        listener.stop()
        logging_mod._listener = None

    output = buf.getvalue()
    assert "CANARYBYBITKEY0123456789ABCDEF" not in output
    # Field-shape scenario: still one JSON object per line.
    lines = [line for line in output.splitlines() if line.strip()]
    for line in lines:
        json.loads(line)
