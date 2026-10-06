"""Shared, environment-independent paths for the xstate gate scripts (#1928).

Every script under ``docs/research/xstate/issues/**`` and
``bench/bench_c_timers_v2.py`` resolves the upstream source tree and the
CandleViewer repo through this module. Nothing here may hard-code a
developer's home directory.

Resolution of the upstream ``xstate-statemachine`` source tree (``XSTATE_SRC``):

1. the ``XSTATE_SRC`` environment variable, when set (used verbatim);
2. ``<repo>/_upstream`` -- where ``.github/workflows/xstate-nightly.yml``
   checks out ``basiltt/xstate-statemachine`` at tag ``v0.9.1``
   (``actions/checkout`` with ``path: _upstream`` under ``$GITHUB_WORKSPACE``,
   which is the repo root), when it exists;
3. the local developer checkout ``<repo>/../_ref/xstate-statemachine``, only
   when it exists;
4. otherwise ``<repo>/_upstream`` (missing; scripts that need it fail loudly).

Scripts that need the upstream *main* dev venv (``.venv-main``) call
:func:`upstream_main_python`. When that interpreter is absent they exit with
:data:`SKIP_ENV_EXIT`; ``run_gate.py`` records that as ``SKIP-ENV`` --
"skipped (environment)" -- which is neither a pass nor a regression.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Exit code meaning "skipped (environment)" (the automake/ctest SKIP convention).
SKIP_ENV_EXIT = 77

GATE_DIR = Path(__file__).resolve().parent
XSTATE_DOCS = GATE_DIR.parent  # docs/research/xstate
REPO_ROOT = XSTATE_DOCS.parents[2]  # CandleViewer checkout root
CI_UPSTREAM = REPO_ROOT / "_upstream"
LOCAL_REF = REPO_ROOT.parent / "_ref" / "xstate-statemachine"


def resolve_xstate_src(
    env: dict[str, str] | None = None,
    ci_upstream: Path = CI_UPSTREAM,
    local_ref: Path = LOCAL_REF,
) -> Path:
    """Return the upstream source tree per the order in the module docstring."""
    environ = os.environ if env is None else env
    explicit = environ.get("XSTATE_SRC", "").strip()
    if explicit:
        return Path(explicit)
    if ci_upstream.is_dir():
        return ci_upstream
    if local_ref.is_dir():
        return local_ref
    return ci_upstream


XSTATE_SRC = resolve_xstate_src()


def find_dev_python(src: Path, venv_name: str = ".venv-main") -> Path | None:
    """The interpreter of the upstream dev venv ``src/venv_name``, if present."""
    venv = src / venv_name
    for rel in ("Scripts/python.exe", "Scripts/python", "bin/python"):
        candidate = venv / rel
        if candidate.is_file():
            return candidate
    return None


def upstream_dev_python(venv_name: str, src: Path | None = None) -> str:
    """Interpreter of an upstream dev venv, or exit ``SKIP_ENV_EXIT``.

    Checks that need ``.venv-main`` / ``.venv-gate`` verify an upstream dev
    build, not the pinned wheel, so they only run where that venv exists.
    """
    root = XSTATE_SRC if src is None else src
    py = find_dev_python(root, venv_name)
    if py is None:
        print(
            f"skipped (environment): requires the upstream dev venv {root / venv_name} "
            "(set XSTATE_SRC to a checkout that has it)"
        )
        sys.exit(SKIP_ENV_EXIT)
    return str(py)


def upstream_main_python() -> str:
    """Interpreter of the upstream-main dev venv, or exit ``SKIP_ENV_EXIT``."""
    return upstream_dev_python(".venv-main")
