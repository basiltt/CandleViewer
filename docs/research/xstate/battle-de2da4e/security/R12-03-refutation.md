# R12-03 (High) — "Engine provenance classes remain forgeable" — REFUTED (→ Info)

Repros re-run at de2da4e from neutral cwd `C:/Users/basil`:
`attack_01_r901_engine_done_forgery.py` (reproduces: forged `_EngineDone`
drives a real `onDone` while the service runs) and new
`attack_01b_r1203_vectors.py` (vector matrix).

| Vector | is_system | Capability required |
|---|---|---|
| V1 public `DoneEvent("done.invoke.svc",…)` | **False** | none — #195 fix holds |
| V1b `object.__setattr__(Event,"_provenance",_ENGINE_MARK)` | True | import private module attr |
| V2 `_replace` retype of a genuine engine event | True | must already hold an engine-minted event |
| V3 pickle/deepcopy round-trip of a genuine event | True | same — and this is **by design** (`_EngineMark.__reduce__`/`__deepcopy__`) |
| V3b crafted pickle naming `_EngineDone` | True | attacker controls unpickling of arbitrary bytes = arbitrary code execution anyway |
| V4 `restore_event({... "engine": True})` | True | documented snapshot trust boundary |
| V4b `restore_event` without the flag | **False** | forged record correctly degrades to user traffic |

## Why refuted
1. **No vector uses only the public API.** Every path needs one of:
   importing a private `_`-prefixed name, poking a private slot on a frozen
   dataclass, holding an event the engine itself handed you, or feeding
   attacker-controlled pickle bytes. In in-process Python each of those is
   equivalent to monkeypatching `is_system_event` outright; there is no
   language-level private access to defeat, so "importable" is not a
   crossable boundary.
2. **The surviving behaviours are documented intent, not oversight.**
   `events.py` (#195 block) states that engine-minted subclasses keep the
   subclass across "`_replace`, pickle and deepcopy" deliberately, so a
   persisted inbox / multiprocessing hand-off / defensive `deepcopy` keeps
   provenance; `_EngineMark` exists as a named singleton precisely for this.
   CHANGELOG #195/#203 and `from_snapshot` state the snapshot payload is
   trusted input by contract (`machine_hash` is a fingerprint, not a MAC) —
   the same R10-01/R11-01 pattern already accepted.
3. **V2 (retype) needs engine-delivered input**: only code running inside
   the machine's own actions/services can hold a genuine `_EngineDone`, and
   that code can already transition the machine arbitrarily. No escalation.
4. **Upstream parity.** XState v5 has no cryptographic provenance either;
   internal event types are structural and any actor may `send` them —
   protection is by naming convention, which this library exceeds.

Residual (Info, defence-in-depth, optional): `_replace`-retype could be
closed by overriding `_replace` on the private subclasses to return the
public class. Not a defect at the documented boundary.
