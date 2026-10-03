"""E43-T05 freeze assertion (SR-130/SR-156).

Recomputes the dependency-graph fingerprint after a frozen install and compares it to
``security/freeze-manifest.sha256``. Independent of any ``pentest-freeze-*`` tag.

Lines of the manifest (``<sha256>  <component>``):
  pnpm-lock.yaml       raw bytes of the lockfile
  uv.lock              raw bytes of services/api/uv.lock
  pnpm-graph           ``pnpm ls -r --json --depth Infinity``, normalised (machine paths dropped)
  uv-graph             ``uv export --frozen --all-groups`` for services/api

Usage: ``python tools/ci/check_freeze_manifest.py [--write]`` (``--write`` regenerates).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "security" / "freeze-manifest.sha256"
_DROP_KEYS = {"path", "from"}


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
    return raw


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
        "pnpm-graph": _sha(json.dumps(graph, sort_keys=True, separators=(",", ":")).encode()),
        "uv-graph": _sha(normalise_uv_export(uv_out.decode("utf-8")).encode()),
    }


def render(digests: dict[str, str]) -> str:
    return "".join(f"{v}  {k}\n" for k, v in digests.items())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="regenerate the committed manifest")
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
        print(
            "Regenerate with --write only for an approved freeze change (35-dependency-freeze-policy §2)."
        )
        return 1
    print("freeze-manifest: OK (graph byte-identical to committed manifest)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
