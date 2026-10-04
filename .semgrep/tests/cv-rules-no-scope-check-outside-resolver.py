"""Fixtures for cv-rules-no-scope-check-outside-resolver."""


def bad(actor, acc) -> bool:
    return acc in actor.granted_accounts  # ruleid: cv-rules-no-scope-check-outside-resolver


def ok(resolver, acc) -> bool:
    return resolver.allowed(acc)  # ok: cv-rules-no-scope-check-outside-resolver
