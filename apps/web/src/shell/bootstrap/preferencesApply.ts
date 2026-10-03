/**
 * Applies `GET /me/preferences` appearance settings to the document root
 * (`data-theme`, `data-density`, reduced-motion, text scale) so the chrome
 * renders in the stored theme without a page reload (ticket AC "Preferences
 * apply without reload"). Consumes the E05 theme runtime's token contract —
 * this module only sets the root attributes/vars the tokens key off; it
 * does not own the token values themselves.
 */
import type { generated } from "@candleviewer/protocol";

export type Appearance = NonNullable<
  generated.rest.components["schemas"]["Settings"]["appearance"]
>;

const DEFAULT_APPEARANCE: Required<Appearance> = {
  theme: "dark",
  density: "comfortable",
  font_scale: 1,
  reduce_motion: false,
  high_contrast: false,
};

/** Applies appearance settings to `root` (defaults to `document.documentElement`). */
export function applyAppearance(
  appearance: Appearance | undefined,
  root: HTMLElement = document.documentElement,
): void {
  const effective = { ...DEFAULT_APPEARANCE, ...appearance };

  root.setAttribute("data-theme", effective.theme);
  root.setAttribute("data-density", effective.density);
  root.setAttribute("data-reduced-motion", String(effective.reduce_motion));
  root.setAttribute("data-high-contrast", String(effective.high_contrast));
  root.style.setProperty("--cv-font-scale", String(effective.font_scale));
}

export type ChartPalette = "default" | "cvd-safe";
export type ChartConvention = "standard" | "inverted";

/**
 * Root-level chart colour contract (E47-S06): `data-palette` selects the
 * CVD-safe `color.cvd.*` set and `data-convention` the buy/sell colour
 * convention. Every surface keys off these two attributes, so a change
 * reaches all views (including the canvas theme object) from one place.
 * Server persistence of the choice arrives with the SCR-116 settings ticket.
 */
export function applyChartColorMode(
  mode: { palette?: ChartPalette; convention?: ChartConvention },
  root: HTMLElement = document.documentElement,
): void {
  root.setAttribute("data-palette", mode.palette ?? "default");
  root.setAttribute("data-convention", mode.convention ?? "standard");
}

const MODE_KEY = "cv.chartColorMode";

/** Local (pre-SCR-116) persisted choice; invalid/missing values fall back to defaults. */
export function readStoredChartColorMode(
  storage: Pick<Storage, "getItem"> | undefined = typeof localStorage === "undefined"
    ? undefined
    : localStorage,
): { palette?: ChartPalette; convention?: ChartConvention } {
  try {
    const raw = JSON.parse(storage?.getItem(MODE_KEY) ?? "{}") as Record<string, unknown>;
    return {
      ...(raw["palette"] === "cvd-safe" ? { palette: "cvd-safe" as const } : {}),
      ...(raw["convention"] === "inverted" ? { convention: "inverted" as const } : {}),
    };
  } catch {
    return {};
  }
}
