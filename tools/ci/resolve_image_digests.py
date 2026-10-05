#!/usr/bin/env python3
"""Resolve and verify container image digest pins (SR-132, #1857).

Scans ``infra/docker-compose*.yml``, ``infra/compose/*.yml``, ``infra/images/*`` and
``.github/workflows/*.yml`` for ``repo:tag@sha256:<64 hex>`` references.

* default mode: resolve the real manifest digest of ``repo:tag`` from the registry and rewrite
  the reference in place when it differs.
* ``--check``: HEAD every pinned manifest; fail on placeholder-shaped digests (repeated hex
  patterns, ``deadbeef``, all zeros) and on digests the registry does not know.

Resolution uses the registry HTTP API with an anonymous bearer token (Docker Hub, ghcr.io,
quay.io); docker is not required. No credentials are ever used. Stdlib only.

Error code: CI-IMG-002 (placeholder or unresolvable digest).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[2]
# repo[:tag]@sha256:digest. The repo may include a registry host.
REF_RE = re.compile(
    r"(?P<repo>[a-z0-9][a-z0-9._/-]*[a-z0-9])(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9._-]*))?"
    r"@sha256:(?P<digest>[0-9a-f]{64})"
)
ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)


class RegistryClient(Protocol):
    def digest(self, repo: str, tag: str) -> str | None:
        """Return ``sha256:<hex>`` of the manifest for ``repo:tag`` or None if unpublished."""

    def exists(self, repo: str, digest: str) -> bool:
        """True if the registry serves a manifest with this digest."""


def split_repo(repo: str) -> tuple[str, str]:
    """Return (registry host, repository path), defaulting to Docker Hub ``library/``."""
    parts = repo.split("/")
    if len(parts) > 1 and (
        "." in parts[0] or ":" in parts[0] or parts[0] == "localhost"
    ):
        return parts[0], "/".join(parts[1:])
    path = repo if "/" in repo else f"library/{repo}"
    return "registry-1.docker.io", path


def is_placeholder(hexdigest: str) -> bool:
    """Heuristic for fabricated digests: tiny alphabet, short repeating period, deadbeef."""
    if "deadbeef" in hexdigest or len(set(hexdigest)) <= 2:
        return True
    return any(hexdigest == hexdigest[:n] * (64 // n) for n in (2, 4, 8, 16, 32))


class HttpRegistry:
    """Anonymous registry v2 client (no credentials)."""

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], str | None] = {}

    def _token(self, host: str, path: str) -> str | None:
        key = (host, path)
        if key in self._tokens:
            return self._tokens[key]
        if host == "registry-1.docker.io":
            url = (
                "https://auth.docker.io/token?service=registry.docker.io"
                f"&scope=repository:{path}:pull"
            )
        elif host == "ghcr.io":
            url = f"https://ghcr.io/token?scope=repository:{path}:pull"
        elif host == "quay.io":
            url = (
                f"https://quay.io/v2/auth?service=quay.io&scope=repository:{path}:pull"
            )
        else:
            self._tokens[key] = None
            return None
        try:
            with urllib.request.urlopen(url, timeout=30) as r:  # nosec B310
                tok = str(json.load(r).get("token") or "") or None
        except (urllib.error.URLError, ValueError):
            tok = None
        self._tokens[key] = tok
        return tok

    def _head(self, repo: str, ref: str) -> str | None:
        host, path = split_repo(repo)
        req = urllib.request.Request(
            f"https://{host}/v2/{path}/manifests/{ref}", method="HEAD"
        )
        req.add_header("Accept", ACCEPT)
        tok = self._token(host, path)
        if tok:
            req.add_header("Authorization", f"Bearer {tok}")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310
                return str(r.headers.get("Docker-Content-Digest") or "") or None
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401, 403, 404):
                return None
            raise

    def digest(self, repo: str, tag: str) -> str | None:
        return self._head(repo, tag)

    def exists(self, repo: str, digest: str) -> bool:
        return self._head(repo, digest) is not None


def iter_files(root: Path) -> list[Path]:
    pats = [
        "infra/docker-compose*.yml",
        "infra/compose/*.yml",
        "infra/images/*",
        ".github/workflows/*.yml",
    ]
    out: list[Path] = []
    for pat in pats:
        out.extend(
            p for p in sorted(root.glob(pat)) if p.is_file() and p.suffix != ".md"
        )
    return out


def find_refs(text: str) -> list[re.Match[str]]:
    return list(REF_RE.finditer(text))


def check(root: Path, client: RegistryClient) -> list[str]:
    errors: list[str] = []
    for f in iter_files(root):
        for m in find_refs(f.read_text(encoding="utf-8")):
            where = (
                f"{f.relative_to(root).as_posix()}: {m.group('repo')}:{m.group('tag')}"
            )
            d = m.group("digest")
            if is_placeholder(d):
                errors.append(f"CI-IMG-002 {where}: placeholder digest sha256:{d}")
            elif not client.exists(m.group("repo"), f"sha256:{d}"):
                errors.append(
                    f"CI-IMG-002 {where}: digest sha256:{d} not found in registry"
                )
    return errors


def resolve(root: Path, client: RegistryClient) -> list[tuple[str, str, str, str]]:
    """Rewrite pins in place; return (file, repo:tag, old, new) for each change."""
    changes: list[tuple[str, str, str, str]] = []
    for f in iter_files(root):
        text = f.read_text(encoding="utf-8")
        new_text = text
        for m in find_refs(text):
            repo, tag = m.group("repo"), m.group("tag")
            if not tag:
                continue
            cur = m.group("digest")
            if not is_placeholder(cur) and client.exists(repo, f"sha256:{cur}"):
                continue  # already a real pin; never drift a floating tag silently
            real = client.digest(repo, tag)
            if real is None:
                changes.append(
                    (f.name, f"{repo}:{tag}", m.group("digest"), "UNPUBLISHED")
                )
                continue
            if real != f"sha256:{m.group('digest')}":
                new_text = new_text.replace(m.group(0), f"{repo}:{tag}@{real}")
                changes.append((f.name, f"{repo}:{tag}", m.group("digest"), real))
        if new_text != text:
            f.write_text(new_text, encoding="utf-8", newline="\n")
    return changes


def main(argv: list[str] | None = None, client: RegistryClient | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    cl: RegistryClient = client or HttpRegistry()
    if args.check:
        errs = check(args.root, cl)
        for e in errs:
            print(e, file=sys.stderr)
        print("resolve_image_digests: " + ("FAIL" if errs else "OK"))
        return 1 if errs else 0
    for name, ref, old, new in resolve(args.root, cl):
        print(f"{name}: {ref} {old[:12]} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
