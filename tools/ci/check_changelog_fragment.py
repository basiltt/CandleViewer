#!/usr/bin/env python3
"""E03-T11: CI-REL-001 changelog-fragment enforcement on PRs.

Called from a PR-triggered job (wired into `.github/workflows/pr.yml`'s
existing gate resolver, ticket "Changelog-fragment enforcement on PRs").
Fails with a message telling the author to fix the PR title or add a
`Changelog:` footer, unless the PR is `chore:`/`ci:`/`docs:`-only.

Usage:
    python tools/ci/check_changelog_fragment.py --title "<pr title>" \\
        --body-file body.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.ci.changelog_lib import check_changelog_fragment  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", type=Path, default=None)
    parser.add_argument("--body", default=None, help="inline body text (tests)")
    args = parser.parse_args(argv)

    if args.body is not None:
        body = args.body
    elif args.body_file is not None and args.body_file.exists():
        body = args.body_file.read_text(encoding="utf-8")
    else:
        body = ""

    result = check_changelog_fragment(args.title, body)
    if result.ok:
        print("changelog-fragment: ok")
        return 0

    print(f"{result.error_code}: {result.reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
