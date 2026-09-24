# -*- coding: utf-8 -*-
"""Regenerate the data-derived tables in docs/plan/31-sprint-plan.md.

Every table this touches is a *projection of the backlog*, so it is rebuilt
from backlog/all-tickets.json rather than hand-edited. That is what lets E50
be inserted into the sprint tables without anyone reconciling totals by hand.

Rebuilt per sprint: the ticket table (x.4), the capacity-by-discipline table
(x.2), the epic mix (x.3), the QA/security tables (x.6) and the train burn-up
(x.9); plus the master capacity table (2.3) and the per-train roll-ups.

Prose -- sprint goals, risks, demo/exit expectations -- is never touched.

Usage:  python sync_sprint_plan.py
"""
from __future__ import annotations

import collections
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
BACKLOG = os.path.dirname(HERE)
PLAN_DIR = os.path.dirname(BACKLOG)
PLAN = os.path.join(PLAN_DIR, "31-sprint-plan.md")
TICKETS = os.path.join(BACKLOG, "all-tickets.json")

LANE_E50 = "Platform & DevSecOps"
E50_TITLE = "xstate-statemachine adoption: factory, persistence, plugins, contract suite, catalogue"

CAP = {n: 90 for n in range(1, 27)}
CAP[7] = 45  # holiday sprint
DES_CAP, QA_CAP, SEC_CAP = 60, 45, 20
TRAINS = [("R0", 1, 4), ("R1", 5, 9), ("R2", 10, 13),
          ("R3", 14, 19), ("R4", 20, 22), ("R5", 23, 26)]


def sprint_num(x):
    m = re.match(r"^Sprint (\d+)", x or "")
    return int(m.group(1)) if m else None


def suffix(k):
    m = re.match(r"^E\d{2}-([A-Z])", k)
    return m.group(1) if m else None


def touches_statechart(t):
    b = t.get("body") or ""
    return ("statechart" in (t.get("labels") or []) or "xstate_contract" in b
            or "statechart.factory" in b or "machine.json" in b)


def discipline(k):
    return {"D": "des", "Q": "qa", "X": "sec"}.get(suffix(k), "eng")


def blockers(t):
    r = t.get("blocked_by") or []
    return ", ".join("`%s`" % x for x in r)


def train_of(n):
    for t, lo, hi in TRAINS:
        if lo <= n <= hi:
            return t, lo, hi
    return None, None, None


def load():
    d = json.load(io.open(TICKETS, encoding="utf-8"))
    d = d["tickets"] if isinstance(d, dict) else d
    by_sprint = collections.defaultdict(list)
    for t in d:
        if t.get("kind") == "Epic" or "retired" in (t.get("labels") or []):
            continue
        n = sprint_num(t.get("sprint"))
        if n:
            by_sprint[n].append(t)
    pts = collections.defaultdict(collections.Counter)
    for n, ts in by_sprint.items():
        for t in ts:
            pts[n][discipline(t["key"])] += t.get("estimate") or 0
    return by_sprint, pts


def section_map(s):
    out = {}
    for n in range(1, 27):
        m = re.search(r"^## (\d+)\. S%02d " % n, s, re.M)
        if m:
            out[n] = int(m.group(1))
    return out


def replace_after(text, heading_pat, new_body):
    """Replace everything between a heading and the next heading."""
    m = re.search(heading_pat, text, re.M)
    if not m:
        return text, False
    start = m.end()
    nxt = re.search(r"\n(?=###? )", text[start:])
    end = start + (nxt.start() if nxt else len(text) - start)
    return text[:start] + new_body + text[end:], True


