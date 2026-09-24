# ADR-0005 — WS protocol: snapshot + delta with binary market-data frames

- Status: **decided**
- Date: 2026-09-14
- Deciders: Architect, Backend lead, Frontend lead, Chart-engine lead
- Consulted: `docs/research/22-architecture-options.md` §4, `docs/research/06-bybit-api.md` §14, digest 10 open question #6
- Related: `docs/plan/23-ws-protocol.md`, `docs/plan/26-chart-engine-design.md` §9, ADR-0004

## Context and problem statement

The browser needs book top-N, footprint cells, heatmap columns (one per 100 ms), bars, trades, CVD/OI/funding series and OMS state, continuously, for several symbols and several chart panes at once, within a ≤ 250 ms tick-to-pixel budget of which only ~20 ms belongs to fan-out. JSON over WebSocket is the obvious starting point and is easy to debug, but the heatmap alone is 512 floats every 100 ms per symbol, and a footprint window is thousands of numeric cells — exactly the payload shapes where JSON parsing dominates the frontend frame budget.

## Decision drivers

- Chart engine decodes in a worker and wants **typed arrays it can hand to the GPU without a copy**.
- Backend must not re-serialise per client: one encode, many sends.
- Protocol must be client-agnostic (planning brief P1) and versioned.
- Recovery must be deterministic without checksums, mirroring Bybit's own model.
- Debuggability matters: an engineer must be able to read the control plane in DevTools.

## Considered options

1. **Hybrid: JSON control frames + custom binary market-data frames**, snapshot+delta with per-topic sequence numbers.
2. **JSON everywhere.**
3. **MessagePack everywhere.**
4. **Protobuf everywhere** (schema-first, codegen for Python and TS).

## Decision outcome

**Chosen: option 1.**

- **Control plane (JSON)**: `hello`, `welcome`, `subscribe`, `unsubscribe`, `ack`, `error`, `resync_required`, `ping`/`pong`, OMS commands and OMS state updates. Human-readable in DevTools, low volume.
- **Data plane (binary)**: book, footprint, heatmap, bars, trades, profile. Little-endian, fixed 24-byte header `{magic u16, version u8, kind u8, flags u16, topicId u16, seq u64, payloadLen u32, count u32}` followed by struct-of-arrays payloads whose column layouts are declared in `23-ws-protocol.md`. Prices are int32 ticks relative to a per-topic `priceOrigin`; times are int64 microseconds.
- **MessagePack** is used for mid-tier structured payloads that are neither tiny control messages nor columnar arrays (e.g. a profile period descriptor with heterogeneous fields).
- **Snapshot + delta**: every topic has one sequence domain. A `snapshot` frame carries the state and the seq it is consistent with; `delta` frames carry monotonically increasing seqs. A gap, an overflow, or any doubt produces a `resync_required` control frame followed by a fresh snapshot. **No checksums**, matching Bybit's own philosophy.
- **Capability negotiation**: `hello` declares `binary: true|false`. A client that declares `binary: false` receives JSON for everything — so the protocol remains fully usable from `wscat` and from any future client that has not implemented the decoders.
- **Versioning**: `proto` integer in `hello`/`welcome`. The server supports the current and previous version; a mismatch closes with a typed code and an explanatory reason.
- **Compression**: `permessage-deflate` is **off** for the data plane (the payloads are already dense numerics and deflate would add per-frame CPU on both ends) and on for the control plane only if measured to help.

### Consequences

Positive:
- The worker decodes a frame into `Float32Array`/`Int32Array` views over the received buffer with no parse and no copy, then transfers it to the render worker — this is what keeps the ≤ 4 ms p95 decode budget achievable.
- One encode per topic serves all subscribers, so client count does not multiply backend CPU.
- The JSON control plane keeps the system debuggable and keeps the contract legible in `23-ws-protocol.md`.

Negative / risks:
- Two encodings to maintain and test. Mitigated by generating both the Python encoder and the TS decoder from a single schema declaration in `packages/protocol`, with a round-trip property test.
- Binary framing is unforgiving of drift. Mitigated by the `version` byte, a CI check that regenerates `packages/protocol` and fails on a diff, and fuzz tests feeding malformed frames to the decoder.

### Why not the alternatives

- **JSON everywhere**: simplest, but measurement in comparable systems puts `JSON.parse` of a 512-float heatmap column plus a footprint window well into the frame budget, and it triples bandwidth. It remains available as the negotiated fallback, which captures most of its debuggability benefit at no architectural cost.
- **MessagePack everywhere**: better than JSON, but it still produces JS arrays of numbers rather than typed arrays, so the copy into GPU-ready buffers remains. Adopted for the mid-tier only.
- **Protobuf everywhere**: strong schema and codegen, but varint encoding of dense numeric columns is both slower to decode and larger than a fixed-width struct-of-arrays layout for our shapes, and research found the Python/TS codegen DX unresearched. Rejected for the data plane; the schema-first discipline is recovered by generating our own codecs.

## Validation

- Spike S5: measure binary vs JSON on a real heatmap + footprint workload. Gate: ≥ 40 % bandwidth reduction and ≥ 30 % decode-time reduction, else the data plane stays JSON and this ADR is amended.
- Contract tests: every frame kind round-trips Python encode → TS decode → re-encode, byte-identical.
- Fuzz tests: malformed frames, truncated payloads, out-of-order and duplicate sequences, NaN/Infinity values.
- Benchmark B7 in `26-chart-engine-design.md` §13 enforces the decode budget in CI.
