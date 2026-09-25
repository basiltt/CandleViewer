#!/usr/bin/env bash
# GOV-001: CODEOWNERS coverage checker (C-8.1, C-10.1).
# Thin wrapper around scripts/check_codeowners_coverage.py for parity with the
# other governance checkers' invocation style. See that script for behaviour.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/check_codeowners_coverage.py" --repo-root "${REPO_ROOT}" "$@"
