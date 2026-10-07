import { describe, expect, it } from "vitest";
import {
  BINARY_FRAME_MAGIC,
  BinaryFrameError,
  BODY_KIND,
  COMMON_HEADER_BYTES,
  BAR_RECORD_BYTES,
  decodeBars,
  decodeBookDelta,
  decodeBookSnapshot,
  decodeFootprint,
  decodeHeatmapColumn,
  decodeTrades,
  parseBinaryFrameHeader,
  unscale,
} from "../src/runtime/index.js";

/** Builds a valid 24-byte common header (§3.4) with the given overrides. */
function buildHeader(opts: {
  bodyKind: number;
  priceScale?: number;
  qtyScale?: number;
  recordCount: number;
  tsBaseMs?: bigint;
  flags?: number;
}): DataView {
  const buf = new ArrayBuffer(COMMON_HEADER_BYTES);
  const view = new DataView(buf);
  view.setUint32(0, BINARY_FRAME_MAGIC, true);
  view.setUint8(4, 1); // format_version
  view.setUint8(5, opts.bodyKind);
  view.setUint8(6, opts.flags ?? 0);
  view.setUint8(7, opts.priceScale ?? 2);
  view.setUint8(8, opts.qtyScale ?? 3);
  view.setUint8(9, 0);
  view.setUint8(10, 0);
  view.setUint8(11, 0);
  view.setUint32(12, opts.recordCount, true);
  view.setBigUint64(16, opts.tsBaseMs ?? 0n, true);
  return view;
}

function concatBuffers(...parts: ArrayBufferView[]): Uint8Array {
  const total = parts.reduce((sum, p) => sum + p.byteLength, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const p of parts) {
    out.set(new Uint8Array(p.buffer, p.byteOffset, p.byteLength), offset);
    offset += p.byteLength;
  }
  return out;
}

describe("unscale", () => {
  it("converts a positive scaled integer to a decimal string", () => {
    expect(unscale(123456n, 2)).toBe("1234.56");
  });
  it("converts a negative scaled integer to a decimal string", () => {
    expect(unscale(-500n, 2)).toBe("-5.00");
  });
  it("pads fractional digits with leading zeros", () => {
    expect(unscale(100005n, 2)).toBe("1000.05");
  });
  it("returns a whole number string when scale is 0", () => {
    expect(unscale(42n, 0)).toBe("42");
  });
});

describe("parseBinaryFrameHeader", () => {
  it("parses a well-formed header", () => {
    const view = buildHeader({ bodyKind: 1, recordCount: 0, tsBaseMs: 1789132262104n });
    const header = parseBinaryFrameHeader(view);
    expect(header.magic).toBe(BINARY_FRAME_MAGIC);
    expect(header.formatVersion).toBe(1);
    expect(header.bodyKind).toBe(1);
    expect(header.priceScale).toBe(2);
    expect(header.qtyScale).toBe(3);
    expect(header.recordCount).toBe(0);
    expect(header.tsBaseMs).toBe(1789132262104n);
    expect(header.flags).toEqual({
      estimated: false,
      coalesced: false,
      replay: false,
      partial: false,
    });
  });

  it("decodes every flag bit independently", () => {
    const view = buildHeader({ bodyKind: 1, recordCount: 0, flags: 0b1111 });
    const header = parseBinaryFrameHeader(view);
    expect(header.flags).toEqual({
      estimated: true,
      coalesced: true,
      replay: true,
      partial: true,
    });
  });

  it("rejects a buffer shorter than the common header", () => {
    const short = new Uint8Array(10);
    expect(() => parseBinaryFrameHeader(short)).toThrow(BinaryFrameError);
  });

  it("rejects a bad magic number", () => {
    const view = buildHeader({ bodyKind: 1, recordCount: 0 });
    view.setUint32(0, 0xdeadbeef, true);
    expect(() => parseBinaryFrameHeader(view)).toThrow(/bad magic/);
  });

  it("rejects an unknown body_kind", () => {
    const view = buildHeader({ bodyKind: 9, recordCount: 0 });
    expect(() => parseBinaryFrameHeader(view)).toThrow(/unknown body_kind/);
  });
});

