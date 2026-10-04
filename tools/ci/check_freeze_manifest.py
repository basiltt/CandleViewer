"""E43-T05 freeze assertion (SR-130/SR-156).

Recomputes the dependency-graph fingerprint after a frozen install and compares it to
``security/freeze-manifest.sha256``. Independent of any ``pentest-freeze-*`` tag.

Lines of the manifest (``<sha256>  <component>``):
  pnpm-lock.yaml       raw bytes of the lockfile
  uv.lock              raw bytes of services/api/uv.lock
  pnpm-graph           ``pnpm ls -r --json --depth Infinity``, normalised (machine paths dropped)
  uv-graph             ``uv export --frozen --all-groups`` for services/api

Usage: ``python tools/ci/check_freeze_manifest.py [--write | --propose DIR]``.
  --write        regenerates the committed manifest (approved freeze change, policy §2)
  --propose DIR  Dependabot-aware CI mode (policy §2.1): on mismatch, writes the regenerated
                 manifest and a unified diff into DIR and appends them to
                 ``$GITHUB_STEP_SUMMARY`` for the reviewer. The committed manifest is never
                 touched and the exit status is still 1 — a human commits the proposal.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "security" / "freeze-manifest.sha256"
# ``path``/``from`` are absolute machine paths. ``unsavedDependencies`` is pnpm's view of root
# devDependencies hoisted into a workspace's node_modules: it depends on local install state
# (which packages happen to be linked), not on the lockfile, so it differs between a fresh CI
# install and a developer checkout and must not feed the freeze hash (E43-T05-B1 #1737).
# ``deduped``/``dedupedDependenciesCount`` mark where pnpm elided an already-printed subtree;
# which occurrence is printed first depends on hoisting/traversal order of the local
# node_modules, so these are install-state too.
_DROP_KEYS = {"path", "from", "unsavedDependencies", "deduped", "dedupedDependenciesCount"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run(cmd: list[str], cwd: Path) -> bytes:
    exe = shutil.which(cmd[0])
    if exe is None:
        raise SystemExit(f"freeze-manifest: '{cmd[0]}' not found on PATH")
    return subprocess.run([exe, *cmd[1:]], cwd=cwd, check=True, capture_output=True).stdout


def normalise_pnpm_graph(raw: Any) -> Any:
    """Drop machine-specific keys (absolute paths) and sort, so the graph is portable."""
    if isinstance(raw, dict):
        return {k: normalise_pnpm_graph(v) for k, v in sorted(raw.items()) if k not in _DROP_KEYS}
    if isinstance(raw, list):
        items = [normalise_pnpm_graph(v) for v in raw]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(raw, str):
        return raw.replace(chr(92), "/").replace(chr(13) + chr(10), chr(10))
    return raw


def canonical_json(graph: Any) -> bytes:
    """Canonical JSON bytes: sorted keys, compact separators, LF, forward slashes."""
    return json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()


def normalise_uv_export(text: str) -> str:
    """Keep requirement lines only (drop the generator comment header)."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln and not ln.lstrip().startswith("#")) + "\n"


def compute() -> dict[str, str]:
    api = ROOT / "services" / "api"
    graph = normalise_pnpm_graph(
        json.loads(_run(["pnpm", "ls", "-r", "--json", "--depth", "Infinity"], ROOT))
    )
    uv_out = _run(
        ["uv", "export", "--frozen", "--all-groups", "--no-emit-project", "--no-header"], api
    )
    return {
        "pnpm-lock.yaml": _sha((ROOT / "pnpm-lock.yaml").read_bytes().replace(b"\r\n", b"\n")),
        "uv.lock": _sha((api / "uv.lock").read_bytes().replace(b"\r\n", b"\n")),
        "pnpm-graph": _sha(canonical_json(graph)),
        "uv-graph": _sha(normalise_uv_export(uv_out.decode("utf-8")).encode()),
    }


def render(digests: dict[str, str]) -> str:
    return "".join(f"{v}  {k}\n" for k, v in digests.items())


def manifest_diff(expected: str, actual: str) -> str:
    """Unified diff of the committed manifest vs the recomputed one (relative path header)."""
    return "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile="a/security/freeze-manifest.sha256",
            tofile="b/security/freeze-manifest.sha256",
        )
    )


def write_proposal(out_dir: Path, expected: str, actual: str) -> Path:
    """Policy §2.1: materialise the regenerated manifest + diff without touching the committed file.

    Returns the path of the proposed manifest. Also appends a reviewer-facing block to
    ``$GITHUB_STEP_SUMMARY`` when that variable is set (i.e. in GitHub Actions).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    proposed = out_dir / "freeze-manifest.sha256"
    proposed.write_text(actual, encoding="utf-8", newline="\n")
    diff = manifest_diff(expected, actual)
    (out_dir / "freeze-manifest.diff").write_text(diff, encoding="utf-8", newline="\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(
                "## Freeze manifest proposal (E43-T05, policy §2.1)\n\n"
                "The dependency graph of this PR differs from `security/freeze-manifest.sha256`. "
                "Nothing was committed. If the bump is approved, a reviewer commits the regenerated "
                "manifest (download the `freeze-manifest-proposal` artifact or run "
                "`python tools/ci/check_freeze_manifest.py --write`) and re-runs CI.\n\n"
                "```diff\n" + diff + "```\n"
            )
    return proposed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="regenerate the committed manifest")
    mode.add_argument(
        "--propose",
        metavar="DIR",
        help="on mismatch, write the regenerated manifest + diff to DIR (never commits); exit 1",
    )
    args = ap.parse_args(argv)
    text = render(compute())
    if args.write:
        MANIFEST.write_text(text, encoding="utf-8", newline="\n")
        print(text, end="")
        return 0
    expected = MANIFEST.read_text(encoding="utf-8") if MANIFEST.is_file() else ""
    if text != expected:
        print("freeze-manifest: dependency graph differs from security/freeze-manifest.sha256")
        print("--- expected\n" + expected + "--- actual\n" + text, end="")
        if args.propose:
            proposed = write_proposal(Path(args.propose), expected, text)
            print(f"freeze-manifest: proposal written to {proposed} (not committed, policy §2.1)")
        else:
            print(
                "Regenerate with --write only for an approved freeze change "
                "(35-dependency-freeze-policy §2)."
            )
        return 1
    print("freeze-manifest: OK (graph byte-identical to committed manifest)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
