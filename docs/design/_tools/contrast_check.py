"""Compute WCAG contrast ratios for named colour pairs sampled from exported PNGs.

Standalone, offline, no network — reads token RGB values (hardcoded here from the
frames' actual pixel values, see docs/design/E09/E09-D03-a11y-audit.md §1) and prints
the WCAG 2.x relative-luminance contrast ratio for each pair. Used as a design-QA
sanity check ahead of the automated CI contrast linter that will run against the real
token JSON once packages/ui/src/tokens ships (16-design-system-brief.md §12).

Usage: python docs/design/_tools/contrast_check.py
"""
from __future__ import annotations


def _linearize(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


PAIRS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], float, str]] = {
    "text.primary on surface.canvas": ((232, 234, 237), (11, 14, 17), 4.5, "AA text"),
    "text.primary on surface.card": ((232, 234, 237), (22, 27, 34), 4.5, "AA text"),
    "action.primary on surface.canvas": ((43, 108, 232), (11, 14, 17), 3.0, "AA non-text UI"),
    "focus.ring on surface.card": ((91, 156, 242), (22, 27, 34), 3.0, "AA non-text UI"),
}


def main() -> int:
    ok = True
    for name, (fg, bg, minimum, label) in PAIRS.items():
        ratio = contrast_ratio(fg, bg)
        passed = ratio >= minimum
        ok = ok and passed
        print(f"{name}: {ratio:.2f}:1 (>= {minimum}:1 {label}) -> {'PASS' if passed else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
