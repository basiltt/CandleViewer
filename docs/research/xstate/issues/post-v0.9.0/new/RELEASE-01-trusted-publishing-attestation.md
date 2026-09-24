---
id: RELEASE-01
title: "Feature: publish v0.9.0+ via PyPI Trusted Publishing with build provenance attestations"
labels: [enhancement, receipts]
severity: Low
repro_script: null
commit: "v0.9.0 (91bd979)"
---

## Summary

Not a defect — filed for tracking so a trust decision we already made
("wheel diffed against the tag across 42 modules, 0 differ," per
`73-r13-findings-register.md` §3 `R13-12a`) rests on a signed, machine-checkable
artifact rather than on a diff we ran once ourselves. v0.9.0 is published to
PyPI and the wheel-vs-tag match is confirmed, which is the outcome we need —
but that match is currently something *we* verified by hand, not something
PyPI or GitHub attests to. Anyone pinning `xstate-statemachine==0.9.0` (as this
workspace does) is trusting that the artifact on PyPI corresponds to the
source at `v0.9.0` (`91bd979`) on the strength of one manual diff, run once,
by one party.

## Environment

- `xstate_statemachine` v0.9.0 (91bd979), distributed via PyPI
  (`pip install xstate-statemachine==0.9.0`).
- Release/publish workflow: `.github/workflows/` (whichever job runs
  `twine upload` / `pypa/gh-action-pypi-publish` today).

## Current state

The package is published to PyPI. This workspace independently verified
wheel == tag by downloading the wheel and diffing its 42 modules against the
`v0.9.0` git tag, finding zero differences, and recorded the wheel's sha256
(`018505a1b5e7ef1d53c6a820aa680541e87bf2b5b7ad0069e13bae12256c7c0c`). That
sha256 is *observed* by us, not *attested* by the publishing pipeline: there
is no Sigstore/SLSA provenance attestation attached to the release, and no
indication in the GitHub Actions workflow of PyPI Trusted Publishing (OIDC,
no long-lived API token) versus a traditional token-based upload.

## Requested change

1. Move the release workflow to **PyPI Trusted Publishing** (OIDC-based,
   configured in PyPI's project settings + a `pypa/gh-action-pypi-publish`
   step with no `password`/API-token secret), if not already the case —
   removes a long-lived credential from the pipeline and lets PyPI record
   which GitHub Actions run produced the upload.
2. Enable **PyPI's build provenance attestations** (the
   `attestations: true` behaviour of recent `gh-action-pypi-publish`
   versions, backed by Sigstore) so each release carries a verifiable
   attestation binding the published wheel/sdist back to the exact GitHub
   Actions run, commit SHA, and workflow file that built it.
3. Once attestations are live, a consumer (this workspace included) can run
   `pip download` + `pypi-attestations verify` (or `python -m pip
   inspect`/`gh attestation verify` equivalents) to confirm the artifact's
   provenance automatically, rather than diffing 42 files by hand on every
   pinned version.

## Root cause analysis

N/A — release-infrastructure request, not a code defect.

## Impact

Low today (the manual diff already closed the immediate question for
v0.9.0), but the ask is durable: without provenance attestation, every future
pinned version requires the same manual re-verification, and there is no way
for a third party (or an automated dependency-scanning tool) to check it
without redoing the diff themselves.

## Proposed fix

Enable Trusted Publishing + attestations in the release workflow (typically a
small change to the existing publish job: switch to OIDC-based auth, bump
`pypa/gh-action-pypi-publish` to a version supporting
`attestations: true`, and remove any stored PyPI API token secret once OIDC is
confirmed working).

## Acceptance criteria

- [ ] The release workflow publishes via PyPI Trusted Publishing (no
      long-lived PyPI API token secret required).
- [ ] Each published release (starting with the next tag after v0.9.0) carries
      a verifiable build provenance attestation, checkable via
      `pypi-attestations verify` or equivalent.
- [ ] The project README or release docs note that releases are attested, so
      adopters know to verify rather than trust-by-diff.

## Related

`73-r13-findings-register.md` §3 `R13-12a` ("0.9.0 is published; wheel diffed
against the tag across 42 modules, 0 differ. Pin
`xstate-statemachine==0.9.0` from the index.") and `74-r13-final-readiness-verdict.md`
§0 (wheel sha256 `018505a1b5e7ef1d53c6a820aa680541e87bf2b5b7ad0069e13bae12256c7c0c`,
observed not attested).
