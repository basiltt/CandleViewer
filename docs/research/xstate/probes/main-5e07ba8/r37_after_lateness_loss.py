"""persist_event() for kind='after' stores ONLY `type`. AfterEvent's
`scheduled_for` / `fired_at` (#48 lateness telemetry) are silently zeroed."""
import sys
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine.events import AfterEvent, persist_event, restore_event
ev=AfterEvent(type="after.5000.m.pending", scheduled_for=1000.0, fired_at=1007.5)
print("original  :", ev, "lateness_ms=", getattr(ev,"lateness_ms",None))
rec=persist_event(ev); print("record    :", rec)
b=restore_event(rec); print("restored  :", b, "lateness_ms=", getattr(b,"lateness_ms",None))
print("VERDICT: telemetry fields silently lost ->", (b.scheduled_for, b.fired_at) != (ev.scheduled_for, ev.fired_at))
