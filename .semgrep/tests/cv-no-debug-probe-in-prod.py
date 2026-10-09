"""Fixtures for cv-no-debug-probe-in-prod (E12-X03, SR-E12-16 / BR-26).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""

import freezegun  # ruleid: cv-no-debug-probe-in-prod
from tests.helpers import fake_clock  # ruleid: cv-no-debug-probe-in-prod

from candleviewer.settings import Environment


def make_router(router, settings):
    @router.get("/market/_probe")  # ruleid: cv-no-debug-probe-in-prod
    async def probe() -> dict:
        return {}

    router.add_api_route("/bars/debug/dump", probe)  # ruleid: cv-no-debug-probe-in-prod

    @router.get("/market/bars")  # ok: cv-no-debug-probe-in-prod
    async def bars() -> dict:
        return {}

    if settings.environment is not Environment.LIVE:
        router.add_api_route("/__test/clock", probe)  # ok: cv-no-debug-probe-in-prod

    return router


def builder_step(bar):
    breakpoint()  # ruleid: cv-no-debug-probe-in-prod
    return bar
