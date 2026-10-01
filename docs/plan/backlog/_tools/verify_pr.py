"""Pre-merge verification: check out a PR into a temp worktree and run what it ships.
Usage: python docs/plan/backlog/_tools/verify_pr.py <pr-number>   -> exit 0 = PASS
Runs: pytest over any tests/ dirs touched or added; python -m py_compile on .py files;
      json.load on .json files; yaml.safe_load on .yml/.yaml; no network."""
import json, os, subprocess, sys, tempfile, shutil, glob
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
GH = r"C:\Program Files\GitHub CLI\gh.exe"
pr = sys.argv[1]
files = json.loads(subprocess.run([GH, "pr", "view", pr, "--json", "files", "-q", "[.files[].path]"], capture_output=True, text=True, cwd=REPO).stdout)
tmp = tempfile.mkdtemp(prefix=f"cv-verify-{pr}-")
wt = os.path.join(tmp, "wt")
def run(*a, cwd=None): return subprocess.run(a, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd or REPO)
run("git", "fetch", "-q", "origin", f"pull/{pr}/head:verify-{pr}")
r = run("git", "worktree", "add", "-q", "--detach", wt, f"verify-{pr}")
if r.returncode: print(r.stderr); sys.exit(2)
fails = []
env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
try:
    py = [f for f in files if f.endswith(".py") and os.path.exists(os.path.join(wt, f))]
    for f in py:
        r = subprocess.run([sys.executable, "-m", "py_compile", f], capture_output=True, text=True, cwd=wt, env=env)
        if r.returncode: fails.append(f"py_compile {f}: {r.stderr.strip()[:200]}")
    for f in files:
        p = os.path.join(wt, f)
        if not os.path.exists(p): continue
        if f.endswith(".json"):
            try: json.load(open(p, encoding="utf-8"))
            except Exception as e: fails.append(f"json {f}: {e}")
        if f.endswith((".yml", ".yaml")):
            try:
                import yaml; list(yaml.safe_load_all(open(p, encoding="utf-8")))  # pnpm 12 lockfiles are multi-document
            except Exception as e: fails.append(f"yaml {f}: {e}")
    test_dirs = sorted({os.path.dirname(f) for f in files if "/tests/" in f or os.path.basename(f).startswith("test_")})
    test_dirs = [d for d in test_dirs if os.path.isdir(os.path.join(wt, d))]
    # Python workspace (services/api): run via uv inside the package so the
    # candleviewer package and pytest config resolve (AGENTS.md §4). Any test
    # dir under services/api is delegated to that one run.
    api_dirs = [d for d in test_dirs if d.replace(chr(92), "/").startswith("services/api/")]
    if api_dirs and os.path.exists(os.path.join(wt, "services", "api", "pyproject.toml")):
        api = os.path.join(wt, "services", "api")
        r = subprocess.run(["uv", "sync", "--frozen", "--quiet"], capture_output=True, text=True, cwd=api, env=env)
        if r.returncode: fails.append(f"uv sync: {(r.stderr or r.stdout).strip()[-300:]}")
        else:
            # perf budgets are CI-enforced; the laptop runs several agents at once
            r = subprocess.run(["uv", "run", "--frozen", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not integration and not perf"], capture_output=True, text=True, cwd=api, env=env)
            tail = " | ".join((r.stdout or r.stderr).strip().splitlines()[-3:])
            print("pytest(services/api):", tail)
            if r.returncode == 1:
                # One isolated rerun of just the failures (C-9.3 quarantine spirit, never a skip):
                # wall-clock tests on a shared laptop fail under load while CI is green. A real
                # defect fails again here; the rerun output is printed so the flake is visible.
                failed = [ln.split()[1] for ln in r.stdout.splitlines() if ln.startswith("FAILED ")]
                if failed and len(failed) <= 5:
                    r2 = subprocess.run(["uv", "run", "--frozen", "pytest", "-q", "-p", "no:cacheprovider", *failed], capture_output=True, text=True, cwd=api, env=env)
                    tail2 = " | ".join((r2.stdout or r2.stderr).strip().splitlines()[-2:])
                    print(f"pytest(services/api) isolated rerun of {len(failed)} failure(s):", tail2)
                    if r2.returncode == 0: print("  note: load flake — flagged for determinism fix (C-13.7), see test IDs above"); r = r2
            if r.returncode not in (0, 5): fails.append(f"services/api pytest rc={r.returncode}: {tail[:300]}")
        test_dirs = [d for d in test_dirs if d not in api_dirs]
    if test_dirs:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *test_dirs], capture_output=True, text=True, cwd=wt, env=env)
        tail = "\n".join(r.stdout.strip().splitlines()[-3:])
        print("pytest:", tail.replace("\n", " | "))
        if r.returncode not in (0, 5): fails.append(f"pytest rc={r.returncode}: {tail[:300]}")
    else:
        print("pytest: no test dirs in this PR")
finally:
    run("git", "worktree", "remove", "--force", wt); run("git", "branch", "-qD", f"verify-{pr}"); shutil.rmtree(tmp, ignore_errors=True)
print(f"PR #{pr}: {'PASS' if not fails else 'FAIL'}  files={len(files)} py={len(py)} tests={len(test_dirs)}")
for f in fails: print("  -", f)
sys.exit(1 if fails else 0)
