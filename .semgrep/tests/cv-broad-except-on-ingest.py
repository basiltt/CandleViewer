"""Fixtures for cv-broad-except-on-ingest (E08-X03): a bare
`except Exception: pass`-shaped handler on the ingestion hot path.
Run with: python tools/ci/check_semgrep_rule_tests.py
"""


def parse_frame_bad(raw: bytes) -> dict | None:
    try:  # ruleid: cv-broad-except-on-ingest
        return decode(raw)
    except Exception:
        pass
    return None


def parse_frame_ok(raw: bytes) -> dict:
    try:  # ok: cv-broad-except-on-ingest
        return decode(raw)
    except ValueError as exc:
        raise MalformedFrameError(str(exc)) from exc


def decode(raw: bytes) -> dict:
    raise NotImplementedError


class MalformedFrameError(Exception):
    pass
