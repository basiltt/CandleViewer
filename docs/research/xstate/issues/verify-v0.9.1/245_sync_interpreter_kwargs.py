"""Verify #245: SyncInterpreter(max_queue_size/overflow_policy) refuses non-None."""
from xstate_statemachine import create_machine
from xstate_statemachine.sync_interpreter import SyncInterpreter

CFG = {"id": "m", "initial": "a", "states": {"a": {}}}

def make():
    return SyncInterpreter(create_machine(CFG))

def check():
    make()  # None,None -> ok
    # max_queue_size non-None -> documented ValueError naming the alternative.
    try:
        SyncInterpreter(create_machine(CFG), max_queue_size=5)
        raise AssertionError("expected ValueError for max_queue_size=5")
    except ValueError as e:
        msg = str(e)
        assert "no inbox to bound" in msg, msg
        assert "wrapper" in msg, msg
    # overflow_policy alone (max_queue_size still None) is accepted/ignored
    # per docstring: "ignored unless a bound is requested".
    s = SyncInterpreter(create_machine(CFG), overflow_policy="DROP_NEWEST")
    s.start()
    s.send("T") if False else None
    print("OK #245")

if __name__ == "__main__":
    check()
