"""R0 -- extract THIS run's f2 B2-illegal-configuration repros into
out/q10_cfg.json (+ out/q10_cfg_N.json) so q10/q11 replay this build's own
captures rather than 221ce7c's."""
import json, sys

d = json.loads(open("out/f2_events.json", encoding="utf-8").read())
defs = d["defects"] if isinstance(d, dict) and "defects" in d else d
hits = [x for x in defs if "B2" in str(x.get("kind", ""))]
print(f"B2 hits: {len(hits)}")
for i, h in enumerate(hits):
    r = h.get("repro")
    if isinstance(r, str):
        r = json.loads(r)
    cfg = r["config"]
    open(f"out/q10_cfg_{i}.json", "w", encoding="utf-8").write(json.dumps(cfg))
    open(f"out/q10_evs_{i}.json", "w", encoding="utf-8").write(
        json.dumps(r.get("events", []))
    )
    print(f"  [{i}] engine={r.get('engine')} strict={r.get('strict')} "
          f"events={r.get('events')} sig={h.get('signature', h.get('kind'))}")
if hits:
    import shutil
    shutil.copy("out/q10_cfg_0.json", "out/q10_cfg.json")
    print("wrote out/q10_cfg.json from hit 0")
