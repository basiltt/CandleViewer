"""v1 upcast re-derives provenance BY NAME. A user event whose name happens to
match an engine shape is promoted to engine provenance on restore -- the exact
name-based rule #79 removed, reintroduced at the restore boundary."""
import sys
sys.path.insert(0,"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src")
from xstate_statemachine.events import restore_event, is_system_event, ENGINE_EVENT_SHAPES
print("ENGINE_EVENT_SHAPES:", ENGINE_EVENT_SHAPES)
for t in ["xstate.mine","after.party","done.invoke.NEVER","error.platform.fake","done.review","PAY"]:
    b=restore_event({"type":t,"payload":{"amount":1e9}})   # v1 record, no kind
    print(f"  v1 user event {t:22s} -> system={is_system_event(b)}")
