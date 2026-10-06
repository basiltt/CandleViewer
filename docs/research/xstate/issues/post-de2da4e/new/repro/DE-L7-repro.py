"""DE-L7 repro: engine_* factories are unprefixed and importable from a
public module; _replace on a private engine subclass preserves the
engine-minted marker rather than downgrading to the public class.
STANDALONE: stdlib + xstate_statemachine only. Run from cwd C:/Users/basil.
"""
import sys as _xs_sys  # noqa: E402
from pathlib import Path as _XsPath  # noqa: E402
_xs_sys.path.insert(0, str(_XsPath(__file__).resolve().parents[4] / "gate"))
from _paths import REPO_ROOT as _REPO, XSTATE_SRC as _XS, upstream_main_python as _xs_main_py  # noqa: E402,F401
import sys
sys.path.insert(
    0,
    str(_XS / 'src'),
)
import xstate_statemachine as x
from xstate_statemachine.events import (
    engine_done, is_system_event,
)

# 1. engine_* factories are plain, unprefixed module-level functions --
#    not exported via __all__, but freely importable from the module.
print("engine_done in package __all__:", "engine_done" in x.__all__)
print("directly importable from events module:", engine_done)

# 2. _replace on a private engine subclass re-mints a genuine engine event
#    with the same subclass, i.e. still trusted as engine-owned.
ev = engine_done("done.invoke.fill", {"x": 1}, "fill")
print("original is_system_event:", is_system_event(ev))
mutated = ev._replace(data={"y": 2})
print("type after _replace:", type(mutated))
print("mutated is_system_event:", is_system_event(mutated))
