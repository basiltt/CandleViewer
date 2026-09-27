// Runtime binary frame decoders and sequence/resync helpers for the WS
// protocol (docs/plan/23-ws-protocol.md §3.4, §3.6, §7). This module parses
// *untrusted* input from the network — flagged as a fuzz target for E03's
// Schemathesis/contract job (E02-T09).

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

// ---------------------------------------------------------------------------
// §3.4 binary payload format (e: "b")
// ---------------------------------------------------------------------------

/** `0x43565742` ("CVWB"), the magic number every binary frame body starts with. */
export const BINARY_FRAME_MAGIC = 0x43565742;

export const BODY_KIND = {
  BOOK_SNAPSHOT: 1,
  BOOK_DELTA: 2,
  TRADES: 3,
  BARS: 4,
  FOOTPRINT: 5,
  HEATMAP_COLUMN: 6,
} as const;

export type BodyKind = (typeof BODY_KIND)[keyof typeof BODY_KIND];

/** Bit flags carried in the common header's `flags` byte (§3.4). */
export interface BinaryFrameFlags {
  estimated: boolean;
  coalesced: boolean;
  replay: boolean;
  partial: boolean;
}

/** The 24-byte common header prefixing every binary frame body. */
export interface BinaryFrameHeader {
  magic: number;
  formatVersion: number;
  bodyKind: BodyKind;
  flags: BinaryFrameFlags;
  /** Decimal exponent: real price = int / 10^priceScale. */
  priceScale: number;
  /** Decimal exponent: real size = int / 10^qtyScale. */
  qtyScale: number;
  recordCount: number;
  /** Epoch-ms base; per-record times are u32 offsets from this. */
  tsBaseMs: bigint;
}

export const COMMON_HEADER_BYTES = 24;

/** Thrown by every decoder below on any malformed input (§3.4 "Client obligations"). */
export class BinaryFrameError extends Error {
  constructor(
    message: string,
    readonly code: "frame_malformed" | "unsupported_body_kind" = "frame_malformed",
  ) {
    super(message);
    this.name = "BinaryFrameError";
  }
}

function readFlags(byte: number): BinaryFrameFlags {
  return {
    estimated: (byte & 0b0001) !== 0,
    coalesced: (byte & 0b0010) !== 0,
    replay: (byte & 0b0100) !== 0,
    partial: (byte & 0b1000) !== 0,
  };
}

/**
 * Parses the 24-byte common header (§3.4). Per the client-obligations
 * paragraph, this validates `magic` and `format_version` but never rejects
 * trailing bytes it does not recognise — callers ignore anything after the
 * body they know how to decode, for forward compatibility.
 */
