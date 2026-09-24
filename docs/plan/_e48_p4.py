# -*- coding: utf-8 -*-
"""E48 part 4 — engineering tasks T01-T06."""
from _e48_gen import t

T01 = """## Context
`docs/plan/30-release-roadmap.md` §9.3 exit criterion 6 requires an **API/WS reference** at GA. The obvious way to produce one — write it by hand — is the way it rots, and a rotted reference is worse than none because it is trusted. The contract already exists in machine-readable form: `docs/plan/22-api-openapi.yaml` is OpenAPI 3.1 with the `x-rbac`, `x-idempotency`, `x-error-codes` and `x-contract-validation` extensions, and `docs/plan/23-ws-protocol.md` §13–§15 carries fenced JSON Schemas that `tools/contracts/extract_ws_schemas.py` already bundles into `ws-schemas.json` for the `ws_message_schemas` gate (`docs/plan/03-testing-strategy.md` §5.0).

So this Task does two things: **generate** the human reference from those two sources, and **gate** it so drift is a build failure rather than documentation debt. The generator reuses the existing extraction tooling; it does not introduce a second parser of the protocol markdown, because two parsers would themselves drift.

The reference is internal and file-based. There is no documentation website: the system is private, Tailscale-only, single-owner (`docs/plan/00-planning-brief.md`), so the output is static HTML/markdown committed under `docs/reference/` and opened from the repo or linked from SCR-119 Help & about.

## Scope / Deliverables
- `tools/docs/gen_api_reference.py` — renders `docs/plan/22-api-openapi.yaml` to `docs/reference/api/` : one page per tag (`market`, `orders`, `positions`, `rules`, `admin`, `auth`, …), each operation showing path, method, summary, description, parameters, request/response schemas, the **`x-rbac` permission and scope rule**, the `x-idempotency` requirement, and the operation's error codes resolved out of `x-error-codes`.
- `tools/docs/gen_ws_reference.py` — renders `docs/reference/ws/` from `ws-schemas.json` plus the §6 topic tables of `docs/plan/23-ws-protocol.md`: the public topic catalogue (`book.{symbol}.{depth}`, `trades.{symbol}`, `bars.{symbol}.{bar_type}.{param}`, `footprint.{symbol}.{bar_type}.{param}`, `heatmap.{symbol}`, `profile.{symbol}.{kind}`, `metrics.{symbol}`, `ticker.{symbol}`, `ticker`, `liquidations.{symbol}`, `liquidations`), the private topics (`orders`, `positions`, `executions`, `wallet`, `trade_groups`, `rules`, `alerts`, `recorder`, `system`), each with its options, snapshot content, default throttle, binary kind and payload schema, plus the §6.3 topic→permission matrix, the §4.4 close codes and the §10.2 error-code table.
- A **single error-code index** page built from the one canonical registry (`x-error-codes` + `x-error-codes-ws`) — the `error_registry_single_source` gate already guarantees there is only one, so the page cites it rather than restating it.
- A **hand-written orientation page** per reference (`docs/reference/api/README.md`, `docs/reference/ws/README.md`) covering the conventions C1–C10 from the OpenAPI header and the WS envelope/sequencing model (§3, §7) — the only hand-written files in the tree, explicitly marked as such.
- **CI freshness gate** `docs-freshness` (`.github/workflows/docs.yml`): regenerates the reference and fails if the committed output differs (`git diff --exit-code`), the same regenerate-and-diff pattern the `error_registry_single_source` gate already uses for `error_codes.py` / `errorCodes.ts`. Wired as a required check on PRs touching `22-api-openapi.yaml`, `23-ws-protocol.md`, `backend/app/api/**`, `backend/app/ws/**` or `docs/reference/**`.
- **Front-matter validation** in the same job: every file under `docs/guide/`, `docs/runbooks/`, `docs/onboarding/` and `docs/reference/` validates against `docs/_meta/frontmatter.schema.json` (E48-D01), including the `reviewer != author` rule that is the machine-enforceable half of the §9.4 Docs gate.
- **Link checker** in the same job: every relative link and anchor across `docs/guide/`, `docs/runbooks/`, `docs/reference/`, `docs/onboarding/` resolves; explicit `<a id="…">` anchors referenced from the app (E48-D01's cross-link contract) must exist.
- Generated-file banner on every generated page, per E48-D01's *Look-up* template.

## Out of scope
- A documentation website, static-site generator, hosted search, or any internet-facing publication.
- Changing the contract itself. If generation reveals a contract defect (an operation missing `x-rbac`, an unreferenced component), that is a Bug against the owning epic; the existing `contracts` gate already blocks those cases, so this Task should surface few.
- Client SDK generation (TS/Python clients) — already covered by the existing codegen in the `contracts` job.
- The architecture/ADR prose reconciliation — E48-T02.

## Acceptance criteria
```gherkin
Scenario: The reference is generated, not written
  Given a clean checkout
  When tools/docs/gen_api_reference.py and tools/docs/gen_ws_reference.py are run
  Then docs/reference/api/ and docs/reference/ws/ are produced
  And git diff --exit-code reports no change against the committed output
  And every generated page carries the do-not-edit banner

Scenario: Contract drift fails the build
  Given a PR that adds an operation to docs/plan/22-api-openapi.yaml
  And the PR does not regenerate docs/reference/api/
  When CI runs the docs-freshness job
  Then the job fails naming the file that is stale
  And the PR cannot be enqueued to the merge queue

Scenario: Every operation's RBAC is visible to a reader
  Given the generated API reference
  Then every operation page states its x-rbac permissions and account-scope rule
  And every order or position mutating operation states that Idempotency-Key is required
  And an operation missing x-rbac causes generation to fail rather than render a blank

Scenario: Every WS topic is documented with its permission
  Given the generated WS reference
  Then all twenty topics of docs/plan/23-ws-protocol.md sections 6.1 and 6.2 are present
  And each states options, snapshot content, default throttle and payload schema
  And the topic-to-permission matrix of section 6.3 is rendered
  And the never-throttled rule for orders and executions is stated on those two topics

Scenario: A broken link fails the build
  Given a documentation page linking to docs/reference/ws/#topic-heatmap
  When that anchor is removed
  Then the docs-freshness job fails naming the source file and the dead target

Scenario: A document without a non-author reviewer fails
  Given a page under docs/guide/ whose front-matter reviewer equals its author
  When the front-matter validation runs
  Then it fails citing the reviewer-must-differ-from-author rule
```

## Technical notes / design
Generator design, deliberately boring:

```
gen_api_reference.py
  spec = yaml.safe_load(22-api-openapi.yaml)          # already validated by the contracts job
  errors = index(spec["x-error-codes"])
  for tag in spec["tags"]:
      ops = [op for op in walk(spec["paths"]) if tag in op.tags]
      render("templates/api_tag.md.j2", ops=ops, errors=errors) -> docs/reference/api/<tag>.md
  assert every op has x-rbac        # hard failure, not a warning
```

`gen_ws_reference.py` consumes `ws-schemas.json` produced by the existing `tools/contracts/extract_ws_schemas.py` — it **must not** re-parse `23-ws-protocol.md` for schemas. It does read the §6 topic tables as markdown tables (they are the only machine-usable form of the topic catalogue); the parse is strict and fails on an unexpected column count so a table edit cannot silently drop a topic.

Rendering target: markdown (`.md`) with explicit `<a id="…">` anchors, per E48-D01's anchor rule. Markdown rather than HTML because it diffs readably, which is what makes the regenerate-and-diff gate legible in review.

CI job sketch (`.github/workflows/docs.yml`):

```yaml
docs-freshness:
  steps:
    - run: python tools/contracts/extract_ws_schemas.py
    - run: python tools/docs/gen_api_reference.py && python tools/docs/gen_ws_reference.py
    - run: git diff --exit-code docs/reference/
    - run: python tools/docs/check_frontmatter.py docs/guide docs/runbooks docs/onboarding docs/reference
    - run: python tools/docs/check_links.py docs/
```

Exit codes are distinct per step so the failure message names which of the three rules broke. `make docs` runs all of it locally in under 10 s, matching the ergonomics of the existing `make contracts`.

Ordering constraint: this Task is `blocked_by` E48-T02 because reconciliation may change the contract files, and generating a reference from a spec that is about to be corrected wastes the review.

## Test plan
- **Unit** (`tools/docs/tests/`): tag grouping; error-code resolution for an operation referencing two codes; `x-rbac` absent → generator raises; topic-table parser given a table with a missing column → raises; anchor slug generation is stable across a heading reword (the explicit-id rule).
- **Fixture corpus**: the six front-matter fixtures from E48-D01 (valid, missing reviewer, reviewer == author, bad date, missing `doc_type`, unknown persona) asserted accept/reject by `check_frontmatter.py`.
- **Link checker**: fixtures for a dead relative link, a dead anchor, a link into `docs/plan/` (allowed), and an absolute external link (allowed but not checked for reachability — offline CI).
- **Integration**: run the full generator against the real `22-api-openapi.yaml` and `23-ws-protocol.md`; assert every path in the spec appears exactly once in the output and every topic in §6.1/§6.2 appears exactly once.
- **CI behaviour test**: a deliberate drift commit on a scratch branch confirms the job fails and the message names the stale file. Recorded as evidence on the ticket.
- Coverage target: ≥85% on `tools/docs/` (backend-package threshold, `docs/plan/03-testing-strategy.md`).

## Security notes
- Threat (information disclosure, `docs/plan/04-security-program.md` §5.7): the reference enumerates every admin endpoint and its required permission. That is acceptable — the repo is private, access is Tailscale-only, and an operator who cannot see the permission model cannot verify it. But it means the generated tree must never be published outside the repo; the orientation page states this.
- Threat (secret exposure, SR-143 / IR-02): the spec contains example values. The generator **must not** emit `example` values from any schema tagged with the key/secret classifications, and the generated tree is scanned by E48-X02's redaction sweep and by the repo's existing gitleaks rule.
- The link checker never fetches external URLs — no network egress from CI for documentation, avoiding both flakiness and an SSRF-shaped surface.
- Data classification: internal-confidential. Review label `security` not set on this ticket; its output is audited by E48-X02.

## Accessibility notes
Generated markdown is read in the repo host's renderer and linked from SCR-119. Constraints from `docs/plan/05-accessibility-standard.md` that the templates enforce: single `h1` per page, no skipped heading levels, real tables with header cells (the topic catalogue is a table, not preformatted text), link text that is meaningful out of context (never "here"), and no colour-only distinctions in the generated output.

## Performance notes
No product budget from `docs/plan/06-performance-and-load-standard.md` applies. One CI budget is set so the gate stays a pleasure rather than a tax: full generation + front-matter + link check completes in **≤30 s** in CI and **≤10 s** locally via `make docs`. Exceeding it is a Bug against this Task.

## Observability
- CI job emits the count of generated pages, operations and topics on each run so a silent drop (a tag disappearing from the spec) is visible in the log even when the diff is empty.
- No runtime telemetry. SCR-119's existing `help.about_viewed` analytics event is unchanged; no new events.

## Definition of Done
- [ ] Both generators merged with tests at ≥85% coverage.
- [ ] `docs/reference/api/` and `docs/reference/ws/` committed and byte-identical to a fresh generation.
- [ ] `docs-freshness` job added and made a **required check** on the listed paths; drift demonstrated to fail.
- [ ] Front-matter validator and link checker green across the whole `docs/` tree.
- [ ] `make docs` documented in `CONTRIBUTING.md` and in the onboarding guide (E48-T05).
- [ ] Orientation pages written and reviewed by a non-author (front-matter reviewer field populated).
- [ ] ADR not required (no new architectural decision); one-line note in `docs/plan/27-adrs/README.md` pointing at the generated reference.
- [ ] QA sign-off from E48-Q01 on reference accuracy.
- [ ] Demoed: the drift-fails-the-build behaviour shown at Sprint Review.

## Dependencies
- `blocked_by` E48-T02 — reconciliation lands contract corrections first, so the reference is generated from the final spec.
- `blocked_by` E48-D01 — supplies `docs/_meta/frontmatter.schema.json`, the Look-up template and the anchor/cross-link contract this Task implements.
- Relies on existing tooling from E01/E02/E03: `tools/contracts/extract_ws_schemas.py`, the `contracts` workflow, the merge-queue required-check configuration.

## Branch
`feat/e48-docs-api-ws-reference` — split into two PRs: (1) generators + tests + generated output, (2) CI job + front-matter/link checkers. Each comfortably under 400 LOC of hand-written code; the generated tree is large but is reviewed as generated output, flagged as such in the PR description.

## References
- `docs/plan/22-api-openapi.yaml` (header conventions C1–C10, `x-rbac`, `x-idempotency`, `x-error-codes`, `x-contract-validation`)
- `docs/plan/23-ws-protocol.md` §3 framing, §4.4 close codes, §6.1/§6.2/§6.3 topic catalogue and permissions, §7 snapshot+delta, §10.2 error codes, §13–§15 schemas
- `docs/plan/03-testing-strategy.md` §5.0 contracts gate
- `docs/plan/30-release-roadmap.md` §9.3 criterion 6, §9.4 Docs gate
- `docs/plan/14-screens-catalogue.md` SCR-119
- `docs/plan/05-accessibility-standard.md`, `docs/plan/06-performance-and-load-standard.md`
"""

