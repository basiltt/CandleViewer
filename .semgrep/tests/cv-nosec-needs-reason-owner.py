"""Fixtures for cv-nosec-needs-reason-owner (E12-X03 suppression policy).
Run with: python tools/ci/check_semgrep_rule_tests.py
"""

A = "SELECT 1"  # nosec  # ruleid: cv-nosec-needs-reason-owner
B = "SELECT 2"  # nosec B608 - table from allowlist  # ruleid: cv-nosec-needs-reason-owner
C = "SELECT 3"  # nosec B608 reason=closed-allowlist  # ruleid: cv-nosec-needs-reason-owner
D = "SELECT 4"  # nosec B608 reason=closed-allowlist owner=@CandleViewer/backend  # ok: cv-nosec-needs-reason-owner
E = "SELECT 5"  # ok: cv-nosec-needs-reason-owner
