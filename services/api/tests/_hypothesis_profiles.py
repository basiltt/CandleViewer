"""Shared Hypothesis profiles (C-13.7, C-9.3; issue #1855).

Selected by the ``HYPOTHESIS_PROFILE`` env var (default ``dev``; CI sets ``ci``).

* ``ci``  - ``deadline=None`` (a wall-clock deadline measures runner load, not
  correctness, and caused the cold-run ``DeadlineExceeded`` flakes #1536/#1547),
  ``derandomize=True`` (same examples every run), ``database=None`` (no
  cross-run example cache), ``print_blob=True``.
* ``dev`` - generous 2000 ms deadline, random exploration.

Reproduction: a ``ci`` failure prints an ``@reproduce_failure`` blob, which
replays it exactly. ``derandomize=True`` makes Hypothesis ignore
``--hypothesis-seed``; to explore with a seed use
``HYPOTHESIS_PROFILE=dev pytest --hypothesis-seed=N``.
"""

from __future__ import annotations

import os

from hypothesis import settings

CI = "ci"
DEV = "dev"

settings.register_profile(
    CI,
    deadline=None,
    derandomize=True,
    database=None,
    max_examples=100,
    print_blob=True,
)
settings.register_profile(DEV, deadline=2000, derandomize=False)


def load_active_profile() -> str:
    name = os.environ.get("HYPOTHESIS_PROFILE", DEV)
    settings.load_profile(name)
    return name
