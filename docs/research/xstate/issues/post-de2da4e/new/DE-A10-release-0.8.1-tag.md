---
id: DE-A10
title: "Release: bump __version__ and tag 0.8.1 at de2da4e"
labels: [documentation, docs, severity/low]
severity: Info
repro_script: null
commit: de2da4e
verified: true
---

## Summary

Twelve consecutive rounds of external verification have pinned every gate, CI
assertion, and issue report to the commit hash rather than to `__version__`,
because `__version__` has read `0.8.0` since round 3 while `CHANGELOG.md`
`[Unreleased]` has targeted `0.8.1` for the same span. This is the last
item on an otherwise essentially clean board — we consider the library
adopted, and this request sits between "adopt with constraints" and
"nothing open": please cut the release so the version string catches up
with the tree it has been describing for three months of rounds.

## Environment

`xstate-statemachine` @ `de2da4e` (main), `__version__ == "0.8.0"`,
`CHANGELOG.md` `[Unreleased]` section targets `0.8.1`. Full suite at this
commit: **3545 passed, 0 failed, 13 skipped**, 92.87% coverage (required
90.0%). Library-side defect board at this commit: **0 Blocker, 0 High**.

## Current state

- `xstate_statemachine/__init__.py` (or wherever `__version__` is defined)
  still reports `"0.8.0"` at `de2da4e`.
- `CHANGELOG.md` has carried an `[Unreleased]` heading targeting `0.8.1`
  since round 3 of our verification, i.e. across `c78ce99`,
  `19cb1f1`, `f28719c`, `6db65d8`, `221ce7c`, `cec108b`, `3ed3099`,
  `5e07ba8`, `3c527b0`, `5327ba6`, and now `de2da4e`.
- There is no `0.8.1` tag in the repository.
- Every one of our reports for the last twelve rounds has had to add a
  disclaimer of the form "identify this build by commit, never by version
  string" because `__version__` cannot be trusted to distinguish these
  commits from one another or from actual 0.8.0.

## Evidence

- our round-12 verdict note §0: *"`__version__` still reports
  `0.8.0` on `de2da4e` ... while `CHANGELOG.md [Unreleased]` targets
  0.8.1. Twelfth consecutive round."*
- Same document, diff-review row (Low, library board): *"`__version__` reports `0.8.0`
  on an `[Unreleased] — targeting 0.8.1` tree, twelve rounds running. Any
  gate keyed on the version string mis-identifies this build."*
- Suite result this round: 3545 passed / 0 failed / 13 skipped, 92.87%
  coverage — a clean baseline to release from.

## Requested change

At `de2da4e` (or the commit that becomes the release point), please:

1. Bump `__version__` to `"0.8.1"`.
2. Move the `CHANGELOG.md` `[Unreleased]` heading to a dated `## [0.8.1]`
   entry.
3. Tag the release `v0.8.1` (or `0.8.1`) at that commit.

## Root cause analysis

N/A (release-process ask, not a code defect).

## Impact

Low direct impact — every downstream consumer that keys correctly on the
commit hash (as our twelve rounds of gates do) is unaffected either way.
The impact is entirely on projects that don't do that: anything gating on
`importlib.metadata.version("xstate_statemachine")` or `__version__`
during this window silently mis-identifies a tree that has accumulated
five rounds of fixes (#218–#222 among them) since actual 0.8.0.

## Proposed fix

Standard release bump: version string, changelog heading, tag. No code
change implied.

## Acceptance criteria

- [ ] `xstate_statemachine.__version__ == "0.8.1"` on the release commit.
- [ ] `CHANGELOG.md` has a dated `## [0.8.1]` heading (no bare
      `[Unreleased]` covering already-shipped content).
- [ ] A tag (`v0.8.1` or `0.8.1`) exists pointing at the release commit.
- [ ] Optional but appreciated: a PyPI publish so `pip install
      xstate-statemachine==0.8.1` resolves to this tree.

## Verification

Every factual claim in this issue was checked against the tree at
`de2da4e`:

- `__version__ == "0.8.0"` — confirmed at
  `src/xstate_statemachine/__init__.py:200`.
- `CHANGELOG.md` `[Unreleased]` targets 0.8.1 — confirmed at
  `CHANGELOG.md:7` (`## [Unreleased] — targeting 0.8.1`).
- No `0.8.1` tag exists — `git tag --list` on the clone returns
  `v0.4.3`, `v0.6.0`, `v0.7.0`, `v0.8.0` as the only version tags.
- `de2da4e` is the merge of PR #223 (`Merge pull request #223 from
  basiltt/fix/0.8.1-round11`), i.e. the round-11 fix set (#218–#222) is
  already on this tree while the version string still reads 0.8.0.
- Suite numbers quoted in the Environment section are from a full run at
  this commit: **3545 passed, 0 failed, 13 skipped**, `Required test
  coverage of 90.0% reached. Total coverage: 92.87%`.
- Library-side defect board at this commit: **0 Blocker, 0 High** — the
  remaining items are the Medium/Low/Info set this round files.

## Related

- PR #223 — the round-11 fix set this release would carry.
- `#218`, `#219`, `#220`, `#221`, `#222` — all verified FIXED at this
  commit by us; a tag is what lets downstream users depend on those fixes
  by version rather than by commit hash.
- Our adoption audit (#26).
