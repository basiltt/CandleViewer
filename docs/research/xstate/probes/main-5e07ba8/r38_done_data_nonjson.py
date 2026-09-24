"""persist_event for kind='done' deepcopies DoneEvent.data straight into the
snapshot. A service returning a non-JSON object makes get_persisted_snapshot()
produce a payload that json.dumps() cannot serialise -- the snapshot write
fails AFTER the machine has accepted the completion."""
import sys, json, datetime, decimal
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine.events import DoneEvent, persist_event
for data in [{"when": datetime.datetime(2026,1,1)}, {"amt": decimal.Decimal("10.5")}, {"s": {1,2}}]:
    rec=persist_event(DoneEvent(type="done.invoke.f", data=data, src="f"))
    try:
        json.dumps(rec); print("JSON ok  :", rec)
    except TypeError as e:
        print("JSON FAIL:", type(data["when" if "when" in data else list(data)[0]]).__name__, "->", e)
