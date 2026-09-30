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
