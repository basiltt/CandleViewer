// Capability probe + context-loss check. Usage: node probe.mjs <label> <playwright-core-path> [chrome args...]
import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";
const [label, pw, ...args] = process.argv.slice(2);
const { chromium } = createRequire(import.meta.url)(pw);
const b = await chromium.launch({ args });
const p = await b.newPage();
const r = await p.evaluate(async () => {
  const out = {};
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const gl = c.getContext("webgl2");
  out.webgl2 = !!gl;
  if (gl) {
    const d = gl.getExtension("WEBGL_debug_renderer_info");
    out.renderer = d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    for (const k of ["MAX_TEXTURE_SIZE", "MAX_TEXTURE_IMAGE_UNITS", "MAX_VERTEX_ATTRIBS"])
      out[k] = gl.getParameter(gl[k]);
    out.EXT_color_buffer_float = !!gl.getExtension("EXT_color_buffer_float");
    out.OES_texture_float_linear = !!gl.getExtension("OES_texture_float_linear");
    out.instancing = typeof gl.drawArraysInstanced === "function";
    out.integerAttribs = typeof gl.vertexAttribIPointer === "function";
    // R16F render
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R16F, 4, 4, 0, gl.RED, gl.HALF_FLOAT, null);
    const f = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, f);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t, 0);
    out.R16F_render = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
    out.R16F_sample = gl.getError() === 0;
    // context loss / restore
    const ext = gl.getExtension("WEBGL_lose_context");
    out.loseContextExt = !!ext;
    if (ext) {
      let lost = false,
        restored = false;
      c.addEventListener("webglcontextlost", (e) => {
        e.preventDefault();
        lost = true;
      });
      c.addEventListener("webglcontextrestored", () => {
        restored = true;
      });
      ext.loseContext();
      await new Promise((r) => setTimeout(r, 100));
      out.lostEvent = lost;
      out.isContextLost = gl.isContextLost();
      out.drawWhileLostThrows = (() => {
        try {
          gl.clear(gl.COLOR_BUFFER_BIT);
          return false;
        } catch {
          return true;
        }
      })();
      ext.restoreContext();
      await new Promise((r) => setTimeout(r, 300));
      out.restoredEvent = restored;
      out.contextUsableAfterRestore = !gl.isContextLost();
      // quick double loss
      ext.loseContext();
      ext.restoreContext();
      await new Promise((r) => setTimeout(r, 300));
      out.doubleLossRecovers = !gl.isContextLost();
    }
  }
  // degraded-2d floor
  const c2 = document.createElement("canvas");
  c2.width = 1200;
  c2.height = 600;
  const x = c2.getContext("2d");
  const N = 2500,
    reps = [];
  for (let r = 0; r < 30; r++) {
    const t0 = performance.now();
    for (let i = 0; i < N; i++) {
      x.fillStyle = `hsl(${i % 360},60%,50%)`;
      x.fillRect((i % 50) * 24, ((i / 50) | 0) * 12, 22, 10);
      x.fillText("12", (i % 50) * 24, ((i / 50) | 0) * 12 + 9);
    }
    reps.push(performance.now() - t0);
  }
  reps.sort((a, b) => a - b);
  out.canvas2d_2500cells_ms = { p50: reps[15], p95: reps[28] };
  out.offscreenCanvas_main = typeof OffscreenCanvas !== "undefined";
  out.worker = await new Promise((res) => {
    const w = new Worker(
      URL.createObjectURL(
        new Blob([
          'const o=typeof OffscreenCanvas!=="undefined";let g=false;try{g=!!new OffscreenCanvas(8,8).getContext("webgl2")}catch{};postMessage({o,g})',
        ]),
      ),
    );
    w.onmessage = (e) => res(e.data);
  });
  out.dpr = devicePixelRatio;
  return out;
});
r.browserVersion = b.version();
r.args = args;
writeFileSync(new URL(`./${label}.json`, import.meta.url), JSON.stringify(r, null, 2));
console.log(label, JSON.stringify(r));
await b.close();
