"""Is a v2 snapshot rejected cleanly by older code? Simulate 0.8.0 by setting
SNAPSHOT_VERSION=1 and checking the error surface."""
import sys
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine import persistence as P
from xstate_statemachine.exceptions import SnapshotVersionError
P.SNAPSHOT_VERSION=1
try:
    P.check_version({"version":2})
except SnapshotVersionError as e:
    print("v2 read by 0.8.0-era code ->", type(e).__name__)
    print("message:", e)
