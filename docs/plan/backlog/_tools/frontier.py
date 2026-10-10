"""Compute the executable frontier: open, non-retired, non-epic tickets whose blocked_by are all CLOSED
(or Done on the board), not assigned / in progress. Writes _frontier.json. Usage: python frontier.py [N]

Run board_snapshot.py first; this script is offline and reads only local JSON."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(*parts: str) -> object:
    with open(os.path.join(HERE, *parts), encoding="utf-8") as fh:
        return json.load(fh)


b = {i["number"]: i for i in _load("_board_snapshot.json")}
led = _load("published.json")
tix = {t["key"]: t for t in _load("..", "all-tickets.json")}
num = {k: v["number"] for k, v in led.items()}


UNRESOLVED: set[str] = set()


def done(key: str) -> bool:
    """Fail closed: a blocker we cannot see on the board counts as NOT done (and is reported)."""
    n = num.get(key)
    it = b.get(n) if n is not None else None
    if it is None:
        UNRESOLVED.add(key)
        return False
    return it["state"] == "CLOSED" or it["status"] == "Done"


def sprint_no(s: str | None) -> int:
    return int(s.split()[-1]) if s and s.startswith("Sprint") else 99


def main() -> None:
    rows: list[dict[str, object]] = []
    for key, t in tix.items():
        n = num.get(key)
        it = b.get(n) if n else None
        if not it or it["state"] != "OPEN" or t["kind"].lower() == "epic":
            continue
        if (
            "retired" in it["labels"]
            or it["status"] in ("In Progress", "In Review", "Done")
            or it["assignees"]
        ):
            continue
        blockers = t.get("blocked_by") or []
        open_blk = [k for k in blockers if not done(k)]
        rows.append(
            {
                "key": key,
                "number": n,
                "sprint": it["sprint"],
                "status": it["status"],
                "kind": t["kind"],
                "labels": [
                    lb
                    for lb in it["labels"]
                    if lb.startswith(("area/", "type/", "security"))
                ],
                "estimate": t.get("estimate"),
                "title": t["title"],
                "open_blockers": open_blk,
                "open_blocker_numbers": [num.get(k) for k in open_blk],
            }
        )
    rows.sort(key=lambda r: (sprint_no(r["sprint"]), r["number"]))
    ready = [r for r in rows if not r["open_blockers"]]
    with open(os.path.join(HERE, "_frontier.json"), "w", encoding="utf-8") as fh:
        json.dump(ready, fh, ensure_ascii=False, indent=1)
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    print(f"{len(ready)} unblocked of {len(rows)} open non-epic tickets")
    if UNRESOLVED:
        print(
            f"WARNING: {len(UNRESOLVED)} blocker key(s) not published / not in the snapshot were"
            f" treated as NOT done (fail-closed): {', '.join(sorted(UNRESOLVED)[:12])}"
            + (" ..." if len(UNRESOLVED) > 12 else ""),
            file=sys.stderr,
        )
    for r in ready[:limit]:
        print(
            f"#{r['number']:<5} {r['sprint'] or '-':<9} {r['status']:<8} {r['kind']:<8} "
            f"{r['estimate'] or '':<3} {r['key']:<9} {str(r['title'])[:80]}"
        )


if __name__ == "__main__":
    main()
