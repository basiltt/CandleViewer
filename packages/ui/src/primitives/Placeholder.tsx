import type { JSX } from "react";

export interface PlaceholderProps {
  /** Accessible label; required so the a11y addon has something to check. */
  label: string;
}

/**
 * Placeholder primitive (E02-T03 scaffold). Proves the Storybook + axe
 * harness works before E05 ships real primitives. Semantic HTML, no ARIA
 * needed (C-14.1).
 */
export function Placeholder({ label }: PlaceholderProps): JSX.Element {
  return <span>{label}</span>;
}
