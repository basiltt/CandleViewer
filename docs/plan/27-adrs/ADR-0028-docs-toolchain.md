# ADR-0028 — Documentation toolchain and reference-generation pipeline

- Status: **proposed-with-deadline (offline-build proof tracked in #1750; owner waiver pending, not assumed)** — deadline: first green E48-T02 CI run that proves the network-less build and the <=180 s budget. Owner approval pending.
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

## Evidence and its limits

Measured: unscoped MkDocs build median 201 s over 3 runs on a loaded Windows box (**over budget unscoped**; one scoped
run 111 s), 16/16 mermaid fences emitted, 220 operations in the OpenAPI source. **Not measured:** other candidates'
builds, Redocly run, `--network=none` build (no docker locally), axe, FCP, link-check noise, `pip-audit`. See the
spike's honesty box. The ADR is proposed rather than decided precisely because those hard requirements are unproven.

## Rejected (desk assessment, not benchmarked)

- **Docusaurus:** MDX makes `{}`/`<` in runbooks a build error; large npm surface; native versioning not needed (one live version).
- **Astro/Vite on `packages/ui`:** best theming, but we would own search, mermaid and link checking.
- **Scalar:** new dependency, default CDN assets; Redocly is already vetted.

## Consequences / revisit

Adds a Python docs dependency group (needs `security-review` + CODEOWNER when introduced in E48-T02). Revisit if the
scoped build exceeds 180 s on CI, if the network-less build fails (that candidate is eliminated; fall back to
Docusaurus), or if MkDocs 2.0 forces a migration.
