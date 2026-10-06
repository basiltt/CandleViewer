"""Regenerate (or ``--check``) the committed bar-model artefacts (E12-T01).

Usage: uv run python scripts/generate_bar_artifacts.py [--check]
Then `pnpm --filter @candleviewer/protocol generate` re-renders the TS mirror.
"""

from __future__ import annotations

import difflib
import sys
from collections.abc import Callable
from pathlib import Path

from candleviewer.bars.schema import render_schema, render_vectors

GOLDEN = Path(__file__).resolve().parents[3] / "packages" / "fixtures" / "golden" / "bars"
TARGETS: dict[str, Callable[[], str]] = {
    "bar-model.schema.json": render_schema,
    "spec_hash_vectors.json": render_vectors,
}


def main(argv: list[str]) -> int:
    rc = 0
    for name, render in TARGETS.items():
        path = GOLDEN / name
        generated = render()
        if "--check" in argv:
            committed = path.read_text(encoding="utf-8") if path.exists() else ""
            if committed != generated:
                rc = 1
                sys.stderr.write(
                    f"{name} is stale; run scripts/generate_bar_artifacts.py\n"
                    + "".join(
                        difflib.unified_diff(
                            committed.splitlines(True),
                            generated.splitlines(True),
                            "committed",
                            "generated",
                        )
                    )
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(generated, encoding="utf-8", newline="\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
