"""Token proof verification for E05-D01 (design-system foundations).

Pure-stdlib (no numpy/PIL). Verifies, over the DTCG token JSON in
packages/ui/tokens/, the acceptance criteria from the ticket's Gherkin:

  1. Every Tier-2 semantic colour token resolves in all 3 modes
     (dark, light, high-contrast) with no unset/dangling reference.
  2. Naming matches code exactly (token key == code token name; enforced
     structurally, since both sides read the same JSON file).
  3. Light is tuned, not inverted (spot-checks candle/buy/sell hex values
     differ from a naive lightness inversion of the dark value).
  4. `color.status.danger.default` and `color.sell.default` are visibly
     distinct hues (CIE76 dE) in every mode.

Run: python packages/ui/tokens/tests/verify_tokens.py
Exit code 0 = pass, 1 = fail (see stderr for details).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

TOKENS_DIR = Path(__file__).resolve().parent.parent

PRIMITIVES = "primitives.tokens.json"
THEMES = {
    "dark": ["semantic-dark.tokens.json"],
    "light": ["semantic-dark.tokens.json", "semantic-light.tokens.json"],
    "high-contrast": ["semantic-dark.tokens.json", "semantic-hc.tokens.json"],
}


def load(name: str) -> dict:
    return json.loads((TOKENS_DIR / name).read_text(encoding="utf-8"))


def merged_set(files: list[str]) -> dict:
    """Later files override earlier ones (theme-set layering order)."""
    merged: dict = {}
    for f in files:
        merged.update(load(f))
    return merged


def resolve(value, all_tokens: dict, _seen: frozenset = frozenset()) -> object:
    """Resolve a DTCG `{token.path}` reference recursively."""
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        ref = value[1:-1]
        if ref in _seen:
            raise ValueError(f"circular reference: {ref}")
        if ref not in all_tokens:
            raise KeyError(f"unset variable: {ref}")
        return resolve(all_tokens[ref]["$value"], all_tokens, _seen | {ref})
    if isinstance(value, dict):
        return {k: resolve(v, all_tokens, _seen) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, all_tokens, _seen) for v in value]
    return value


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")[:6]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la = relative_luminance(hex_to_rgb(hex_a))
    lb = relative_luminance(hex_to_rgb(hex_b))
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def chan(c: int) -> float:
        c = c / 255.0
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92

    r, g, b = (chan(c) for c in rgb)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 1.0
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy) - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e76(hex_a: str, hex_b: str) -> float:
    la, aa, ba = rgb_to_lab(hex_to_rgb(hex_a))
    lb, ab, bb = rgb_to_lab(hex_to_rgb(hex_b))
    return math.sqrt((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2)


REQUIRED_TIER2_COLOUR_PREFIXES = (
    "color.text.",
    "color.surface.",
    "color.border.",
    "color.action.",
    "color.buy",
    "color.sell",
    "color.neutral",
    "color.status.",
    "color.env.",
    "color.focus.ring",
    "color.candle.",
    "color.footprint.",
    "color.profile.",
    "color.drawing.",
    "color.order.line",
    "color.position.",
    "color.node.",
    "color.heatmap.",
)


def main() -> int:
    failures: list[str] = []
    primitives = load(PRIMITIVES)

    resolved_by_theme: dict[str, dict] = {}
    for theme, files in THEMES.items():
        all_tokens = {**primitives, **merged_set(files)}
        resolved: dict[str, object] = {}
        for name, entry in all_tokens.items():
            try:
                resolved[name] = resolve(entry["$value"], all_tokens)
            except (KeyError, ValueError) as exc:
                failures.append(f"[{theme}] {name}: {exc}")
        resolved_by_theme[theme] = resolved

    # 1. every colour-ish semantic token must resolve (already enforced above)
    #    plus: must exist identically (same key set) across all 3 themes.
    dark_keys = {k for k in resolved_by_theme["dark"] if k.startswith("color.")}
    for theme in ("light", "high-contrast"):
        missing = dark_keys - set(resolved_by_theme[theme])
        if missing:
            failures.append(f"[{theme}] missing keys present in dark: {sorted(missing)[:5]}")

    # 3. light is tuned, not inverted: spot-check candle/buy/sell hexes differ
    #    from dark AND are not a naive value-inversion of the dark hex.
    for key in ("color.candle.up", "color.candle.down", "color.buy.default", "color.sell.default"):
        dark_hex = resolved_by_theme["dark"][key]
        light_hex = resolved_by_theme["light"][key]
        if dark_hex == light_hex:
            failures.append(f"light theme did not retune {key} (identical to dark)")
        inv = "#" + "".join(f"{255 - c:02X}" for c in hex_to_rgb(dark_hex))
        if light_hex.upper() == inv:
            failures.append(f"light theme value for {key} is a naive inversion of dark")

    # 4. danger vs sell hue separation, every mode
    for theme in THEMES:
        danger = resolved_by_theme[theme]["color.status.danger.default"]
        sell = resolved_by_theme[theme]["color.sell.default"]
        de = delta_e76(danger, sell)
        if de < 8.0:
            failures.append(f"[{theme}] danger/sell hues too close (dE76={de:.2f} < 8.0): {danger} vs {sell}")

    # focus ring contrast >=3:1 against every surface tier, every theme
    surfaces = ("color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.overlay")
    for theme in THEMES:
        ring = resolved_by_theme[theme]["color.focus.ring"]
        for surf in surfaces:
            cr = contrast_ratio(ring, resolved_by_theme[theme][surf])
            if cr < 3.0:
                failures.append(f"[{theme}] focus.ring vs {surf} contrast {cr:.2f} < 3.0")

    # primary text contrast >=4.5:1 on its intended surfaces
    for theme in THEMES:
        text = resolved_by_theme[theme]["color.text.primary"]
        for surf in ("color.surface.app", "color.surface.canvas"):
            cr = contrast_ratio(text, resolved_by_theme[theme][surf])
            if cr < 4.5:
                failures.append(f"[{theme}] text.primary vs {surf} contrast {cr:.2f} < 4.5")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        print(f"\n{len(failures)} failure(s).", file=sys.stderr)
        return 1

    total_tokens = sum(len(r) for r in resolved_by_theme.values())
    print(f"OK: 3 themes resolved, {total_tokens} token instances, zero unset variables, all contrast checks pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
