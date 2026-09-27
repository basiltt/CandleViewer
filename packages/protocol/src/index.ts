// Public entrypoint for @candleviewer/protocol.
// Generated OpenAPI/WS types (rest, ws) plus the runtime binary frame
// decoders and seq/resync helpers (E02-T09). App code imports from here,
// never from src/generated directly.
export * from "./runtime/index.js";
export * as rest from "./generated/rest.js";
export * as ws from "./generated/ws.js";
