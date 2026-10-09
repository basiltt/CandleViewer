"""Fixtures for cv-unbounded-query-window (E12-X03, SR-E12-02).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""

from candleviewer.bars.limits import MAX_NON_TIME_WINDOW_US, MAX_TIME_WINDOW_US


async def bars_without_cap(reader, symbol, spec, start_us, end_us, limit):
    return await reader.read_bars(symbol, spec, start_us, end_us, limit + 1)  # ruleid: cv-unbounded-query-window


async def klines_local_number(cache, symbol, interval, tr, start_us, end_us, limit):
    if end_us - start_us > 10**15:
        return None
    return await cache.read_klines(symbol, interval, tr, limit=limit + 1)  # ruleid: cv-unbounded-query-window


async def klines_capped(cache, symbol, interval, tr, start_us, end_us, limit):
    if end_us - start_us > MAX_TIME_WINDOW_US:
        return None
    while True:
        return await cache.read_klines(symbol, interval, tr, limit=limit + 1)  # ok: cv-unbounded-query-window


async def bars_capped(reader, symbol, spec, start_us, end_us, limit):
    span_cap = MAX_TIME_WINDOW_US if spec.kind == "time" else MAX_NON_TIME_WINDOW_US
    if end_us - start_us > span_cap:
        return None
    return await reader.read_bars(symbol, spec, start_us, end_us, limit + 1)  # ok: cv-unbounded-query-window
