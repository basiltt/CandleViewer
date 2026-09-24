"""Verify #243: RestoredChainError IS-A RunawayChainError AND RestoredError."""
from xstate_statemachine.exceptions import (
    RestoredChainError, RunawayChainError, RestoredError,
)

def check():
    assert issubclass(RestoredChainError, RunawayChainError)
    assert issubclass(RestoredChainError, RestoredError)
    e = RestoredChainError("latch-id")
    assert isinstance(e, RunawayChainError)
    assert isinstance(e, RestoredError)
    print("OK #243")

if __name__ == "__main__":
    check()
