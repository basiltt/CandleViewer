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
4. otherwise nothing resolves.

If ``XSTATE_SRC`` is set but is not a directory, or nothing resolves, reading
``XSTATE_SRC`` exits with :data:`SKIP_ENV_EXIT` ("skipped (environment)") rather
than handing back a missing path that would later surface as a false FAIL. It is
resolved lazily (module ``__getattr__``), so importing this module never exits.

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
) -> Path | None:
    """Return the upstream source tree per the module docstring, or None if unusable."""
    environ = os.environ if env is None else env
    explicit = environ.get("XSTATE_SRC", "").strip()
    if explicit:
        return Path(explicit) if Path(explicit).is_dir() else None
    if ci_upstream.is_dir():
        return ci_upstream
    if local_ref.is_dir():
        return local_ref
    return None


def require_xstate_src(
    env: dict[str, str] | None = None,
    ci_upstream: Path = CI_UPSTREAM,
    local_ref: Path = LOCAL_REF,
) -> Path:
    """The upstream source tree, or exit ``SKIP_ENV_EXIT`` with the reason."""
    src = resolve_xstate_src(env, ci_upstream, local_ref)
    if src is None:
        environ = os.environ if env is None else env
        explicit = environ.get("XSTATE_SRC", "").strip()
        why = (
            f"XSTATE_SRC={explicit} is not a directory"
            if explicit
            else f"XSTATE_SRC is unset and neither {ci_upstream} nor {local_ref} exists"
        )
        print(f"skipped (environment): no upstream xstate-statemachine source tree ({why})")
        sys.exit(SKIP_ENV_EXIT)
    return src


def __getattr__(name: str) -> Path:
    # Lazy so that `import _paths` never exits; only reading XSTATE_SRC can skip.
    if name == "XSTATE_SRC":
        return require_xstate_src()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    root = require_xstate_src() if src is None else src
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
