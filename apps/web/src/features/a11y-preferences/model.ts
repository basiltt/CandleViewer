/** Accessibility preference model (E47-S07, SCR-117). Closed enums only; presentation-only. */

export type TriState = "system" | "on" | "off";
export type AnnouncePrices = "off" | "significant" | "always";
export type Verbosity = "low" | "normal" | "high";

export interface A11yPreferences {
  readonly reduced_motion: TriState;
  readonly increased_contrast: TriState;
  readonly disable_canvas_animation: boolean;
  readonly always_show_tables: boolean;
  readonly thick_focus_ring: boolean;
  readonly announce_prices: AnnouncePrices;
  readonly verbosity: Verbosity;
  readonly keyboard_only: boolean;
}

export const DEFAULT_PREFERENCES: A11yPreferences = {
  reduced_motion: "system",
  increased_contrast: "system",
  disable_canvas_animation: false,
  always_show_tables: false,
  thick_focus_ring: false,
  announce_prices: "significant",
  verbosity: "normal",
  keyboard_only: false,
};

export interface SystemMedia {
  readonly reducedMotion: boolean;
  readonly highContrast: boolean;
}

/** Flags consumed by DOM components and posted to the chart engine as plain booleans. */
export interface EngineFlags {
  readonly animate: boolean;
  readonly heatmapFade: boolean;
  readonly inertia: boolean;
  readonly flashOnTick: boolean;
}

export function resolveTriState(value: TriState, system: boolean): boolean {
  return value === "system" ? system : value === "on";
}

export function resolveFlags(p: A11yPreferences, media: SystemMedia): EngineFlags {
  const calm = resolveTriState(p.reduced_motion, media.reducedMotion) || p.disable_canvas_animation;
  return { animate: !calm, heatmapFade: !calm, inertia: !calm, flashOnTick: !calm };
}

const TRI: readonly string[] = ["system", "on", "off"];
const ANN: readonly string[] = ["off", "significant", "always"];
const VERB: readonly string[] = ["low", "normal", "high"];

/** Parse the `accessibility` settings subtree; unknown/invalid leaves fall back to defaults. */
export function parsePreferences(raw: unknown): A11yPreferences {
  const o = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  const d = DEFAULT_PREFERENCES;
  const pick = <T extends string>(k: string, allowed: readonly string[], fb: T): T =>
    typeof o[k] === "string" && allowed.includes(o[k]) ? (o[k] as T) : fb;
  const bool = (k: string, fb: boolean): boolean => (typeof o[k] === "boolean" ? o[k] : fb);
  return {
    reduced_motion: pick("reduced_motion", TRI, d.reduced_motion),
    increased_contrast: pick("increased_contrast", TRI, d.increased_contrast),
    disable_canvas_animation: bool("disable_canvas_animation", d.disable_canvas_animation),
    always_show_tables: bool("always_show_tables", d.always_show_tables),
    thick_focus_ring: bool("thick_focus_ring", d.thick_focus_ring),
    announce_prices: pick("announce_prices", ANN, d.announce_prices),
    verbosity: pick("verbosity", VERB, d.verbosity),
    keyboard_only: bool("keyboard_only", d.keyboard_only),
  };
}

/** Live-region throttle used by E47-S01/S02: should this price update be announced? */
export function shouldAnnounce(
  p: Pick<A11yPreferences, "announce_prices" | "verbosity">,
  update: { readonly significant: boolean; readonly cadenceElapsed: boolean },
): boolean {
  if (p.announce_prices === "off") return false;
  if (update.significant) return true;
  if (p.announce_prices === "significant" || p.verbosity === "low") return false;
  return update.cadenceElapsed;
}
