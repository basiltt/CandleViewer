# R12-04 — DE-L6 refuted: `SimulatedClock` restored `after` timer is dormant *by design*

**Status: REFUTED. Not filed.**
**Commit:** `de2da4e` (`__version__` 0.8.0, targeting 0.8.1)

## The claim as drafted

> `SimulatedClock` does not fire a restored after-timer following
> `from_snapshot` + `start()` — the interpreter stays parked in its
> pre-timer state.

The draft's root-cause section attributed this to a clock-binding-order
bug: *"if the re-arm in `_rearm_restored_self_sends` runs before `start()`
finishes binding `clk2` as `self.clock` ... the newly-created timer never
lands in `clk2._heap`."*

## Why it is refuted

The observation reproduces, but the diagnosis is wrong and the behaviour
is the documented default, not a defect.

### 1. `_rearm_restored_self_sends` is not the mechanism

An `after` timer is not a `scheduled_sends` record. Instrumenting the
draft's own scenario:

```
snapshot scheduled_sends : []
snapshot pending_events  : []
restored _restored_self_sends : []
r.clock is clk2 : True      (binding order is correct)
after start, clk2.pending : 0
```

`_persist_scheduled_sends` (`base_interpreter.py:1245`) records only
`self._restored_self_sends` plus `self._armed_self_sends` — i.e. delayed
**self-sends** from `raise(delay=)` (#213). A declarative `after` deadline
is not in either collection, so the snapshot's `scheduled_sends` is empty
and `_rearm_restored_self_sends` has nothing to re-arm. The clock is bound
correctly (`r.clock is clk2` is `True` before `start()`); nothing about
binding order is implicated.

### 2. Dormant `after` timers are opt-in by documented default

`from_snapshot` documents that it "by default restarts neither services
nor timers" (`docs/api/index.md:726`). `restart_timers` (#128) is the
opt-in, and it works exactly as specified on this commit:

```python
r = SyncInterpreter.from_snapshot(snap, m, clock=clk2, restart_timers=True)
r.start()
# clk2.pending == 1
clk2.increment(2000)
# state: ['m', 'm.done'], status: done
```

The timer fires on the `SimulatedClock`, on schedule.

### 3. The condition is not silent — it has a dedicated signal

`has_dormant_timers` (#128) is `True` for exactly this scenario, both
before and after `start()`:

```
has_dormant_timers (before start): True
has_dormant_timers (after start, no restart_timers): True
```

The API surfaces the state the draft called invisible. `docs/api/index.md:747`
describes it as "the timer counterpart of `has_dormant_invocations`;
cleared by `start()` with `restart_timers=True` (#128)."

### 4. #154 already fixed the real version of this bug

The draft's suspected mechanism — a restore branch returning before
`clock._attach()` — was a genuine bug, filed as #154 and fixed. The
comment at `sync_interpreter.py:313-317` records the fix, and
`_attach_clock()` now precedes `_rearm_restored_self_sends()` in both
restore branches (`sync_interpreter.py:317-318` and `338-339`).

## Verdict

Correct, documented, opt-in behaviour with a dedicated dormancy signal and
a prior fix (#154) covering the failure mode the draft suspected. Filing
this would ask the library to change a default its own API documents, and
would report as missing a control (`restart_timers=`) that exists and
works. **Not filed.**

## Residual

None as a defect. The only carry-forward is that our own restore paths
must pass `restart_timers=True` (or consult `has_dormant_timers`) when a
restored chart owns `after` deadlines — an adoption note, not a library
item.
