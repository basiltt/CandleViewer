# `issues/post-6db65d8/` — round-8 upstream drafts

**STATUS: DRAFT. NOTHING HERE HAS BEEN POSTED.** No GitHub write was performed in this
round; `gh` was used read-only or not at all.

Target: `basiltt/xstate-statemachine`, `main` @ **`6db65d8`** (merge of PR #191,
`fix/0.8.1-round7`; unreleased 0.8.1 — `__version__` still reports `0.8.0`, so everything
here keys on the commit).

## Contents

| Path | What |
|---|---|
| `comments/` | 16 per-issue comments — the 10 clean closures (#167, #168, #175, #182, #183, #184, #187, #188, #189, #190), the 5 fixed-with-residual (#179, #180, #181, #185, #186), and the documentation-only acknowledgement (#174). Two are **reopens, narrowed**: #181 and #186. |
| `new/` | 10 new-issue drafts, one per CONFIRMED Medium-and-above library defect, each with front-matter (severity, engines, service kinds, repro path) and a standalone repro. |
| `new/repro/` | 12 standalone repro scripts, copied from the battle-track artefacts that produced the findings. Each runs on a clean interpreter with no project imports. |
| `meta-26.md` | The scorecard update for the meta issue (#26). |
| `manifest.json` | Machine-readable index: every comment, every new issue, the counts, the gate decision and the exit condition. |

## The one thing to read first

**R8-01** (`new/R8-01-priority-lane-charges-by-provenance-sheds-by-position.md`). It is the
round's only Blocker, it is the regression surface of this release's own #180, and it is
one function's worth of work. A 0.8.1 tag cut before it lands ships an unbounded,
unobservable livelock on the priority lane plus silent destruction of external priority
events.

## Posting order, if and when this is posted

1. `meta-26.md` as a comment on #26 (sets the context for everything else).
2. The 10 clean closures — good news first, and they are the larger half.
3. `new/R8-01-*` — filed against the #180 milestone, since it is that fix's regression
   surface.
4. The comments on #179, #180, #185 and #174, each cross-linking the new issue that carries
   its residual.
5. The two narrowed reopens (#181, #186), each stating explicitly what *is* fixed before
   what is not.
6. The remaining 9 new-issue drafts.

Every claim in these drafts was reproduced in a clean process at `6db65d8` before it was
written, and every service-bearing check was run with **both** `def` and `async def`
services. Where our own first analysis was wrong, the draft says so — see the refutation
notes in `R8-02`, `R8-04` and the #185 comment.
