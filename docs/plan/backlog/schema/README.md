# Backlog ticket schema

Owner: this directory (`docs/plan/backlog/schema/`) is the **single source of truth** for the
backlog ticket schema (CONSTITUTION.md C-16.5). No other file may restate the field list or its
enums — link here instead.

## Files

- `ticket.schema.json` — JSON Schema (2020-12) for one ticket object.
- `backlog-file.schema.json` — the array form: `docs/plan/backlog/E<nn>.json` is an array whose
  first element is the epic and whose remaining elements are that epic's children. `all-tickets.json`
  is a merged superset across all epics and validates against the same per-ticket schema, without
  the single-epic-first-element constraint (see "Merged files" below).
- `../../../../scripts/validate-backlog.py` — the validator that checks both schemas plus the
  cross-file semantic rules a JSON Schema cannot express (dependency cycles, sprint ordering,
  design-ahead lead time, epic budget reconciliation).

## Field-by-field semantics

| Field | Type | Meaning |
|---|---|---|
| `key` | string | Epic id (`E01`) or ticket id (`E01-T06`). The letter after the epic number encodes `kind`: `S` Story, `T` Task, `K` Spike, `D` Design, `Q` QA, `X` Security, `C` Chore. Pattern: `^E\d{2}(-[STKDQXC]\d{2})?$`. |
| `kind` | enum | One of `Epic`, `Story`, `Task`, `Spike`, `Bug`, `Chore`. Must agree with the key-prefix letter above (the validator's cross-file checks enforce this; the JSON Schema alone cannot cross-reference the key). |
| `title` | string | ≤80 chars, human summary. |
| `labels` | string[] | GitHub issue labels. Exactly one `type/*`, one `area/*`, one `priority/*` — closed lists owned by `docs/plan/01-sdlc-and-branching.md` §5.2 (this schema does not restate them; the validator derives them from that doc). |
| `component` | enum | One of the fixed component slugs (see `ticket.schema.json`). |
| `phase` | enum | One of the six roadmap phases P0–P5. |
| `sprint` | string | `Sprint 01`…`Sprint 26`, or `Backlog` for unscheduled tickets. |
| `priority` | enum | `P0 Critical` \| `P1 High` \| `P2 Medium` \| `P3 Low`. |
| `perspective` | enum | The discipline lens the ticket is written from: `Product`, `Architecture`, `Development`, `Test`, `QA`, `Security`, `Compliance`, `Ops`. |
| `risk` | enum | One of the fifteen registered risk categories (`R1`…`R15`) or `None`. |
| `estimate` | integer | Fibonacci-like: `0, 1, 2, 3, 5, 8` for non-Epic kinds (0 permitted for zero-point tracking chores/spikes); `13` permitted **only** for `kind == "Epic"` and only as a transient sizing value that must be split before sprint planning. |
| `parent` | string \| null | The owning epic key. `null` only for the epic itself. |
| `blocked_by` | string[] | Ticket keys or bare epic ids this ticket cannot start before. |
| `milestone` | enum | One of the six release-train milestones `R0 Foundations` … `R5 Hardening / GA`. |
| `body` | string | Markdown ticket body. Must contain every heading of the mandated body template (Context, Scope/Deliverables, Out of scope, Acceptance criteria, Technical notes, Test plan, Security notes, Accessibility notes, Performance notes, Observability, Definition of Done, Dependencies, Branch, References) — checked by the validator, not by JSON Schema (headings are content, not structure). |

## `test_plan`

`docs/plan/03-testing-strategy.md` §11.1 describes a `test_plan` field that "travels with the
ticket". As shipped, no ticket carries a separate `test_plan` JSON field — the test plan lives
inside `body`'s `## Test plan` section instead, and the acceptance-criteria Gherkin block doubles
as the verification steps. This schema therefore does **not** require a top-level `test_plan` key;
§11.1 has been reconciled to point at the `## Test plan` body section (see the note added there in
this same change). If a future ticket needs a structured (non-prose) test plan, add it as an
**optional** property here first, in its own PR, before any ticket relies on it.

## Merged files

`all-tickets.json` is produced by `docs/plan/backlog/_tools/validate.py` by concatenating every
`E<nn>.json`. It is not itself hand-authored, so `backlog-file.schema.json`'s "epic must be first
element" rule does not apply to it — the validator's `--merged` handling (see `validate-backlog.py`
`--help`) checks only the per-ticket schema plus cross-file rules for merged files.

## Adding or changing a field

This directory owns the schema (C-16.5). Changing the agreed field set needs an Architect decision;
if the change also touches a rule already covered by CONSTITUTION.md, it needs an amendment under
C-16.1. Do not add a field silently — a schema change that isn't matched by every backlog file
becomes a validator failure across ~50 files.
