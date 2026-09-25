#!/usr/bin/env bash
# GOV-002: rule-reference link checker (C-16.4).
# Thin wrapper around scripts/check_rule_refs.py for parity with the canonical
# one-liner published in CONSTITUTION.md C-16.4. See that script for behaviour.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/check_rule_refs.py" --repo-root "${REPO_ROOT}" "$@"
