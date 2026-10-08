// E06-T01: fixture identity for the cross-runtime matrix. "Same fixture" is
// asserted by sha256 of the canonical serialisation (K01 `serializeFixture`)
// recorded in every report; the K01 FNV-1a hash is recorded alongside so the
// two can be cross-checked against `bench/fixtures` tests. Works in Node and
// in any browser/WebView (WebCrypto is available on secure contexts, and
// http://127.0.0.1 counts as one).
import { serializeFixture } from "../fixtures/index.mjs";
import { fnv1aHex } from "../fixtures/rng.mjs";

/** @param {Uint8Array} bytes */
export async function sha256Hex(bytes) {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** @param {import("../fixtures/index.mjs").M0Fixture} fixture */
export async function fixtureDigests(fixture) {
  const text = serializeFixture(fixture);
  const sha256 = await sha256Hex(new TextEncoder().encode(text));
  return { sha256, fnv1a: fnv1aHex(text), serializedChars: text.length };
}
