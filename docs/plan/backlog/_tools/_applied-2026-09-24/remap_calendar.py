"""ONE-SHOT (applied 2026-09-24): remap plan docs from the 2-week human calendar
(Mon 2026-09-28 start) to the 1-week AI calendar (Fri 2026-09-25 start).
DO NOT RE-RUN — dates are already on the new calendar."""
import re, sys, os, datetime, glob, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from calendar_cv import old_to_new
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
LO, HI = datetime.date(2026, 9, 26), datetime.date(2027, 10, 15)   # plan horizon only
DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
DUR = re.compile(r"(:\s*(?:crit,\s*|done,\s*|active,\s*|milestone,\s*)?[a-z0-9_]+,\s*20\d\d-\d\d-\d\d,\s*)(\d+)d\b")

def remap_dates(text):
    def f(m):
        try: d = datetime.date.fromisoformat(m.group(1))
        except ValueError: return m.group(0)
        if not (LO <= d <= HI): return m.group(0)
        return old_to_new(d).isoformat()
    return DATE.sub(f, text)

def remap_gantt(text):
    # working days (10 per sprint) -> calendar days (7 per sprint)
    def f(m):
        n = int(m.group(2)); return m.group(1) + str(max(1, round(n * 7 / 10))) + "d"
    text = DUR.sub(f, text)
    return text.replace("    excludes weekends\n", "")

files = ["docs/plan/30-release-roadmap.md", "docs/plan/31-sprint-plan.md",
         "docs/plan/26-chart-engine-design.md", "docs/plan/01-sdlc-and-branching.md",
         "docs/plan/00-planning-brief.md", "docs/plan/07-release-and-prr.md",
         "docs/plan/17-ux-diagrams.md", "docs/plan/32-risk-register.md", "docs/plan/33-raci.md"]
files += sorted(os.path.relpath(g, ROOT) for g in glob.glob(os.path.join(ROOT, "docs/plan/backlog/E*.json")))
tot = 0
for rel in files:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p): continue
    s = open(p, encoding="utf-8").read()
    n = remap_dates(s)
    if rel.endswith("30-release-roadmap.md"): n = remap_gantt(n)
    if n != s:
        c = sum(1 for a, b in zip(DATE.findall(s), DATE.findall(n)) if a != b)
        tot += c; print(f"{rel}: {c} dates remapped")
        open(p, "w", encoding="utf-8", newline="\n").write(n)
print("total", tot)
