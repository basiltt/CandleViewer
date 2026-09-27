// Runtime binary frame decoders and sequence/resync helpers for the WS
// protocol (docs/plan/23-ws-protocol.md). This directory parses *untrusted*
// input from the network — flagged as a fuzz target for E03's
// Schemathesis/contract job. Scaffold only (E02-T03); real decoders land
// alongside the generated WS types in E02-T09.

/** Result of a sequence-gap check against the last-seen frame sequence number. */
export type SeqCheckResult = "ok" | "gap" | "duplicate" | "out-of-order";

/**
 * Compares an incoming frame sequence number against the last-accepted one.
 * A `"gap"`, `"duplicate"` or `"out-of-order"` result means the caller must
 * resync from a fresh snapshot (C-2.5) — this helper only classifies, it
 * never resyncs itself.
 */
export function checkSequence(lastSeq: number, incomingSeq: number): SeqCheckResult {
  if (incomingSeq === lastSeq + 1) return "ok";
  if (incomingSeq === lastSeq) return "duplicate";
  if (incomingSeq < lastSeq) return "out-of-order";
  return "gap";
}