describe("decodeBookSnapshot / decodeBookDelta", () => {
  function buildBookRecord(side: 0 | 1, price: bigint, size: bigint): Uint8Array {
    const buf = new ArrayBuffer(17);
    const view = new DataView(buf);
    view.setUint8(0, side);
    view.setBigInt64(1, price, true);
    view.setBigUint64(9, size, true);
    return new Uint8Array(buf);
  }

  it("round-trips a book snapshot with its xu/xseq trailer", () => {
    const header = buildHeader({ bodyKind: BODY_KIND.BOOK_SNAPSHOT, recordCount: 2 });
    const rec1 = buildBookRecord(0, 5000000n, 100000n);
    const rec2 = buildBookRecord(1, 5001000n, 50000n);
    const trailer = new ArrayBuffer(16);
    new DataView(trailer).setBigUint64(0, 111n, true);
    new DataView(trailer).setBigUint64(8, 222n, true);
    const frame = concatBuffers(header, rec1, rec2, new Uint8Array(trailer));

    const decoded = decodeBookSnapshot(frame);
    expect(decoded.levels).toEqual([
      { side: "bid", price: "50000.00", size: "100.000" },
      { side: "ask", price: "50010.00", size: "50.000" },
    ]);
    expect(decoded.trailer).toEqual({ xu: 111n, xseq: 222n });
  });

  it("treats size 0 as a level deletion marker, not an error", () => {
    const header = buildHeader({ bodyKind: BODY_KIND.BOOK_DELTA, recordCount: 1 });
    const rec = buildBookRecord(0, 5000000n, 0n);
    const frame = concatBuffers(header, rec);
    const decoded = decodeBookDelta(frame);
    expect(decoded.levels[0]?.size).toBe("0.000");
  });

  it("rejects a snapshot whose body disagrees with record_count", () => {
    const header = buildHeader({ bodyKind: BODY_KIND.BOOK_SNAPSHOT, recordCount: 2 });
    const rec1 = buildBookRecord(0, 5000000n, 100000n);
    const frame = concatBuffers(header, rec1); // only 1 of 2 records present, no trailer
    expect(() => decodeBookSnapshot(frame)).toThrow(BinaryFrameError);
  });

  it("rejects a body_kind mismatch", () => {
    const header = buildHeader({ bodyKind: BODY_KIND.TRADES, recordCount: 0 });
    expect(() => decodeBookSnapshot(header)).toThrow(/expected body_kind=1/);
  });
});

describe("decodeTrades", () => {
  it("decodes trade records including flags and aggressor side", () => {
    const header = buildHeader({
      bodyKind: BODY_KIND.TRADES,
      recordCount: 1,
      tsBaseMs: 1000n,
    });
    const rec = new ArrayBuffer(22);
    const rv = new DataView(rec);
    rv.setUint32(0, 500, true); // ts_offset_ms
    rv.setBigInt64(4, 4200000n, true); // price
    rv.setBigUint64(12, 1500n, true); // size
    rv.setUint8(20, 1); // side = sell
    rv.setUint8(21, 0b0101); // block trade + cluster-aggregated
    const frame = concatBuffers(header, new Uint8Array(rec));

    const decoded = decodeTrades(frame);
    expect(decoded.trades).toEqual([
      {
        tsMs: 1500n,
        price: "42000.00",
        size: "1.500",
        side: "sell",
        flags: { blockTrade: true, liquidationOrigin: false, clusterAggregated: true },
      },
    ]);
  });
});

function barRecord(generation: bigint, index: bigint, close: bigint, confirm: number): Uint8Array {
  const rec = new ArrayBuffer(BAR_RECORD_BYTES);
  const rv = new DataView(rec);
  rv.setBigUint64(0, generation, true);
  rv.setBigUint64(8, index, true);
  rv.setUint32(16, 60000, true); // ts_offset_ms
  rv.setBigInt64(20, 100000n, true); // o
  rv.setBigInt64(28, 110000n, true); // h
  rv.setBigInt64(36, 90000n, true); // l
  rv.setBigInt64(44, close, true); // c
  rv.setBigUint64(52, 200000n, true); // v
  rv.setBigUint64(60, 400000n, true); // turnover
  rv.setUint32(68, 42, true); // trades
  rv.setBigInt64(72, -5000n, true); // delta
  rv.setUint8(80, confirm); // confirm
  return new Uint8Array(rec);
}

function barsHeader(recordCount: number, version = 2): DataView {
  const header = buildHeader({ bodyKind: BODY_KIND.BARS, recordCount, tsBaseMs: 0n });
  header.setUint8(4, version);
  return header;
}

