# Independent recheck: #218 (delayed-send timer-handle leak on fire/cancel)

## Method
Standalone repro (stdlib + xstate_statemachine only), neutral cwd `<home>`,
venv-main python, both engines: 200-beat heartbeat + explicit cancel-before-fire,
`_timer_handles` counted directly.

## First pass — apparent false negative, then resolved
My first cancel check used fire-and-forget `await i.send({"type": "CUT"})` on the
async engine and saw `held_after == 1` (leak). This was **my repro's bug, not the
library's**: `Interpreter.send()` without `wait=True` schedules delivery via
`asyncio.ensure_future` / an internal task and returns before that task has run a
single loop iteration, so `_cancel()`'s `_release_timer_handle` call had not yet
executed when I sampled `_timer_handles`. Re-running with either `await i.send(...,
wait=True)` (receipt awaited, guaranteeing the cancel action has actually executed)
or a fire-and-forget send followed by a few `await asyncio.sleep(0)` drain turns
gives `held_after == 0`, matching the sync engine and the shipped test suite.

## Verified behaviour (both engines)
- 200-beat heartbeat (`raise(delay=10)` self-arm ping-pong `up`/`down`): ≥150 beats
  fire, `_timer_handles` holds ≤1 live handle throughout — no per-beat growth.
- Explicit `cancel(sendId=...)` before the timer fires: handle count goes 1 → 0 on
  both sync and async engines once the cancel action has actually run.
- Code check: async `_deliver`'s `_cancel` closure (interpreter.py ~2443) calls
  `self.clock.clear_timeout(handle)`, `_settle_debt()` (which itself calls
  `_release_timer_handle`), and `_armed_self_sends.pop` — so the release is present
  and reached; sync engine's two `_release_timer_handle` call sites (fire path and
  cancel path, sync_interpreter.py ~1190/1199) are likewise present and symmetric.

## Verdict
**218 | VERIFIED FIX — no defect | fire-and-forget send() needs a loop turn to
observe cancellation's effects; once drained/awaited, handle count is bounded (≤1)
on both engines for heartbeats and explicit cancels.**