def main():
    s = io.open(PLAN, encoding="utf-8", newline="").read()
    by_sprint, pts = load()
    sec_of = section_map(s)
    stats = collections.Counter()

    # lane/title lookup harvested from the existing epic-mix tables
    lanes = {}
    for m in re.finditer(r"^\| \*\*(E\d\d)\*\* \| (.+?) \| (.+?) \| \d+ \| \d+ \|",
                         s, re.M):
        lanes.setdefault(m.group(1), (m.group(2), m.group(3)))
    lanes["E50"] = (E50_TITLE, LANE_E50)

    for n in sorted(sec_of):
        sec = sec_of[n]
        ts = sorted(by_sprint[n], key=lambda t: t["key"])
        p = pts[n]

        # --- x.4 ticket table -------------------------------------------
        rows = ["| Key | Title | Kind | Est | Component | blocked_by |",
                "|---|---|---|---|---|---|"]
        for t in ts:
            rows.append("| `%s` | %s | %s | %d | %s | %s |"
                        % (t["key"], t["title"], t["kind"],
                           t.get("estimate") or 0, t.get("component", ""),
                           blockers(t)))
        s, ok = replace_after(s, r"^### %d\.4 Tickets \(\d+\)$" % sec,
                              "\n\n" + "\n".join(rows) + "\n")
        if ok:
            s = re.sub(r"^### %d\.4 Tickets \(\d+\)$" % sec,
                       "### %d.4 Tickets (%d)" % (sec, len(ts)), s, flags=re.M)
            stats["ticket_tables"] += 1

        # --- statechart lane (inserted after the x.3 epic mix) -----------
        sc = collections.defaultdict(list)
        for t in ts:
            if touches_statechart(t):
                sc[t["key"].split("-")[0]].append(t["key"])
        if sc:
            lane = ("**Statechart lane:** " + "; ".join(
                "%s (%s)" % (e, ", ".join("`%s`" % k for k in ks))
                for e, ks in sorted(sc.items()))
                + " — built on `cv.statechart.factory` over `xstate-statemachine"
                "==0.9.1` (ADR-0016 Accepted); each must stay green in the "
                "BLOCKING `tests/xstate_contract` suite.")
        else:
            lane = "**Statechart lane:** none this sprint."
        lane_block = "\n\n" + lane + "\n"

        # --- x.2 capacity by discipline ---------------------------------
        def drow(name, got, cap):
            head = cap - got
            return "| %s | %d | %d | %+d | %s |" % (
                name, got, cap, head, "ok" if head >= 0 else "**OVER**")

        tot = p["eng"] + p["des"] + p["qa"] + p["sec"]
        tcap = CAP[n] + DES_CAP + QA_CAP + SEC_CAP
        rows = ["| Discipline | Planned | Capacity | Headroom | Status |",
                "|---|---|---|---|---|",
                drow("Engineering (S/T/K/C)", p["eng"], CAP[n]),
                drow("Design (D)", p["des"], DES_CAP),
                drow("QA (Q)", p["qa"], QA_CAP),
                drow("Security (X)", p["sec"], SEC_CAP),
                "| **Total** | **%d** | **%d** | **%+d** | |"
                % (tot, tcap, tcap - tot)]
        s, ok = replace_after(
            s, r"^### %d\.2 Capacity by discipline vs planned points$" % sec,
            "\n\n" + "\n".join(rows) + "\n")
        stats["capacity_tables"] += int(ok)

        # --- x.3 epic mix ------------------------------------------------
        agg, cnt = collections.Counter(), collections.Counter()
        for t in ts:
            e = t["key"].split("-")[0]
            agg[e] += t.get("estimate") or 0
            cnt[e] += 1
        rows = ["| Epic | Title | Lane | Pts | Tickets |", "|---|---|---|---|---|"]
        for e, v in sorted(agg.items(), key=lambda x: (-x[1], x[0])):
            title, lane = lanes.get(e, ("", ""))
            rows.append("| **%s** | %s | %s | %d | %d |" % (e, title, lane, v, cnt[e]))
        s, ok = replace_after(s, r"^### %d\.3 Epic mix$" % sec,
                              "\n\n" + "\n".join(rows) + "\n" + lane_block)
        stats["epic_mix"] += int(ok)

        # --- x.6 QA & security tables ------------------------------------
        m = re.search(r"^### %d\.6 " % sec, s, re.M)
        if m:
            nxt = re.search(r"\n(?=### )", s[m.end():])
            segend = m.end() + (nxt.start() if nxt else len(s) - m.end())
            seg = s[m.end():segend]
            for label, code in (("QA", "qa"), ("Security", "sec")):
                sub = sorted((t for t in ts if discipline(t["key"]) == code),
                             key=lambda t: t["key"])
                stot = sum(t.get("estimate") or 0 for t in sub)
                mm = re.search(r"\*\*%s tickets \([^)]*\):\*\*" % label, seg)
                if not mm:
                    continue
                tstart = mm.end()
                # Consume the blank line and the whole contiguous table that
                # follows the header. Searching for the next "\n\n" instead
                # would match the blank line *before* the table and append a
                # second copy on every run.
                te = re.match(r"\n+(?:\|[^\n]*\n)+", seg[tstart:])
                tend = tstart + (te.end() if te else 0)
                rows = ["| Key | Title | Est | blocked_by |", "|---|---|---|---|"]
                for t in sub:
                    rows.append("| `%s` | %s | %d | %s |"
                                % (t["key"], t["title"], t.get("estimate") or 0,
                                   blockers(t)))
                seg = (seg[:mm.start()]
                       + "**%s tickets (%d pts, %d tickets):**" % (label, stot, len(sub))
                       + "\n\n" + "\n".join(rows) + "\n" + seg[tend:])
                stats["qa_sec_tables"] += 1
            s = s[:m.end()] + seg + s[segend:]

    # --- design totals: refresh the trailing line to match its table -----
    out, pos = [], 0
    for m in re.finditer(r"Design total: \*\*\d+ pts\*\* across \d+ tickets\.", s):
        seg = s[pos:m.start()]
        tbl = re.findall(r"^\| `(E\d\d-D\d\d)` \| .*? \| (\d+) \| [\d-]+ \|$", seg, re.M)
        out.append(seg)
        if tbl:
            out.append("Design total: **%d pts** across %d tickets."
                       % (sum(int(x[1]) for x in tbl), len(tbl)))
            stats["design_totals"] += 1
        else:
            out.append(m.group(0))
        pos = m.end()
    out.append(s[pos:])
    s = "".join(out)

    # --- 2.3 master capacity table ---------------------------------------
    def master_row(mo):
        n = int(mo.group(1))
        p = pts[n]
        tot = p["eng"] + p["des"] + p["qa"] + p["sec"]
        flags = []
        if p["eng"] > CAP[n]:
            flags.append("**ENG %+d**" % (CAP[n] - p["eng"]))
        if p["des"] > DES_CAP:
            flags.append("DES +%d" % (p["des"] - DES_CAP))
        if p["qa"] > QA_CAP:
            flags.append("**QA +%d**" % (p["qa"] - QA_CAP))
        if p["sec"] > SEC_CAP:
            flags.append("SEC +%d" % (p["sec"] - SEC_CAP))
        return ("| **S%02d** | %s | %s | %d | %d | %+d | %d | %d | %d | %d | %s |"
                % (n, mo.group(2), mo.group(3), p["eng"], CAP[n],
                   CAP[n] - p["eng"], p["des"], p["qa"], p["sec"], tot,
                   ", ".join(flags) if flags else "ok"))

    s, c = re.subn(
        r"^\| \*\*S(\d\d)\*\* \| ([^|]+?) \| (\w+) \| \d+ \| \d+ \| [+-]\d+ \| "
        r"\d+ \| \d+ \| \d+ \| \d+ \| [^|]*\|$", master_row, s, flags=re.M)
    stats["master_rows"] = c

    T = collections.Counter()
    for n in range(1, 27):
        for k in ("eng", "des", "qa", "sec"):
            T[k] += pts[n][k]
    tcap = sum(CAP.values())
    grand = T["eng"] + T["des"] + T["qa"] + T["sec"]
    s, c = re.subn(
        r"^\| \| \| \*\*Total\*\* \|( \*\*[+\d]+\*\* \|){7} \|$",
        "| | | **Total** | **%d** | **%d** | **+%d** | **%d** | **%d** | **%d** | "
        "**%d** | |" % (T["eng"], tcap, tcap - T["eng"], T["des"], T["qa"],
                        T["sec"], grand), s, flags=re.M)
    stats["master_total"] = c

    # --- x.9 burn-up tables ----------------------------------------------
    def burn_sub(mo):
        head = mo.group(0).split("\n")[0]
        sec = int(re.search(r"^### (\d+)\.9", head).group(1))
        this = [k for k, v in sec_of.items() if v == sec][0]
        tr, lo, hi = train_of(this)
        total = sum(pts[i]["eng"] for i in range(lo, hi + 1))
        rows = ["| Sprint | Eng pts this sprint | Cumulative %s | %s total | "
                "Remaining | %% complete |" % (tr, tr),
                "|---|---|---|---|---|---|"]
        cum = 0
        for i in range(lo, hi + 1):
            cum += pts[i]["eng"]
            lab = "S%02d **<- this sprint**" % i if i == this else "S%02d" % i
            pct = int(round(100.0 * cum / total)) if total else 0
            rows.append("| %s | %d | %d | %d | %d | %d%% |"
                        % (lab, pts[i]["eng"], cum, total, total - cum, pct))
        return head + "\n\n" + "\n".join(rows)

    s, c = re.subn(
        r"^### \d+\.9 Burn-up - R\d train\n\n\| Sprint \|.*?(?=\n\n|\n---)",
        burn_sub, s, flags=re.M | re.S)
    stats["burnups"] = c

    # --- per-train roll-up headers ("Eng pts in backlog | N of M") -------
    def train_hdr(mo):
        tr = mo.group(1)
        lo, hi = [(a, b) for t, a, b in TRAINS if t == tr][0]
        eng = sum(pts[i]["eng"] for i in range(lo, hi + 1))
        cap = sum(CAP[i] for i in range(lo, hi + 1))
        allp = sum(pts[i][k] for i in range(lo, hi + 1)
                   for k in ("eng", "des", "qa", "sec"))
        return (mo.group(0)
                .replace(mo.group(2), "%d of %d capacity (%d%%)"
                         % (eng, cap, int(round(100.0 * eng / cap))))
                .replace(mo.group(3), str(allp)))

    for tr, lo, hi in TRAINS:
        eng = sum(pts[i]["eng"] for i in range(lo, hi + 1))
        cap = sum(CAP[i] for i in range(lo, hi + 1))
        allp = sum(pts[i][k] for i in range(lo, hi + 1)
                   for k in ("eng", "des", "qa", "sec"))
        pat = (r"(\| Sprints \| S%02d-S%02d \|.*?\| Eng pts in backlog \| )"
               r"[^|]*?( \|.*?\| All-discipline pts \| )[^|]*?( \|)"
               % (lo, hi))
        s, c = re.subn(pat,
                       lambda mo, e=eng, cp=cap, a=allp: "%s%d of %d capacity (%d%%)%s%d%s"
                       % (mo.group(1), e, cp, int(round(100.0 * e / cp)),
                          mo.group(2), a, mo.group(3)),
                       s, flags=re.S)
        stats["train_headers"] += c

    io.open(PLAN, "w", encoding="utf-8", newline="").write(s)
    print(json.dumps(dict(stats), indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
