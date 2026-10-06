"""LC-53 verification on xstate-statemachine 0.8.0.

Acceptance criteria (from LC-53-undocumented-production-characteristics.md):

- [ ] docs/_guide/production-characteristics.md exists, three sections with
      measured numbers + hardware/Python version.
- [ ] Page linked from nav and from interpreters.md, delayed-transitions.md, faq.md.
- [ ] delayed-transitions.md states "not before", not "at", links to §2.
- [ ] interpreters.md thread-safety row corrected for SyncInterpreter.
- [ ] faq.md per-transition cost qualified, background-threads bullet
      attributed to the right interpreter.
- [ ] repro/LC-53_undocumented-production-characteristics.py exits 0.
- [ ] Tests added: test_production_characteristics_page_exists,
      test_production_characteristics_covers_all_three_topics,
      test_sync_interpreter_thread_safety_row_mentions_timer_threads.
- [ ] A reproducible benchmark script ships under benchmarks/.

This script checks each criterion directly against the shipped guide/repo,
independent of the library's own test suite (which we also run separately).
Exit 0 if ALL criteria hold, 1 otherwise.
"""

from __future__ import annotations
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[2] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py, upstream_dev_python as _xs_dev_py  # noqa: E402,F401

import os
import pathlib
import re
import sys

REPO = pathlib.Path(os.environ.get("XSM_REPO", str(_XS)))
GUIDE = REPO / "docs" / "_guide"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


# --- criterion 1: production-characteristics.md exists with 3 sections + numbers
pc_path = GUIDE / "production-characteristics.md"
pc = read(pc_path)
has_three_sections = bool(
    re.search(r"starv|fires? late|not before", pc, re.I)
    and re.search(r"threading contract|background thread|SyncInterpreter", pc, re.I)
    and re.search(r"ev/s|throughput|events? per second", pc, re.I)
)
has_numbers = bool(re.search(r"\d[\d,]*\s*(ms|ev/s|k trivial)", pc, re.I))
has_hw = bool(re.search(r"windows|python 3\.\d|laptop|cpu", pc, re.I))
check("production-characteristics.md exists", pc_path.is_file(), str(pc_path))
check("covers all three topics with numbers", has_three_sections and has_numbers, "")
check("states hardware/python version measured on", has_hw, "")

# --- criterion 2: linked from nav + three pages
# This is a Jekyll site (docs/_config.yml + docs/_layouts), not mkdocs.
nav_files = [REPO / "docs" / "_layouts" / "default.html", REPO / "docs" / "index.html"]
nav_text = ""
for f in nav_files:
    nav_text += read(f)
linked_in_nav = "production-characteristics" in nav_text
interp = read(GUIDE / "interpreters.md")
delayed = read(GUIDE / "delayed-transitions.md")
faq = read(GUIDE / "faq.md")
linked_interp = "production-characteristics" in interp
linked_delayed = "production-characteristics" in delayed
linked_faq = "production-characteristics" in faq
check("linked from mkdocs nav", linked_in_nav, str([str(f) for f in nav_files]))
check("linked from interpreters.md/delayed-transitions.md/faq.md",
      linked_interp and linked_delayed and linked_faq,
      f"interp={linked_interp} delayed={linked_delayed} faq={linked_faq}")

# --- criterion 3: delayed-transitions.md "not before" wording + link to §2
not_before = bool(re.search(r"not before.{0,40}never.{0,10}at|not before", delayed, re.I))
links_section2 = "#2-" in delayed or "§ 2" in delayed or "§2" in delayed
check("delayed-transitions.md: 'not before' + link to §2", not_before and links_section2, "")

# --- criterion 4: interpreters.md thread-safety row corrected
thread_row = re.search(r"\|\s*Thread safety\s*\|.*\|.*\|", interp)
row_text = thread_row.group(0) if thread_row else ""
row_ok = bool(thread_row) and "single-threaded" in row_text.lower() and (
    "background thread" in row_text.lower() or "caller's thread" in row_text.lower()
    or "calling thread" in row_text.lower()
)
check("interpreters.md thread-safety row corrected", row_ok, row_text[:160])

# --- criterion 5: faq.md qualifications
faq_qualified = bool(
    re.search(r"unloaded loop", faq, re.I) and re.search(r"fixed budget|per-process budget", faq, re.I)
)
check("faq.md per-transition cost qualified + background-thread bullet", faq_qualified, "")

# --- criterion 6: original repro exits 0
import subprocess

env = dict(os.environ)
env["XSM_REPO"] = str(REPO)
repro_path = pathlib.Path(__file__).resolve().parents[1] / "repro" / "LC-53_undocumented-production-characteristics.py"
py = _xs_dev_py(".venv-gate", REPO)
proc = subprocess.run([py, str(repro_path)], env=env, capture_output=True, text=True)
check("original repro exits 0", proc.returncode == 0, f"exit={proc.returncode}")

# --- criterion 7: tests added and pass
test_file = REPO / "tests" / "test_docs_site.py"
test_src = read(test_file)
required_tests = [
    "test_production_characteristics_page_exists",
    "test_production_characteristics_covers_all_three_topics",
    "test_sync_interpreter_thread_safety_row_mentions_timer_threads",
]
missing_tests = [t for t in required_tests if t not in test_src]
check("required tests present in test_docs_site.py", not missing_tests, f"missing={missing_tests}")

if not missing_tests:
    # No pytest available in the sanctioned venv; import the test module directly
    # and invoke each required test function/method by hand instead.
    import importlib.util

    spec = importlib.util.spec_from_file_location("test_docs_site_lc53", test_file)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO))
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        failures = []
        for tname in required_tests:
            found = False
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type):
                    fn = getattr(attr, tname, None)
                    if fn is not None:
                        found = True
                        try:
                            instance = attr()
                            fn(instance)
                        except Exception as e:  # noqa: BLE001
                            failures.append(f"{tname}: {e!r}")
                        break
                elif attr_name == tname and callable(attr):
                    found = True
                    try:
                        attr()
                    except Exception as e:  # noqa: BLE001
                        failures.append(f"{tname}: {e!r}")
            if not found:
                failures.append(f"{tname}: not found as function or method")
        check("required tests pass", not failures, "; ".join(failures))
    except Exception as e:  # noqa: BLE001
        check("required tests pass", False, f"import/exec error: {e!r}")
    finally:
        sys.path.pop(0)
else:
    check("required tests pass", False, "skipped: tests missing")

# --- criterion 8: benchmark script ships
bench = REPO / "benchmarks" / "production_characteristics.py"
check("benchmarks/production_characteristics.py exists", bench.is_file(), str(bench))

print()
all_ok = all(ok for _, ok, _ in results)
print("RESULT:", "PASS - LC-53 FIXED-DEFAULT" if all_ok else "FAIL - LC-53 not fully satisfied")
sys.exit(0 if all_ok else 1)
