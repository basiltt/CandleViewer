# ADR-0028 — Documentation toolchain and reference-generation pipeline

- Status: **proposed** — owner approval pending. Measurements: CI run 37148408413 (offline `--network=none` builds, all candidates).
- Date: 2026-10-03
- Deciders: Owner (`@basiltt`). The ticket says "ADR-0016 (or next free number)"; 0028 is next free.
- Related: E48-K01 (#1328), E48-T02, `docs/plan/spikes/E48-K01.md`, `30-release-roadmap.md` §9.3-9.4, C-16.5.

## Context

R5 needs a built, searchable doc set with REST/WS reference generated from `22-api-openapi.yaml` and
`23-ws-protocol.md`, building without network, rendering mermaid, in <=3 min. The site is private (Tailscale only).

## Decision

- **Prose site: MkDocs Material**, pinned `mkdocs<2` and hash-locked (MkDocs 2.0 announces plugin/theme breakage).
- **REST reference: Redocly CLI `build-docs`** (already the OpenAPI linter) from the single YAML source.
- **WS reference: small generator script** emitting Markdown from the WS schema bundle.
- **Staleness:** `make docs && git diff --exit-code` fails with `DOC-002`.
- Mermaid via `pymdownx.superfences`; **vendor mermaid.js** so viewing works air-gapped.
- Build scope excludes `docs/plan/backlog/` (35 MB of JSON).

Drivers: plain-Markdown authoring (the pre-committed tiebreaker), no new language runtime (Python/uv already present),
no second copy of endpoint docs, small supply chain (31 Python distributions measured).

## Evidence

Measured on CI (spike doc, "CI measurements"): all five candidates build offline in `--network=none` containers from a
20-page fixture. MkDocs Material 0.7 s build / 12 s install / 80 MB deps; Docusaurus 2-10 s / 39 s / 207 MB (needed a webpack
override to build at all); Astro Starlight 3.1 s / 18 s / 250 MB; Redocly 2.0 s / 1 s / 10 MB for the full 220-op spec; Scalar
0.4 s but 181 MB deps and its CLI needs Node>=24. Local full-tree MkDocs: 201 s unscoped, 60 s scoped (loaded laptop).
Timing does not discriminate at this size; supply-chain size, authoring friction and fixture stability do: MkDocs has the
smallest dependency surface (80 MB, 31 Python dists) and plain-Markdown authoring; Docusaurus broke on the stock install.
Not yet measured (E48-T02): full-tree CI time, axe, FCP, link-check noise, pip-audit.

## Rejected

- **Docusaurus:** passes offline but required a pin workaround, MDX makes `{}`/`<` errors, 207 MB npm tree.
- **Astro Starlight:** passes, but 250 MB tree and we would own mermaid/link checking.
- **Scalar:** passes, but 181 MB tree, Node>=24 CLI vs repo Node 20; Redocly is smaller and already the linter.

## Consequences / revisit

Adds a Python docs dependency group (needs `security-review` + CODEOWNER when introduced in E48-T02). Revisit if the
scoped build exceeds 180 s on CI, if the network-less build fails (that candidate is eliminated; fall back to
Docusaurus), or if MkDocs 2.0 forces a migration.
