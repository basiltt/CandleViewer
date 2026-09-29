"""Fixtures for cv-secret-shaped-literal.
Run with: python tools/ci/check_semgrep_rule_tests.py (covers cv-secret-shaped-literal)
"""


def bad_hardcoded_api_key() -> None:
    api_key = "not-a-real-key-but-secret-shaped-value"  # ruleid: cv-secret-shaped-literal


def bad_hardcoded_api_secret() -> None:
    api_secret = "s3cr3t-value-should-never-be-here"  # ruleid: cv-secret-shaped-literal


def bad_hardcoded_password() -> None:
    password = "hunter2"  # ruleid: cv-secret-shaped-literal


def ok_env_lookup(get_env: object) -> None:
    api_key = get_env("CV_BYBIT_API_KEY")  # ok: cv-secret-shaped-literal


def ok_unrelated_string() -> None:
    label = "not-a-secret-name"  # ok: cv-secret-shaped-literal
