#!/usr/bin/env python3
"""E03-T11: semver state and the 1.0.0 explicit-declaration guard.

`version.txt` at repo root is the single source of truth for the current
released version in this polyglot monorepo (ticket "Technical notes":
"Version state lives in the git tags plus a `version.txt` written at
release time, so no package file is the source of truth"). Git tags
(`vX.Y.Z`) are the durable record; `version.txt` mirrors the latest one so
tooling that can't shell out to git (e.g. a packaging step) can read it.

Error code: CI-REL-002 (1.0.0 guard) — see `docs/plan/07-release-and-prr.md`
§2: "staying 0.x.y until the first Live-enablement release, when 1.0.0 is
declared explicitly, not automatically."
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tools.ci.changelog_lib import Bump

_SEMVER_RE = re.compile(r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, text: str) -> Version:
        m = _SEMVER_RE.match(text.strip())
        if not m:
            raise ValueError(f"not a valid semver string: {text!r}")
        return cls(int(m.group("major")), int(m.group("minor")), int(m.group("patch")))


@dataclass(frozen=True)
class BumpResult:
    ok: bool
    next_version: Version | None = None
    reason: str | None = None
    error_code: str | None = None


def compute_next_version(
    current: Version,
    bump: Bump,
    *,
    allow_1_0_0: bool = False,
) -> BumpResult:
    """Apply `bump` to `current`, enforcing the 1.0.0 guard.

    Pre-1.0 major bumps stay within the `0.x.y` line (bumping MINOR
    instead) unless the computed next version would literally be `1.0.0`,
    in which case the caller must pass `allow_1_0_0=True` or the release
    fails with CI-REL-002 (acceptance scenario "1.0.0 cannot be produced
    accidentally").
    """
    if bump is Bump.NONE:
        return BumpResult(ok=True, next_version=current)

    if current.major == 0:
        if bump is Bump.MAJOR:
            candidate = Version(1, 0, 0)
            if not allow_1_0_0:
                return BumpResult(
                    ok=False,
                    reason=(
                        "1.0.0 requires explicit Live-enablement declaration "
                        "(RELEASE_ALLOW_1_0_0=true)"
                    ),
                    error_code="CI-REL-002",
                )
            return BumpResult(ok=True, next_version=candidate)
        if bump is Bump.MINOR:
            return BumpResult(ok=True, next_version=Version(0, current.minor + 1, 0))
        return BumpResult(ok=True, next_version=Version(0, current.minor, current.patch + 1))

    if bump is Bump.MAJOR:
        return BumpResult(ok=True, next_version=Version(current.major + 1, 0, 0))
    if bump is Bump.MINOR:
        return BumpResult(ok=True, next_version=Version(current.major, current.minor + 1, 0))
    return BumpResult(
        ok=True,
        next_version=Version(current.major, current.minor, current.patch + 1),
    )
