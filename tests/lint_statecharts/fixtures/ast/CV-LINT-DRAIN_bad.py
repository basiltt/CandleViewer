"""Fixture for CV-LINT-DRAIN: drain_pending() must be called only from
statechart/persistence.py."""


async def teardown(gateway):
    await gateway.drain_pending()
