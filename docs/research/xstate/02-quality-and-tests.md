# xstate-statemachine — Study 2: Tests & Quality

Repo studied: `C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine`
Version: `0.7.0` (pyproject.toml). Date of this study: 2026-09-15.

## Actual test run (verbatim results)

Environment: no `uv` available on this machine; used
`python -m venv .venv_study && .venv_study/Scripts/pip install -e ".[format]" pytest pytest-cov pytest-asyncio`
(Windows, Python 3.13.7).

### Full suite

```
=========== 2805 passed, 2 skipped, 1 warning in 569.61s (0:09:29) ============
```

Second run (with `--cov`) reproduced the same count:

```
=========== 2805 passed, 2 skipped, 1 warning in 581.07s (0:09:41) ============
```

Single warning:

```
tests/tests_cli/test_main_execution.py::TestHierarchyExecution::test_main_hierarchy_with_function_style
  .../cli/__main__.py:806: DeprecationWarning: --style is deprecated, use --template function-json instead.
```

No failures, no errors, 2 skips (in `tests/tests_cli/test_code_quality.py`, unexamined further — likely environment-conditional, e.g. skipped when `black`/`isort` unavailable, though both were installed here so this needs checking if it matters; not investigated in depth since it's non-blocking).

**Wall-clock cost is real**: ~9.5–10 minutes for the full suite on this machine. That's slow for a unit-test suite and would need to run in CI-only or a slow/marked-optional bucket if imported into CandleViewer's own pre-commit/dev loop — do not expect a sub-second feedback loop from this library's own test suite as a model for CandleViewer's tests.

### Coverage (this run, py3.13, branch coverage on)

```
TOTAL: 6651 stmts, 697 miss, 2918 branch, 315 partial → 87% cover
```

Per-module lowlights (i.e. where a battle-tester should look first for edge cases the maintainers themselves flagged as under-covered):

| Module | Cover | Note |
|---|---|---|
| `cli/generator.py` | 63% | code-gen internals, large uncovered blocks (lines 65-105, 131-240) |
| `cli/strategies/_shared.py` | 58% | shared codegen helpers, lines 316-475 uncovered |
| `cli/__main__.py` | 69% | CLI entrypoint plumbing, argparse wiring |
| `events.py` | 74% | small file, 6 lines uncovered (85-90) |
| `plugins.py` | 83% | error-hook edge cases |
| `cli/emit.py` | 83% | |
| `cli/simulation.py` | 85% | |
| `cli/validation.py` | 86% | |
| `base_interpreter.py` | 86% (890 stmts, largest file) | many scattered misses across error/edge branches — rollback paths, cancellation edge cases |
| `sync_interpreter.py` | 91% | |
| `interpreter.py` | 87% | |
| `models.py` | 87% | |

CI's coverage gate is `--cov-fail-under=86` (see CI section) — i.e. the maintainers deliberately ratchet a real, measured number with headroom, not a made-up round figure. This is more rigorous than most repos but note **87% aggregate still leaves ~700 statements unexercised**, concentrated in code-generation internals and the two engines' rarer error/rollback branches — exactly the areas most relevant to a production trading system doing OMS/order-flow via statecharts (rollback-on-raising-action, mid-transition failures). Battle-testing effort for CandleViewer should specifically target `base_interpreter.py`'s uncovered lines (rollback semantics, cancellation) since those are the paths this project will lean on hardest.

## Test inventory by feature area

Core engine / model tests (`tests/`, non-CLI):
- `test_factory.py` — `create_machine()` factory surface
- `test_interpreter.py` — async `Interpreter` engine, largest single test file besides CLI ones
- `test_sync_interpreter.py` — thread-based `SyncInterpreter` engine
- `test_engine_conformance.py` — **cross-engine parity tests**, explicitly written after finding that async and sync engines silently diverged (6 release-blocking bugs listed in its own header: empty-config corruption on mid-transition raise, silent death on unresolvable target, parallel deep-history double-leaf, early `onDone` leak, unbounded self-raise hang, sync engine using a synthetic event and losing payload in entry/exit actions). This is the single most important test file for "does the library's advertised guarantee (two engines, same semantics) actually hold."
- `test_models.py` — state/config model layer
- `test_resolver.py` — target resolution
- `test_scxml_correctness.py` — SCXML/statechart algorithm correctness (microstep semantics, etc.)
- `test_xstate_v5_parity.py` — parity with XState v5 JSON semantics (largest non-CLI file by row count of dots in output)
- `test_pythonic.py` — the Pythonic builder API (non-JSON, code-first machine construction)
- `test_plugins.py` — plugin/hook system, including `on_action_error`
- `test_logic_loader.py` — logic module discovery / camelCase↔snake_case mapping
- `test_task_manager.py` — asyncio task bookkeeping/cancellation-by-owner
- `test_exceptions.py` — exception hierarchy + message formatting
- `test_event_payload.py` — tiny, one test: guards against payload-dict aliasing between `Event` instances (a real mutable-default-style bug class)
- `test_issue_17.py` — regression test for a specific reported GitHub issue (logic_providers camelCase mapping) — good practice, issue-driven regression tests exist
- `test_public_api_surface.py` — **contract tests** pinning documented interpreter attributes/methods so docs and implementation cannot silently diverge again (explicitly written after several documented names didn't exist pre-0.5.1)
- `test_readme.py` — executes every runnable Python block in README.md and asserts it actually works (not just imports)
- `test_docs_site.py` — executes the code samples embedded in the GitHub Pages landing page HTML and asserts the demoed machine actually transitions (not just "runs without error") — written specifically because a prior sample looked fine, ran with exit 0, and never worked
- `test_examples.py` — runs every file under `examples/` as a subprocess and asserts success (guards against the examples importing `src.xstate_statemachine` instead of the installed package, which broke all 71 examples for pip-install users pre-0.7.0)

CLI/codegen tests (`tests/tests_cli/`, ~35 files, clearly the largest test surface):
- `test_args.py`, `test_main_execution.py`, `test_check_mode.py` — CLI entrypoint/argument handling, `--check`/`--diff` flags
- `test_generator.py`, `test_extractor.py`, `test_ir.py`, `test_naming.py`, `test_postprocess.py`, `test_utils.py` — codegen pipeline stages
- `test_class_json_strategy.py`, `test_function_json_strategy.py`, `test_pythonic_builder_strategy.py`, `test_pythonic_class_strategy.py`, `test_pythonic_functional_strategy.py`, `test_strategy_registry.py` — one file per code-generation template/strategy
- `test_round_trip.py` — **golden round-trip harness**: generated code is compiled, executed, and the resulting machine structurally compared against `create_machine(source_json)` (added in 0.7.0 specifically because prior tests asserted on generated *strings*, which let broken codegen pass for the library's entire life)
- `test_hierarchy_pythonic.py`, `test_injection.py`, `test_simulation.py`, `test_validation.py`, `test_code_quality.py`, `test_production_quality.py` — cross-cutting codegen quality gates (black/pyflakes cleanliness, unused imports, etc.)
- `test_stately_100_complex.py`, `test_stately_real_machines.py`, `test_stress_50machines.py` — **corpus tests** against ~104 real-world Stately.ai exported JSON machines (fixtures under `tests/tests_cli/stately_machines/*.json` — genuinely large and varied: ATM, authentication, e-commerce, IoT/thermostat controllers, games, subscription flows, etc.) — this is the strongest signal of real-world robustness testing beyond synthetic toy machines.

## What is NOT covered

- **No mypy / static type-checking anywhere** — searched `pyproject.toml`, `.pre-commit-config.yaml`, both CI workflows, `AGENTS.md`. No `mypy` config section, no mypy step in CI, no mypy in dev/lint dependency groups. The library ships `py.typed` (PEP 561 marker) and claims "Typing :: Typed" in classifiers, and the codebase appears to use inline type hints (`AGENTS.md` mandates `typing` imports), but **nothing enforces hints are correct** — the marker is a promise to downstream type-checkers, unverified by the library's own CI. For a codebase this large (6651 statements) with no mypy gate, hint drift/rot is plausible and unverified.
- **No property-based testing** (no Hypothesis) found in dependency groups or imports — correctness relies entirely on example-based tests plus the real-world JSON corpus, not generated adversarial inputs.
- **No performance/benchmark test suite** in this tests/ tree (separate from CandleViewer's own bench harness at `docs/research/xstate/bench` referenced elsewhere in this session, which is external to the library).
- **No concurrency stress/fuzzing beyond `test_stress_50machines.py`** (which stresses code-generation across many machines, not concurrent interpreter execution under load — i.e. it's a codegen stress test, not a threading/asyncio race-condition stress test for the interpreters themselves).
- Coverage gaps concentrated in code-generation internals (`generator.py` 63%, `_shared.py` 58%) and CLI entrypoint glue — the actual statechart engines (`base_interpreter.py` 86%, `sync_interpreter.py` 91%, `interpreter.py` 87%) are covered better but still leave real gaps, notably in `base_interpreter.py`'s error/rollback/cancellation branches (see table above) — precisely the paths CandleViewer's OMS/order-flow use case would stress hardest under exchange disconnects, partial fills, and cancel races.
- No visible test for behavior under Python's GIL-free / free-threaded builds, no test matrix entry for it (matrix is standard CPython 3.9–3.14 only).
- Docs: only the landing page (`index.html`) and its layout are execution-tested (`test_docs_site.py`); the broader guide content and `docs/api/` reference pages are not shown to be executed/verified beyond that, so guide prose could still drift from behavior outside the landing page and README.

## CI matrix

`.github/workflows/ci.yml`, four parallel jobs:
- **lint**: black --check + flake8, ubuntu-latest, py3.13 only
- **test**: matrix `os: [ubuntu-latest]` × `python-version: ["3.9","3.10","3.11","3.12","3.13","3.14"]`, plus explicit `include` spot-checks: windows-latest×py3.9, windows-latest×py3.14, macos-latest×py3.14. So: 6 ubuntu runs + 3 extra OS/version combos = 9 total test jobs. `fail-fast: false` (a failure on one interpreter doesn't hide others). Also runs doctests on `exceptions.py` and `models.py` as a separate step in the same job (guards against previously-rotted, never-executed doctests).
- **coverage**: single ubuntu/py3.13 run, `--cov-fail-under=86` (documented rationale: measured ~87.4%, truncated by pytest-cov's reporting to 87%, gate set to 86 to leave real headroom rather than pin exactly to the measured number — avoids a gate that trips on interpreter-version arc-count differences under `branch=true`).
- **build**: builds sdist+wheel, `twine check`, installs the **built wheel** (not source tree) into a clean venv and runs a smoke test asserting a real transition works, plus verifies the `xsm` CLI entry point runs `--version`.

Notably: `test` job installs the package with `pip install -e .` but does not install `pytest-cov`/`pytest-asyncio` extras beyond bare `pytest` — so CI's own "test" job doesn't use pytest-asyncio explicitly (async tests may rely on `unittest.IsolatedAsyncioTestCase` rather than pytest-asyncio fixtures, consistent with `test_issue_17.py`'s use of `unittest.IsolatedAsyncioTestCase`).

`publish.yml`: triggered on GitHub Release publish or manual dispatch (testpypi/pypi choice). Rebuilds artifacts from source rather than reusing CI's build (defense against a compromised/stale artifact), verifies tag == `pyproject.toml` version before publishing, uses PyPI Trusted Publishing (OIDC, no stored token), smoke-tests the wheel including an assertion `len(x.__all__) == 48` (a hard pin on public API surface size — any addition/removal to `__all__` must be a deliberate, visible diff in this workflow file).

## Typing

- **mypy: absent.** Confirmed by grep across pyproject.toml, pre-commit config, both workflow files, AGENTS.md — zero mentions of mypy as a tool, only one comment referencing "so the... hints are actually invisible to mypy" as the *reason* `py.typed` is shipped, i.e. an aspirational nod to downstream consumers' type-checkers, not a self-check.
- The library ships `py.typed` via `force-include` in `[tool.hatch.build.targets.wheel]` and claims `Typing :: Typed` classifier — so CandleViewer's own mypy/pyright, if used, will attempt to check against xstate-statemachine's inline hints, but those hints are themselves **unverified by the upstream project's own CI**. Treat any type errors surfaced against this dependency with suspicion — they could be real upstream hint bugs, not necessarily CandleViewer misuse.

## Lint

- **black** (line-length 79, targets py3.9–py3.14) + **flake8** (`--max-complexity=35`, `--select=B,C,E,F,W,T4,B9`, broad `--ignore=E203,E266,E501,W503,F403,F401,E402`) + **flake8-isort**. Pre-commit mirrors CI exactly (explicitly stated architecture decision — pinned versions kept in sync between `.pre-commit-config.yaml` and `ci.yml` "so a local run and CI can never disagree").
- Line length 79 is unusually strict (PEP 8 default is fine, but many modern projects use 88/100/120) — worth noting only if CandleViewer intends to vendor/patch this library's source; contributions would need to match this narrow width.
- `--max-complexity=35` is very permissive (McCabe complexity 35 is high) — the lint doesn't meaningfully prevent complex functions; this is a real quality gap for a stateful engine's core files (`base_interpreter.py` is 890 statements/one file).
- `E501` (line too long) is explicitly ignored in flake8 despite black enforcing 79 — a slight redundancy/looseness (black is the actual enforcer of width; flake8 not re-checking it is fine, just noting the two tools' configs aren't symmetric reasoning at a glance).

## Release process / semver discipline (from CHANGELOG.md, 847 lines)

- Follows Keep a Changelog + SemVer, per its own header.
- Current version 0.7.0, described in its own changelog entry as **"The code generator rewrite"** — and it self-reports serious defects in the *previous* release (0.6.0): three of five codegen templates (`pythonic-class`, `pythonic-builder`, `pythonic-functional`) "did not match their source JSON, on inputs as simple as a two-state machine," two failed *silently* with exit code 0. Round-trip fidelity on a 104-machine corpus went from measured **0/104 to 103/104** across those three templates going into 0.7.0. This is an unusually candid admission of a near-total prior-release failure in a specific subsystem (code generation), not merely a changelog bullet — it is presented as the headline of the release.
- 0.6.0's entry documents "defects found by an adversarial battle test run against the merged release branch... Six were release blockers," including transition-atomicity bugs (no rollback on raising action, leaving `current_state_ids == set()` while `status` still reports `"running"` — a machine reporting itself healthy while permanently dead) and the async run loop dying silently on any per-event error while `send()` is fire-and-forget (masking failures from callers). Both were fixed in 0.6.0 with engine-level rollback and re-raise semantics.
- Only one literal "breaking" mention found via grep (line 377, an `after.*` event regression description) — the project seems to prefer describing changes as "Fixed"/"Changed"/"Added" with explicit upgrade notes (e.g., a `[!IMPORTANT]` callout in 0.7.0 telling users of the three broken pythonic-* templates to regenerate) rather than a formal "BREAKING CHANGES" section per release. Given 0.6.0 and earlier 0.6.0 dev builds were "never published to PyPI," the effective public history for anyone on PyPI is described as starting meaningfully at 0.6.0 from 0.5.0's perspective.
- Practical read for adoption: **this library's public track record includes at least two rounds of the maintainer's own "adversarial battle testing" finding release-blocking correctness bugs shortly before each of the last two releases** (0.6.0 and 0.7.0). That is a positive signal for process rigor (bugs are being found and fixed via deliberate battle-testing rather than by users in production) but also a negative signal for how much latent risk this early-stage (Beta classifier, 0.x) library still carries — CandleViewer's own adoption should assume more undiscovered edge cases exist, especially in code-generation (lowest coverage numbers) and in the two engines' rarer error paths.
- `[project.scripts] xsm = ...` CLI entry point is smoke-tested end-to-end in both CI and publish workflows (`xsm --version`).

## Dependency footprint

- **Core runtime: zero dependencies** — explicitly called out in pyproject.toml comments ("The core library has ZERO runtime dependencies, and that stays true"). This is a strong point for a production system: no transitive dependency risk from the statechart engine itself.
- **Optional `[format]` extra**: `black>=24.0`, `isort>=5.13` — only used to pretty-print generated code; absence degrades gracefully (unformatted but still valid/faithful output, per changelog).
- **Dev/test/lint** are separate PEP 735 `[dependency-groups]`: `dev` (pytest, pytest-cov, pytest-asyncio, pre-commit), `lint` (black, flake8, flake8-isort), `test` (pytest, pytest-cov, pytest-asyncio) — these never ship to end users.
- No dependency on any async framework (no anyio, no trio) — pure `asyncio` + `threading` for the two engines.

## Supported Python versions

`requires-python = ">=3.9"`; classifiers and CI matrix both cover 3.9 through **3.14** (including a not-yet-final/very new interpreter at time of writing — aggressive forward support). Actually run in this study: **3.13.7** on Windows (matches one of CI's ubuntu 3.13 lint/coverage jobs' interpreter version, though this study ran on Windows, not Linux — the CI matrix does include windows-latest but only pins py3.9 and py3.14 for Windows, not 3.13, so this exact combination (Windows + 3.13) is untested by upstream CI itself).

## Packaging

- Hatchling build backend, wheel + sdist.
- Sdist inclusion is an **allowlist** (`/src`, `/tests`, `/docs`, `/examples`, docs files, `pyproject.toml`) rather than a denylist — pyproject.toml's own comment explains this was a direct fix for `.claude/` internal review notes previously leaking into published PyPI tarballs via the default broad-inclusion behavior. `/docs/superpowers` is explicitly excluded from the otherwise-wholesale `/docs` inclusion.
- `py.typed` is force-included in the wheel target specifically (separate from the general src package glob) — a deliberate fix noted in a comment: the PEP 561 marker existed on disk but wasn't reliably shipped, silently invalidating the "Typed" classifier for any consumer relying on it.
- Both CI and publish workflows install the **built wheel** into a clean venv and run a functional smoke test + `xsm --version`, not just `import` — catches "module exists on disk, not in wheel" class of packaging bugs.

## Docs build

- Documentation is a **Jekyll site** (Gemfile, `_config.yml`, `_layouts/`, published to GitHub Pages at basiltt.github.io/xstate-statemachine), not Sphinx/mkdocs — no Python-side docs-build tooling (no `mkdocs.yml`, no `conf.py` found anywhere in the repo). No docs-build CI job exists in `ci.yml` (only lint/test/coverage/build jobs) — the docs site's *build* (Jekyll → static HTML) is not itself tested in CI; only its already-rendered `index.html` landing-page code samples are executed by `tests/test_docs_site.py`, which reads and regex-extracts `<pre><code>` blocks straight from the committed HTML rather than rendering Jekyll from source. This means a broken Jekyll build (bad front-matter, broken layout include) would not be caught by this repo's own CI/test suite; only content-level regressions in the landing page's code samples are guarded against.

## Bottom line for CandleViewer adoption

1. Test count and corpus breadth (2805 passing tests, 104 real-world Stately.ai machines, cross-engine conformance suite) are genuinely strong signals for a 0.x pure-Python library — better process rigor than most similarly-sized OSS projects.
2. But: no mypy gate (typed classifier is unverified by upstream CI), permissive complexity limit (35), coverage gaps concentrated exactly where CandleViewer will lean hardest (engine rollback/cancellation paths, 86-91% not 100%), and a self-admitted history of release-blocking correctness bugs caught only by deliberate late-cycle "battle testing" in the last two releases (0.6.0, 0.7.0) — meaning the *published* record between adversarial passes has had real gaps.
3. Full test suite takes ~9.5 minutes locally — too slow to run as a routine CandleViewer pre-commit gate if vendored/patched; would need to be treated as an upstream-only CI concern.
4. Zero runtime dependencies and the wheel-smoke-test discipline are strong reasons for confidence in *packaging* correctness specifically, independent of statechart-logic correctness.
