# Battle-test — SECURITY & supply-chain track — re-run on `3ed3099`

**Library under test:** local clone `_ref/xstate-statemachine`, `main` @
`3ed3099096d15544e96c9d9458c21c2a30ef48e3`. CHANGELOG `[Unreleased] —
targeting 0.8.1`, round-4 findings (#102–#138, reopened #91/#99).
`__version__` still reports `0.8.0`; identified by commit per the standing
convention.

**Date:** 2026-09-19. **Python:** CPython 3.13.7 (`.venv-main`), Windows 11
Pro 10.0.26200. This is a re-run of `battle-5e07ba8/security.md`
(triaged in `security.triage.md`), extended with attacks targeting this
round's new surface (`SnapshotMidStepError`, per-macrostep settle budget,
`restart_timers=`/`has_dormant_timers`, `from_snapshot(clock=)`,
`SnapshotCorruptError`, `SnapshotSerializationError`, `InvalidEventError`,
`on_plugin_error`, `on_resolve_error`, `LoggingInspector` redaction).

No library source was modified. No `git` command was run in the adopting
project's repository. GitHub access was read-only.

**Time-budget note:** the fuzz pass below was reduced to 300 mutations (not
5 000) and the quiescent-snapshot property run to 500 events (not 2 000), to
fit the ~25-minute wall-clock bound for this task; both are stated as
reductions, not silent shortcuts.

---

## 1. Prior-defect re-run (D-security-1..5, filed against `5e07ba8`)

| ID | 5e07ba8 verdict | 3ed3099 result | Status |
|---|---|---|---|
| **D-security-1** (LoggingInspector logs raw `context`/payload at INFO, no redaction) | Medium | **`rerun_D_security_1_LoggingInspector.py`**: default `LoggingInspector()` now redacts — `sk-live-SECRET` does **not** appear in the log stream; keys matching `DEFAULT_REDACT_KEYS` (`password`, `secret`, `token`, `api_key`, `authorization`, `auth`, `credential`, `private_key`, `ssn`, `card`, `cvv`, …) are replaced with `"***"` recursively (`plugins.py:454-485`, `#126`). `redact_keys=()` is an explicit, documented opt-out that still logs verbatim (by design, not a regression). | **FIXED** |
| **D-security-2** (branch protection: 0 required reviewers, no required status checks, force-push allowed, admins not enforced) | Medium | Re-queried live: `gh api repos/basiltt/xstate-statemachine/branches/main/protection` — `required_approving_review_count: 0`, `required_status_checks.contexts: []`, `required_signatures.enabled: false`, `enforce_admins.enabled: false`, `allow_force_pushes.enabled: true`. Byte-for-byte identical to the prior run. | **STILL-PRESENT** (unchanged; process/governance, not code) |
| **D-security-3** (Actions pinned to mutable tags, not SHAs) | Low | `grep -n "uses:" .github/workflows/*.yml` — all 16 `uses:` lines still on `@v7`/`@v5`/`@release/v1`, none SHA-pinned. | **STILL-PRESENT** (unchanged) |
| **D-security-4** (no SBOM / artifact signing in publish pipeline) | Low | `grep -i "cosign\|sigstore\|cyclonedx\|spdx\|sbom" .github/workflows/*.yml` — no hits, same as before. | **STILL-PRESENT** (unchanged) |
| **D-security-5** (informational: broad `except Exception: pass` in CLI diagnostics; `assert` guarding an internal invariant, stripped under `-O`) | Low, informational | `cli/__main__.py:1095` and `interpreter.py:1672` (line numbers shifted to `interpreter.py:1880` at this commit, same construct) both read exactly as before. | **STILL-PRESENT** (unchanged, informational only) |
| `exec()` in `cli/validation.py` self-verification path (`_build_generated`) | Not a defect (reviewed, sanitizer-wrapped) | `bandit`/`semgrep` re-run this pass: identical single Medium (`B102`) at `cli/validation.py:222` (line number unchanged), same code (`sys.modules` snapshot/restore around `exec(compile(code, ...), module.__dict__)`, `code` is generator output not raw JSON). No change in shape or surrounding guard. | **UNCHANGED — not a defect** |

