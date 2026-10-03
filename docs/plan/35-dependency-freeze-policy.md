# 35 — Dependency freeze policy and vendored-code register (E43-T05)

Owner: Security engineer + @basiltt. Requirements: SR-130..SR-139, SR-156
(`04-security-program.md` §6.13). Code freeze for the pen-test: **2027-02-11**
(`30-release-roadmap.md` §8.5).

## 1. Freeze artefacts

| Surface | Frozen by                                           | Verified by                                                    |
| ------- | --------------------------------------------------- | -------------------------------------------------------------- |
| Python  | `uv.lock` (hashes)                                  | CI `uv sync --frozen`                                          |
| JS      | `pnpm-lock.yaml`                                    | `pnpm install --frozen-lockfile --ignore-scripts`              |
| Images  | `FROM ...@sha256:` in `infra/images/Dockerfile.api` | `tools/ci/check_dockerfile_pins.py`, `check_image_non_root.py` |
| Actions | full SHAs, ledger `.github/actions-pins.md`         | `tools/ci/check_action_pins.py`, Semgrep `cv-unpinned-action`  |

Tags: `pentest-freeze-<yyyymmdd>` (the build under test) and `pentest-retest-<yyyymmdd>`;
both hashes go in the evidence pack (E43-X07). Create the tag on the commit that
passes every gate in §4 — creating it is a release-manager action after this PR merges.

## 2. Changes allowed inside the freeze window

