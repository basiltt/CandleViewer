import json, re, pathlib
SRC = pathlib.Path(r"C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/docs/plan/28-statechart-catalogue.md")
lines = SRC.read_text(encoding="utf-8").splitlines()
spans = {"B16": (5071, 5232), "B17": (5330, 5437), "B18": (5519, 5656),
         "B19": (5743, 5938), "B20": (6047, 6181)}
for b, (s, e) in spans.items():
    body = "\n".join(lines[s:e-1])
    body = re.sub(r'(?m)\s*//.*$', '', body)
    cfg = json.loads(body)
    pathlib.Path(b + ".catalogue.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(b, cfg["id"], cfg.get("actionErrorPolicy"), cfg.get("onUnhandled"),
          "wildcard" if '"*"' in body else "-", "halted" if "halted" in body else "-")
