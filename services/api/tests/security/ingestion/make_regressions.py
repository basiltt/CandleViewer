"""Write the minimised E08-X02 crashers into `regressions/` (run once, committed).

Usage (from services/api): `python -m tests.security.ingestion.make_regressions`
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.security.ingestion.corpus import TS, book, nested

OUT = Path(__file__).with_name("regressions")

CRASHERS: dict[str, tuple[str, str]] = {
    # name: (issue, frame)
    "deep_nesting_recursion.frame": ("#1889", nested(5_000)),
    "book_ts_infinity.frame": (
        "#1889",
        book("snapshot", 1, [], []).replace(f'"ts":{TS + 1}', '"ts":Infinity'),
    ),
    "huge_exponent_levels.frame": ("#1893", book("snapshot", 1, [["1e4200", "1"]] * 1000, [])),
    "off_tick_collision.frame": (
        "#1890",
        book("snapshot", 1, [["100.05", "1"], ["100.0", "2"]], []),
    ),
    "instrument_launchtime_inf.frame": (
        "#1896",
        '{"symbol":"BTCUSDT","status":"Trading","launchTime":Infinity}',
    ),
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    index = {}
    for name, (issue, frame) in CRASHERS.items():
        (OUT / name).write_text(frame, encoding="utf-8")
        index[name] = issue
    (OUT / "INDEX.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
