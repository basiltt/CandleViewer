"""Fixtures for cv-unbounded-read (E08-X03): reading a response body or WS
frame without an explicit size bound in the adapter/ingestion path.
Run with: python tools/ci/check_semgrep_rule_tests.py
"""


async def read_ws_frame_bad(ws) -> bytes:
    return await ws.recv()  # ruleid: cv-unbounded-read


def read_response_bad(resp) -> bytes:
    return resp.content  # ruleid: cv-unbounded-read


async def read_ws_frame_ok(bounded_ws) -> bytes:
    return await bounded_ws.recv_bounded()  # ok: cv-unbounded-read
