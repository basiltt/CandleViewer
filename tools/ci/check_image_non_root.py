#!/usr/bin/env python3
"""E03-T08: SR-131 -- assert a built container image runs as a non-root user.

Acceptance scenario "The image runs as a non-root user": inspects the image
config (`docker inspect`, plus a live container probe) and fails the build
(CI-IMG-002) if the runtime user resolves to uid 0 or is unset (Docker's
default when `USER` is never set is root).

This does not itself build the image; `.github/workflows/main.yml` builds it
first and passes the local tag here via ``--image``.

Exit codes: 0 non-root confirmed, 1 root user (CI-IMG-002), 2 internal error
(docker/image not available).

Stdlib only (invokes the `docker` CLI as a subprocess; no docker SDK dep).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def _inspect_config_user(image: str) -> str:
    """Return the raw `Config.User` field from `docker inspect` (may be "")."""
    proc = subprocess.run(
        ["docker", "inspect", "--format", "{{json .Config.User}}", image],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"docker inspect failed: {proc.stderr.strip()}")
    result: str = json.loads(proc.stdout.strip())
    return result


def _probe_container_id(image: str) -> str:
    """Run `id -u` inside an ephemeral container as a second, stronger signal.

    `Config.User` can lie (e.g. a numeric-looking string that doesn't map to
    a passwd entry); the live probe is what actually executes.
    """
    proc = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "id", image, "-u"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"docker run id probe failed: {proc.stderr.strip()}")
    result: str = proc.stdout.strip()
    return result


def check_non_root(image: str) -> tuple[bool, str]:
    """Return (is_non_root, detail_message)."""
    config_user = _inspect_config_user(image)
    if config_user in ("", "0", "root", "0:0", "root:root"):
        return False, f"Config.User={config_user!r} resolves to root"

    uid_str = _probe_container_id(image)
    try:
        uid = int(uid_str)
    except ValueError:
        return False, f"container id -u probe returned non-numeric uid {uid_str!r}"

    if uid == 0:
        return False, f"container id -u probe returned uid 0 (Config.User was {config_user!r})"

    return True, f"Config.User={config_user!r}, runtime uid={uid}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="local image tag/ref to inspect")
    args = parser.parse_args(argv)

    try:
        ok, detail = check_non_root(args.image)
    except RuntimeError as exc:
        print(f"CI-IMG-002: {exc}", file=sys.stderr)
        return 2

    if not ok:
        print(f"CI-IMG-002: runtime user is root -- {detail}", file=sys.stderr)
        return 1

    print(f"non-root confirmed: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
