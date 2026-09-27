// THROWAWAY PROTOTYPE (E06-K02) — see packages/chart-engine/bench/scenes/README.md.
// Columnar BarStore per docs/plan/26-chart-engine-design.md §3.3: typed-array
// based, append-optimised, ring capacity doubling. Only the fields Scene A
// needs (OHLC + volume) are implemented — delta/footprint/heatmap are
// explicitly out of scope for this ticket (E06-K03/K04).
export class BarStore {
  /** @param {{ capacity?: number }} [opts] */
  constructor(opts = {}) {
    this._capacity = Math.max(1, opts.capacity ?? 1024);
    this._head = 0; // number of bars currently stored, from index 0
    this._allocate(this._capacity);
  }

  _allocate(capacity) {
    this.time = new Float64Array(capacity);
    this.open = new Float32Array(capacity);
    this.high = new Float32Array(capacity);
    this.low = new Float32Array(capacity);
    this.close = new Float32Array(capacity);
    this.volume = new Float32Array(capacity);
  }

  get length() {
    return this._head;
  }

  get capacity() {
    return this._capacity;
  }

  /**
   * Appends bars, doubling capacity (never per-bar reallocation) when the
   * ring is full. Returns the affected index range per §3.3's mutation API
   * contract ("every mutation returns the affected index range").
   * @param {{ tOpenMs: number, o: number, h: number, l: number, c: number, v: number }[]} bars
   */
  appendBars(bars) {
    const from = this._head;
    const needed = this._head + bars.length;
    if (needed > this._capacity) {
      let newCapacity = this._capacity;
      while (newCapacity < needed) newCapacity *= 2;
      const old = {
        time: this.time,
        open: this.open,
        high: this.high,
        low: this.low,
        close: this.close,
        volume: this.volume,
      };
      this._allocate(newCapacity);
      this.time.set(old.time.subarray(0, this._head));
      this.open.set(old.open.subarray(0, this._head));
      this.high.set(old.high.subarray(0, this._head));
      this.low.set(old.low.subarray(0, this._head));
      this.close.set(old.close.subarray(0, this._head));
      this.volume.set(old.volume.subarray(0, this._head));
      this._capacity = newCapacity;
    }
    for (let i = 0; i < bars.length; i += 1) {
      const b = bars[i];
      const idx = from + i;
      this.time[idx] = b.tOpenMs;
      this.open[idx] = b.o;
      this.high[idx] = b.h;
      this.low[idx] = b.l;
      this.close[idx] = b.c;
      this.volume[idx] = b.v;
    }
    this._head = needed;
    return { from, to: needed };
  }

  /**
   * Monotone index -> time map lookup (§3.5 "BarStore keeps a monotone
   * index->time map"). Bars are equally spaced in this synthetic fixture so
   * this is O(1); a real store with gaps would still keep `time` monotone
   * and could binary-search it for the inverse (timeToIndex), not needed here.
   * @param {number} index
   */
  timeAt(index) {
    if (index < 0) index = 0;
    if (index >= this._head) index = this._head - 1;
    return this.time[index];
  }
}
