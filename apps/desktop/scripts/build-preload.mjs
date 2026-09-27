// Bundles the preload script into a single CommonJS file.
//
// Electron's sandboxed preload (sandbox: true, per shellPort.ts) runs in a
// restricted context that cannot resolve/load an ESM module's relative
// imports (e.g. `./allowList.js` from `dist/preload/index.js`) the way a
// normal Node ESM loader would; the result is `window.cv` silently missing
// with no thrown error visible to the renderer. Bundling to one CJS file
// removes the runtime module resolution step entirely.
import { build } from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outfile = path.join(__dirname, "../dist/preload/index.js");

await build({
  entryPoints: [path.join(__dirname, "../src/preload/index.ts")],
  outfile,
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node20",
  external: ["electron"],
  sourcemap: false,
});
