"""
221ce7c observability track re-run @ 6db65d8, ASYNC-SERVICE lane.

The original rerun_prior.py / new_attacks.py used def-only or no services at
all. Round-7's headline defect (R7-01) was that async def *service*
completions took a different, uncharged code path from def services and
from plain self-raised events. This script re-runs the subset of prior
attacks that involve a service, substituting async def services, to check
whether the round-7 fix (#179, _publish_completion / _chain_owed) closed
that lane for these observability-relevant behaviors too.

Run:
  PYTHONIOENCODING=utf-8 PYTHONUTF8=1 <venv>/python rerun_prior_async.py
"""
import asyncio
import time

from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    create_machine,
    PluginBase,
    RunawayChainError,
)


class Recorder(PluginBase):
    def __init__(self):
        self.calls = []

    def on_event_dropped(self, interpreter, event, reason):
        self.calls.append(("on_event_dropped", reason))


# --- M-async: service_pool_size=1, 50 ASYNC DEF services, stop() mid-flight
async def m_async_services_stop():
    cfg = {
        "id": "m_pool_async",
        "type": "parallel",
        "states": {
            f"r{i}": {
                "initial": "running",
                "states": {"running": {"invoke": {"src": f"svc{i}", "onDone": "done"}}, "done": {}},
            }
            for i in range(50)
        },
    }

    async def make_svc(i):
        async def svc(ctx, ev):
            await asyncio.sleep(0.05)
            return {"i": i}
        return svc

    services = {}
    for i in range(50):
        async def svc(interp_, ctx, ev, i=i):
            await asyncio.sleep(0.05)
            return {"i": i}
        services[f"svc{i}"] = svc

    logic = MachineLogic(services=services)
    machine = create_machine(cfg, logic=logic)
    interp = Interpreter(machine, service_pool_size=1)
    t0 = time.time()
    await interp.start()
    await asyncio.sleep(0.2)
    completed = sum(
        1 for i in range(50)
        if list(interp.current_state_ids and []) or True  # placeholder, real check below
    )
    # Count actually-done regions via configuration
    done_regions = sum(1 for sid in interp.current_state_ids if sid.endswith(".done"))
    await interp.stop()
    elapsed = time.time() - t0
    print(
        f"M-async service_pool_size=1 stop-mid-service: status={interp.status} "
        f"done_regions_at_stop~{done_regions}/50 elapsed={elapsed:.2f}s "
        f"last_error={interp.last_error!r}"
    )


async def main():
    await m_async_services_stop()
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
