# SEMANTICS battle track — v0.9.1

Target: tag v0.9.1 = 45bb7f3, main = 801eacd (merge commit only, `git diff v0.9.1..HEAD` empty).
`__version__` 0.9.1, imported from the clone's `src`. Full test suite (separate run):
**3601 passed, 13 skipped, coverage 92.93%.**
Scripts and outputs are in `battle-v0.9.1/semantics/`. Every script runs standalone with
cwd `<home>`.

## 1. Prior scripts re-run (`prior_rerun/*.out`)

| Script | Result | Notes |
|---|---|---|
| a_identity.py (A1–A6, #225/#232) | 6/6 PASS | no change |
| b_persist.py (B1–B5) | 4/5; B1 **SUPERSEDED** | B1 checked `type(latch).__name__ == "RestoredError"`. Since #243 the latch is `RestoredChainError`, whose MRO is (RestoredError, RunawayChainError). All the other B1 checks pass: trips monotonic, message byte-stable, clear keeps the counter, legacy upcast gives 0/None, a new trip gives +1. N5 below re-checks the type with `issubclass`. |
| c_conc_fuzz.py (C1–C4) | 4/4 PASS | determinism check: 50 runs per lane, 1 distinct trace in each |
| k_soak.py | PASS (**shortened**: 90 s, 200 machines, not 12 min) | 0 external dropped, 0 hook dropped, 0 chain trips, 440/440 chaos restores, 0 RuntimeWarnings, handles flat at 400, RSS +8.7 MB and flat for the last 60 s |

Round-13 semantics defects: **#239, #240, #243, #244, #245 and #246 are FIXED** (N2–N7 below).
#248 is fixed but opens a new hole: see D14-semantics-1.

## 2. New attacks (`n_r13.py` → `n_r13.out`)

| ID | Attack | Result |
|---|---|---|
| N1 | re_mint changes a completion's type to `done.invoke.victim` under strict | **FAIL on async**: see D14-semantics-1 |
| N2 | drain→persist→restore→start, 300 random mixes of priority and inbox events | 300/300. pending_events == drained == expected order (priority first). Each event delivered exactly once, in order. |
| N3 | restored_from_snapshot after 20 chained restores (sync); 100 concurrent restores + double start (async) | flags correct; on_interpreter_start fired exactly once, with restored=True |
| N4 | 1000 `def` actions each drop a wait=True receipt | dropped_receipts=1000, hook=1000, transitions=1000 |
| N5 | RestoredChainError isinstance matrix | IS-A RunawayChainError, RestoredError, XStateMachineError ✔ |
| N5b | SyncInterpreter kwargs | max_queue_size=None accepted; max_queue_size=5 → ValueError ✔; overflow_policy="drop" is accepted and ignored. That matches the docstring ("ignored unless a bound is requested"), so it is **not a defect**. |
| N6 | chain-field fuzz, 300 blobs × 2 engines (None/-1/2**70/1.5/"7"/True/[]/{}/NaN …) | 538 SnapshotCorruptError, 62 ok, **0 untyped** |
| N7 | drain_pending during 16 concurrent senders + an in-flight macrostep, 20 rounds | nothing lost, nothing duplicated; every wait=True receipt settled (the ones for drained events settled as InterpreterStoppedError) |
| N8 | forged chain fields in the snapshot blob | still gate nothing (prior B5 PASS) |
| N9 | PEP 740 attestation | PyPI's integrity endpoint returns an attestation bundle for the 0.9.1 wheel. The signature was not verified cryptographically (see §4). |

## 3. Defects

### D14-semantics-1 — `re_mint(type=...)` forges a different completion (HIGH, security)

`events.re_mint` checks only that its input is engine-minted. It then lets the caller override
**any** field, `type` and `src` included, and the result is still marked as engine-minted. The
test is simple: capture any benign engine completion, for example `done.invoke.benign` from a
plugin's `on_event_received`, and re-mint it as `done.invoke.victim`. The async engine accepts
it under `strict` and takes the victim's `onDone` transition while the victim service is still
running. User-built and `_replace`-demoted copies of the same event are refused with
UnknownEventError.

This breaks the #248 promise that re_mint "can carry provenance forward but never create it".
In effect it creates provenance for a completion the engine never produced. Our spec for the
round was that a re_mint mutation "must never drive a transition the original could not".

Other shapes tested:
- **Cross-kind** (an AfterEvent retyped to `done.invoke.victim`): the result keeps the
  `_EngineAfter` class and did **not** drive the transition (value stayed `b`).
- **Sync engine**, same chart: did not transition. In that repro the victim service raised, so
  the invocation was already gone. Not proven safe for a sync victim that is still pending.

Location: `src/xstate_statemachine/events.py:661-702` (`re_mint`; fields go unchecked into
`_EngineDone(*original._replace(**fields))`).

Suggested fix: refuse `type`/`src` overrides, or any change that alters the event's identity,
in re_mint. Allow only payload fields (`data`, `fired_at`, `error`).

Repro: `repro_d14_sem.py` → `repro_d14_sem.out`. The core of it, standalone:
```python
import asyncio, json, logging
from xstate_statemachine import Interpreter, MachineLogic, create_machine
from xstate_statemachine.plugins import PluginBase
from xstate_statemachine import events as E
logging.disable(logging.CRITICAL)
CFG = {"id": "v", "initial": "a", "strict": True, "states": {
  "a": {"invoke": {"id": "benign", "src": "benign", "onDone": "b"}},
  "b": {"invoke": {"id": "victim", "src": "victim", "onDone": "PAID"}}, "PAID": {}}}
class Cap(PluginBase):
    def __init__(s): s.ev = []
    def on_event_received(s, i, e): s.ev.append(e)
async def victim(i, c, e): await asyncio.sleep(30)
async def main():
    cap = Cap()
    i = await Interpreter(create_machine(CFG, logic=MachineLogic(
        services={"benign": lambda i, c, e: 1, "victim": victim}))).use(cap).start()
    while i.value != "b": await asyncio.sleep(0.01)
    src = next(e for e in cap.ev if e.type == "done.invoke.benign")
    await i.send(E.re_mint(src, type="done.invoke.victim", src="victim"))
    await asyncio.sleep(0.3); print(i.value)   # -> PAID  (victim still sleeping)
    await i.stop()
asyncio.run(main())
```
Observed:
- hand-built DoneEvent → UnknownEventError
- `_replace` → UnknownEventError
- `re_mint(data=)` → stays `b`
- `re_mint(type=victim)` → **PAID**

Trust boundary: the attacker needs a captured engine event, meaning plugin or in-process code.
The #235 / #248 design, however, treats provenance as a boundary *against* in-process code
that only handles events. So this falls inside what the release claims to protect, not
outside the documented trust boundary.

## 4. Not covered / reduced
- Soak: 90 s instead of 12 min (HARD BOUNDS). The prior v0.9.0 12-min soak passed.
- Livelock fuzzer: the prior C-suite ran at its built-in size. The ≥500 configs × kinds ×
  engines sweep was not scaled up this round.
- re_mint fuzz: targeted type/src/data mutations only (N1 + cross-kind), not a random fuzz.
- Determinism with restored_from_snapshot / dropped_receipts in the trace: covered only by the
  exactly-once counts in N3/N4, not by a 50× trace comparison.
- Attestation: bundle is present; the Sigstore signature was not verified cryptographically.
- Sync engine with a still-pending victim service and a re-minted forged done: not tested.

## 5. Verdict

The persistence, concurrency, observability and typing fixes are all verified closed. One
**HIGH** new defect remains: D14-semantics-1, re_mint type forgery on the async engine. It is
the exact question this round was asked to settle.

**Semantics track: NOT READY for a financial OMS while it is open.** Mitigation until fixed:
forbid `events.re_mint` in our codebase via a lint rule, and keep plugins trusted. With that
mitigation the remaining semantics surface is GO.
