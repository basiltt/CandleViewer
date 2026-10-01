// THROWAWAY PROTOTYPE (E06-K03). FootprintStore-shaped columnar cell store
// (docs/plan/26-chart-engine-design.md §3.3): parallel typed arrays plus
// per-bar `offsets` prefix sums. Cells within a bar are ordered by priceLevel.
export class FootprintStore {
  constructor(capacity = 1024, barCapacity = 64) {
    this.length = 0;
    this.barCount = 0;
    this.barIndex = new Uint32Array(capacity);
    this.priceLevel = new Int32Array(capacity);
    this.bidVol = new Float32Array(capacity);
    this.askVol = new Float32Array(capacity);
    this.tradeCount = new Uint16Array(capacity);
    this.flags = new Uint8Array(capacity); // bit0 imbalanced, bit1 estimated
    /** offsets[b]..offsets[b+1] = cell range of bar b; length barCount+1 */
    this.offsets = new Uint32Array(barCapacity + 1);
  }

  _grow(minCells, minBars) {
    if (minCells > this.barIndex.length) {
      let cap = this.barIndex.length;
      while (cap < minCells) cap *= 2;
      for (const k of ["barIndex", "priceLevel", "bidVol", "askVol", "tradeCount", "flags"]) {
        const next = new this[k].constructor(cap);
        next.set(this[k].subarray(0, this.length));
        this[k] = next;
      }
    }
    if (minBars + 1 > this.offsets.length) {
      let cap = this.offsets.length;
      while (cap < minBars + 1) cap *= 2;
      const next = new Uint32Array(cap);
      next.set(this.offsets.subarray(0, this.barCount + 1));
      this.offsets = next;
    }
  }

  /** @returns {{from:number,to:number}} cell range of bar b */
  barRange(b) {
    return { from: this.offsets[b], to: this.offsets[b + 1] };
  }

  _find(bar, level) {
    let lo = this.offsets[bar];
    let hi = this.offsets[bar + 1];
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (this.priceLevel[mid] < level) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  /**
   * Upserts cells {barIndex, priceLevel, bidVol, askVol, tradeCount, flags?}.
   * Existing (bar, level) is updated in place; new levels are inserted in
   * order (shifting the tail). Returns merged affected cell ranges so the
   * caller can issue partial bufferSubData uploads.
   * @returns {{from:number,to:number}[]}
   */
  upsertFootprintCells(cells) {
    const ranges = [];
    for (const c of cells) {
      if (c.barIndex >= this.barCount) {
        this._grow(this.length, c.barIndex + 1);
        for (let b = this.barCount; b <= c.barIndex; b += 1) this.offsets[b + 1] = this.length;
        this.barCount = c.barIndex + 1;
      }
      const at = this._find(c.barIndex, c.priceLevel);
      const exists = at < this.offsets[c.barIndex + 1] && this.priceLevel[at] === c.priceLevel;
      let from = at;
      if (!exists) {
        this._grow(this.length + 1, this.barCount);
        for (const k of ["barIndex", "priceLevel", "bidVol", "askVol", "tradeCount", "flags"]) {
          this[k].copyWithin(at + 1, at, this.length);
        }
        for (let b = c.barIndex + 1; b <= this.barCount; b += 1) this.offsets[b] += 1;
        this.length += 1;
        from = at;
      }
      this.barIndex[at] = c.barIndex;
      this.priceLevel[at] = c.priceLevel;
      this.bidVol[at] = c.bidVol;
      this.askVol[at] = c.askVol;
      this.tradeCount[at] = c.tradeCount ?? 0;
      this.flags[at] = c.flags ?? 0;
      ranges.push({ from, to: exists ? at + 1 : this.length });
    }
    return mergeRanges(ranges);
  }

  /** Data accessor for E06-D03 (cell values exposed for DOM-surrogate measurement). */
  cellAt(i) {
    return {
      barIndex: this.barIndex[i],
      priceLevel: this.priceLevel[i],
      bidVol: this.bidVol[i],
      askVol: this.askVol[i],
      delta: this.askVol[i] - this.bidVol[i],
      tradeCount: this.tradeCount[i],
      flags: this.flags[i],
    };
  }
}

export function mergeRanges(ranges) {
  const sorted = [...ranges].sort((a, b) => a.from - b.from);
  const out = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    if (last && r.from <= last.to) last.to = Math.max(last.to, r.to);
    else out.push({ from: r.from, to: r.to });
  }
  return out;
}
