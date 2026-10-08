// Browser shim for `node:fs`, used ONLY by scenes/heatmap-lut.mjs (reads design tokens).
// The runner's server exposes packages/ui/tokens at /tokens/; they are fetched once here
// (top-level await) so the scene's synchronous readFileSync keeps working unmodified.
const names = [
  "primitives.tokens.json",
  "semantic-dark.tokens.json",
  "semantic-light.tokens.json",
  "semantic-hc.tokens.json",
];
const store = new Map();
for (const n of names) store.set(n, await (await fetch(`/tokens/${n}`)).text());
export function readFileSync(path) {
  const base = String(path).split(/[\\/]/).pop();
  const v = store.get(base);
  if (v === undefined) throw new Error(`node-fs shim: ${base} not served`);
  return v;
}
