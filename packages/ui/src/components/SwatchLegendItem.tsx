import type { JSX } from "react";

export interface SwatchLegendItemProps {
  /** CSS colour expression, normally a token custom property, e.g. `var(--color-buy-default)`. */
  color: string;
  label: string;
  value?: string;
  /** Non-colour channel (glyph) so the row never relies on hue alone. */
  glyph?: string;
}

/** CMP-037: one legend row (swatch + glyph + label + value). */
export function SwatchLegendItem({
  color,
  label,
  value,
  glyph,
}: SwatchLegendItemProps): JSX.Element {
  return (
    <li
      data-cmp="CMP-037"
      style={{ display: "flex", alignItems: "center", gap: "var(--space-2, 8px)" }}
    >
      <span
        aria-hidden="true"
        data-testid="legend-swatch"
        style={{ width: 12, height: 12, background: color, display: "inline-block" }}
      />
      {glyph === undefined ? null : <span aria-hidden="true">{glyph}</span>}
      <span>{label}</span>
      {value === undefined ? null : <span>{value}</span>}
    </li>
  );
}
