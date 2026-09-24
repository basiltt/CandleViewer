import json, re, subprocess, sys, time, os

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = "basiltt/xstate-statemachine"
BASE = os.path.dirname(os.path.abspath(__file__))
GH = "gh"

ALLOWED_LABELS = {
    "bug","enhancement","documentation","performance","meta","tracking",
    "severity/blocker","severity/high","severity/medium","severity/low",
    "area/interpreter","area/sync-interpreter","area/actors","area/persistence",
    "area/timers","area/validation","area/perf","area/docs",
    "area/events","area/plugins","area/receipts",
}

FOOTER = (
    "\n\n---\n"
    "Found during round 4 of our adoption audit (#26) on main @ 5e07ba8. "
    "Self-contained repro attached: exits 1 while present, 0 once fixed — "
    "usable directly as a regression test."
)

def run(cmd, **kw):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **kw)
    if r.returncode != 0:
        print("STDOUT:", r.stdout)
        print("STDERR:", r.stderr)
        raise SystemExit(f"command failed: {cmd}")
    return r.stdout.strip()

def strip_front_matter(text):
    m = re.match(r"^---\n.*?\n---\n", text, re.S)
    if not m:
        return text
    return text[m.end():]

def main():
    manifest = json.load(open(os.path.join(BASE, "manifest.json"), encoding="utf-8"))

    r4_to_issue = {}
    log_lines = []

    # Step 2: create each new issue
    for item in manifest["new_issues"]:
        path = os.path.join(BASE, item["file"])
        raw = open(path, encoding="utf-8").read()
        fm_match = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
        front = fm_match.group(1)
        body_wo_fm = strip_front_matter(raw)

        labels = [l for l in item["labels"] if l in ALLOWED_LABELS]
        dropped = [l for l in item["labels"] if l not in ALLOWED_LABELS]
        if dropped:
            print(f"WARNING dropping disallowed labels for {item['r4']}: {dropped}")
        if "candleviewer" in " ".join(labels).lower():
            raise SystemExit("candleviewer label detected, aborting")

        body = body_wo_fm.rstrip() + FOOTER

        tmp_body = os.path.join(BASE, f"_tmp_body_{item['r4']}.md")
        with open(tmp_body, "w", encoding="utf-8") as f:
            f.write(body)

        cmd = [GH, "issue", "create", "-R", REPO,
               "--title", item["title"],
               "--body-file", tmp_body]
        for l in labels:
            cmd += ["--label", l]

        out = run(cmd)
        # out is issue URL
        num_match = re.search(r"/issues/(\d+)", out)
        num = num_match.group(1)
        r4_to_issue[item["r4"]] = (num, out)
        print(f"Created {item['r4']} -> issue #{num} ({out})")
        os.remove(tmp_body)
        time.sleep(2)

    # attach repro scripts as comment with note? Task says "self-contained repro attached"
    # Attach repro file via gh issue comment with --body-file referencing? GH doesn't support
    # attaching files via CLI directly except through markdown; we will upload repro content
    # inline in a follow-up comment containing the script in a code block.
    for item in manifest["new_issues"]:
        r4 = item["r4"]
        num, url = r4_to_issue[r4]
        # find repro script path from front matter
        raw = open(os.path.join(BASE, item["file"]), encoding="utf-8").read()
        fm_match = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
        front = fm_match.group(1)
        rs_match = re.search(r"repro_script:\s*(.+)", front)
        if not rs_match:
            continue
        repro_rel = rs_match.group(1).strip()
        repro_path = os.path.join(BASE, repro_rel)
        if not os.path.exists(repro_path):
            print(f"WARNING: repro script missing for {r4}: {repro_path}")
            continue
        script_text = open(repro_path, encoding="utf-8").read()
        comment_body = (
            f"Standalone repro script for {r4} (exits 1 while the defect is present, "
            f"0 once fixed):\n\n```python\n{script_text}\n```\n"
        )
        tmp_comment = os.path.join(BASE, f"_tmp_repro_{r4}.md")
        with open(tmp_comment, "w", encoding="utf-8") as f:
            f.write(comment_body)
        run([GH, "issue", "comment", num, "-R", REPO, "--body-file", tmp_comment])
        os.remove(tmp_comment)
        time.sleep(2)

    # Step 3: post the 19 comments
    reopened = []
    for c in manifest["comments"]:
        num = str(c["issue"])
        path = os.path.join(BASE, c["file"])
        run([GH, "issue", "comment", num, "-R", REPO, "--body-file", path])
        time.sleep(2)
        if c["action"] == "comment+reopen":
            run([GH, "issue", "reopen", num, "-R", REPO,
                 "--comment", "Reopening: see comment above — narrowly scoped residual unmet by code."])
            reopened.append(num)
            time.sleep(2)

    # Step 4: substitute placeholders in meta-26.md
    meta_path = os.path.join(BASE, manifest["meta"]["file"])
    meta_raw = open(meta_path, encoding="utf-8").read()

    def repl(m):
        r4id = m.group(1)
        if r4id not in r4_to_issue:
            return m.group(0)
        num, _ = r4_to_issue[r4id]
        return f"#{num} ({r4id})"

    meta_new = re.sub(r"<(R4-\d+)>", repl, meta_raw)

    # strip the "Replacement body" header note lines before posting as actual issue body
    # (Those first two lines are instructions, not the actual body.)
    body_lines = meta_new.splitlines()
    # find first '---' separator after front instructions
    if body_lines[0].startswith("# Replacement body"):
        # drop until first line that's just '---'
        idx = None
        for i, line in enumerate(body_lines):
            if line.strip() == "---":
                idx = i
                break
        if idx is not None:
            meta_new = "\n".join(body_lines[idx+1:]).lstrip("\n")

    tmp_meta = os.path.join(BASE, "_tmp_meta26.md")
    with open(tmp_meta, "w", encoding="utf-8") as f:
        f.write(meta_new)
    run([GH, "issue", "edit", "26", "-R", REPO, "--body-file", tmp_meta])
    os.remove(tmp_meta)

    # Save mapping for verification / ledger
    with open(os.path.join(BASE, "_r4_mapping.json"), "w", encoding="utf-8") as f:
        json.dump({k: v[0] for k, v in r4_to_issue.items()}, f, indent=2)
    with open(os.path.join(BASE, "_reopened.json"), "w", encoding="utf-8") as f:
        json.dump(reopened, f, indent=2)

    print("DONE")
    for k, v in r4_to_issue.items():
        print(k, "->", v[1])
    print("Reopened:", reopened)

if __name__ == "__main__":
    main()