export function parseBinaryFrameHeader(buf: ArrayBufferView): BinaryFrameHeader {
  if (buf.byteLength < COMMON_HEADER_BYTES) {
    throw new BinaryFrameError(
      `binary frame too short for the ${COMMON_HEADER_BYTES}-byte common header (got ${buf.byteLength} bytes)`,
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const magic = view.getUint32(0, true);
  if (magic !== BINARY_FRAME_MAGIC) {
    throw new BinaryFrameError(
      `bad magic 0x${magic.toString(16)}, expected 0x${BINARY_FRAME_MAGIC.toString(16)} ("CVWB")`,
    );
  }
  const formatVersion = view.getUint8(4);
  const rawBodyKind = view.getUint8(5);
  if (rawBodyKind < 1 || rawBodyKind > 6) {
    throw new BinaryFrameError(`unknown body_kind ${rawBodyKind}`, "unsupported_body_kind");
  }
  return {
    magic,
    formatVersion,
    bodyKind: rawBodyKind as BodyKind,
    flags: readFlags(view.getUint8(6)),
    priceScale: view.getUint8(7),
    qtyScale: view.getUint8(8),
    // bytes 9-11 reserved, deliberately skipped.
    recordCount: view.getUint32(12, true),
    tsBaseMs: view.getBigUint64(16, true),
  };
}

/** Converts a scaled 64-bit integer (price or size) back to a decimal string, per §3.4. */
export function unscale(value: bigint, scale: number): string {
  const negative = value < 0n;
  const magnitude = negative ? -value : value;
  const divisor = 10n ** BigInt(scale);
  const whole = magnitude / divisor;
  const frac = magnitude % divisor;
  const sign = negative ? "-" : "";
  if (scale === 0) return `${sign}${whole.toString()}`;
  return `${sign}${whole.toString()}.${frac.toString().padStart(scale, "0")}`;
}

export interface BookLevel {
  side: "bid" | "ask";
  price: string;
  /** `size === "0"` means delete this level (§3.4). */
  size: string;
}

export interface BookSnapshotTrailer {
  /** Bybit update id, carried for diagnostics only — never used for our own sequencing. */
  xu: bigint;
  /** Bybit cross-sequence, carried for diagnostics only. */
  xseq: bigint;
}

export interface DecodedBookSnapshot {
  header: BinaryFrameHeader;
  levels: BookLevel[];
  trailer: BookSnapshotTrailer;
}

export interface DecodedBookDelta {
  header: BinaryFrameHeader;
  levels: BookLevel[];
}

const BOOK_RECORD_BYTES = 17;
const BOOK_TRAILER_BYTES = 16;

function decodeBookLevels(
  view: DataView,
  offset: number,
  header: BinaryFrameHeader,
): { levels: BookLevel[]; nextOffset: number } {
  const levels: BookLevel[] = [];
  let cursor = offset;
  for (let i = 0; i < header.recordCount; i += 1) {
    if (cursor + BOOK_RECORD_BYTES > view.byteLength) {
      throw new BinaryFrameError(
        `book record ${i} runs past the buffer (record_count=${header.recordCount})`,
      );
    }
    const sideByte = view.getUint8(cursor);
    if (sideByte !== 0 && sideByte !== 1) {
      throw new BinaryFrameError(`invalid book side byte ${sideByte} at record ${i}`);
    }
    const price = view.getBigInt64(cursor + 1, true);
    const size = view.getBigUint64(cursor + 9, true);
    levels.push({
      side: sideByte === 0 ? "bid" : "ask",
      price: unscale(price, header.priceScale),
      size: unscale(size, header.qtyScale),
    });
    cursor += BOOK_RECORD_BYTES;
  }
  return { levels, nextOffset: cursor };
}

/** Decodes a `body_kind: 1` (book_snapshot) binary frame body. */
export function decodeBookSnapshot(buf: ArrayBufferView): DecodedBookSnapshot {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.BOOK_SNAPSHOT) {
    throw new BinaryFrameError(
      `expected body_kind=1 (book_snapshot), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const { levels, nextOffset } = decodeBookLevels(view, COMMON_HEADER_BYTES, header);
  if (nextOffset + BOOK_TRAILER_BYTES > view.byteLength) {
    throw new BinaryFrameError("book snapshot missing its 16-byte xu/xseq trailer");
  }
  return {
    header,
    levels,
    trailer: {
      xu: view.getBigUint64(nextOffset, true),
      xseq: view.getBigUint64(nextOffset + 8, true),
    },
  };
}

/** Decodes a `body_kind: 2` (book_delta) binary frame body. */
export function decodeBookDelta(buf: ArrayBufferView): DecodedBookDelta {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.BOOK_DELTA) {
    throw new BinaryFrameError(
      `expected body_kind=2 (book_delta), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const { levels } = decodeBookLevels(view, COMMON_HEADER_BYTES, header);
  return { header, levels };
}

export interface TradeFlags {
  blockTrade: boolean;
  liquidationOrigin: boolean;
  clusterAggregated: boolean;
}

export interface DecodedTrade {
  tsMs: bigint;
  price: string;
  size: string;
  side: "buy" | "sell";
  flags: TradeFlags;
}

export interface DecodedTrades {
  header: BinaryFrameHeader;
  trades: DecodedTrade[];
}

const TRADE_RECORD_BYTES = 22;

/** Decodes a `body_kind: 3` (trades) binary frame body. */
export function decodeTrades(buf: ArrayBufferView): DecodedTrades {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.TRADES) {
    throw new BinaryFrameError(
      `expected body_kind=3 (trades), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const trades: DecodedTrade[] = [];
  let cursor = COMMON_HEADER_BYTES;
  for (let i = 0; i < header.recordCount; i += 1) {
    if (cursor + TRADE_RECORD_BYTES > view.byteLength) {
      throw new BinaryFrameError(
        `trade record ${i} runs past the buffer (record_count=${header.recordCount})`,
      );
    }
    const tsOffsetMs = view.getUint32(cursor, true);
    const price = view.getBigInt64(cursor + 4, true);
    const size = view.getBigUint64(cursor + 12, true);
    const sideByte = view.getUint8(cursor + 20);
    if (sideByte !== 0 && sideByte !== 1) {
      throw new BinaryFrameError(`invalid trade side byte ${sideByte} at record ${i}`);
    }
    const flagsByte = view.getUint8(cursor + 21);
    trades.push({
      tsMs: header.tsBaseMs + BigInt(tsOffsetMs),
      price: unscale(price, header.priceScale),
      size: unscale(size, header.qtyScale),
      side: sideByte === 0 ? "buy" : "sell",
      flags: {
        blockTrade: (flagsByte & 0b0001) !== 0,
        liquidationOrigin: (flagsByte & 0b0010) !== 0,
        clusterAggregated: (flagsByte & 0b0100) !== 0,
      },
    });
    cursor += TRADE_RECORD_BYTES;
  }
  return { header, trades };
}

export interface DecodedBar {
  tsMs: bigint;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  turnover: string;
  trades: number;
  delta: string;
  /** bit0 `confirm` — this bar is closed and will not be revised further. */
  confirmed: boolean;
}

export interface DecodedBars {
  header: BinaryFrameHeader;
  bars: DecodedBar[];
}

const BAR_RECORD_BYTES = 69;

/** Decodes a `body_kind: 4` (bars) binary frame body. */
export function decodeBars(buf: ArrayBufferView): DecodedBars {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.BARS) {
    throw new BinaryFrameError(
      `expected body_kind=4 (bars), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const bars: DecodedBar[] = [];
  let cursor = COMMON_HEADER_BYTES;
  for (let i = 0; i < header.recordCount; i += 1) {
    if (cursor + BAR_RECORD_BYTES > view.byteLength) {
      throw new BinaryFrameError(
        `bar record ${i} runs past the buffer (record_count=${header.recordCount})`,
      );
    }
    const tsOffsetMs = view.getUint32(cursor, true);
    const o = view.getBigInt64(cursor + 4, true);
    const h = view.getBigInt64(cursor + 12, true);
    const l = view.getBigInt64(cursor + 20, true);
    const c = view.getBigInt64(cursor + 28, true);
    const v = view.getBigUint64(cursor + 36, true);
    const turnover = view.getBigUint64(cursor + 44, true);
    const tradeCount = view.getUint32(cursor + 52, true);
    const delta = view.getBigInt64(cursor + 56, true);
    const flagsByte = view.getUint8(cursor + 64);
    bars.push({
      tsMs: header.tsBaseMs + BigInt(tsOffsetMs),
      open: unscale(o, header.priceScale),
      high: unscale(h, header.priceScale),
      low: unscale(l, header.priceScale),
      close: unscale(c, header.priceScale),
      volume: unscale(v, header.qtyScale),
      turnover: unscale(turnover, header.qtyScale),
      trades: tradeCount,
      delta: unscale(delta, header.qtyScale),
      confirmed: (flagsByte & 0b0001) !== 0,
    });
    cursor += BAR_RECORD_BYTES;
  }
  return { header, bars };
}

export interface FootprintCellFlags {
  buyImbalance: boolean;
  sellImbalance: boolean;
  inStack: boolean;
  poc: boolean;
}

export interface FootprintCell {
  price: string;
  bidVolume: string;
  askVolume: string;
  trades: number;
  flags: FootprintCellFlags;
}

export interface FootprintGroup {
  tsMs: bigint;
  cells: FootprintCell[];
}

export interface DecodedFootprint {
  header: BinaryFrameHeader;
  groups: FootprintGroup[];
}

const FOOTPRINT_GROUP_PREFIX_BYTES = 8; // u32 ts_offset_ms + u32 cell_count
const FOOTPRINT_CELL_BYTES = 33;

/**
 * Decodes a `body_kind: 5` (footprint) binary frame body. `record_count` in
 * the common header is the number of per-bar groups, per §3.4.
 */
export function decodeFootprint(buf: ArrayBufferView): DecodedFootprint {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.FOOTPRINT) {
    throw new BinaryFrameError(
      `expected body_kind=5 (footprint), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const groups: FootprintGroup[] = [];
  let cursor = COMMON_HEADER_BYTES;
  for (let g = 0; g < header.recordCount; g += 1) {
    if (cursor + FOOTPRINT_GROUP_PREFIX_BYTES > view.byteLength) {
      throw new BinaryFrameError(
        `footprint group ${g} prefix runs past the buffer (record_count=${header.recordCount})`,
      );
    }
    const tsOffsetMs = view.getUint32(cursor, true);
    const cellCount = view.getUint32(cursor + 4, true);
    cursor += FOOTPRINT_GROUP_PREFIX_BYTES;
    const cells: FootprintCell[] = [];
    for (let i = 0; i < cellCount; i += 1) {
      if (cursor + FOOTPRINT_CELL_BYTES > view.byteLength) {
        throw new BinaryFrameError(
          `footprint cell ${i} in group ${g} runs past the buffer (cell_count=${cellCount})`,
        );
      }
      const price = view.getBigInt64(cursor, true);
      const bidVolume = view.getBigUint64(cursor + 8, true);
      const askVolume = view.getBigUint64(cursor + 16, true);
      const tradeCount = view.getUint32(cursor + 24, true);
      const flagsByte = view.getUint8(cursor + 28);
      cells.push({
        price: unscale(price, header.priceScale),
        bidVolume: unscale(bidVolume, header.qtyScale),
        askVolume: unscale(askVolume, header.qtyScale),
        trades: tradeCount,
        flags: {
          buyImbalance: (flagsByte & 0b0001) !== 0,
          sellImbalance: (flagsByte & 0b0010) !== 0,
          inStack: (flagsByte & 0b0100) !== 0,
          poc: (flagsByte & 0b1000) !== 0,
        },
      });
      cursor += FOOTPRINT_CELL_BYTES;
    }
    groups.push({ tsMs: header.tsBaseMs + BigInt(tsOffsetMs), cells });
  }
  return { header, groups };
}

export interface HeatmapRow {
  bidSize: string;
  askSize: string;
}

export interface DecodedHeatmapColumn {
  header: BinaryFrameHeader;
  tsMs: bigint;
  priceMin: string;
  priceStep: string;
  rows: HeatmapRow[];
}

const HEATMAP_COLUMN_PREFIX_BYTES = 24; // u32 ts_offset_ms + i64 price_min + i64 price_step + u32 row_count
const HEATMAP_ROW_BYTES = 16;

/** Decodes a `body_kind: 6` (heatmap_column) binary frame body. */
export function decodeHeatmapColumn(buf: ArrayBufferView): DecodedHeatmapColumn {
  const header = parseBinaryFrameHeader(buf);
  if (header.bodyKind !== BODY_KIND.HEATMAP_COLUMN) {
    throw new BinaryFrameError(
      `expected body_kind=6 (heatmap_column), got ${header.bodyKind}`,
      "unsupported_body_kind",
    );
  }
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  if (COMMON_HEADER_BYTES + HEATMAP_COLUMN_PREFIX_BYTES > view.byteLength) {
    throw new BinaryFrameError("heatmap column body shorter than its fixed prefix");
  }
  let cursor = COMMON_HEADER_BYTES;
  const tsOffsetMs = view.getUint32(cursor, true);
  const priceMin = view.getBigInt64(cursor + 4, true);
  const priceStep = view.getBigInt64(cursor + 12, true);
  const rowCount = view.getUint32(cursor + 20, true);
  cursor += HEATMAP_COLUMN_PREFIX_BYTES;
  const rows: HeatmapRow[] = [];
  for (let i = 0; i < rowCount; i += 1) {
    if (cursor + HEATMAP_ROW_BYTES > view.byteLength) {
      throw new BinaryFrameError(`heatmap row ${i} runs past the buffer (row_count=${rowCount})`);
    }
    rows.push({
      bidSize: unscale(view.getBigUint64(cursor, true), header.qtyScale),
      askSize: unscale(view.getBigUint64(cursor + 8, true), header.qtyScale),
    });
    cursor += HEATMAP_ROW_BYTES;
  }
  return {
    header,
    tsMs: header.tsBaseMs + BigInt(tsOffsetMs),
    priceMin: unscale(priceMin, header.priceScale),
    priceStep: unscale(priceStep, header.priceScale),
    rows,
  };
}
