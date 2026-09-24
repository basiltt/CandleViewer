# Battle-test — SECURITY & supply-chain track

**Library under test:** local clone `_ref/xstate-statemachine`, `main` @ commit
`5e07ba8842345a73ef8f830f0281de16370a7c74` (merge of PR #101). CHANGELOG
`[Unreleased] — targeting 0.8.1`. `__version__` still reports `0.8.0`; this
build is identified by commit, per the standing convention.

**Date:** 2026-09-18. **Python:** CPython 3.13.7 (`.venv-main`), Windows 11 Pro
10.0.26200. **Scope:** the security and supply-chain surface of a library that
will hold trading state for an order-management system — every silent
failure, secret-leak path, or unbounded-growth vector is treated as a defect,
per the standing instruction for this track.

No library source was modified. No `git` command was run in the adopting
project's repository. GitHub access was read-only for this entire track.

---

## 1. Method

| Step | Tool / command | Output |
|---|---|---|
| Static security lint | `bandit -r src -f txt -o security/bandit.txt` (bandit 1.9.4, installed fresh into `.venv-main`) | `bandit.txt` |
| Static security lint (2nd engine, cross-check) | `semgrep --config p/python --config p/security-audit src` (semgrep 1.177.0, 346 community rules, 43 files, 100% parsed) | `semgrep.txt` |
| Dependency / supply-chain audit | `pip-audit --path .` (pip-audit 2.10.1) | `pip-audit.txt` |
| Manual grep sweep | `eval|exec|pickle|marshal|yaml.load|subprocess|__import__|importlib` across `src/` | inline, this report |
| Dynamic-import surface | Read `logic_loader.py` (`logic_modules`, `logic_providers`), `cli/validation.py` (`_build_generated`), `cli/naming.py` (`docstring_safe`, `to_identifier`, `escape_for_string`) | this report |
| Snapshot reconstruction surface | Read `persistence.py`, `events.py` (`persist_event`/`restore_event`, the `kind` discriminator) | this report |
| Logging / secret-leak surface | Read `plugins.py` (`LoggingInspector`) | this report |
| DoS / unbounded-structure sweep | Grep for `DEFER_MAX`, `_SIBLING_FALLBACKS_WARNED`, `max_queue_size`, `_receipts`, `normalize_logic_name` | this report |
| Repo hygiene | `grep uses: .github/workflows/*.yml`, read `publish.yml`/`ci.yml`, `gh api repos/basiltt/xstate-statemachine/branches/main/protection` | this report |

Interpreter for every run: `_ref/xstate-statemachine/.venv-main/Scripts/python`
(or `.venv-main/Scripts/semgrep.exe` directly — `python -m semgrep` is
deprecated in 1.38+ and silently no-ops without erroring, which cost one
throwaway run; the direct executable was used for the real scan). All output
files are under `battle-5e07ba8/security/` alongside this report.

---

## 2. Results — static analysis

### 2.1 bandit (1.9.4), full source tree, default profile

19 254 lines scanned, 0 `# nosec` suppressions present anywhere (i.e. nothing
is locally hidden from the tool).

| Severity | Count |
|---|---|
| High | 0 |
| Medium | 1 |
| Low | 4 |

| # | Rule | File:line | Verdict |
|---|---|---|---|
| 1 | B102 `exec_used` | `cli/validation.py:222` | **Reviewed, not a defect** — see §3.1 |
| 2 | B404/B603 `subprocess` | `cli/postprocess.py:28,241` | **Reviewed, not a defect** — see §3.2 |
| 3 | B110 `try_except_pass` | `cli/__main__.py:1095` | Low — swallows all exceptions around a best-effort name-extraction path used only for a diagnostic hint; not a security boundary, but broad `except Exception: pass` is worth narrowing for debuggability (not filed as a security defect) |
| 4 | B101 `assert_used` | `interpreter.py:1672` | Low — an internal invariant assert (`self._wakeup is not None`) that is stripped under `-O`; if it ever fired in production with asserts disabled the following line would raise `AttributeError` instead of a clear invariant message. Not attacker-reachable; cosmetic. |

### 2.2 semgrep (1.177.0), `p/python` + `p/security-audit`, 346 rules / 200 applicable, 43 files, ~100% parsed

**1 finding, identical root cause to bandit's B102** — `python.lang.security.audit.exec-detected.exec-detected`
at `cli/validation.py:222`. No divergence between the two engines; this
independently corroborates that the `exec()` call is the only static
security-audit hit in the entire codebase.

### 2.3 pip-audit (2.10.1), `--path .`

**No known vulnerabilities found.** Expected and confirms the CHANGELOG's own
claim: the core library ships with **zero runtime dependencies**
(`black`/`isort` are optional dev/codegen extras, invoked defensively — see
§3.2 — and absent from the smoke-tested wheel's install closure). There is
therefore no transitive-dependency attack surface to audit at this commit;
this result will need re-running whenever an extra is added.

---

## 3. Manual review — dynamic-code and injection surfaces

### 3.1 `exec()` in the CLI's self-verification path (`cli/validation.py:196-260`, `_build_generated`)

**What it is.** `xsm gt --strict` (and the test-suite injection tests) verify
that CLI-generated code actually builds the machine the source JSON describes.
That requires *running* the generated code, so `_build_generated` does
`exec(compile(code, ..., "exec"), module.__dict__)` against a scratch
`types.ModuleType` that is never registered in `sys.modules`, and
`sys.modules` is snapshotted/restored around the call so nothing the executed
code imports or injects can persist into the CLI process (`validation.py:203-232`).

**Why this is not filed as a defect.** `code` here is the *generator's own
output* for one of five templates (`class-json`, `function-json`,
`pythonic-*`), not attacker JSON verbatim. The generator's docstring text is
run through `naming.docstring_safe()` (strips `"`, `\`, `\r`, `\n` — the
characters that would let an id like `p"""; import os; os.system(...)"""`
close a docstring early and turn the remainder into code), and every
string-literal interpolation of a user-controlled name (event names,
action/guard/service names) goes through `naming.escape_for_string()`
(escapes `\`, `"`, `'`). Module/file-stem identifiers (`machine_names`,
`a_name`) are always produced by `to_identifier`/`module_safe_name`, which
strip to `[A-Za-z0-9_]`, so those particular interpolation sites can never
carry a quote or triple-quote at all.

**Verified paths, spot-checked:**
- `cli/builders.py:148,257,485,492` and all four `strategies/*.py` docstring
  emitters route through `docstring_safe()`.
- `cli/strategies/_shared.py:70` (`generate_action_docstring`) — the single
  choke point for per-action/guard/service docstrings — calls
  `docstring_safe()` before interpolation; confirmed by reading the call sites
  in `class_json.py:562` and `function_json.py` (same pattern).
- `escape_for_string()` is applied at every site that embeds a **JSON-derived**
  string inside a Python string literal in the five strategy modules (event
  names sent in simulations, guard/action/service names in decorators and log
  calls) — 25 call sites grepped, all consistent.
- The one place a JSON-derived name is embedded *without* `escape_for_string`
  (`class_json.py:428,442` etc., `a_name` in an f-string) is safe **because**
  `a_name` is drawn from `ctx.machine_names`, which is already
  `module_safe_name(camel_to_snake(raw_name))` — an identifier-shaped string
  that cannot contain a quote, backslash or newline by construction
  (`utils.py:18-100`). This was checked specifically because it looked like a
  gap at first read; it is not.

**Residual risk (documented, not a defect we are filing):** `_build_generated`
runs with the CLI's own process privileges and is explicitly *not* a sandbox
(the module's own docstring says so, `validation.py:203-213`) — a
still-unknown escape from `docstring_safe`/`escape_for_string`'s character
sets, or a future template that interpolates a JSON-derived string in a *new*
way without routing through either helper, would become code execution when
`xsm gt --strict` runs it. This is an architectural acceptance of risk that
the maintainers state explicitly and mitigate with two centralized sanitizers
plus injection tests (`validation.py` docstring references "the injection
tests"); we did not find a case where a sanitizer is bypassed at this commit.
**Constraint for the adopting project:** `xsm gt` must only ever be pointed at
XState JSON the adopting project itself authored or reviewed — never at JSON
sourced from an external/multi-tenant input — because `--strict` verification
executes the generated code in-process. This is a process constraint, not a
code defect, and should be stated in any operator runbook for the CLI.

### 3.2 `subprocess` (`cli/postprocess.py`)

`black` is invoked as `[sys.executable, "-m", "black", "--quiet",
f"--line-length={line_length}", "-"]` with `input=code` over stdin,
`capture_output=True`, `text=True`, `timeout=60`, **no `shell=True`**, and the
argument list is static except a caller-supplied integer (`line_length`)
interpolated into an f-string as `--line-length=N` — an integer from CLI args,
not free text, so it cannot inject a second flag. `isort.code()` is a Python
API call, not a subprocess. Both are wrapped in defensive `try/except` that
degrades to "leave code unformatted" rather than failing generation — correct
behaviour for an optional dev-dependency, and not a security concern since
neither runs untrusted code paths beyond what §3.1 already covers (the code
being formatted is the generator's own output, passed as *data* over stdin,
never as a shell string).

### 3.3 `logic_modules` / `logic_providers` (`logic_loader.py:298-310`)

`importlib.import_module(item)` runs when `logic_modules` contains a string.
This is standard "config names a Python module to import" behaviour (the same
shape as Django's `INSTALLED_APPS` or Celery's autodiscovery) — the string
comes from the **adopting application's own source code** (the `logic_modules=`
argument to `create_machine`/`LogicLoader.build_logic`), never from the XState
JSON itself. We did not find a path where an attacker-controlled JSON value
reaches `import_module`. **Not a defect**, but worth stating as a documented
trust boundary: an application that builds its `logic_modules` list from
user-supplied or database-supplied strings would hand full arbitrary-import
capability to that input — this is inherent to the feature, not specific to
this library, and the library does nothing to make it worse or better than
the stdlib primitive it wraps.

### 3.4 Snapshot restore — `kind`-based reconstruction (`persistence.py`, `events.py:284-335`)

`get_persisted_snapshot()`/`from_snapshot()` are JSON-only: the payload is
`json.dumps`-safe primitives, `restore_event()`'s `kind` field is matched
against a **fixed 5-value allow-list** (`"done" | "error" | "after" | "system"
| "event"`, `events.py:314-335`) with no class-name lookup, no `globals()[...]`,
no `pickle`, no `eval`. `ErrorEvent.error` on restore is always wrapped in the
library's own `RestoredError` (`events.py:323-328`), never the original
exception type — so a restored snapshot cannot smuggle an arbitrary class
into the running process via the `error` field either. **Clean; no object
reconstruction beyond JSON primitives, and the `kind` sentinel is a closed
enum, not user-extensible.** This confirms the CHANGELOG's own framing of
snapshot v2 (#86/#87) is accurate from a security as well as a correctness
standpoint.

### 3.5 `LoggingInspector` — secrets-in-context leak by default (D-security-1)

`plugins.py:404-520`, the library's own built-in, documented-as-canonical
inspection plugin:

- `on_event_received` logs `event.payload` (or `.error`/`.data`) at `INFO` —
  `plugins.py:443-446`.
- `on_transition` logs **the entire machine context** at `INFO` on every
  external *and* internal transition — `plugins.py:477,484`
  (`logger.info("🕵️ [INSPECT] New Context: %s", interpreter.context)`).

For a library whose stated production use case is an order-management system,
`context` and event payloads are exactly where API keys, auth tokens, PII, or
order/account details would live. `LoggingInspector` is opt-in (a user must
attach it as a plugin), but it is presented in the docs/README as the
canonical example of `PluginBase`, which is precisely the kind of
copy-pasted-into-production code that leaks secrets into log aggregators.
There is no redaction hook, no size cap, and no way to opt out of the context
dump short of not using the plugin (or monkey-patching it) — `repr(context)`
of an unbounded dict is logged verbatim on every transition.

**Severity: Medium.** Not exploitable by an external attacker against the
library itself, but a straightforward, foreseeable secret-disclosure footgun
in code the project ships and documents as the reference implementation.

**Constraint we would need:** the adopting project must **not** enable
`LoggingInspector` (or any custom plugin copied from it) against a machine
whose `context` or event payloads ever carry credentials, tokens, or PII,
without first wrapping/subclassing it to redact. This should be a written
rule in our plugin usage guidance, not something we rely on engineering
discipline to remember per call site.

---

## 4. DoS / unbounded-growth sweep

| Structure | Bound | Evidence |
|---|---|---|
| Defer buffer (`onUnhandled: "defer"`) | `DEFER_MAX = 1000` (`base_interpreter.py:3291`), enforced at `base_interpreter.py:3326` before appending | Bounded |
| `_SIBLING_FALLBACKS_WARNED` (module-level warn-once cache, `resolver.py`) | `_SIBLING_FALLBACKS_WARNED_MAX = 1024`, cleared (not merely capped-with-drop) once the bound is hit (`resolver.py:100-104`) | Bounded (per #31 ride-along, confirmed present at this commit) |
| Inbox / event queue | `max_queue_size` optional, `None` (unbounded) by default, `RAISE`/`BLOCK`/`DROP_NEWEST` overflow policy when set (`interpreter.py:184-232`, `:815-867`) | **Opt-in bound** — the default is still unbounded, which is correct for a queue backed by application backpressure but is a constraint the adopting project must set explicitly (`max_queue_size=`) if an untrusted or bursty producer can call `send()` |
| `_receipts` (per-event `wait=True` futures) | Popped on resolution (normal completion, `interpreter.py:731,740,763`) and drained wholesale on stop (`_fail_all_receipts`, `interpreter.py:774-777,996`) | Bounded by lifecycle, not a fixed cap — a caller that does `send(wait=True)` in a tight loop without awaiting the receipt could accumulate futures between sends, but each is resolved by the same macrostep that processes its event, so growth is proportional to in-flight `wait=True` sends, not unbounded backlog |
| `normalize_logic_name` (`machine_logic.py:110-133`) | No regex at all — a single-pass character filter (`ch not in _NAME_SEPARATORS`) plus `casefold()` | **No ReDoS surface** — confirmed by reading the implementation; there is no backtracking construct anywhere in the normalisation path |
| Target-resolution recursion (`resolver.py`) | Not exhaustively fuzzed this track (see §6, out of scope) — read the sibling-fallback and `_resolve_target` code paths and found no unbounded recursion on a pathological id (traversal is bounded by the machine's own node tree depth, which is fixed at parse time, not by the input event), but no adversarial-depth-generation test was run | Not independently verified with a crafted pathological config in this track |

No new unbounded structure was found beyond what the CHANGELOG's own #31
ride-along claims; the claim (`_SIBLING_FALLBACKS_WARNED` bounded to 1024) was
independently confirmed by reading the source, not just trusting the
changelog.

---

## 5. Repository / supply-chain hygiene

| Item | Finding |
|---|---|
| GitHub Actions pinning | **Not pinned to commit SHA.** `.github/workflows/ci.yml` and `publish.yml` reference `actions/checkout@v7`, `actions/setup-python@v7`, `actions/upload-artifact@v7`, `actions/download-artifact@v5`, `pypa/gh-action-pypi-publish@release/v1` — all by mutable tag/branch ref, not SHA. Standard practice for many projects, but a compromised upstream action tag (or `release/v1` moving) would run in CI/publish with no pin to catch it. **Low-Medium** (mitigated somewhat by `permissions: contents: read` at workflow scope in `ci.yml:41-42`, and by Trusted Publishing meaning there is no long-lived PyPI token to steal even if a step were compromised). |
| Signed releases / SBOM | **Neither found.** No sigstore/cosign signing step, no SBOM (CycloneDX/SPDX) generation in `publish.yml`. Given zero runtime dependencies, an SBOM would be near-trivial and cheap to add; its absence is a Low finding, not a Medium one, precisely because the dependency surface it would document is empty at this commit. |
| Dependency count (runtime) | **0**, confirmed by `pip-audit` finding nothing to audit and by the CHANGELOG's own repeated claim (checked, not just trusted). |
| License | `LICENSE` present, MIT, matches `pyproject.toml`'s `license = {text = "MIT"}`. Clean. |
| CODEOWNERS | **Absent.** No `CODEOWNERS` file at repo root or `.github/`. |
| Branch protection (`main`, via `gh api repos/basiltt/xstate-statemachine/branches/main/protection`) | `required_pull_request_reviews.required_approving_review_count: 0` (reviews not actually required), `required_signatures.enabled: false` (commit signing not enforced), `enforce_admins.enabled: false` (rules don't bind the repo owner), `allow_force_pushes.enabled: true`. `required_status_checks.strict: true` is set but `contexts: []` — no specific CI check is actually required to pass before merge. **This is the most consequential hygiene gap found**: a `main`-branch merge (or a direct push, since force-push is allowed and admins are exempted) is not gated on CI passing, code review, or signed commits. For a library that will run inside a money-handling OMS, this means a compromised or careless maintainer push reaches `main` — and eventually a tagged release — with no automated or human backstop enforced by GitHub itself. |
| Publish workflow | **Good.** OIDC Trusted Publishing (`id-token: write`, no stored PyPI token — `publish.yml:112-114`), version-vs-tag consistency check before upload (`publish.yml:58-66`), rebuilds from source rather than reusing release-attached artifacts (per the workflow's own stated rationale), smoke-tests the **built wheel** in a clean venv before shipping (`publish.yml:68-95`). This is materially better than the branch-protection posture above. |

**Severity for the branch-protection gap: Medium**, filed as D-security-2
below — it is a process control, not a code vulnerability, but it directly
determines how much trust a downstream adopter should place in "what's on
`main`" versus "what a human reviewed."

---

## 6. Defects filed

| ID | Severity | Summary | Location | Minimal repro |
|---|---|---|---|---|
| **D-security-1** | **Medium** | `LoggingInspector` (the library's own canonical example plugin) logs full event payload/error and the **entire machine context** at `INFO` on every transition, with no redaction and no size cap | `src/xstate_statemachine/plugins.py:443-446` (event payload), `:477,484` (context) | Attach `LoggingInspector()` to any interpreter whose context holds a secret, e.g. `context={"api_key": "sk-live-..."}`; send any event that causes a transition; observe `sk-live-...` at `INFO` in the log stream. No code change needed to reproduce — this is the shipped behaviour. |
| **D-security-2** | **Medium** | `main` branch protection does not require passing CI, code review, or signed commits, and allows force-push with admins exempted from the ruleset | GitHub repo settings (`branches/main/protection`, verified via `gh api`) | `gh api repos/basiltt/xstate-statemachine/branches/main/protection` — inspect `required_pull_request_reviews.required_approving_review_count` (0), `required_status_checks.contexts` (empty), `enforce_admins.enabled` (false), `allow_force_pushes.enabled` (true). |
| **D-security-3** | **Low** | GitHub Actions referenced by mutable tag (`@v7`, `@v5`, `@release/v1`), not pinned to a commit SHA, across both workflows | `.github/workflows/ci.yml`, `.github/workflows/publish.yml` (all `uses:` lines) | `grep -n "uses:" .github/workflows/*.yml` — none contain a 40-hex SHA. |
| **D-security-4** | **Low** | No SBOM or artifact signing in the release pipeline | `.github/workflows/publish.yml` | Read the workflow: `build` job produces `dist/` via `python -m build`, uploads as a plain artifact, `publish` job installs via `pypa/gh-action-pypi-publish` with no `cosign`/sigstore/CycloneDX step anywhere in either job. |
| **D-security-5** | **Low** (informational, not filed as actionable) | Two housekeeping bandit hits that are not security-critical but worth narrowing for hygiene: a broad `except Exception: pass` around a diagnostic-only path, and an `assert` guarding an internal invariant that is stripped under `-O` | `src/xstate_statemachine/cli/__main__.py:1095`; `src/xstate_statemachine/interpreter.py:1672` | See §2.1 rows 3–4. |

No **Blocker** or **High** security defects were found at this commit. The
`exec()` in the CLI's self-verification path (§3.1) was the single flag both
scanners raised independently, and it survives review as a documented,
narrowly-scoped, defence-in-depth-wrapped design choice rather than an
exploitable injection — contingent on the constraint stated in §3.1 (never
point `xsm gt --strict` at untrusted JSON).

---

## 7. What this track covered, and what it did not

**Covered:**
- Two independent static-analysis engines (bandit, semgrep) across the full
  `src/` tree, both clean except the one reviewed `exec()`.
- Dependency/supply-chain audit via `pip-audit` (0 findings, consistent with
  the library's zero-runtime-dependency design).
- Manual trace of every `exec`/`subprocess`/`importlib.import_module` call
  site to its actual input source, not just its presence.
- The snapshot restore path's object-reconstruction surface, confirmed to be
  a closed 5-value enum with no class-name lookup.
- The one built-in logging plugin's default verbosity against a
  secrets-in-context threat model.
- The four DoS-relevant bounded/unbounded structures named in the task brief,
  each independently confirmed by reading the code rather than trusting the
  CHANGELOG's claims.
- Actions pinning, license, CODEOWNERS, branch protection (queried live via
  `gh api`, not assumed), and the release/publish pipeline's trust model.

**Not covered / explicitly out of scope for this pass:**
- No adversarial fuzzing of `resolver.py`'s target-resolution recursion with
  deliberately pathological (deeply nested, cyclic-looking) state ids — read
  the code and found no obvious unbounded recursion, but did not construct a
  crafted stress input. If deep-recursion DoS on attacker-influenced config
  matters to the adopting project's threat model, that needs a dedicated
  probe, not the read-through done here.
- No review of the test suite's own security-relevant coverage (e.g. whether
  the "injection tests" `validation.py` references actually exercise the
  `docstring_safe`/`escape_for_string` boundary adversarially, or just
  happy-path). We read the sanitizers' implementations directly instead of
  auditing their test coverage.
- No SCA/SBOM tool was run to *generate* an SBOM (only pip-audit, which
  audits, not generates) — D-security-4 is a gap statement, not something we
  attempted to remediate or simulate.
- No secrets-scanning pass (e.g. gitleaks/trufflehog) over full git history
  was run; this track relied on `pip-audit` + manual grep, not a dedicated
  history-wide secret scan.
- CLI argument-injection surface (`args.py`) was not separately fuzzed for
  path-traversal via `--output`/JSON filename arguments beyond the direct
  `subprocess.run` review in §3.2; `out_dir.mkdir(parents=True,
  exist_ok=True)` (`__main__.py:165`) and `target_path.write_text(...)`
  (`__main__.py:348` etc.) were located but not adversarially tested against
  a JSON config engineered to produce a `../../` output path — worth a
  follow-up probe if the CLI is ever exposed to untrusted config paths rather
  than operator-supplied ones.

This track is honest that "clean at the static-analysis and manual-review
level" is not the same claim as "adversarially fuzzed" for the two items
above (recursion depth, output-path traversal) — both are flagged as residual
unknowns rather than asserted safe.
