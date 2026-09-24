# Refuted before filing — R12-03: engine-event provenance is forgeable

**NOT POSTED. Never will be. Retained as method evidence.**

**Filed severity:** Blocker. **Verdict after independent refutation: REFUTED — Info-level hardening option only.** Build: `main` @ `de2da4e`.

## The claim

Engine-minted event classes (`_EngineDone`, `_EngineAfter`, …) can be forged or retyped, so `is_system_event()` is not a trustworthy provenance signal and a user-supplied event can impersonate a completion.

## Why it is refuted

Re-ran the original repro at `de2da4e` and built a **full vector matrix**. **Not one vector uses only the public API.** Every one requires a capability that is already strictly greater than the thing it buys:

| Vector | Capability required | Already implies |
|---|---|---|
| import a private `_`-prefixed class | in-process privileged code | can monkeypatch the interpreter outright |
| poke the private `_provenance` slot on a frozen dataclass | same | same |
| `_replace`-retype an engine-minted event | **already holding one** — reachable only from code running inside the machine's own actions/services | that code can already transition the machine arbitrarily |
| unpickle attacker-controlled bytes | arbitrary code execution | everything |
| `restore_event({"engine": true})` | authoring snapshot bytes | the documented `from_snapshot` trust boundary — and `configuration`/`context` can be written directly |

**The public-API paths behave correctly, which is the actual test:**

- `is_system_event(DoneEvent(...))` → **False**. A user-constructed public event is not mistaken for engine traffic.
- A forged snapshot record **without** the `engine` flag restores as ordinary user traffic.

**Subclass preservation across `_replace` / pickle / deepcopy is documented intent**, not an oversight — the `events.py` #195 block and `_EngineMark.__reduce__` / `__deepcopy__` exist precisely so persisted inboxes and defensive copies keep their provenance. Removing it would break the feature it implements.

**Upstream comparison:** XState v5 provides no stronger guarantee — internal events there are structural and convention-named. SCXML §5.10 treats the queue as engine-internal.

**Precedent:** the same in-process trust boundary already accepted in R10-01 and R11-01.

## The error in the claim, named

**"Type identity is not a capability" attacks a capability claim the library never makes.** The engine classes mark provenance for *the engine's own* dispatch decisions; they were never advertised as an authentication mechanism against in-process code. A threat model in which attacker code is already running inside the process has no remaining boundary for an event class to defend.

## Residual — Info

Optional hardening, offered without a severity: override `_replace` on the private subclasses to return the **public** class. It costs little and it removes the one vector that looks alarming in a code review even though it is unreachable from outside the machine's own logic. We are not requesting it.

## Method note

Third round running that a provenance Blocker died on a control probe, and the second in this round alone (with R12-02). Recorded as **standing amendment 16** in our gate: *a row asserting a security property must state the minimum capability it presumes and carry a control showing what that capability achieves **without** the finding.* If the control achieves as much as the exploit, the row is hardening, not a defect.
