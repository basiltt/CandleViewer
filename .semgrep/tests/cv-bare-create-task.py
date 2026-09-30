"""Fixtures for cv-bare-create-task (E04-T02).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""

import asyncio


async def bare_bad(coro):
    return asyncio.create_task(coro)  # ruleid: cv-bare-create-task


async def loop_bad(coro):
    loop = asyncio.get_running_loop()
    return loop.create_task(coro)  # ruleid: cv-bare-create-task


async def executor_bad(fn):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn)  # ruleid: cv-bare-create-task


async def spawn_ok(spawn, coro):
    return spawn(coro, name="x")  # ok: cv-bare-create-task
