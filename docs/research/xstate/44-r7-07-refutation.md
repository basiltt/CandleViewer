# R7-07 adversarial refutation — a root snapshot harvests a child actor's half-applied context

**Verdict: CONFIRMED (High).** Refutation attempted on four axes; all failed.

## 1. Original repro re-run (commit 221ce7c)

`battle-221ce7c/semantics/repro/d7s3_child_midentry_torn_actor_blob.py`:

```
root in flight during child entry : False
live child after settle           : ['kid.y'] ctx={'q': 100, 'p': 101}
root snapshot during child entry  : ACCEPTED child=['kid.y'] ctx={'q': 0, 'p': 0}
root snapshot during child entry  : ACCEPTED child=['kid.y'] ctx={'q': 100, 'p': 0}   >>> TORN
```

Reproduced exactly as filed.

## 2. "API misuse — you snapshotted from inside an action" — REFUTED

This is the strongest available defence and it does not hold. The documented
contract (`docs/api/index.md:715`, `_guide/snapshots.md:134`,
`_guide/troubleshooting.md:56`) says a snapshot must be taken **from a settled
interpreter**, and names "from inside an action" as the misuse. The original
probe used an `on_action_execute` hook, so the objection is at least colourable
there — but the tearing survives removing the hook entirely.

Correct-usage variant (`/tmp/r7/correct_usage.py`, preserved below): no plugin,
no action hook. The child's entry action is `async def` and awaits, so the
child is mid-entry while the **caller's own coroutine** — an ordinary settled
caller — takes the root snapshot:

```
root in flight : False
kid  in flight : True
ACCEPTED ['kid.y'] {'q': 100, 'p': 0} >>> TORN
settled ctx    : {'q': 100, 'p': 101} ['kid.y']
```

The caller is doing precisely what the docs prescribe: it holds a settled root
(`_step_in_flight()` False) and calls `get_persisted_snapshot()` from outside
every action. The blob is still torn. An `async def` entry action is a
first-class documented feature on the async engine, and nothing in
`_guide/snapshots.md` warns that a live child actor makes a settled root
unsafe to persist. **Not API misuse.**

## 3. "Documented behaviour" — REFUTED

`snapshots.md:137` states legality is checked "on both sides" and that
mid-transition regions are refused. `docs/api/index.md:715` advertises the
snapshot as capturing "the full actor hierarchy". No page documents that the
child half of that hierarchy is captured under a *weaker* rule than the root.
The inline comment at `base_interpreter.py:1385-1391` (#169) records the
correct reasoning and then applies it only at the root:

> "Legality is a necessary condition, not a sufficient one: inside an ENTRY
> action the new leaf is already active (legal) while the context that entry
> is still writing is half-applied."

The very next clause keeps legality as the test for the child branch
(`if not self._configuration_is_legal(): self._await_settled_for_snapshot()`,
line 1393-1395). That is a deliberate but unjustified asymmetry, not a
documented contract. A comment explaining a known-insufficient test is not
documentation that the resulting blob may be torn.

## 4. "XState v5 agrees" — NOT AVAILABLE AS A DEFENCE

XState v5's `actor.getPersistedSnapshot()` likewise recurses into children, but
v5 actions are synchronous and run to completion inside a single microstep on a
single thread: there is no interleaving point at which an external caller can
observe a child between two entry actions. The window this finding exploits —
an `async def` entry action yielding the event loop, or a sync child stepping
on its own actor thread — does not exist in v5. v5 therefore neither sanctions
nor contradicts the behaviour; it is an artefact of this library's concurrency
model and must be adjudicated on this library's own stated contract, which it
violates.

## 5. "Duplicate of a closed issue" — REFUTED

#102 (refuse mid-step), #142/#143 (legality, not any-leaf), #169 (in-flight
alone refuses at root) are all closed and all sit on this exact code path.
None covers it: #169 explicitly *narrowed* its fix to the root. Confirmed
against the 0.8.1 `[Unreleased]` round-6 list (#166–#175, #157, #122) — no
entry addresses child-branch snapshot tearing.

## 6. Silent-restore half of the claim — CONFIRMED

`/tmp/r7/restore.py` round-trips the torn blob:

```
restored: ['kid.y'] {'q': 100, 'p': 0} error= None status= running
```

`from_snapshot` accepts it, `error is None`, `status == "running"`. The
configuration is legal, so neither `_repair_configuration` nor the #142/#143
restore-side legality check has anything to object to. The corruption is
purely in context and is undetectable by every guard the library ships.

## 7. Compounding with R7-08

The bounded wait meant to cover this case is doubly inert here. First, its
guard `not self._configuration_is_legal()` is false during a child entry
(one leaf, legal), so `_await_settled_for_snapshot` is never entered at all.
Second, even when entered on the async engine it spins `time.sleep` on the
event-loop thread (R7-08), so the child it waits for cannot progress. The
mitigation cannot fix R7-07 without both being corrected.

## Verdict

**CONFIRMED at High.** Financial-OMS reading: a persisted order hierarchy can
record a child order in state `filled` with `filled_qty` half-written, restore
clean with `status="running"` and `error=None`, and no library-side check will
ever flag it. Not Blocker only because it requires a snapshot concurrent with a
child's step rather than occurring on every persist; the read side has no
detection, which is what holds it at High rather than Medium.

Fix direction: apply #169's own rule symmetrically — `_step_in_flight()` on a
recursed child should trigger the settle wait unconditionally (not only when
the configuration is illegal), and that wait must be loop-aware (R7-08).
