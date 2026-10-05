"""Make the harness modules and the `candleviewer` package importable whether
pytest runs from the repo root (verify_pr: plain `python -m pytest`) or via
`uv run --project services/api` (fixes the round-3 collection error)."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE.parents[2] / "services" / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