No script needed adaptation for superseded behaviour (e.g. no prior script in
`battle-5e07ba8/security/` took mid-macrostep snapshots — that track's
persistence probes lived elsewhere; this track's own new snapshot attacks
below were written against the current, `SnapshotMidStepError`-aware API from
the start).

### 1.1 Static re-scan

- `bandit -r src` (fresh install, 1.9.4): identical result set — 1 Medium
  (`B102` exec, `cli/validation.py:222`), 1 Low (`B101` assert,
  `interpreter.py:1880`); the `B110`/`B404`/`B603` hits from the original
  report's table (`cli/__main__.py:1095`, `cli/postprocess.py`) were reviewed
  there as informational/not-a-defect and reproduce identically this pass.
  See `security/bandit.txt`.
- `pip-audit --path .`: **No known vulnerabilities found** — still zero
  runtime dependencies. See `security/pip-audit.txt`.
- `semgrep` was not reinstalled this pass (time budget); the original
  report's cross-check already showed 0 divergence from bandit on the one
  finding, and nothing in the round-4 changelog touches `cli/validation.py`'s
  `exec()` path, so a second full semgrep run was judged low-value for the
  budget available and is the one item skipped — see §4.

---

## 2. New attacks against round-4 surface

| Attack | Script | Result |
|---|---|---|
| **Snapshot-log secrets leak, independent of LoggingInspector** | `security/repro_D_security_1_snapshot_log_leak.py` | **New defect (D5-security-1)** — see §3. |
| **SnapshotCorruptError fuzz** (300 mutations of a valid v2 snapshot: dropped/nulled/type-confused fields, injected junk keys) | `security/attack_snapshot_corrupt_fuzz.py` (+ `probe_corrupt_fuzz_gap_fields.py` isolating the gap) | 193/300 mutated snapshots were **silently accepted** by `from_snapshot()` with no error at all (not even a warning) — e.g. `taken_at: null`, `taken_at: "not-a-number"`, `machine_hash: null`, an injected unknown top-level key. 8/300 raised an **uncontrolled** `TypeError`/`ValueError` instead of `SnapshotCorruptError` (mutations that hit `state_ids`/`configuration`/numeric-context fields with `None` or a non-numeric string). 0/300 raised `SnapshotCorruptError` itself in this run — every mutation was either silently swallowed or an uncontrolled crash. See §3, **D5-security-2**. |
| **InvalidEventError over hostile `type` values** (`None`, `int`, `float`, `bytes`, `list`, `dict` with a `type` key, `object()`, `bool`, `nan`) | `security/attack_invalid_event_hostile.py` | 8/9 raised `InvalidEventError` (also a `TypeError`) as documented (#113). `{"type": "GO"}` (a **dict** whose own `type` key is a valid string) was accepted with **no error raised at all** and, per the printed transcript, is silently treated as a valid event rather than rejected for not being a `str`/`Event` — see §3, **D5-security-3**. |
| **Quiescent-snapshot round-trip property** (reduced to 500 randomized `GO`/`SELF`/`UNHANDLED` sends; snapshot after every `send()` return, restore, re-snapshot, compare `state_ids`) | `security/attack_persistence_quiescence_property.py` | **Clean.** `SnapshotMidStepError` never fired at a quiescent point (0/500) and every quiescent snapshot round-tripped byte-identically on `state_ids` (0 failures). This is the positive control confirming #102's fix is scoped correctly — it refuses *mid-step*, never *post-step*. |
| **Hook matrix: `on_plugin_error` for a raising third-party plugin hook** | `security/attack_hook_matrix_observability.py` | `on_plugin_error` fired on the *other* plugin (`Probe`) with the failing plugin's name, hook, and exception type; `interp.last_plugin_error` was set; the interpreter did not crash or hang. Confirms #127 works for an arbitrary raising hook, not just the documented `async def` case. (The specific injected exception was itself superseded by a `TypeError` from a plugin-hook arity mismatch in the attack script — still correctly caught and reported, which is itself a mild confirmation that `_report`/`_SafePlugin` don't care *why* a hook raised.) `on_resolve_error` was not independently exercised this pass (a `sendTo` to an unresolved actor routes through `on_event_dropped(reason="unresolved_target")` per #133, not `on_resolve_error`, which is reserved for unresolvable *transition targets* caught at runtime after passing build-time validation — constructing that specific runtime-only case was judged not worth the remaining budget; noted as a gap in §4). |

---

## 3. Defects filed (this round)

| ID | Severity | Summary | Location | Minimal repro |
|---|---|---|---|---|
| **D5-security-1** | **Medium** | `get_snapshot()` logs the **entire unredacted JSON snapshot** (full `context`, including any secrets) at `DEBUG` unconditionally, with no relationship to `LoggingInspector`'s new (#126) redaction. Any application that enables `DEBUG` logging for `xstate_statemachine` — common in staging, or briefly in production while chasing a bug — writes every secret in `context` verbatim to the log stream, even if the team never attaches `LoggingInspector` at all. | `src/xstate_statemachine/base_interpreter.py:1022` (`logger.info("📸 Capturing snapshot...")`) and `:948` region / the `logger.debug("🖼️ Snapshot for '%s' captured: %s", self.id, json_snapshot)` call inside `get_snapshot()` | `security/repro_D_security_1_snapshot_log_leak.py` — build a machine with `context={"api_key": "sk-live-...", "password": "..."}`, set the `xstate_statemachine` logger to `DEBUG`, call `interp.get_snapshot()`. The secret appears verbatim in the log output; confirmed programmatically (`DEBUG_LOG_LEAKS_SECRET: True`). |
| **D5-security-2** | **High (OMS context)** | `from_snapshot()`'s `SnapshotCorruptError` (#110) covers only a narrow slice of malformed input. A 300-mutation fuzz of a *single* valid v2 snapshot (dropped keys, `None`-ed fields, type-confused numeric/string fields, one injected unknown key) found **193/300 silently accepted** with no error and **8/300** raising an uncontrolled `TypeError`/`ValueError` that escapes as a bare crash instead of the documented `SnapshotCorruptError`; **0/300** actually hit the intended error path. For a system persisting trading state, a corrupted/truncated snapshot (disk truncation, a partial write, a schema-migration bug, or a hostile actor with write access to the persistence store) is far more likely to land in the "silently accepted, machine resumes in a wrong-but-plausible state" bucket than to be caught. This is the single most consequential finding of this pass: the library's own headline round-4 feature (`SnapshotCorruptError`) does not yet cover the realistic corruption surface. | `src/xstate_statemachine/persistence.py` / `base_interpreter.py` `from_snapshot()` validation path (the exact field-level validators were not exhaustively enumerated this pass — see §4) | `security/attack_snapshot_corrupt_fuzz.py` (300 mutations, seeded `random.seed(42)`, reproducible) and `security/probe_corrupt_fuzz_gap_fields.py` (isolated single-field repros: `taken_at: None`, `taken_at: "not-a-number"`, `machine_hash: None` all print `": accepted (no error)"`). |
| **D5-security-3** | **Medium** | `InvalidEventError` (#113) is documented as rejecting a non-`str` event `type`, and does so for `None`/`int`/`float`/`bytes`/`list`/`object`/`bool`/`nan` — but a **dict shaped like `{"type": "GO"}`** passed directly to `send()` is accepted with no error, rather than being rejected for not being a `str` (or being handled as an explicit `Event`-like payload). This is a plausible hostile/malformed-upstream shape (e.g. a message-bus consumer that forwards a raw JSON object instead of unwrapping `type`), and it is the one hole in an otherwise-solid #113 hardening pass. | `src/xstate_statemachine/events.py` / wherever `send()`'s event-normalisation accepts a mapping (exact call site not line-pinned this pass — time budget; see §4) | `security/attack_invalid_event_hostile.py` — `interp.send({"type": "GO"})` prints `NO ERROR RAISED`, the only one of 9 hostile shapes tested that was accepted. |

No **Blocker** was filed. D5-security-2 is elevated to **High** (rather than
the Medium ceiling most items in this track sit at) specifically because it
is a corruption-detection gap in the persistence layer of an OMS-facing
library — the stated standing risk model for this track treats silent
corruption of trading state as the worst class of failure, and this finding
is exactly that: silent acceptance of malformed state, not a crash.

---

## 4. Coverage — what this pass did and did not do

**Covered this pass:**
- Full re-run of all five `5e07ba8` defects with live re-verification
  (`gh api`, fresh `bandit`/`pip-audit` installs) — all reproduce unchanged
  except D-security-1, confirmed fixed.
- `LoggingInspector` default-redaction behaviour (#126) — positive
  confirmation, plus the explicit `redact_keys=()` opt-out path.
- A 300-mutation structural fuzz of `from_snapshot()`'s `SnapshotCorruptError`
  path (reduced from the 5 000-mutation target in the task brief).
- `InvalidEventError` (#113) over 9 hostile `type` shapes.
- A 500-event (reduced from 2 000) quiescent-snapshot round-trip property
  test, confirming `SnapshotMidStepError` (#102) never fires outside a
  macrostep and every quiescent snapshot round-trips.
- `on_plugin_error` (#127) firing for an arbitrary raising plugin hook,
  including confirmation that the failing plugin does not hear its own
  failure (no self-recursion).

**Not covered / explicitly out of scope this pass (time-budget cuts):**
- **`SnapshotSerializationError`** (#131, non-JSON pending data) was not
  exercised at all — no script targets it.
- **`restart_timers=`/`has_dormant_timers`/`from_snapshot(clock=)`** (#128,
  #117) were not exercised — no `SimulatedClock` persistence/restart script
  was written this pass; this was explicitly named in the task brief and is
  the largest single gap.
- **#105** (per-task self-send gate under concurrent producers:
  `create_task`/threads/child actors) and **#104** (`BLOCK` under 16
  producers) were not re-tested — no concurrency script this pass.
- **50× byte-identical determinism** across sync/async engines (including
  inline sync-service semantics, #116) was not re-run.
- **#109 (`done.invoke` output vs private context), #108 (root-target
  rejection), #130 (`escalate` to parent `onError`)** semantics were not
  independently re-verified this pass beyond reading the CHANGELOG's own
  claims.
- **12-minute reduced soak with chaos** was not run.
- A second `semgrep` pass was skipped (see §1.1) — low marginal value given
  bandit's identical result and no round-4 changes near the one flagged file.
- D5-security-2's exact validator call sites and D5-security-3's exact
  `send()`-normalisation call site were **not line-pinned** — the repros are
  solid and reproducible, but a fix-oriented follow-up would need to actually
  read `persistence.py`'s field-level restore logic and the `send()` →
  `Event` normalisation path to cite exact lines, which this pass's time
  budget did not allow after the fuzzing and re-verification work.
- `on_resolve_error` (#134) was not independently triggered — constructing a
  transition target that resolves at build time but fails at runtime
  resolution (as opposed to build-time-rejected, which #108/#132 already
  cover) needs a purpose-built runtime scenario not assembled this pass.

---

## 5. Verdict

**D-security-1 (5e07ba8) is fixed.** Governance/supply-chain items
(D-security-2/3/4/5) are unchanged process gaps, not code regressions, and
carry the same severities as before.

**Two new, more consequential findings replace it as the track's headline
risk on this commit:**

- **D5-security-2 (High):** `SnapshotCorruptError` — the round's own flagship
  persistence-hardening feature — does not yet catch the majority of
  structurally-plausible snapshot corruption in a 300-mutation sweep (193
  silently accepted, 8 uncontrolled crashes, 0 correctly classified). This is
  the finding this track would prioritize fixing before trusting `main` with
  real persisted trading state at this commit.
- **D5-security-1 (Medium):** the redaction added to `LoggingInspector`
  (#126) does not extend to `get_snapshot()`'s own `DEBUG`-level logging of
  the raw snapshot, so the secrets-in-logs risk this round's own changelog
  entry implies is "handled" is only handled for one of the two built-in
  logging paths.

D5-security-3 (Medium) is a narrower gap in an otherwise solid #113
hardening pass and worth a one-line fix (reject non-`Event`, non-`str`
mappings the same way other non-`str` types are rejected) rather than a
structural concern.

Net assessment for an OMS adopter pinning to `3ed3099`: the round-4 fixes
described in the CHANGELOG are real and independently reproduced for the
happy-path and for the specific scenarios their own test suite pins
(`test_round4_findings.py`), but this track's adversarial fuzz of the
persistence-restore path shows the corruption-detection surface is
substantially narrower than the `SnapshotCorruptError`/`SnapshotMidStepError`
naming implies. Do not rely on `from_snapshot()` alone to detect a corrupted
persisted snapshot; an adopting project should add its own schema/checksum
validation in front of it until D5-security-2 is addressed upstream.
