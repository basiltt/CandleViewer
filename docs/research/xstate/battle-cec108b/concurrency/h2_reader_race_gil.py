"""(h) Control: is the concurrent-reader race specific to free-threading?

h1 V4 found 58 exceptions in 144 reads on 3.13t -- `RuntimeError: Set
changed size during iteration` from `current_state_ids` (which comprehends
over `_active_state_nodes`, base_interpreter.py:556) and `deque mutated
during iteration` from `queue_depth`/`pending_events` (which does
`list(q._queue)`, interpreter.py:1026).

This runs the IDENTICAL reader loop on the ordinary GIL build. If the GIL
build is clean, the race is real but currently masked by the GIL holding
across the C-level iteration -- i.e. it is a 3.13t/future hazard, not a
present defect on supported builds. If the GIL build also trips, it is a
present defect.
"""
import asyncio, sys
from h1_free_threading import v4_racy_readers
from common import emit

async def main():
    import sysconfig
    r = await v4_racy_readers()
    emit("h2_reader_race_gil", {
        "build": sys.version,
        "Py_GIL_DISABLED": sysconfig.get_config_var("Py_GIL_DISABLED"),
        "gil_enabled_at_runtime": sys._is_gil_enabled() if hasattr(sys,"_is_gil_enabled") else "n/a",
        "v4_racy_readers": r,
    })

asyncio.run(main())
