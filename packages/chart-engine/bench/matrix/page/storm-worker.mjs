// B7 worker-mode receiver: decodes + applies in the worker; renders a minimal
// OffscreenCanvas WebGL2 pass per tick when available (reports whether it was).
import { StormStores, STORM } from "../scenes/b7-storm.mjs";
const stores = new StormStores();
const decodeMs = [];
const frameMs = [];
let gl = null;
let sent = 0;
self.onmessage = (ev) => {
  const m = ev.data;
  if (m.type === "init") {
    if (m.canvas && typeof OffscreenCanvas !== "undefined") {
      try {
        gl = m.canvas.getContext("webgl2");
      } catch {
        gl = null;
      }
    }
    self.postMessage({ type: "ready", offscreenWebgl2: Boolean(gl) });
  } else if (m.type === "msg") {
    sent += 1;
    const a = performance.now();
    stores.decodeAndApply(m.buf);
    decodeMs.push(performance.now() - a);
    if (gl && stores.applied % STORM.storeCount === 0) {
      const f = performance.now();
      gl.clearColor(0.05, (stores.applied % 255) / 255, 0.1, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.finish();
      frameMs.push(performance.now() - f);
    }
  } else if (m.type === "done") {
    self.postMessage({
      type: "result",
      sent,
      applied: stores.applied,
      gaps: stores.gaps,
      duplicates: stores.duplicates,
      decodeMs,
      frameMs,
    });
  }
};
