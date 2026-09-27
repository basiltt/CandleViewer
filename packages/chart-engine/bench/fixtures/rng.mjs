// Deterministic PRNG + hash for the M0 bench fixture generator (E06-K01).
// mulberry32: tiny, seedable, same sequence on every platform/Node version —
// required so "same seed -> byte-identical output" (ticket AC1) holds across
// machines, not just within one process.

/**
 * Creates a mulberry32 PRNG seeded from a 32-bit unsigned integer.
 * @param {number} seed
 * @returns {() => number} function returning floats in [0, 1)
 */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Derives a 32-bit unsigned integer seed from an arbitrary string/number so
 * CLI callers can pass human-friendly seeds (e.g. "20260928").
 * @param {string|number} input
 */
export function toSeed32(input) {
  const str = String(input);
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/**
 * FNV-1a hash over a UTF-8 string, returned as lowercase hex. Used to assert
 * byte-reproducibility of generated fixtures without hashing large binary
 * blobs through a heavier crypto dependency.
 * @param {string} content
 */
export function fnv1aHex(content) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < content.length; i += 1) {
    hash ^= content.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}
