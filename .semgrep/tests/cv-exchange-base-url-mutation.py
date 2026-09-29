"""Fixtures for cv-exchange-base-url-mutation (E08-X03, SR-040a): base
URL/host must be bound at construction only, never mutated afterward.
Run with: python tools/ci/check_semgrep_rule_tests.py
"""


class ClientBad:
    def __init__(self, host: str) -> None:
        self.host = host

    def switch_environment(self, new_host: str) -> None:
        self.host = new_host  # ruleid: cv-exchange-base-url-mutation


class ClientOk:
    def __init__(self, host: str) -> None:
        self.host = host  # ok: cv-exchange-base-url-mutation
