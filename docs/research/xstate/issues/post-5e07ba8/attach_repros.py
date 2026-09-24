import json, re, subprocess, sys, time, os

os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = "basiltt/xstate-statemachine"
BASE = os.path.dirname(os.path.abspath(__file__))
GH = "gh"

def run(cmd):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print("STDOUT:", r.stdout)
        print("STDERR:", r.stderr)
        raise SystemExit(f"command failed: {cmd}")
    return r.stdout.strip()

def main():
    manifest = json.load(open(os.path.join(BASE, "manifest.json"), encoding="utf-8"))
    mapping = json.load(open(os.path.join(BASE, "_r4_mapping.json"), encoding="utf-8"))

    for item in manifest["new_issues"]:
        r4 = item["r4"]
        num = mapping[r4]
        raw = open(os.path.join(BASE, item["file"]), encoding="utf-8").read()
        fm_match = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
        front = fm_match.group(1)
        rs_match = re.search(r"repro_script:\s*(.+)", front)
        repro_rel = rs_match.group(1).strip()
        # actual location is new/repro/<basename>
        basename = os.path.basename(repro_rel)
        repro_path = os.path.join(BASE, "new", "repro", basename)
        if not os.path.exists(repro_path):
            print(f"STILL MISSING for {r4}: {repro_path}")
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

    print("REPRO ATTACH DONE")

if __name__ == "__main__":
    main()
