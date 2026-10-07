# Independent recheck — #243, #244, #245, #246 (v0.9.1)

Environment: v0.9.1 checkout (801eacd, tag 45bb7f3 + CI-only merge commit),
installed wheel `xstate_statemachine-0.9.1-py3-none-any.whl`, fresh venv,
standalone stdlib+library-only repros run from neutral cwd `<home>`.
Full suite (3614 tests) running green in parallel per `suite-v0.9.1.log`
(observed through test_interpreter_send_receipt.py, no failures/hangs).

Repro: `repro_243_246.py` in this directory.

## #243 — RestoredChainError IS-A RunawayChainError AND RestoredError
`RestoredChainError("msg")` (real ctor — 1 positional message arg, not
`limit=`/`dropped=` kwargs) is `isinstance` of both `RunawayChainError` and
`RestoredError`; `.limit`/`.dropped` are `None`, `.stranded == ()`. Matches
CHANGELOG and `tests/test_round13_findings.py` assertions exactly.
**CLOSED.**

## #244 — dropped wait=True receipt observable without warning filters
A `def` (sync, non-awaitable-capable) action does `interp.send("B",
wait=True)` and discards the returned wrapped receipt. After `gc.collect()`,
`interp.dropped_receipts == 1` and the `on_receipt_dropped` plugin hook fired
with `event_type="B"` — asserted with no `warnings.catch_warnings()` around
the counter checks (a `RuntimeWarning` is also emitted, as documented, but
the counter/hook are independent of any `-W` filter). Machine still drove
`s1->s2->s3` (`status == "done"`): dropped-receipt semantics don't affect
transition execution, matching the changelog note "Transition behaviour is
unchanged." **CLOSED.**

## #245 — SyncInterpreter(max_queue_size=..., overflow_policy=...) parity
Verified against the actual docstring/impl (`sync_interpreter.py::__init__`),
not just the one-line brief paraphrase: **only `max_queue_size` is checked.**
A non-`None` `max_queue_size` raises a `ValueError` containing "no inbox to
bound" and "wrapper" (matches `TestSyncInterpreterHasNoInboxBound`).
`overflow_policy` alone (with `max_queue_size=None`) is accepted and the
interpreter runs normally — it only matters paired with a bound, and a bound
is refused regardless of policy. `(None, None)` is accepted.

Flagging a **false-negative risk in the computed task text**, not the
library: the brief phrases this as "raising ValueError if non-None" for
*either* kwarg, which would predict `overflow_policy=<anything>` alone also
raises. It does not, and per the source docstring is not supposed to
("accepted for signature parity; ignored unless a bound is requested"). This
is the intentional, documented, tested contract, not a stale-script issue in
the fix — but a recheck script written to the brief's paraphrase would
false-flag this as unfixed. Confirmed against `tests/test_round13_findings.py
::TestSyncInterpreterHasNoInboxBound::test_parity_keywords_with_none_are_accepted`,
which passes `overflow_policy=OverflowPolicy.RAISE` with `max_queue_size=None`
and expects success. **CLOSED** (as shipped and as documented/tested;
brief's paraphrase is imprecise, no code change needed).

## #246 — production_characteristics.py --json / --json-file
`benchmarks/production_characteristics.py --json` (run from the source
checkout, since the script ships in the repo/sdist, not inside the
*wheel's* purelib — confirmed by walking up from the installed package
`__file__` and finding it only in the checkout, not under
site-packages) emits one JSON object with a host block containing
`library_version, python_version, python_implementation, platform, machine,
processor, cpu_count, method` plus measured rows. Matches
`TestBenchmarkJson::test_host_info_has_the_documented_keys`. **CLOSED.**
Note: this script is a dev/CI benchmark tool, not part of the installed
package surface — its absence from the wheel is expected and not a defect.

## Verdict lines

243 | CLOSED | RestoredChainError is-a both RunawayChainError and RestoredError, verified live.
244 | CLOSED | dropped_receipts + on_receipt_dropped fire deterministically under any warning filter; transitions unaffected.
245 | CLOSED | max_queue_size non-None raises documented ValueError; overflow_policy alone is accepted-by-design (brief's "either" wording is imprecise, not a code defect).
246 | CLOSED | --json emits full host block + rows from the repo script; expected to be absent from the wheel (dev/CI tool).
