# @candleviewer/protocol

Generated TS types/decoders from `docs/plan/22-api-openapi.yaml` (REST) and
`docs/plan/23-ws-protocol.md` (WS), plus hand-written runtime binary frame
decoders and sequence/resync helpers.

- `src/generated/rest/` — TS types for every OpenAPI schema/operation, via
  `openapi-typescript`. **Never hand-edit.**
- `src/generated/ws/` — TS types for every WS envelope/message-kind/topic
  payload, via `json-schema-to-typescript` compiling
  `docs/plan/ws-schema.json` (a machine-readable extract of
  `23-ws-protocol.md` §13-15, produced by
  `scripts/extract-ws-schema.mjs`). Also exports `WsTopicPayloadMap`, mapping
  every §6 topic pattern to its payload type. **Never hand-edit.**
- `src/generated/index.ts` — barrel re-exporting both surfaces as `rest` and
  `ws` namespaces.
- All of `src/generated/` is marked `linguist-generated` in `.gitattributes`;
  `pnpm generate` regenerates it and updates `src/generated/.manifest.json`.
  `scripts/check-generated-guard.mjs` fails the build if a file's header or
  hash no longer matches the manifest (i.e. someone hand-edited it).
- `src/runtime/` — sequence-gap classification (`checkSequence`) and binary
  frame decoders for the six §3.4 `body_kind`s (book snapshot/delta, trades,
  bars, footprint, heatmap column) over untrusted WS input; a fuzz target for
  E03's Schemathesis/contract job.

The Python side of this same contract pair (pydantic v2 models under
`services/api/candleviewer/{api,ws}/_generated/`) is generated separately by
`services/api/scripts/generate_protocol_models.py`, wrapping
`datamodel-code-generator` — see that script's docstring.

## Scripts

- `pnpm --filter @candleviewer/protocol generate` — runs, in order:
  `extract-ws-schema.mjs` (markdown → `docs/plan/ws-schema.json`),
  `generate-rest-types.mjs` (OpenAPI → `src/generated/rest/`),
  `generate-ws-types.mjs` (ws-schema.json → `src/generated/ws/`),
  `update-manifest.mjs` (recomputes `.manifest.json`), then
  `check-generated-guard.mjs`.
- `pnpm --filter @candleviewer/protocol generate:check` — the staleness gate:
  re-extracts the WS schema and diffs it against the committed
  `docs/plan/ws-schema.json`, then runs the header-guard check. CI additionally
  runs `pnpm generate && git diff --exit-code` to catch drift in the TS output
  itself (`AGENTS.md` §4).
- `pnpm --filter @candleviewer/protocol build` / `test` / `test:cov`.
