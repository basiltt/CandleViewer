// E06-T01 — REAL WebGL2 work for the matrix page. The K02-K04 scenes MODEL their GPU
// cost (no GL context existed when they were written), which would make every runtime
// look identical. This adds measured GL work per frame so runtimes actually differ:
//   * `drawCalls` instanced draws x INSTANCES_PER_DRAW quads (~ scene B's 2,500 visible cells),
//   * gl.finish() each frame so wall time includes GPU execution (deliberate, documented),
//   * one texSubImage2D column upload on every heatmapStream event (the 10 Hz streaming
//     ADR-0011 criterion 3 is about), timed separately,
//   * a DOM-mirror update (E06-D03 stage) timed separately.
export const INSTANCES_PER_DRAW = 2500;
const TEX_W = 2048;
const TEX_H = 512;

const VS = `#version 300 es
in vec4 inst; uniform float t;
void main(){
  vec2 corner = vec2(float(gl_VertexID & 1), float((gl_VertexID >> 1) & 1));
  vec2 p = inst.xy + corner * 0.004 + vec2(sin(t + inst.z) * 0.001, 0.0);
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;
const FS = `#version 300 es
precision mediump float; out vec4 o; void main(){ o = vec4(0.2, 0.6, 0.9, 0.5); }`;

/** Capability probe (ADR-0011 criterion 4). Pure feature detection on a scratch canvas. */
export function probeCapabilities(createCanvas = () => document.createElement("canvas")) {
  const caps = {
    webgl2: false,
    EXT_color_buffer_float: false,
    r16fSampling: false,
    OES_texture_float_linear: false,
    instancing: false,
    offscreenCanvas: typeof OffscreenCanvas !== "undefined",
    offscreenCanvasWorker: false, // filled by the worker probe in page-main
    renderer: "unknown",
    vendor: "unknown",
    maxTextureSize: 0,
  };
  const gl = createCanvas().getContext("webgl2");
  if (!gl) return caps;
  caps.webgl2 = true;
  caps.instancing = typeof gl.drawArraysInstanced === "function";
  caps.EXT_color_buffer_float = Boolean(gl.getExtension("EXT_color_buffer_float"));
  caps.OES_texture_float_linear = Boolean(gl.getExtension("OES_texture_float_linear"));
  caps.maxTextureSize = gl.getParameter(gl.MAX_TEXTURE_SIZE);
  const dbg = gl.getExtension("WEBGL_debug_renderer_info");
  caps.renderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
  caps.vendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
  // R16F sampling + render: allocate, attach, check framebuffer completeness.
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.R16F, 4, 4, 0, gl.RED, gl.HALF_FLOAT, null);
  const fb = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  caps.r16fSampling =
    gl.getError() === gl.NO_ERROR &&
    caps.EXT_color_buffer_float &&
    gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
  return caps;
}

export class GlLoad {
  /** @param {HTMLCanvasElement | OffscreenCanvas} canvas */
  constructor(canvas) {
    const gl = canvas.getContext("webgl2", {
      antialias: false,
      powerPreference: "high-performance",
    });
    if (!gl) throw new Error("webgl2 unavailable");
    this.gl = gl;
    const prog = gl.createProgram();
    for (const [type, src] of [
      [gl.VERTEX_SHADER, VS],
      [gl.FRAGMENT_SHADER, FS],
    ]) {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      gl.attachShader(prog, s);
    }
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);
    this.tLoc = gl.getUniformLocation(prog, "t");
    const inst = new Float32Array(INSTANCES_PER_DRAW * 4);
    for (let i = 0; i < inst.length; i += 1) inst[i] = ((i * 2654435761) >>> 0) / 4294967296; // deterministic
    const vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    gl.bufferData(gl.ARRAY_BUFFER, inst, gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "inst");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 4, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(loc, 1);
    // Heatmap ring texture (R16F when capable, else R8 = reduced profile).
    this.halfFloat = Boolean(gl.getExtension("EXT_color_buffer_float"));
    this.tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    if (this.halfFloat) {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.R16F, TEX_W, TEX_H, 0, gl.RED, gl.HALF_FLOAT, null);
      this.column = new Uint16Array(TEX_H);
      this.colType = gl.HALF_FLOAT;
      this.colFmt = gl.RED;
    } else {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, TEX_W, TEX_H, 0, gl.RED, gl.UNSIGNED_BYTE, null);
      this.column = new Uint8Array(TEX_H);
      this.colType = gl.UNSIGNED_BYTE;
      this.colFmt = gl.RED;
    }
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    this.col = 0;
  }

  /** @returns {number} ms spent in texSubImage2D (CPU-side call; includes driver copy/sync). */
  uploadColumn() {
    const { gl } = this;
    for (let i = 0; i < this.column.length; i += 1) this.column[i] = (i * 31 + this.col) & 0xff;
    const t0 = performance.now();
    gl.texSubImage2D(
      gl.TEXTURE_2D,
      0,
      this.col % TEX_W,
      0,
      1,
      TEX_H,
      this.colFmt,
      this.colType,
      this.column,
    );
    const ms = performance.now() - t0;
    this.col += 1;
    return ms;
  }

  /** @returns {{ submitMs: number, finishMs: number }} */
  draw(drawCalls, tSec) {
    const { gl } = this;
    const t0 = performance.now();
    gl.clearColor(0.04, 0.05, 0.07, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform1f(this.tLoc, tSec);
    for (let d = 0; d < drawCalls; d += 1)
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, INSTANCES_PER_DRAW);
    const t1 = performance.now();
    gl.finish();
    return { submitMs: t1 - t0, finishMs: performance.now() - t1 };
  }

  dispose() {
    this.gl.getExtension("WEBGL_lose_context")?.loseContext();
  }
}
