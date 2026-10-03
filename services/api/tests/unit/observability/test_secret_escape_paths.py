"""E43-T06: a secret-shaped value cannot escape via response, log, audit or traceback."""

from __future__ import annotations

import io
import logging
import traceback

from fastapi.testclient import TestClient
from pydantic import BaseModel

from candleviewer.app import create_app
from candleviewer.audit.redact import redact
from candleviewer.observability.logging import RedactionFilter

SECRET = "ZxCvBnMqWeRtYuIoPaSdFgHjKl"  # noqa: S105 - synthetic canary


class Payload(BaseModel):
    qty: int
    note: str = ""


def _client() -> TestClient:
    # Real application factory: proves the redaction handlers win in the real app.
    app = create_app()
    app.router.dependencies = []  # test-only routes are not in the OpenAPI deny-by-default set
    log = logging.getLogger("e43t06.route")

    @app.post("/o")
    async def o(p: Payload) -> dict[str, int]:
        log.info("got %s", p.note)
        if p.note == "boom":
            try:
                raise RuntimeError(f"failed with {SECRET}")
            except RuntimeError:
                log.exception("handler failed")
                raise
        return {"qty": p.qty}

    return TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000))


def test_validation_error_response_does_not_echo_secret() -> None:
    r = _client().post("/o", json={"qty": SECRET, "api_secret": SECRET})
    assert r.status_code == 422
    assert SECRET not in r.text
    body = r.json()
    assert r.headers["content-type"].startswith("application/problem+json")
    assert {"type", "title", "status", "code"} <= body.keys()
    assert body["code"] == "validation_failed"


def test_unhandled_exception_response_does_not_contain_secret() -> None:
    r = _client().post("/o", json={"qty": 1, "note": "boom"})
    assert r.status_code == 500
    assert SECRET not in r.text
    assert r.json()["code"] == "internal_error"


def test_500_path_traceback_logged_through_redaction_filter_is_clean() -> None:
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.addFilter(RedactionFilter())
    h.setFormatter(logging.Formatter("%(message)s"))
    lg = logging.getLogger("e43t06.route")
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    try:
        r = _client().post("/o", json={"qty": 1, "note": "boom"})
    finally:
        lg.removeHandler(h)
    assert r.status_code == 500
    assert "handler failed" in buf.getvalue()
    assert SECRET not in buf.getvalue()


def test_log_record_with_secret_is_redacted_incl_traceback() -> None:
    try:
        raise RuntimeError(f"failed with {SECRET}")
    except RuntimeError as exc:
        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "err %s", (f"key={SECRET}",), None)
        rec.exc_text = "".join(traceback.format_exception(exc))
    assert RedactionFilter().filter(rec) is True
    assert SECRET not in rec.getMessage()
    assert SECRET not in (rec.exc_text or "")


def test_log_stream_end_to_end_redacts_secret() -> None:
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.addFilter(RedactionFilter())
    payload = {"api_secret": SECRET, "nested": [{"x": SECRET}]}
    rec = logging.LogRecord(
        "e43t06.stream", logging.INFO, __file__, 1, "payload %s", (payload,), None
    )
    h.handle(rec)
    assert SECRET not in buf.getvalue()


def test_audit_payload_redacts_nested_secret() -> None:
    items = [{"recovery_code": SECRET, "totp_seed": SECRET}]
    out = redact({"api_secret": SECRET, "meta": {"items": items}})
    assert SECRET not in repr(out)


def test_audit_export_record_with_embedded_json_secret_is_redacted() -> None:
    import json

    row = {"before": json.dumps({"api_secret": SECRET}), "after": {"api_secret": SECRET}}
    out = redact(row)
    assert SECRET not in json.dumps(out, default=str)
