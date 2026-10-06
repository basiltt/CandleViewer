"""Verify #229 on v0.9.0/main: docs describe production-relevant facts
accurately, and CHANGELOG's #219 entry is qualified.

Note: on v0.9.0 the underlying behaviours were also fixed at the code
level (#225 narrowed the ReentrantWaitError predicate so ensure_future
tasks are ordinary external traffic regardless of further awaits; #226
made chain_trips/last_chain_error snapshot fields). This script checks
that the docs accurately reflect that FIXED state, which is what #229's
acceptance criteria reduce to once the code no longer has the gap.

STANDALONE: file-based check only, no machine execution needed beyond a
quick sanity read.
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys, re

ROOT = str(_XS)

failures = []


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


interp = read(f"{ROOT}/docs/_guide/interpreters.md")
snaps = read(f"{ROOT}/docs/_guide/snapshots.md")
prodchar = read(f"{ROOT}/docs/_guide/production-characteristics.md")
changelog = read(f"{ROOT}/CHANGELOG.md")

# --- Criterion 1: ensure_future example carries the (now-updated) rule
# inline, not a footnote, and covers the def-action case too.
if "asyncio.ensure_future(i.send(\"GO\", wait=True))" not in interp:
    failures.append("interpreters.md missing the ensure_future example line")
if "The rule is about *tasks*, not about code position (#225)" not in interp:
    failures.append("interpreters.md missing #225 task-based rule explanation")
if "whether the action returns immediately or awaits again afterwards" not in interp:
    failures.append("interpreters.md doesn't state the precondition/non-precondition inline")
if "A plain `def` action cannot `await` at all" not in interp or "#232" not in interp:
    failures.append("interpreters.md missing the def-action RuntimeWarning note (#232)")

# --- Criterion 2 (CHANGELOG #219 qualified)
if "predicate narrowed in #225" not in changelog:
    failures.append("CHANGELOG #219 entry not qualified with #225 narrowing")

# --- Criterion 3: snapshots.md states chain_trips/last_chain_error status
# in the same list that documents dormant services/timers, alongside the
# scheduled_sends/pending_events bullets.
if not re.search(r"chain_trips.*last_chain_error.*#226", snaps):
    failures.append("snapshots.md missing chain_trips/last_chain_error #226 bullet")
if "Timers are NOT resumed by default" not in snaps:
    failures.append("snapshots.md missing the timers-not-resumed sentence used as the model")

# --- Criterion 4: production-characteristics.md links back to snapshots.md
if "(see [Snapshots](../snapshots/))" not in prodchar:
    failures.append("production-characteristics.md missing cross-reference to snapshots.md")
if "snapshot fields (#226)" not in prodchar:
    failures.append("production-characteristics.md doesn't state latch/counter are snapshot fields")

print("interpreters.md ensure_future section present:", "ensure_future(i.send" in interp)
print("CHANGELOG #219 qualified:", "predicate narrowed in #225" in changelog)
print("snapshots.md chain_trips bullet present:", bool(re.search(r"chain_trips.*last_chain_error.*#226", snaps)))
print("production-characteristics.md links to snapshots:", "(see [Snapshots](../snapshots/))" in prodchar)

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
