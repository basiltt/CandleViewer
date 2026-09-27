# @candleviewer/protocol

Generated TS types/decoders from `docs/plan/22-api-openapi.yaml` (REST) and
`docs/plan/23-ws-protocol.md` (WS), plus hand-written runtime binary frame
decoders and sequence/resync helpers.

- `src/generated/` — **never hand-edit**. Marked `linguist-generated` in
  `.gitattributes`; `pnpm generate` regenerates it and updates
  `src/generated/.manifest.json`. `scripts/check-generated-guard.mjs` fails
  the build if a file's hash no longer matches the manifest.
- `src/runtime/` — sequence-gap classification and frame decoding for
  untrusted WS input; a fuzz target for E03's Schemathesis/contract job.

Real generated content lands in E02-T09; this is an E02-T03 scaffold.

## Scripts

- `pnpm --filter @candleviewer/protocol generate` — runs the header-guard
  check, then (once E02-T09 lands) the OpenAPI/WS codegen.
- `pnpm --filter @candleviewer/protocol build` / `test` / `test:cov`.
