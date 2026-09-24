# -*- coding: utf-8 -*-
"""Build post-3ed3099/manifest.json."""
import glob, json, os, re, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
NEW = os.path.join(HERE, "new")

# Canonical severity per the normative register (33-…) §2 + §10 counts
# table, which is normative. Row-by-row it yields 4 Blocker / 9 High /
# 7 Medium / 1 Low; the register's own §10 headline says "8 High, 8 Medium",
# which is off by one on R5-11 (§2 and verdict §5 both list it as High).
# The per-finding table governs. R5-10 and R5-11 also carry a stale
# `severity: low` in their draft front matter; overridden here.
SEV = {
    "R5-01": "Blocker", "R5-02": "Blocker", "R5-04": "Blocker", "R5-12": "Blocker",
    "R5-03": "High", "R5-05": "High", "R5-06": "High", "R5-07": "High",
    "R5-08": "High", "R5-09": "High", "R5-10": "High", "R5-13": "High",
    "R5-11": "High",
    "R5-14": "Medium", "R5-15": "Medium", "R5-16": "Medium",
    "R5-17": "Medium", "R5-18": "Medium", "R5-19": "Medium", "R5-20": "Medium",
    "R5-21": "Low",
}
SEVLABEL = {"Blocker": "severity/blocker", "High": "severity/high",
            "Medium": "severity/medium", "Low": "severity/low"}
ORDER = {"Blocker": 0, "High": 1, "Medium": 2, "Low": 3}

# The repo's label set has no `area/semantics` or `area/observability`; map the
# two drafts that used them onto the nearest existing area label.
AREA_FIX = {"area/semantics": "area/interpreter",
            "area/observability": "area/receipts"}
VALID = (set("bug enhancement documentation performance meta tracking".split())
         | {"severity/" + s for s in "blocker high medium low".split()}
         | {"area/" + a for a in ("interpreter sync-interpreter actors persistence "
                                  "timers validation perf docs events plugins "
                                  "receipts").split()})


def front(path):
    txt = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
    if not m:
        raise SystemExit("no front matter: " + path)
    fm = {}
    for line in m.group(1).split("\n"):
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip()
    return fm


new_issues = []
for p in sorted(glob.glob(os.path.join(NEW, "*.md"))):
    fm = front(p)
    if fm.get("status", "").strip().strip('"') == "not-reproduced":
        continue
    rid = fm["r5"].strip().strip('"')
    title = fm["title"].strip()
    if title.startswith('"') and title.endswith('"'):
        title = title[1:-1].replace('\\"', '"')
    labels = [s.strip() for s in fm["labels"].strip("[]").split(",") if s.strip()]
    labels = [AREA_FIX.get(l, l) for l in labels]
    # drop duplicates introduced by the area remap, preserving order
    seen, dedup = set(), []
    for l in labels:
        if l not in seen:
            seen.add(l); dedup.append(l)
    labels = dedup
    # normalise the severity label to the canonical register severity
    labels = [l for l in labels if not l.startswith("severity/")]
    labels.insert(1 if len(labels) > 1 else len(labels), SEVLABEL[SEV[rid]])
    bad = [l for l in labels if l not in VALID]
    if bad:
        raise SystemExit("unknown label(s) %r on %s" % (bad, rid))
    new_issues.append({
        "file": "new/" + os.path.basename(p),
        "r5": rid,
        "title": title,
        "labels": labels,
        "_sev": SEV[rid],
    })

new_issues.sort(key=lambda d: (ORDER[d["_sev"]], d["r5"]))
for d in new_issues:
    d.pop("_sev")

CLOSED = "91 99 102 103 104 105 106 107 108 109 110 111 112 113 114 115 116 117 119 120 121 123 124 126 127 128 129 130 131 132 135 136 137 138".split()
PARTIAL = "118 122 125 133 134".split()

comments = []
for n in CLOSED:
    comments.append({"issue": int(n), "file": "comments/%s.md" % n, "action": "comment"})
for n in PARTIAL:
    comments.append({"issue": int(n), "file": "comments/%s.md" % n, "action": "comment+reopen"})
comments.sort(key=lambda d: d["issue"])

manifest = {
    "new_issues": new_issues,
    "comments": comments,
    "meta": {"issue": 26, "file": "meta-26.md"},
}

p = os.path.join(HERE, "manifest.json")
open(p, "w", encoding="utf-8", newline="\n").write(
    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

from collections import Counter
c = Counter(l for d in new_issues for l in d["labels"] if l.startswith("severity/"))
print("new_issues:", len(new_issues), dict(c))
print("comments:", len(comments),
      "comment=%d" % sum(1 for x in comments if x["action"] == "comment"),
      "comment+reopen=%d" % sum(1 for x in comments if x["action"] == "comment+reopen"))
for d in new_issues:
    if not os.path.exists(os.path.join(HERE, d["file"])):
        print("MISSING", d["file"])
for d in comments:
    if not os.path.exists(os.path.join(HERE, d["file"])):
        print("MISSING", d["file"])
