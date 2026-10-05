"""Fixtures for cv-rules-no-scope-check-outside-resolver."""


def bad(actor, acc) -> bool:
    return acc in actor.granted_accounts  # ruleid: cv-rules-no-scope-check-outside-resolver


def bad_disjoint(actor, accs) -> bool:
    return actor.granted_accounts.isdisjoint(accs)  # ruleid: cv-rules-no-scope-check-outside-resolver


def bad_subset(actor, accs) -> bool:
    return accs <= actor.granted_accounts  # ruleid: cv-rules-no-scope-check-outside-resolver


def bad_any(actor, accs) -> bool:
    return any(a in actor.granted_accounts for a in accs)  # ruleid: cv-rules-no-scope-check-outside-resolver


def ok(resolver, acc) -> bool:
    return resolver.allowed(acc)  # ok: cv-rules-no-scope-check-outside-resolver


def _require_grants(actor, acc) -> bool:
    return acc in actor.granted_accounts  # ok: cv-rules-no-scope-check-outside-resolver