Only security fixes (a High/Critical advisory, or a pen-test finding). Each needs
**Security + Owner approval**, is recorded as a comment on E43-T05, produces a new
`pentest-freeze-*` tag, and the tester is notified (via E43-X02's channel) of the
new tag and the diff. Everything else waits until after the retest.

## 3. Advisory SLA (SR-134)

Advisories touching the order path or key handling: triage within **48 h**; all others
**7 days**. Dependabot (`.github/dependabot.yml`) labels PRs `sla/48h` or `sla/7d`.
Unfixable High: §16.2 exception in `04-security-program.md` AND `security/accepted-risks.yaml`
(expiry <= one release cycle; Critical is never exception-able).

## 4. Gates (required checks, names in C-9.1)

`pip-audit`, `npm-audit`, `license-scan` (allowlist `tools/ci/licenses-allowlist.json`),
`trivy`, `semgrep`. Local: `pnpm audit --audit-level=high`.

## 5. postinstall review (SR-138)

CI installs with `--ignore-scripts`. Exceptions are the two in
`tools/ci/allowed-postinstall.json`: `electron` (pinned binary download) and `esbuild`
(pinned platform binary). Any addition needs Security review.

## 6. Container hardening

`Dockerfile.api`: digest-pinned base, multi-stage, `USER 10001:10001`; compose sets
`read_only: true` and drops capabilities; weekly rebuild via Dependabot docker +
scheduled build. Verified by `check_image_non_root.py`.

## 7. Vendored / forked third-party code (SR-139)

| Source               | Version | Reason | Update owner |
| -------------------- | ------- | ------ | ------------ |
| _none at 2026-10-03_ |         |        |              |

Adding any vendored or forked code requires a row here in the same PR.

## 8. SCA sweep triage (2026-10-03, `pnpm audit`, High/Critical)

| Package                               | Advisory                                 | Path                         | Area          | Decision                                                               |
| ------------------------------------- | ---------------------------------------- | ---------------------------- | ------------- | ---------------------------------------------------------------------- |
| tar (<=7.5.20, 1 Critical + 6 High)   | GHSA-23hp-3jrh-7fpw et al.               | transitive, electron-builder | build-time    | **Fixed**: `overrides: tar >=7.5.21`                                   |
| vitest 2.1.8 (Critical) / vite (High) | GHSA-5xrq-8626-4rwp, GHSA-fx2h-pf6j-xcff | dev, test runner             | dev-only      | **Fixed**: vitest + coverage-v8 -> ^3.2.6                              |
| electron 33.4.11 (11 High)            | e.g. GHSA-9qh4-3jw8-366w                 | direct                       | desktop shell | **Fixed**: electron -> ^41.10.7 (hardening gate + desktop tests green) |
| app-builder-lib, builder-util-runtime | GHSA-7g7r-gx96-252g, GHSA-p2f4-r6v6-j797 | direct, electron-builder     | build-time    | **Fixed**: electron-builder -> ^26.15.3                                |
| extract-zip                           | GHSA-jmr9-qjv8-65gv, GHSA-7pqw-9j4j-h8q3 | transitive of electron       | install-time  | **Fixed**: electron 41 no longer depends on `extract-zip`              |

### 8.1 Python and container sweep (2026-10-03)

| Scan               | Command                                                                                                                  | Result                                                                                                                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| pip-audit (Python) | `uv export --frozen --no-emit-project` (services/api/uv.lock, hashed) then `pip-audit -r <file> --no-deps --disable-pip` | **No known vulnerabilities found**; no Python exceptions needed                                                                                                                                 |
| Trivy (container)  | `trivy` job on `infra/images/Dockerfile.api`                                                                             | **Not run locally: no docker / trivy binary.** Runs in the required CI `trivy` job; base image is digest-pinned. Any High/Critical it reports needs a fix or an exception before the freeze tag |
| Licences           | `license-scan` job, allowlist `tools/ci/licenses-allowlist.json`                                                         | CI-only; gate behaviour proven by fixture tests in `scripts/tests/test_dependency_freeze.py`                                                                                                    |

Tests in `scripts/tests/test_dependency_freeze.py`: known-vulnerable finding fails the SCA gate
(CI-SEC-001); prohibited licence fails with a message naming package and licence (CI-SEC-002);
Dockerfile is digest-pinned and non-root (static; runtime probe `check_image_non_root.py` needs
docker, not run locally); lockfiles are integrity-hashed (frozen installs reproduce byte-identically).

### 8.2 Post-fix sweep (2026-10-03)

After the electron / electron-builder bumps, `pnpm audit --audit-level=high` reports
**0 High / 0 Critical** (2 Low, 6 Moderate); `pip-audit` unchanged (none). No High/Critical
exceptions are needed, so EX-02..EX-04 are withdrawn (§16.2 of `04-security-program.md`).

**Correction (E43-T05-B1, #1737):** that sweep later reports 2 High with no upstream patch:
http-cache-semantics (GHSA-ch52-4w7c-c8xp) and braces (GHSA-vfj7-8cjw-p6xm). Both are build/dev-only
transitives; recorded as EX-05/EX-06 (EX-02..EX-04 stay withdrawn) (§16.2) and in `security/accepted-risks.yaml`, expiry 2026-12-31.
The freeze-manifest `pnpm-graph` hash mismatch is not claimed closed here; it is out of scope for #1737.

### 8.3 Freeze assertion and tag procedure

- CI (`license-scan` job, `_job-security.yml`) runs `tools/ci/check_freeze_manifest.py` after
  `pnpm install --frozen-lockfile` and `uv sync --frozen`: SHA-256 of `pnpm-lock.yaml`, `uv.lock`,
  the normalised `pnpm ls -r --json --depth Infinity` graph and `uv export --frozen` must equal
  `security/freeze-manifest.sha256`. It does not depend on any tag. Any approved freeze change
  (§2) regenerates the manifest with `--write` in the same PR.
- Tag (owner-only): on the merged commit whose CI is green, the owner runs
  `git tag -a pentest-freeze-<yyyymmdd> <sha> -m "pen-test freeze; manifest <sha256 of freeze-manifest.sha256>"`
  and `git push origin pentest-freeze-<yyyymmdd>`; the tag sha + manifest hash go into the
  evidence pack (E43-X07). Retest uses `pentest-retest-<yyyymmdd>` the same way.
