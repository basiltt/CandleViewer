"""WCAG contrast + a simple CVD (colour-vision-deficiency) sanity pass for SCR-152.

Standalone, offline, no network. RGB values below are the actual resolved values of
the semantic-dark tokens bound on the E08-D03 Penpot frames (read via the Penpot MCP
`execute_code` tool -- see docs/design/E08/E08-D03.md for the token names each pair
maps to). This is the programmatic substitute for a manual contrast/CVD review per
the ticket's agent-delivery adaptations.

Usage: python docs/design/_tools/scr152_contrast_check.py
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


# name -> (fg, bg, minimum, label)
PAIRS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], float, str]] = {
    "text.primary on status.danger.subtle (banner title)": (
        (232, 234, 237), (78, 21, 24), 4.5, "AA text",
    ),
    "text.secondary on status.danger.subtle (banner body)": (
        (177, 186, 196), (78, 21, 24), 4.5, "AA text",
    ),
    "status.danger.strong icon on status.danger.subtle (! glyph)": (
        (240, 180, 65), (78, 21, 24), 3.0, "AA non-text UI",
    ),
    # Retry now is a filled button (btn-retry-now-bg + on-action text), not a plain-text
    # control, so it is judged at the 3:1 non-text-UI bar against the banner background,
    # same as the light theme (see section 6 of E08-D03.md for the rationale).
    "action.primary.default fill on status.danger.subtle (Retry now button)": (
        (43, 108, 232), (78, 21, 24), 3.0, "AA non-text UI (filled button)",
    ),
    "text.link on status.danger.subtle (Details)": (
        (110, 161, 245), (78, 21, 24), 4.5, "AA text (link-style control)",
    ),
    "text.tertiary on surface.app (workspace note)": (
        (139, 148, 158), (11, 14, 17), 4.5, "AA text",
    ),
}

# Light-theme resolved values (semantic-light set, read via the Penpot MCP bridge from
# the `-light` frame boards added alongside the dark ones). Same six pairs as PAIRS above.
LIGHT_PAIRS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], float, str]] = {
    "text.primary on status.danger.subtle (banner title)": (
        (20, 23, 26), (251, 226, 227), 4.5, "AA text",
    ),
    "text.secondary on status.danger.subtle (banner body)": (
        (58, 65, 72), (251, 226, 227), 4.5, "AA text",
    ),
    "status.danger.strong icon on status.danger.subtle (! glyph)": (
        (154, 106, 5), (251, 226, 227), 3.0, "AA non-text UI",
    ),
    # Retry now is a filled button (btn-retry-now-bg + on-action text), not a plain-text
    # control, so it is judged at the 3:1 non-text-UI bar against the banner background,
    # same as the dark theme (see section 6 of E08-D03.md for the rationale).
    "action.primary.default fill on status.danger.subtle (Retry now button)": (
        (43, 108, 232), (251, 226, 227), 3.0, "AA non-text UI (filled button)",
    ),
    "text.link on status.danger.subtle (Details)": (
        (31, 85, 191), (251, 226, 227), 4.5, "AA text (link-style control)",
    ),
    "text.tertiary on surface.app (workspace note)": (
        (82, 92, 102), (255, 255, 255), 4.5, "AA text",
    ),
}


def simulate_deuteranopia(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Rough Brettel-style deuteranopia projection, sufficient as a sanity check.

    Not a substitute for a full Machado/Oliveira/Fernandes simulation; used only to
    confirm the banner's severity signal does not collapse to background under a
    common red-green deficiency (icon + text label are never colour-only, per the
    ticket's accessibility notes, so this is a secondary check, not the primary one).
    """
    r, g, b = rgb
    r2 = 0.625 * r + 0.375 * g + 0.0 * b
    g2 = 0.7 * r + 0.3 * g + 0.0 * b
    b2 = 0.0 * r + 0.3 * g + 0.7 * b
    return tuple(max(0, min(255, round(c))) for c in (r2, g2, b2))


def main() -> int:
    ok = True
    print("-- WCAG contrast (dark theme) --")
    for name, (fg, bg, minimum, label) in PAIRS.items():
        ratio = contrast_ratio(fg, bg)
        passed = ratio >= minimum
        ok = ok and passed
        print(f"{name}: {ratio:.2f}:1 (>= {minimum}:1 {label}) -> {'PASS' if passed else 'FAIL'}")

    print("\n-- WCAG contrast (light theme) --")
    for name, (fg, bg, minimum, label) in LIGHT_PAIRS.items():
        ratio = contrast_ratio(fg, bg)
        passed = ratio >= minimum
        ok = ok and passed
        print(f"{name}: {ratio:.2f}:1 (>= {minimum}:1 {label}) -> {'PASS' if passed else 'FAIL'}")

    print("\n-- Deuteranopia sanity (icon vs banner bg must stay distinguishable) --")
    fg = (240, 180, 65)  # status.danger.strong
    bg = (78, 21, 24)  # status.danger.subtle
    fg_sim, bg_sim = simulate_deuteranopia(fg), simulate_deuteranopia(bg)
    ratio_sim = contrast_ratio(fg_sim, bg_sim)
    passed = ratio_sim >= 3.0
    ok = ok and passed
    print(
        f"status.danger.strong vs status.danger.subtle (simulated): {ratio_sim:.2f}:1 "
        f"(>= 3.0:1) -> {'PASS' if passed else 'FAIL'}"
    )
    print(
        "Note: severity is also carried by the '!' glyph shape and the banner text "
        "('Disconnected', 'reconnecting'), never colour alone (ticket a11y notes)."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