t("E48-T01", "Task",
  "Publish the API/WS reference from the contract with a CI freshness gate",
  ["type/docs", "area/docs", "priority/p1", "type/ci"],
  "docs", "Sprint 25", "P1 High", "Development", "R10 Key-person", 5, "E48",
  ["E48-T02", "E48-D01", "E01", "E03"], T01)


T02 = """## Context
`docs/plan/02-definition-of-ready-done.md` §2.2 requires, at Epic close, that *"relevant `docs/plan/2x-*` architecture/schema docs and `docs/plan/1x-*` product docs reflect final shipped behavior (not the original proposal) if they diverged during implementation."* Individual epics are supposed to do this as they close. After 22 sprints and 47 preceding epics, some will have; some will have done it partially; some will have recorded the divergence only in a PR description. E48 performs the sweep that makes the statement true as a whole, because R5 exit criterion 6 (`docs/plan/30-release-roadmap.md` §9.3) names the **ADR index** as a GA deliverable and §9.4's Docs gate requires every document to have been *reviewed by someone who did not write it*.

This is deliberately a *reconciliation*, not a rewrite. The planning documents are a historical record of decisions and stay readable as such; where the built system diverged, the divergence is recorded explicitly (what was planned, what shipped, why) rather than edited away, so that the reasoning behind a change survives.

There are fifteen ADRs (`docs/plan/27-adrs/ADR-0001`…`ADR-0015`). Some will have been superseded in practice — ADR-0011 (Electron vs Tauri) was decided by a spike, ADR-0005 (WS protocol and binary encoding) will have been refined by the shipped framing, ADR-0002 (custom WebGL chart engine) by what the engine actually does. An ADR that no longer describes reality must be marked `Superseded by ADR-00NN` and a new ADR written, not silently amended — that is the whole point of the format.

## Scope / Deliverables
- **Divergence audit** across the six technical documents: `docs/plan/20-architecture.md` (C4 L1–L3 diagrams and component responsibilities), `docs/plan/21-database-schema.md` (Postgres DDL, QuestDB tables, Parquet layouts, retention, migrations), `docs/plan/22-api-openapi.yaml`, `docs/plan/23-ws-protocol.md`, `docs/plan/24-internal-schemas.md` (domain events, rule IR, OMS state machine, trade-group model, per-account profile schema, exchange adapter interface), `docs/plan/26-chart-engine-design.md`. Method: for each document, compare against the implemented artefact of record (migration history for the schema doc, the runtime spec for the API doc, `ws-schemas.json` for the protocol doc, the actual module tree for the architecture doc) and list every difference.
- A **divergence register** (`docs/plan/19-divergence-register.md`) — one row per difference: document + section, planned behaviour, shipped behaviour, the epic/PR where it changed, and the disposition (doc corrected / ADR written / accepted as planned-but-not-built with an owner).
- **Corrections merged** into the six documents for every divergence whose disposition is "doc corrected", each marked inline with a short `> Changed during implementation (Exx): …` note rather than a silent edit.
- **ADR reconciliation**: each of ADR-0001…ADR-0015 reviewed and given a current status (`Accepted` / `Superseded by ADR-00NN` / `Amended`); new ADRs written for decisions that were made during implementation but never recorded — the spike ADRs called for by the roadmap are the obvious candidates, plus any decision the divergence register shows was architectural rather than incidental.
- **ADR index** (`docs/plan/27-adrs/README.md`) rebuilt: number, title, status, date, superseded-by, one-line consequence, and the modules it governs — this is the artefact R5 exit criterion 6 names.
- **Architecture diagram refresh**: the C4 L2/L3 mermaid diagrams in `20-architecture.md` regenerated against the shipped module tree, with any module that was planned and never built removed and recorded in the divergence register.
- Front-matter (E48-D01 schema) added to each reconciled document, naming a **non-author reviewer** and date — the §9.4 gate's machine-checkable half, enforced by E48-T01's CI job.

## Out of scope
- Changing the *system* to match the documents. If reconciliation finds that the built behaviour is wrong (not merely undocumented), that is a Bug against the owning epic or E49 — this Task records it and moves on.
- `docs/plan/1x-*` product documents where the divergence is purely visual: screen and component drift is E49's design-QA sweep and E48-S03's in-app help reconciliation. This Task covers `1x-*` only where a *behavioural* contract changed (e.g. a user story's acceptance criteria no longer describe what ships).
- The generated API/WS reference — E48-T01 consumes this Task's corrected contract files.
- Rewriting planning history for readability. Only divergences are touched.

## Acceptance criteria
```gherkin
Scenario: Every technical document has been compared against reality
  Given the six documents in scope
  Then each has a completed audit entry naming the artefact of record it was compared against
  And each carries front-matter with a reviewer who is not its author and a review date

Scenario: A divergence is recorded, not erased
  Given a case where the shipped Postgres schema differs from docs/plan/21-database-schema.md
  When the document is corrected
  Then the divergence register contains a row naming planned, shipped, the originating epic and the disposition
  And the corrected section carries an inline changed-during-implementation note

Scenario: A stale ADR is superseded, not edited
  Given an ADR whose decision no longer describes the built system
  Then its status becomes Superseded by a new ADR
  And the new ADR records the context, the decision and the consequences
  And the original ADR text is left intact

Scenario: The ADR index is complete
  Given docs/plan/27-adrs/README.md
  Then every file in docs/plan/27-adrs/ appears exactly once with a status and date
  And every ADR with status Superseded names its successor
  And a link check finds no dead reference

Scenario: A planned-but-unbuilt module is not silently deleted
  Given a component present in the C4 diagrams that was never implemented
  When the diagram is regenerated
  Then the component is removed from the diagram
  And a divergence-register row records it as not built, with a named owner deciding follow-up or won't-do
```

## Technical notes / design
Artefacts of record for the comparison — chosen because each is mechanically derivable, so the audit is not one engineer's opinion:

| Document | Compared against |
|---|---|
| `20-architecture.md` | the actual package/module tree of `backend/app/**` and `packages/**`, plus the deployment compose files |
| `21-database-schema.md` | the migrated test database, introspected (the `enum_parity_db` contract gate already introspects it — reuse that connection), plus the migration history |
| `22-api-openapi.yaml` | the spec FastAPI emits at runtime — the `runtime_spec_parity` gate already asserts semantic equality, so this reduces to reading its report |
| `23-ws-protocol.md` | `ws-schemas.json` as bundled by `tools/contracts/extract_ws_schemas.py`, plus the server's topic registry |
| `24-internal-schemas.md` | the domain-event and rule-IR type definitions in code; the OMS state-machine enum |
| `26-chart-engine-design.md` | the engine package's render-stage breakdown and its benchmark harness (E46 will have reported against the same stages) |

Three of the six therefore have an existing CI gate that already proves conformance (`runtime_spec_parity`, `enum_parity_db`, `ws_message_schemas`). For those, this Task's job is to confirm the gate is green and to reconcile the **prose around** the machine-checked parts, which no gate covers. That is where the real divergence hides: a schema field can be correct while the paragraph explaining why it exists describes a design that was abandoned.

ADR status vocabulary (recorded in `27-adrs/README.md`): `Proposed`, `Accepted`, `Amended` (decision stands, details changed — amendment appended to the same file with a date), `Superseded by ADR-00NN` (decision reversed or replaced), `Withdrawn` (never implemented). Only `Amended` permits editing an existing ADR's body, and only by appending.

Divergence-register row shape:

```
| # | Document §  | Planned | Shipped | Epic/PR | Disposition | Owner |
```

## Test plan
- **Automated**: the existing `contracts` job (`docs/plan/03-testing-strategy.md` §5.0) must be green on the reconciled files — all nine gates, notably `runtime_spec_parity`, `enum_parity_db`, `error_registry_single_source`, `ws_message_schemas`. A reconciliation that breaks a gate is wrong by construction.
- **Link check**: E48-T01's checker run across `docs/plan/` to prove the ADR index and cross-document references resolve (this is the one place `docs/plan/` itself is link-checked).
- **Front-matter check**: all six documents plus every ADR validate against `docs/_meta/frontmatter.schema.json`.
- **Review test** (manual, this is the substance): for each document, a reviewer who did *not* perform the audit picks three sections at random and independently verifies them against the artefact of record. A miss rate above zero on the sample sends the document back for a full re-audit.
- **Completeness check**: every epic E01…E47 is listed with either a divergence row or an explicit "no divergence found" entry, so an unreviewed epic cannot hide as an absence.
- Coverage target: N/A (documentation Task); the automated gates above are the objective criteria.

## Security notes
- `docs/plan/04-security-program.md` §5.7 (admin screens) and §6.8 (audit log) are described across `20-architecture.md` and `24-internal-schemas.md`; a reconciliation that corrects those sections must not weaken a stated control by describing a shortcut that was taken. Any divergence in a *security* control is escalated to the Security engineer and recorded as a finding for E48-X01, not merely documented.
- Threat (information disclosure): the divergence register names shortcuts and unbuilt controls in one place, which is a useful document for an attacker. It stays in the private repo; it is never included in a support bundle (US-OBS-007) — E48-X01 adds this to the bundle's exclusion allow-list review.
- Data classification: internal-confidential.
- Review label: `security` set — the Security engineer reviews the divergence register before it merges.

## Accessibility notes
N/A for the built product. The documents themselves follow `docs/plan/05-accessibility-standard.md` heading and table rules (single h1, no skipped levels, real tables, mermaid diagrams accompanied by a prose description so the diagram is not the only carrier of the information).

## Performance notes
No budget applies. One note: `26-chart-engine-design.md`'s stage breakdown must be reconciled against the numbers E46 actually measured, so the document the next engineer reads gives real stage costs rather than the planning estimates — coordinate with E46 rather than re-measuring.

## Observability
N/A. The reconciliation adds no runtime signal. The divergence register is the observability artefact for the *planning* process and is reviewed at the R5 retro.

## Definition of Done
- [ ] All six technical documents audited, with an artefact-of-record named for each.
- [ ] `docs/plan/19-divergence-register.md` merged, with an entry or an explicit no-divergence line for every epic E01–E47.
- [ ] Corrections merged; every corrected section carries its inline changed-during-implementation note.
- [ ] All fifteen ADRs given a current status; new ADRs written for unrecorded decisions.
- [ ] `docs/plan/27-adrs/README.md` index rebuilt and link-clean.
- [ ] C4 diagrams regenerated against the shipped module tree.
- [ ] Front-matter with a non-author reviewer on all six documents and the ADR index.
- [ ] `contracts` CI job green; link and front-matter checks green.
- [ ] Architect sign-off recorded; Security engineer sign-off on the divergence register.
- [ ] Sampled re-verification performed by a second reviewer with a zero miss rate.

## Dependencies
- `blocked_by` E46 (supplies the measured engine stage costs for `26-chart-engine-design.md`) and E45 (resilience behaviour described in `20-architecture.md`).
- Blocks E48-T01 (reference generated from the corrected contract) and E48-T05 (onboarding guide reads the reconciled architecture).
- Relies on the `contracts` CI gates from E01/E03 and on each preceding epic's close-out notes.

## Branch
`chore/e48-docs-reconciliation` — one PR per document (six) plus one for the ADR index and one for the divergence register, so each is reviewable by the area owner who knows that document. No single PR should exceed 400 LOC of prose diff.

## References
- `docs/plan/02-definition-of-ready-done.md` §2.2
- `docs/plan/30-release-roadmap.md` §9.3 criterion 6, §9.4 Docs gate
- `docs/plan/20-architecture.md`, `21-database-schema.md`, `22-api-openapi.yaml`, `23-ws-protocol.md`, `24-internal-schemas.md`, `26-chart-engine-design.md`
- `docs/plan/27-adrs/ADR-0001`…`ADR-0015`, `27-adrs/README.md`
- `docs/plan/03-testing-strategy.md` §5.0
- `docs/plan/04-security-program.md` §5.7, §6.8
"""

