"""E03-Q01 fixture: SR-145 synthetic planted secret / clean diff, driven
through the real `tools/ci/security_gate.py::evaluate_findings` policy
(gitleaks: any finding blocks unconditionally, no accepted-risk possible).

The planted "secret" is an obviously fake, dummy-prefixed string and is
never a realistic credential shape (SR-145) — it exists only to prove the
gate's "any gitleaks finding blocks" policy path fires, not to exercise the
gitleaks regex engine itself (that is gitleaks' own upstream test suite).
"""

from __future__ import annotations

from datetime import date

from tools.ci.security_gate import AcceptedRisk, Finding, evaluate_findings

# Obviously fake — asserted never to match a real Bybit/AWS/GitHub key shape.
# Real key patterns (e.g. `gho_`, `ghp_`, `sk-`) are deliberately NOT used
# here; this is a synthetic marker string only, per SR-145.
_DUMMY_SECRET_MARKER = "CV_TEST_DUMMY_SECRET_DO_NOT_USE_0000000000"


def _assert_not_real_key_shape(secret: str) -> None:
    real_prefixes = ("gho_", "ghp_", "sk-", "AKIA", "-----BEGIN")
    assert not any(
        secret.startswith(p) for p in real_prefixes
    ), "SR-145 violation: dummy secret must never match a real key shape"


def build_clean_fixture() -> tuple[bool, str]:
    """No gitleaks findings at all -> gate passes."""
    result = evaluate_findings([], [], run_date=date(2026, 9, 30))
    return (not result.blocked, f"blocked={result.blocked} code={result.code}")


def build_planted_secret_fixture() -> tuple[bool, str]:
    """CI-SEC-001: a single gitleaks finding for the synthetic marker must
    block unconditionally — gitleaks findings can never be accepted-risked
    (security_gate.py enforces this even if a risk entry is mistakenly
    added for one, see `load_accepted_risks`)."""
    _assert_not_real_key_shape(_DUMMY_SECRET_MARKER)
    finding = Finding(
        tool="gitleaks",
        finding_id="synthetic-marker-001",
        severity="HIGH",
        detail=f"planted synthetic marker: {_DUMMY_SECRET_MARKER}",
    )
    accepted: list[AcceptedRisk] = []
    result = evaluate_findings([finding], accepted, run_date=date(2026, 9, 30))
    ok = result.blocked and result.code == "CI-SEC-001"
    return (
        not ok,
        f"blocked={result.blocked} code={result.code} messages={result.messages}",
    )
