# R6-01 adversarial refutation — async `send(wait=True)` livelock

**Verdict: CONFIRMED (Blocker).** Refutation attempted on five axes; all failed.

## Reproduction (unmodified repro)

`battle-cec108b/fuzz/m9_send_hang_min.py`, commit cec108b, fresh venv:

```
async maxIterations=1        HANG (no receipt after 5.0s)  status=running stop() ok
async maxIterations=1000     HANG (no receipt after 5.0s)  status=running stop() ok
sync  baseline               returned in 0.04s states=['m.a.a'] ok=False err=RunawayChainError
always removed               resolved 0.00s
invoke removed               resolved 0.02s
external (non-internal) GO   HANG
HANGS: 3
```

Both ingredients necessary, as claimed. Parity break with the sync engine is real.

## Mechanism (instrumented, `m9c_instrumented.py`)

Patching `Interpreter._process_event` over a 3 s hang window with `maxIterations: 1`:

```
{'done.invoke.i': 11532, '<always>': 11532}  total 23064
qsize 1   _raise_depth 0
```

Livelock, not queue growth — inbox pinned at 1, RSS flat, ~4 k events/s, 4.0 s of
user CPU burned per 4 s wall (`psutil`, one core saturated). The claim's
characterisation is exact.

Root cause is narrower than "`always` chain never terminates". The lap is
`always` → re-enter `m.a.a` → restart `invoke i` → `done.invoke.i` →
`always` … . The `done.invoke.i` leg is an **engine completion**, and
`interpreter.py:1427` deliberately exempts system events from the chain-budget
cut (`if self._raise_depth > limit and not is_system_event(event)`), added for
#120 so a completion is never dropped. `_raise_depth` reads 0 at the hang, so
the budget is not merely being out-voted — it is never charged, because every
second lap is a system event and the counter resets. The cycle is *conservative*
(dequeue one, enqueue one), which is precisely the shape #144 named. The fix for
#144 landed in `sync_interpreter.py` only (`RunawayChainError` at lines 823/942);
`interpreter.py` has no equivalent "chain ends only when nothing self-generated
remains" condition, so the receipt at the macrostep exit is never constructed.

The `always` is not load-bearing as `always`. A plain `invoke.onDone` that
re-enters its own ancestor — i.e. the literal #144 configuration, no `always`
anywhere — reproduces on async (`m9b_144_async_analogue.py`):

```
async start ok ['m.p.w']       # start() settles
async send  HANG
sync  start returned 0.00s err RunawayChainError
```

So this is **#144 reopened on the async engine**, and the CHANGELOG's
"a chain now ends only when nothing self-generated remains queued" is true of
one engine of two.

## Refutation axes, all failed

1. **Documented?** No. `docs/_guide/json-config.md:110` states `maxIterations`
   bounds "eventless (`always`) microsteps while settling, and unbroken chains of
   self-`raise` / self-`send()` / sync `done.invoke` events", and promises a trip
   is observable via `receipt.error` / `last_error` / `on_event_dropped`. Here no
   trip occurs and no receipt is ever produced on async.
   `troubleshooting.md:49` says `RunawayChainError` is "reported on
   `receipt.error` / `last_error`, **never raised** (0.8.1)" — the documented
   contract is exactly the one violated. Note "sync `done.invoke`" in that
   sentence is the only hint the async engine differs, and it describes the bug,
   not a deliberate exclusion: the async engine's own guard *intends* to bound
   the rollback→re-arm cycle ("It still counts toward the depth (below) so a
   rollback->re-arm cycle stays bounded", `interpreter.py:1418`) and fails to.
2. **API misuse / missing mandatory config?** No. `maxIterations` is optional
   with a default, and both 1 and 1000 hang; `strict` is irrelevant (probed both
   ways via `strict=False` and default). No configuration key exists that would
   bound this.
3. **Sync engine?** The sync engine is the *control*, and it behaves correctly —
   that is what makes this a parity defect rather than a shared design limit.
4. **Superseded semantics?** No superseding note in `[Unreleased]`; #144 is
   listed as fixed, not as sync-only. `tests/test_round5_findings.py:331`
   ("#144 — conservative invoke cycle is bounded by maxIterations") pins the sync
   engine only, which is why the gate stayed green.
5. **XState v5 agrees?** No. v5 bounds transient/microstep loops and raises
   rather than spinning (the library's own comment at `interpreter.py:1678`
   cites "XState added the same guard in v5.31.0"), and v5 has no engine-event
   exemption that would let a completion-fed cycle run unbounded. v5's
   equivalent config errors out; it does not livelock an event loop.
6. **Duplicate of a closed issue?** It is the async half of #144 (closed in
   `[Unreleased]`). That strengthens rather than refutes: a fix claimed complete
   is half-shipped, and the reopened-issue pattern (#118/#122/#125/#133/#134 were
   all reopened for exactly this sync/async parity reason) recurs here.

## Severity

Blocker stands, and is arguably understated for an OMS: the failure is a
**silent unbounded await** on `send(wait=True)` — the recommended
request/response spelling — combined with a **saturated event-loop core**, so
every timer, actor and inbound send on that interpreter stalls too
(`status` still reports `"running"`, so liveness checks pass). No timeout, no
receipt, no `last_error`, no `on_event_dropped`. Caller-side
`asyncio.wait_for` is the only mitigation, and it leaves the loop burning.

Recommended fix: port the #144 termination condition into
`Interpreter._run_event_loop` — end a macrostep's chain only when nothing
self-generated remains queued, and charge engine completions to the chain
budget (keep the #120 no-drop guarantee by *failing the chain* with
`RunawayChainError` on the receipt instead of discarding the completion).
Add async-engine cases to the #144 pin in `tests/test_round5_findings.py`.

Artefacts: `battle-cec108b/fuzz/m9_send_hang_min.py` (original),
`m9b_144_async_analogue.py` (`always`-free #144 analogue),
`m9c_instrumented.py` (event census / livelock proof).
