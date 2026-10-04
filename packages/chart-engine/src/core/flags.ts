// Accessibility render flags (E47-S07). Plain booleans posted by the host; no React/DOM (C-2.16).

export interface RenderFlags {
  readonly animate: boolean;
  readonly heatmapFade: boolean;
  readonly inertia: boolean;
  readonly flashOnTick: boolean;
}

export const DEFAULT_RENDER_FLAGS: RenderFlags = {
  animate: true,
  heatmapFade: true,
  inertia: true,
  flashOnTick: true,
};

/** Per-frame animation work units for the given flags (0 when everything is calm). */
export function animationWorkUnits(f: RenderFlags): number {
  return (
    (f.animate ? 1 : 0) + (f.heatmapFade ? 1 : 0) + (f.inertia ? 1 : 0) + (f.flashOnTick ? 1 : 0)
  );
}

export interface FrameState {
  /** Remaining viewport inertia velocity (px/s). */
  velocity: number;
  /** Heatmap fade alpha in [0,1]. */
  fadeAlpha: number;
  /** Tick flash intensity in [0,1]. */
  flash: number;
}

/**
 * Advances one frame in place. With a flag off the effect snaps to its resting value
 * (no decay animation); no scene rebuild is needed. Returns true if another frame is needed.
 */
export function stepFrame(s: FrameState, f: RenderFlags, dtMs: number): boolean {
  const k = Math.exp(-dtMs / 120);
  if (f.inertia) s.velocity = Math.abs(s.velocity) < 0.01 ? 0 : s.velocity * k;
  else s.velocity = 0;
  if (f.heatmapFade) s.fadeAlpha = s.fadeAlpha < 0.01 ? 0 : s.fadeAlpha * k;
  else s.fadeAlpha = 0;
  if (f.flashOnTick) s.flash = s.flash < 0.01 ? 0 : s.flash * k;
  else s.flash = 0;
  return s.velocity !== 0 || s.fadeAlpha !== 0 || s.flash !== 0;
}
