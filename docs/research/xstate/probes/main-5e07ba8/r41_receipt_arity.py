"""Receipt gained a 4th field. Unpacking code written against 0.8.0 breaks."""
import sys
sys.path.insert(0,"<workspace>/_ref/xstate-statemachine/src")
from xstate_statemachine.events import Receipt
r=Receipt(frozenset(), False, None)
try:
    ids, changed, err = r
    print("3-tuple unpack: OK")
except ValueError as e:
    print("3-tuple unpack BREAKS:", e)
print("len(Receipt):", len(r), "| ==-compat with 3-tuple:", r == (frozenset(), False, None))