t("E48-T02", "Task",
  "Reconcile architecture, schema docs and the ADR index with the built system",
  ["type/docs", "area/docs", "priority/p1", "security"],
  "docs", "Sprint 25", "P1 High", "Architecture", "R10 Key-person", 3, "E48",
  ["E46", "E45"], T02)


T03 = """## Context
`docs/plan/07-release-and-prr.md` §5.2 names nine runbooks that must exist before a PRR can pass, and `docs/plan/04-security-program.md` §10.3 adds five incident-response runbooks (IR-01…IR-05). Some of these will already exist in draft from the epics that built the underlying capability — E44 wrote the kill switch, E45 built the chaos catalogue, E42 shipped SCR-146 Admin: backups & restore. This Task's job is not to invent procedures from nothing; it is to **complete the set**, bring every runbook onto the *Do* template from E48-D01, and make each one executable by a person who did not build the subsystem.

It is deliberately small (2 points) and deliberately early in the epic, because E48-S04 — the rehearsal programme — cannot start until the text exists, and S04 is the long pole.

The distinction that makes this Task cheap and S04 expensive: writing down what you believe the procedure is takes an afternoon; discovering that step 4 does not work takes a rehearsal.

## Scope / Deliverables
The complete set under `docs/runbooks/`, each on the *Do* template (trigger, pre-conditions, numbered steps with an **Expected observation** per step, abort/rollback step, escalation, rehearsal-record table):

| ID | Runbook | Source of the procedure |
|---|---|---|
| RB-01 | WS disconnect / reconnect storm | `23-ws-protocol.md` §9.2 reconnection, §9.3 resubscription, §7.4 server-initiated resync; E45's chaos scenario |
| RB-02 | Exchange outage / 5xx | `04-security-program.md` §10.3 IR-05; the stale-data flag (SR-038) |
| RB-03 | Rate-limit breach handling (Bybit `10018`) | SCR-147 Admin: exchange connectivity & rate limits; the per-UID budget model |
| RB-04 | OMS stuck-order reconciliation | `24-internal-schemas.md` OMS state machine; `GET /api/v1/orders/{orderId}/diagnostics` |
| RB-05 | Fan-out partial-failure recovery | `24-internal-schemas.md` trade-group model; the native exchange-side SL invariant |
| RB-06 | Postgres failover | `07-release-and-prr.md` §5.3; SCR-146 |
| RB-07 | QuestDB / Parquet recovery from corruption | `07-release-and-prr.md` §5.3; `21-database-schema.md` retention/tiering |
| RB-08 | Feature-flag emergency kill | `04-security-program.md` §9 kill switch; SCR-145 Admin: feature flags; WS `system` topic kill-switch transitions |
| RB-09 | Full-system rollback | `07-release-and-prr.md` §7 rollback procedure |
| IR-01 | Suspected unauthorised order / account compromise | `04-security-program.md` §10.3 IR-01 (nine steps, verbatim starting point) |
| IR-02 | Secret exposed | §10.3 IR-02 (six steps) |
| IR-03 | Malicious / compromised manager | §10.3 IR-03 |
| IR-04 | Dependency or container vulnerability with known exploitation | §10.3 IR-04 |
| IR-05 | Exchange-side anomaly | §10.3 IR-05 |

Plus:
- `docs/runbooks/README.md` — the index, the on-call escalation path (who is paged, how, backup contact — the third bullet of §5.2), and the "which runbook do I need" decision table that E48-D01's research showed is the actual entry point under stress.
- **Screen and endpoint citations** in every step that requires an operator action: the screen id (SCR-143 system health, SCR-145 feature flags, SCR-146 backups & restore, SCR-147 connectivity & rate limits) and, where the action is API-driven, the endpoint (`POST /api/v1/admin/backups/{backupId}/restore`, `PATCH /api/v1/admin/feature-flags/{flagKey}`, `GET /api/v1/admin/health`, `GET /api/v1/orders/{orderId}/diagnostics`). A step that says "restore the backup" without naming where is not done.
- **Detection line** per runbook: which alert from `07-release-and-prr.md` §5.1 fires to start this runbook, or an explicit "no alert — discovered by observation" so the gap is visible.
- **A hard "do not" list** per runbook where a plausible wrong action exists (e.g. RB-09: do not run a down-migration that was not rehearsed; RB-05: do not re-send the whole fan-out, only the failed legs).

## Out of scope
- Rehearsing them (E48-S04) — this Task ends when the text exists and has been read.
- The DR playbook, which is a different artefact with measured targets (E48-T04); RB-06/RB-07 are the *procedures*, the DR playbook is the *drill and its budget*.
- Building any missing capability a runbook would need. If writing RB-nn reveals that the system has no way to perform a required step, that is a Bug against the owning epic, recorded here and blocking S04's rehearsal of that runbook.
- Runbooks for capabilities out of scope for v1 (other exchanges, mobile, a separate admin app — none exist).

## Acceptance criteria
```gherkin
Scenario: The set is complete
  Given docs/plan/07-release-and-prr.md section 5.2 and docs/plan/04-security-program.md section 10.3
  Then a runbook exists for each of the nine operational and five incident-response procedures
  And each is on the Do template from E48-D01
  And docs/runbooks/README.md indexes all fourteen

Scenario: Every step states what the operator should see
  Given any runbook
  Then every numbered step has a non-empty Expected observation
  And a step whose observation is unknown is marked as such and blocks that runbook's sign-off

Scenario: Every operator action names its surface
  Given a step requiring an action in the application
  Then it cites a screen id from docs/plan/14-screens-catalogue.md or an API path from docs/plan/22-api-openapi.yaml
  And a link check resolves that citation

Scenario: The detection path is explicit
  Given any runbook
  Then it names the alert from docs/plan/07-release-and-prr.md section 5.1 that starts it
  Or it states explicitly that no alert exists for this condition

Scenario: A missing capability surfaces as a bug, not as vague prose
  Given a required step the system cannot currently perform
  Then the runbook records the gap
  And a Bug ticket is filed against the owning epic and linked
  And that runbook cannot be signed off until the Bug is resolved

Scenario: The on-call rotation has read them
  Given the PRR requirement that each runbook be read through by the on-call rotation
  Then each runbook records the names and dates of the rotation members who read it
```

## Technical notes / design
Step-numbering discipline (from the *Do* template): one action per step, imperative mood, present tense, no conjunctions. "Open SCR-145 and disable the flag" is two steps, because under stress a reader loses their place mid-sentence.

Every runbook opens with the same three-line header so the reader can abort immediately if they are in the wrong document:

```
TRIGGER:   you are here because <observable condition>
NOT THIS:  if instead <adjacent condition>, go to <other runbook>
FIRST:     <the one action that reduces risk before diagnosis>
```

`FIRST` matters: `07-release-and-prr.md` §7 rule 2 is *kill-switch before rollback* for any P0 involving live order flow. Every runbook whose condition could involve live order flow therefore has the kill switch (SCR-145 / §9 of the security program) as its `FIRST` line, and says so explicitly rather than burying it at step 6.

RB-05 carries the epic's single most safety-relevant assertion: after a partial fan-out, **every filled leg must carry a native exchange-side SL** (the locked invariant from `docs/plan/00-planning-brief.md` and SR-056). The runbook states how to verify it per account and what to do if it is missing. S04 automates that check during rehearsal.

IR-01…IR-05 are transcribed from `04-security-program.md` §10.3 with steps expanded into the template's granularity and expected observations added — the security program states *what* to do; the runbook adds *what you will see when it worked*. The security program remains the source of truth; a conflict is resolved in its favour and the runbook corrected.

## Test plan
- **Structural check** (automated, part of E48-T01's front-matter validator): every file under `docs/runbooks/` has `doc_type: do`, a trigger, at least one step, a rehearsal-record table, and a reviewer who is not the author.
- **Citation check** (automated, link checker): every SCR id and API path cited resolves.
- **Desk-check** (manual): each runbook is read start-to-finish by an on-call rotation member who did not write it, who flags any step they could not perform from the text alone. This satisfies the §5.2 "read through by the on-call rotation" checkbox and is the input to S04's rehearsal schedule.
- **Cross-reference check**: the `NOT THIS` lines form a closed graph — every referenced runbook exists; no runbook points to itself.
- Coverage target: N/A. The objective criterion is the structural check plus one desk-check signature per runbook.

## Security notes
- IR-01…IR-05 are reproduced from `docs/plan/04-security-program.md` §10.3; the Security engineer reviews the transcription for fidelity before merge (a runbook that drifts from the security program is a control failure, not a typo).
- Threat (information disclosure): the runbooks name admin surfaces, the kill-switch mechanism and the key-rotation procedure. They stay in the private repo and are excluded from the support bundle (US-OBS-007) — verified by E48-X01.
- Threat (privilege escalation): IR-01 step 3 and IR-02 involve credential rotation. The runbook must never contain a credential, a KEK location, or a tailnet address — only the procedure. E48-X02 audits this.
- Data classification: internal-confidential.
- Review label: `security` set; Security engineer sign-off required on IR-01…IR-05 specifically.

## Accessibility notes
Per E48-D01's *Do* template: real tables with header cells (step / action / expected observation), no images (a runbook for "everything is down" cannot depend on loading an asset), heading hierarchy intact, and no colour-only severity marking — severity is a word.

## Performance notes
No product budget applies. One authoring constraint: each runbook must be readable end-to-end in under five minutes and printable to at most three pages. A longer procedure is split, because a runbook nobody finishes is not a control.

## Observability
Each runbook's detection line ties it to a specific alert from `07-release-and-prr.md` §5.1. Where a runbook's condition has **no** alert, this Task files a Task against the observability epic (E03) to add one — writing down that gap is the deliverable here; closing it is not.

## Definition of Done
- [ ] All fourteen runbooks merged under `docs/runbooks/` on the *Do* template.
- [ ] `docs/runbooks/README.md` index, escalation path and decision table merged.
- [ ] Structural, citation and cross-reference checks green.
- [ ] One desk-check signature per runbook from a non-author on-call member; `07-release-and-prr.md` §5.2 read-through checkbox satisfied.
- [ ] Security engineer sign-off on IR-01…IR-05 fidelity.
- [ ] Every capability gap found is filed as a Bug and linked; every missing alert filed against E03.
- [ ] Front-matter with non-author reviewer on every file; CI checks green.
- [ ] Handed to E48-S04 with the rehearsal schedule drafted.

## Dependencies
- `blocked_by` E48-D01 (the *Do* template and front-matter schema).
- Cross-epic: E44 (kill switch and environment separation — RB-08, IR-01), E45 (chaos catalogue — RB-01/RB-02/RB-03 procedures mirror its scenarios), E42 (SCR-143/145/146/147, the admin surfaces every runbook cites), E03 (the alert catalogue the detection lines reference).
- Blocks E48-S04 and E48-T04.

## Branch
`docs/e48-runbook-set` — one PR for the nine operational runbooks, one for the five IR runbooks (so the Security engineer reviews a single coherent PR), one for the index and escalation path.

## References
- `docs/plan/07-release-and-prr.md` §5.1 alerts, §5.2 runbooks, §5.3 backups/restore, §7 rollback
- `docs/plan/04-security-program.md` §9 kill switch, §10.2 incident flow, §10.3 IR-01…IR-05, SR-038, SR-056
- `docs/plan/14-screens-catalogue.md` SCR-143, SCR-145, SCR-146, SCR-147
- `docs/plan/22-api-openapi.yaml` `/admin/backups`, `/admin/backups/{backupId}/restore`, `/admin/feature-flags/{flagKey}`, `/admin/health`, `/orders/{orderId}/diagnostics`
- `docs/plan/23-ws-protocol.md` §7.4, §9.2, §9.3, `system` topic
- `docs/plan/24-internal-schemas.md` (OMS state machine, trade-group model)
"""

t("E48-T03", "Task",
  "Complete the operations and incident-response runbook set",
  ["type/docs", "area/docs", "priority/p0", "security"],
  "docs", "Sprint 25", "P0 Critical", "Ops", "R11 Alert reliability", 2, "E48",
  ["E48-D01", "E44", "E45", "E42", "E03"], T03)
