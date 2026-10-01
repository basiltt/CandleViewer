// THROWAWAY PROTOTYPE (E06-K04) - rolling-texture ring model (26-... §3.8).
// CPU shadow of an R16F texture: data is column-major so one column write is
// exactly one contiguous `texSubImage2D(x=writeCol, w=1, h=rows)`. Every
// "upload" is a counted byte range (no GPU in this environment); the counters
// are the instrumentation the acceptance criteria assert on.
export const FINE_COLS = 2048;
export const ROWS = 512;
export const COARSE_COLS = 14400;
export const FINE_STEP_MS = 100;
export const BYTES_PER_TEXEL = 2; // R16F

/** IEEE half-float quantisation of a 0..1 intensity (value stored as uint16). */
export function toHalf(x) {
  const f32 = new Float32Array(1);
  const u32 = new Uint32Array(f32.buffer);
  f32[0] = x;
  const v = u32[0];
  const sign = (v >>> 16) & 0x8000;
  let exp = ((v >>> 23) & 0xff) - 127 + 15;
  const man = v & 0x7fffff;
  if (exp <= 0) return sign; // flush denormals: depth below 2^-14 reads as empty
  if (exp >= 31) return sign | 0x7bff;
  return sign | (exp << 10) | (man >>> 13);
}

export class Ring {
  constructor(cols, rows, stepMs) {
    this.cols = cols;
    this.rows = rows;
    this.stepMs = stepMs;
    this.data = new Uint16Array(cols * rows);
    this.colTime = new Float64Array(cols).fill(-Infinity);
    this.writeCol = 0;
    this.count = 0;
    this.rowCursor = 0; // vertical ring: logical row r lives at (r + rowCursor) % rows
    this.ringWraps = 0;
    this.uploadedBytes = 0;
  }
  get bytes() {
    return this.cols * this.rows * BYTES_PER_TEXEL;
  }
  /** Write one 1 x rows column (logical row order); returns bytes uploaded. */
  writeColumn(tMs, col) {
    const base = this.writeCol * this.rows;
    for (let r = 0; r < this.rows; r += 1)
      this.data[base + ((r + this.rowCursor) % this.rows)] = col[r];
    this.colTime[this.writeCol] = tMs;
    this.writeCol += 1;
    if (this.writeCol === this.cols) {
      this.writeCol = 0;
      this.ringWraps += 1;
    }
    this.count = Math.min(this.cols, this.count + 1);
    const b = this.rows * BYTES_PER_TEXEL;
    this.uploadedBytes += b;
    return b;
  }
  /**
   * Price-origin shift by `deltaRows` (market left the window). The ring is
   * scrolled vertically by moving rowCursor; only the newly exposed rows are
   * cleared+uploaded: texSubImage2D(0, y, cols, n) per exposed band.
   * Returns uploaded bytes (== exposedRows * cols * 2, never the whole texture).
   */
  shiftRows(deltaRows) {
    const n = Math.min(Math.abs(deltaRows), this.rows);
    if (n === 0) return { bytes: 0, rows: 0 };
    // Physical rows that become the newly exposed band.
    const start = deltaRows > 0 ? this.rowCursor : (this.rowCursor - n + this.rows * 2) % this.rows;
    for (let c = 0; c < this.cols; c += 1) {
      const base = c * this.rows;
      const end = start + n;
      if (end <= this.rows) this.data.fill(0, base + start, base + end);
      else {
        this.data.fill(0, base + start, base + this.rows);
        this.data.fill(0, base, base + (end - this.rows));
      }
    }
    this.rowCursor = (this.rowCursor + deltaRows + this.rows * 4) % this.rows;
    const bytes = n * this.cols * BYTES_PER_TEXEL;
    this.uploadedBytes += bytes;
    return { bytes, rows: n };
  }
  /** Draw ranges (in columns, oldest->newest) as 1 or 2 sub-quads at the wrap. */
  drawRanges() {
    if (this.count < this.cols) return [{ from: 0, to: this.count }];
    return this.writeCol === 0
      ? [{ from: 0, to: this.cols }]
      : [
          { from: this.writeCol, to: this.cols },
          { from: 0, to: this.writeCol },
        ];
  }
  /** Logical-order read of one cell (for tests/goldens). */
  texel(col, logicalRow) {
    return this.data[col * this.rows + ((logicalRow + this.rowCursor) % this.rows)];
  }
}

/** Exact fine/coarse boundary: fine ring covers the newest cols*stepMs. */
export function sourceForAge(ageMs, fineCols = FINE_COLS, fineStepMs = FINE_STEP_MS) {
  return ageMs < fineCols * fineStepMs ? "fine" : "coarse";
}

/** Capability probe -> render profile (ADR-0011 criterion 4). */
export function selectProfile(caps) {
  const r16f = caps.EXT_color_buffer_float && caps.r16fSampling;
  if (caps.webgl2 && r16f) {
    return caps.OES_texture_float_linear ? "full" : "reduced"; // reduced = nearest sampling
  }
  return "degraded-2d";
}

/** Max-pool aggregation (spikes survive; 26-... §3.6). */
export function maxInto(dst, src) {
  for (let i = 0; i < dst.length; i += 1) if (src[i] > dst[i]) dst[i] = src[i];
}

/** Max over half-float magnitudes (sign bit = side; larger magnitude wins, keeps its sign). */
export function maxMagnitudeInto(dst, src) {
  for (let i = 0; i < dst.length; i += 1)
    if ((src[i] & 0x7fff) > (dst[i] & 0x7fff)) dst[i] = src[i];
}
