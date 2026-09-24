# R8-05 — Adversarial refutation: forged `DoneEvent` / `AfterEvent`

**Claim (high):** `DoneEvent`/`AfterEvent` carry no provenance marker and are
exempt from `strict`/`onUnhandled`; a forged completion drives a real `onDone`.

**Verdict: CONFIRMED (high).** Every refutation avenue was tried and failed.

## Reproduction

`battle-6db65d8/persistence/r10_doneevent_forgery.py` → `VERDICT: FAIL`,
6 failures across both service kinds. Re-run on commit 6db65d8 venv-main.

Surface (unchanged from the claim):

```
DoneEvent   has .system=False  has ._provenance=False  base=tuple
AfterEvent  has .system=False  has ._provenance=False  base=tuple
Event       has .system=True   has ._provenance=True   base=object
```

`events.py:125-135` defines `_provenance` (`init=False`) and the read-only
`system` property on the `Event` dataclass **only**. `DoneEvent` (:145) and
`AfterEvent` (:453) are plain `NamedTuple`s. There is nothing to forge because
there is nothing to check.

## The trust predicate makes it worse, not incidental

`events.py:272-282`:

```python
def is_system_event(event: Any) -> bool:
    if isinstance(event, ENGINE_EVENT_TYPES):   # DoneEvent/ErrorEvent/AfterEvent
        return True
    return isinstance(event, Event) and event._provenance is _ENGINE_MARK
```

Measured on hand-built objects (`r10_forgery_refute.py` §B):

| object built by user code | `is_system_event` | `event_kind` |
|---|---|---|
| `DoneEvent(type="done.invoke.k", data={}, src="k")` | **True** | `done` |
| `AfterEvent(type="after.1.x")` | **True** | `after` |
| `Event(type="done.invoke.k")` | False | `event` |

`docs/api/index.md:1193` states the decision "is made by **provenance**, not by
name … `is_system_event` is the single predicate all three consult". For the two
NamedTuple classes the predicate is `isinstance`, which is *type*, not
provenance — and the type is publicly constructible. So the documented invariant
is false exactly for the classes whose entire semantic content is "the engine
authored this".

## Both service kinds fail (financial-OMS standard)

`r10_forgery_refute.py` / `r10_forgery_def2.py`, real clock, live hanging invoke:

| kind | forged `DoneEvent('done.invoke.k')` | outcome |
|---|---|---|
| `async def` | `['sec.a'] → ['sec.done_']`, `ctx.got={'forged':True,'px':9e9}` | **onDone driven by forgery while the real service still runs** |
| `def` | stays `['sec.a']`, no raise, `status=running` | **silently swallowed: `strict=True` did not reject, `onUnhandled:"error"` did not fire** |

Controls on the same machine: `Event('done.invoke.k')` (same *name*, user
provenance) is enforced — `status=error` under async. The real completion moves
the machine. So the difference is purely the class, not the name.

The `def` result is **not** a defence: it is a different failure of the same
root cause. The event is accepted into the hierarchy as trusted and then
discarded without matching (`def` invokes settle through
`run_in_executor` → `_finish_plain_service`, interpreter.py:2813/2837, a
different bookkeeping lane), so the caller gets neither the transition nor the
`UnknownEventError`/`onUnhandled` signal that the same string as an `Event`
would produce. Data-loss-silently vs. wrong-transition — both are R8-05.
Timing was ruled out: settles of 0.5/1.0/2.0 s against an 8 s service all
swallow, and the loop is not blocked (executor hand-off).

## Refutation avenues attempted — all fail

1. **"Documented / internal-only, so API misuse."** No. `DoneEvent` and
   `AfterEvent` are exported from the package root (`__init__.py:93-94`,
   `__all__` :223-224) and documented as public constructible types with a
   field table (`docs/api/index.md:1090`). `AfterEvent`'s docstring says a
   developer "typically does not create this event manually" — *typically*,
   and a docstring aside is not an enforcement boundary. Contrast `Event`,
   where #85 deliberately **removed** the public `system=` parameter rather
   than documenting "please don't pass it". The hardening covers the one class
   users were expected to construct and omits the two that assert engine
   authorship.
2. **"Correct usage exists; use it instead."** There is no alternative. The
   engine's own mint path (`system_event`) covers plain `Event` only; there is
   no `done_event()` factory and no private constructor. `send()` accepts
   `DoneEvent` explicitly in its signature and `_coerce_event`
   (base_interpreter.py:954/967, interpreter.py:750-941 type unions) — the
   library's typed API advertises this call. Using the API as typed and
   documented produces the vulnerability, which is the definition of *not*
   API misuse.
3. **"XState v5 agrees."** It does not. In XState v5 completion events are
   emitted by the actor system; `sendTo`/`actor.send` of a `done.invoke.*`
   shape does not resolve an `onDone` for a still-running invoked actor,
   because `onDone` is bound to the child actor's lifecycle, not to an event
   name on the queue. The Python port reduces the binding to a
   `event.src == inv.id` name/field match (base_interpreter.py:4484-4490) with
   no liveness check against the actually-running invocation — note the
   forged event fires `onDone` while the genuine service is mid-flight, and
   the real completion later has nowhere to land.
4. **"Duplicate of a closed issue."** No. #79/#85/#137/#180 are the provenance
   line and all terminate at the `Event` dataclass; #162 hardened the *v1
   snapshot* name-laundering path. None touches the NamedTuple classes.
   R8-05 is the residue those fixes left behind.

## Escalating factor: no in-process misuse is required

`restore_event` (`events.py:392-395`) reconstitutes a `DoneEvent` from an
attacker-authored record with no signature or provenance check
(`r10_forgery_snapshot.py`):

```
record  {"kind":"done","type":"done.invoke.k","data":{"forged":true,"px":9e9},"src":"k"}
     -> DoneEvent(type='done.invoke.k', ...)   is_system_event=True
```

and that restored object drives `onDone` on a live machine (async) exactly as
the hand-built one does. Snapshot blobs carry `machine_hash` but no integrity
tag over `pending_events`, so any process that can write a persisted snapshot
can inject a trusted service result. This is a wire vector, not only a
in-process one — which is why the `high` severity stands rather than being
downgraded to a "don't do that" documentation note.

## Impact for an order/execution use case

A forged `done.invoke.<fill-service>` carries arbitrary `data` straight into
`onDone` actions and thus into context — a fabricated fill price/quantity
committed while the genuine venue call is still outstanding, with the real
completion arriving to a state that has already moved on. Under `def` services
the same event is swallowed with no error at all, defeating `strict` as a
detection control.

## Suggested fix direction (not applied — library source untouched)

Give the three engine NamedTuples the same sentinel treatment as `Event`
(engine-only factories, `is_system_event` checking the marker rather than
`isinstance`), and re-derive provenance at the `restore_event` boundary the way
#162 did for v1 records instead of trusting `kind`.

## Artefacts

- `battle-6db65d8/persistence/r10_doneevent_forgery.py` (original repro, FAIL)
- `battle-6db65d8/persistence/r10_forgery_refute.py` (predicate + both kinds)
- `battle-6db65d8/persistence/r10_forgery_def.py`, `r10_forgery_def2.py`
  (`def` path is swallow-not-immunity)
- `battle-6db65d8/persistence/r10_forgery_snapshot.py` (restore-boundary vector)
