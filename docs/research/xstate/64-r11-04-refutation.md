# R11-04 adversarial refutation — `_timer_handles` grows one entry per `raise(delay=)` beat

**Verdict: CONFIRMED — High.** Every refutation avenue failed.

## Reproduced (commit c78ce99, fresh venv, neutral cwd `<home>`)

| probe | result |
|---|---|
| `battle-c78ce99/semantics/repro/d11_sem_4_timer_handle_leak.py` | `after:10` 624 beats → **1** handle (0.002/beat); `raise(delay=10)` 624 beats → **624** handles (1.00/beat). `REPRODUCED: true`, leaking cells `raise_delay/plain`, `raise_delay/async` |
| `battle-c78ce99/persistence/x14_timer_handle_leak.py` (async) | 762 beats → 762 retained, **761 already fired**; control `after` 764 beats → 1 |
| same, `KIND=sync` | 766 beats → 766 retained; control 1 |
| `battle-c78ce99/persistence/x13_rss_attribution.py` (200 machines, 24 s) | idle +0.0 MB, `after` −0.1 MB, **`raise(delay=)` +455.4 MB**, heartbeat+ext+chaos +421.4 MB; trace strictly linear (170→284→393→500 MB), no plateau; recovered on `stop()+gc` |

## Refutation attempts — new probe `battle-c78ce99/refutation/r11_04_correct_usage.py`

Six postures × both engines × both `def`/`async def` action flavours, 6 s each:

| variant | handles/beat |
|---|---|
| A id-reusing ping-pong (supersede semantics) | 1.00 |
| B no send id | 1.00 |
| C long period (250 ms) | 1.00 |
| D single self-looping state (never exits) | 1.00 |
| E explicit `cancel(sendId)` before each re-arm | 1.00 |
| CTRL `after:10` | **0.00** |
| SYNC A ping-pong (`def`) | 1.00 |
| SYNC CTRL `after:10` | 0.00 |

- **API misuse? No.** There is no usage that bounds it. Id reuse, explicit `cancel`, and long periods all retain 1.00/beat — `_cancel` (interpreter.py:2383) calls `clock.clear_timeout` and pops `_armed_self_sends`, but never removes the handle from `_timer_handles`. Period only changes the *rate*, not the ratio. A never-exiting state is worst, since no state exit ever runs.
- **Documented? No.** `CHANGELOG [Unreleased]` #212/#213, `docs/_guide/json-config.md` (`maxIterations` row), `production-characteristics.md` and `snapshots.md` all *bless* a self-paced `raise(delay=)` heartbeat "of any period" as a legal periodic process and say nothing about handle retention. #212 is the new rule and it makes this worse, not excused: `grep -i leak/prune/reclaim` over the changelog shows #49/#200/#54 leak fixes but nothing for this path.
- **XState v5 / SCXML agree? No.** v5 `raise({delay})`/`sendTo` clean up the scheduled entry when the timer fires (`system.scheduler` deletes the scheduled id on `_clock`-fire); SCXML `<send delay=>` has no retained-record semantics. Nothing in either model requires keeping a fired timer handle.
- **Duplicate? No.** Round-10's register has no handle-retention item; round-10 soak was +1.2 MB because #206's chain trip killed such cycles at ~12 beats. Same mechanism, newly unbounded.
- **Measurement artefact? No.** Measured on the container itself (`len(i._timer_handles[i.id])`), not inferred from RSS; RSS is a corroborating second signal and the `after` control on the same harness is flat. Polled to convergence at 3/6/9/12 s and 6/12/18/24 s — strictly linear, no plateau or amortised trim.
- **Trust boundary (R10-01 pattern)? Not applicable.** No attacker input, no restore path, no untrusted config: the growth is produced by the machine's own blessed heartbeat.

## Mechanism (unchanged from the register, verified by reading)

`interpreter.py:2352-2354` registers the handle as `self._timer_handles.setdefault(self.id, []).append(handle)` — the **interpreter/machine** id. The sole pruner, `interpreter.py:2556-2557`, runs on state exit: `for handle in self._timer_handles.pop(state.id, [])`. The machine id is never an exiting state, so the list is append-only until `stop()` (`:1514-1517`). `_fire` (`:2323-2346`) settles the #213 debt and clears `_armed_self_sends`/`_scheduled_sends` but leaves the handle. The `after` path (`:2747-2748`) uses `owner_id=state.id` and *is* pruned. Sync engine identical: `sync_interpreter.py:1197-1198` vs. pruner at `:1488`.

Each retained `TimerHandle` pins its `_fire` closure → `target_event`, `handle_box`, `key`, and the interpreter — which is why RSS tracks it linearly.

Fix is one line on each engine: key the delayed-self-send handle by the owning state id (or discard it in `_fire`/`_cancel`).

## Severity

Hold at **High**: unbounded, sustained (no ceiling short of `stop()`), triggered by usage the library now explicitly endorses, reachable in every long-lived process, and it collides with R11-DC-2/K11 — `raise(delay=)` is the only restart-safe (#213) in-chart deadline primitive, so the recommended path to snapshot-safe deadlines is the leaking one. Not Critical: no corruption, no wrong semantics, recovered by `stop()`, and `after:` remains a leak-free workaround for deadlines that do not need `scheduled_sends`.
