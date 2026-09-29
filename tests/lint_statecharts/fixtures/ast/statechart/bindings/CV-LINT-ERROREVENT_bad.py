"""Fixture for CV-LINT-ERROREVENT: onError handlers must use
isinstance(event, ErrorEvent) and event.error."""


async def on_error_entry(ctx, event):
    return event.reason