describe("decodeBars", () => {
  it("uses 85-byte records", () => {
    expect(BAR_RECORD_BYTES).toBe(85);
  });

  it("round-trips generation/index and decodes a confirmed bar record", () => {
    const frame = concatBuffers(barsHeader(1), barRecord(7n, 2n ** 40n, 105000n, 1));
    const decoded = decodeBars(frame);
    expect(decoded.bars).toEqual([
      {
        generation: 7n,
        index: 2n ** 40n,
        tsMs: 60000n,
        open: "1000.00",
        high: "1100.00",
        low: "900.00",
        close: "1050.00",
        volume: "200.000",
        turnover: "400.000",
        trades: 42,
        delta: "-5.000",
        confirmed: true,
      },
    ]);
  });

  it("keeps same-open-time bars distinct by index", () => {
    const frame = concatBuffers(
      barsHeader(2),
      barRecord(0n, 0n, 105000n, 1),
      barRecord(0n, 1n, 106000n, 0),
    );
    const { bars } = decodeBars(frame);
    expect(bars.map((b) => b.index)).toEqual([0n, 1n]);
    expect(bars[0]?.tsMs).toBe(bars[1]?.tsMs);
  });

  it("rejects v1 (69-byte) bars with a typed error", () => {
    const frame = concatBuffers(barsHeader(1, 1), new Uint8Array(69));
    expect(() => decodeBars(frame)).toThrow(BinaryFrameError);
    try {
      decodeBars(frame);
    } catch (e) {
      expect((e as BinaryFrameError).code).toBe("unsupported_format_version");
    }
  });

  it("rejects an unknown format_version", () => {
    const frame = concatBuffers(barsHeader(1, 9), barRecord(0n, 0n, 1n, 0));
    expect(() => decodeBars(frame)).toThrow(/format_version/);
  });

  it("rejects a truncated record", () => {
    const frame = concatBuffers(barsHeader(1), new Uint8Array(69));
    expect(() => decodeBars(frame)).toThrow(BinaryFrameError);
  });
});

describe("decodeFootprint", () => {
  it("decodes one bar group with two cells", () => {
    const header = buildHeader({ bodyKind: BODY_KIND.FOOTPRINT, recordCount: 1, tsBaseMs: 0n });
    const groupPrefix = new ArrayBuffer(8);
    const gv = new DataView(groupPrefix);
    gv.setUint32(0, 60000, true); // ts_offset_ms
    gv.setUint32(4, 2, true); // cell_count

    function buildCell(price: bigint, bid: bigint, ask: bigint, flags: number): Uint8Array {
      const buf = new ArrayBuffer(33);
      const v = new DataView(buf);
      v.setBigInt64(0, price, true);
      v.setBigUint64(8, bid, true);
      v.setBigUint64(16, ask, true);
      v.setUint32(24, 10, true);
      v.setUint8(28, flags);
      return new Uint8Array(buf);
    }

    const cell1 = buildCell(100000n, 5000n, 1000n, 0b1000); // POC
    const cell2 = buildCell(100100n, 500n, 6000n, 0b0010); // sell imbalance
    const frame = concatBuffers(header, new Uint8Array(groupPrefix), cell1, cell2);

    const decoded = decodeFootprint(frame);
    expect(decoded.groups).toHaveLength(1);
    expect(decoded.groups[0]?.tsMs).toBe(60000n);
    expect(decoded.groups[0]?.cells).toEqual([
      {
        price: "1000.00",
        bidVolume: "5.000",
        askVolume: "1.000",
        trades: 10,
        flags: { buyImbalance: false, sellImbalance: false, inStack: false, poc: true },
      },
      {
        price: "1001.00",
        bidVolume: "0.500",
        askVolume: "6.000",
        trades: 10,
        flags: { buyImbalance: false, sellImbalance: true, inStack: false, poc: false },
      },
    ]);
  });
});

describe("decodeHeatmapColumn", () => {
  it("decodes a column with its row grid", () => {
    const header = buildHeader({
      bodyKind: BODY_KIND.HEATMAP_COLUMN,
      recordCount: 1,
      tsBaseMs: 0n,
    });
    const prefix = new ArrayBuffer(24);
    const pv = new DataView(prefix);
    pv.setUint32(0, 30000, true); // ts_offset_ms
    pv.setBigInt64(4, 90000n, true); // price_min
    pv.setBigInt64(12, 100n, true); // price_step
    pv.setUint32(20, 2, true); // row_count

    function buildRow(bid: bigint, ask: bigint): Uint8Array {
      const buf = new ArrayBuffer(16);
      const v = new DataView(buf);
      v.setBigUint64(0, bid, true);
      v.setBigUint64(8, ask, true);
      return new Uint8Array(buf);
    }

    const row1 = buildRow(1000n, 2000n);
    const row2 = buildRow(3000n, 4000n);
    const frame = concatBuffers(header, new Uint8Array(prefix), row1, row2);

    const decoded = decodeHeatmapColumn(frame);
    expect(decoded.tsMs).toBe(30000n);
    expect(decoded.priceMin).toBe("900.00");
    expect(decoded.priceStep).toBe("1.00");
    expect(decoded.rows).toEqual([
      { bidSize: "1.000", askSize: "2.000" },
      { bidSize: "3.000", askSize: "4.000" },
    ]);
  });

  it("rejects a column shorter than its fixed prefix", () => {
    const header = buildHeader({
      bodyKind: BODY_KIND.HEATMAP_COLUMN,
      recordCount: 1,
    });
    expect(() => decodeHeatmapColumn(header)).toThrow(BinaryFrameError);
  });
});
