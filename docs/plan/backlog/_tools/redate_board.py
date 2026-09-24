"""Re-apply Start/Due on every published item from calendar_cv (idempotent)."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from calendar_cv import sprint_dates
import publish_board as pb

led = json.load(open(pb.LEDGER_PATH, encoding="utf-8"))
tickets = pb.load_tickets()
by_key = {t["key"]: t for t in tickets}
todo = [(k, v) for k, v in led.items() if v.get("item_id") and k in by_key
        and "retired" not in (by_key[k].get("labels") or [])]
print("items:", len(todo))
batch, keys, failed = [], [], []
def flush():
    global batch, keys
    if not batch: return
    ok = pb.graphql_batch_raw(batch, aliases_per_call=15)
    for k in keys:
        sk = k.replace("-", "_")
        al = [a for a, _ in batch if a.startswith("d" + sk + "_")]
        if not all(ok.get(a) for a in al): failed.append(k)
    batch, keys = [], []
done = 0
for k, v in todo:
    s, e = sprint_dates(by_key[k].get("sprint"))
    if not s: continue
    sk = k.replace("-", "_")
    batch.append(("d%s_0" % sk, pb._mk_date(v["item_id"], pb.FIELD_IDS["Start"], s)))
    batch.append(("d%s_1" % sk, pb._mk_date(v["item_id"], pb.FIELD_IDS["Due"], e)))
    keys.append(k); done += 1
    if len(batch) >= 30:
        flush(); print("  [%d/%d]" % (done, len(todo)), flush=True); time.sleep(0.5)
flush()
print("re-dated:", done, "failed:", len(failed), failed[:20])
json.dump(failed, open(os.path.join(pb.HERE, "redate_failures.json"), "w"))
