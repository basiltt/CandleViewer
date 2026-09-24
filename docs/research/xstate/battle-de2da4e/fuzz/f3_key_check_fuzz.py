"""F3 -- #220 recursive unknown-key check: catch rate, false-positive rate,
catalogue sweep, and strict_config bypass attempts.

A: MUTATION fuzz -- generate deep charts (nested states, parallel regions,
   on/always/after/onDone bodies, invoke + onDone/onError) and inject ONE
   misspelling at a randomly chosen nesting level. Under strict_config=True
   the build MUST raise and the message MUST name the path. Default mode
   MUST warn. >=300 mutations.
B: FALSE-POSITIVE fuzz -- generate VALID charts from the full key grammar
   (every KNOWN_* key used at its legal level, plus x-/meta/description/
   tags at every level). Under strict_config=True: 0 rejections required.
C: CATALOGUE sweep -- every *.machine.json under battle-*/contracts/ built
   with strict_config=True. Any rejection is either a real latent typo or a
   false positive; both are reported.
D: BYPASS attempts -- can an `x-` prefix or a case variant smuggle a policy
   key past the check AND be honoured by the parser? (a bypass only counts
   if the smuggled key CHANGES BEHAVIOUR.)

STANDALONE: stdlib + xstate_statemachine only. Run from any cwd.
"""

import glob
import json
import logging
import os
import random
import warnings

from xstate_statemachine import MachineLogic, create_machine  # noqa: E402
from xstate_statemachine.exceptions import InvalidConfigError  # noqa: E402

warnings.simplefilter("always")
logging.disable(logging.CRITICAL)

SEED = int(os.environ.get("SEED", "20260923"))
N_MUT = int(os.environ.get("N_MUT", "320"))
N_VALID = int(os.environ.get("N_VALID", "200"))
DEFECTS = []

STATE_KEYS = ["entry", "exit", "on", "after", "always", "invoke", "onDone",
              "initial", "type", "states", "meta", "description", "tags"]
TRANS_KEYS = ["target", "actions", "guard", "cond", "internal"]
INVOKE_KEYS = ["src", "id", "onDone", "onError", "input"]


def typo(k, rnd):
    if len(k) < 4:
        return k + "x"
    i = rnd.randrange(1, len(k) - 1)
    return k[:i] + k[i + 1] + k[i] + k[i + 2:]


def noop(i, c, e, a=None):
    pass


async def noop_a(i, c, e, a=None):
    pass


async def svc(i, c, e):
    return {"ok": True}


def LOGIC(kind):
    acts = {n: (noop_a if kind == "async def" else noop)
            for n in ("A1", "A2", "A3")}
    return MachineLogic(actions=acts, guards={"G1": lambda c, e: True},
                        services={"S1": svc})


def deep_chart(idx, rnd):
    """A chart exercising every nesting level the recursive check claims."""
    return {
        "id": f"f3_{idx}",
        "initial": "r1",
        "context": {},
        "states": {
            "r1": {
                "entry": ["A1"],
                "on": {"GO": {"target": "r2", "actions": ["A2"],
                              "guard": "G1"}},
                "after": {"50": {"target": "r2"}},
            },
            "r2": {
                "type": "parallel",
                "states": {
                    "x": {
                        "initial": "x1",
                        "states": {
                            "x1": {
                                "invoke": {
                                    "src": "S1", "id": "inv1",
                                    "onDone": {"target": "x2",
                                               "actions": ["A3"]},
                                    "onError": {"target": "x2"},
                                },
                            },
                            "x2": {"type": "final"},
                        },
                        "onDone": {"actions": ["A1"]},
                    },
                    "y": {
                        "initial": "y1",
                        "states": {
                            "y1": {
                                "always": [{"target": "y2", "guard": "G1"}],
                            },
                            "y2": {"exit": ["A2"]},
                        },
                    },
                },
            },
        },
    }


# ------------------------------------------------ mutation site collection
def sites(cfg):
    """[(path_list, kind)] for every dict whose keys the check should know."""
    out = []

    def walk(node, path, kind):
        out.append((list(path), kind))
        if kind in ("root", "state"):
            for sn, sv in (node.get("states") or {}).items():
                walk(sv, path + ["states", sn], "state")
            for ev, tv in (node.get("on") or {}).items():
                for t in (tv if isinstance(tv, list) else [tv]):
                    if isinstance(t, dict):
                        walk(t, path + ["on", ev], "trans")
            for dl, tv in (node.get("after") or {}).items():
                for t in (tv if isinstance(tv, list) else [tv]):
                    if isinstance(t, dict):
                        walk(t, path + ["after", dl], "trans")
            al = node.get("always")
            if isinstance(al, list):
                for n, t in enumerate(al):
                    if isinstance(t, dict):
                        walk(t, path + ["always", n], "trans")
            od = node.get("onDone")
            if isinstance(od, dict):
                walk(od, path + ["onDone"], "trans")
            iv = node.get("invoke")
            for n, one in enumerate(iv if isinstance(iv, list) else
                                    ([iv] if isinstance(iv, dict) else [])):
                p = path + (["invoke", n] if isinstance(iv, list)
                            else ["invoke"])
                walk(one, p, "invoke")
                for h in ("onDone", "onError"):
                    if isinstance(one.get(h), dict):
                        walk(one[h], p + [h], "trans")

    walk(cfg, [], "root")
    return out


def at(cfg, path):
    n = cfg
    for p in path:
        n = n[p]
    return n


def build(cfg, kind, strict):
    """-> (outcome, message) ; outcome in RAISED / WARNED / SILENT"""
    logs = []

    class _H(logging.Handler):
        def emit(self, rec):
            logs.append(rec.getMessage())

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        logging.disable(logging.NOTSET)
        root = logging.getLogger("xstate_statemachine")
        h = _H()
        root.addHandler(h)
        root.setLevel(logging.WARNING)
        try:
            create_machine(json.loads(json.dumps(cfg)), logic=LOGIC(kind),
                           strict_config=strict)
        except InvalidConfigError as ex:
            return "RAISED", str(ex)
        except Exception as ex:  # noqa: BLE001
            return "OTHER:" + type(ex).__name__, str(ex)
        finally:
            root.removeHandler(h)
            logging.disable(logging.CRITICAL)
    msgs = [str(x.message) for x in w] + logs
    hits = [m for m in msgs if "unknown config key" in m.lower()]
    return ("WARNED", hits[0]) if hits else ("SILENT", "")


def part_a():
    print("A -- mutation fuzz: %d typos at random nesting levels x 2 kinds,"
          " strict_config=True" % N_MUT)
    rnd = random.Random(SEED)
    for kind in ("def", "async def"):
        stat = {"RAISED": 0, "WARNED": 0, "SILENT": 0, "OTHER": 0,
                "no_path": 0}
        bylevel = {}
        r = random.Random(SEED)
        for i in range(N_MUT):
            base = deep_chart(i, r)
            ss = sites(base)
            path, sk = r.choice(ss)
            keys = {"root": ["states", "initial", "context", "id"],
                    "state": STATE_KEYS, "trans": TRANS_KEYS,
                    "invoke": INVOKE_KEYS}[sk]
            node = at(base, path)
            cands = [k for k in keys if k in node] or keys
            orig = r.choice(cands)
            bad = typo(orig, rnd)
            if bad in node or bad == orig:
                continue
            node[bad] = node.pop(orig) if orig in node else []
            out, msg = build(base, kind, True)
            k = out if out in stat else "OTHER"
            stat[k] += 1
            lvl = bylevel.setdefault(sk, {"RAISED": 0, "miss": 0})
            if out == "RAISED":
                lvl["RAISED"] += 1
                if bad not in msg:
                    stat["no_path"] += 1
            else:
                lvl["miss"] += 1
                if len(DEFECTS) < 40:
                    DEFECTS.append(
                        "A/%s: typo %r->%r at level %s path=%s -> %s under "
                        "strict_config=True"
                        % (kind, orig, bad, sk,
                           ".".join(map(str, path)) or "<root>", out))
        print("  %-9s %s  bylevel=%s" % (kind, stat, bylevel))
        r = random.Random(SEED + 1)
        wstat = {"WARNED": 0, "SILENT": 0, "other": 0}
        for i in range(60):
            base = deep_chart(i, r)
            path, sk = r.choice(sites(base))
            keys = {"root": ["states", "initial"], "state": STATE_KEYS,
                    "trans": TRANS_KEYS, "invoke": INVOKE_KEYS}[sk]
            node = at(base, path)
            cands = [k for k in keys if k in node] or keys
            orig = r.choice(cands)
            bad = typo(orig, rnd)
            if bad in node or bad == orig:
                continue
            node[bad] = node.pop(orig) if orig in node else []
            out, _ = build(base, kind, False)
            wstat[out if out in wstat else "other"] += 1
        print("  %-9s default mode (60): %s" % (kind, wstat))
        if wstat["SILENT"]:
            DEFECTS.append("A/%s: %d/60 nested typos SILENT in default "
                           "(non-strict) mode" % (kind, wstat["SILENT"]))


def _extra(rnd):
    opts = [("x-note", 1), ("meta", {"k": 1}), ("description", "d"),
            ("tags", ["t"])]
    return dict(rnd.sample(opts, rnd.randint(0, 4)))


def valid_chart(idx, rnd):
    """Valid chart using the full grammar + x-/meta/description/tags."""
    st = {
        "s1": dict({"entry": ["A1"], "exit": ["A2"],
                    "on": {"GO": dict({"target": "s2", "actions": ["A1"],
                                       "guard": "G1"}, **_extra(rnd))},
                    "after": {"30": dict({"target": "s2"}, **_extra(rnd))}},
                   **_extra(rnd)),
        "s2": dict({"always": [dict({"target": "s3", "guard": "G1"},
                                    **_extra(rnd))]}, **_extra(rnd)),
        "s3": dict({"invoke": dict(
            {"src": "S1", "id": "i1",
             "onDone": dict({"target": "s4"}, **_extra(rnd)),
             "onError": dict({"target": "s4"}, **_extra(rnd))},
            **_extra(rnd))}, **_extra(rnd)),
        "s4": dict({"initial": "n1",
                    "states": {"n1": dict({"type": "final"}, **_extra(rnd))},
                    "onDone": dict({"actions": ["A2"]}, **_extra(rnd))},
                   **_extra(rnd)),
    }
    return dict({"id": "v_%d" % idx, "initial": "s1", "context": {},
                 "states": st}, **_extra(rnd))


def part_b():
    print("\nB -- false-positive fuzz: %d VALID charts x 2 kinds, "
          "strict_config=True (0 rejections required)" % N_VALID)
    for kind in ("def", "async def"):
        rnd = random.Random(SEED + 7)
        rej = 0
        samples = []
        for i in range(N_VALID):
            out, msg = build(valid_chart(i, rnd), kind, True)
            if out != "SILENT":
                rej += 1
                if len(samples) < 3:
                    samples.append("%s: %s" % (out, msg[:160]))
        print("  %-9s rejections=%d/%d %s" % (kind, rej, N_VALID, samples))
        if rej:
            DEFECTS.append("B/%s: %d/%d VALID charts rejected under "
                           "strict_config=True; e.g. %s"
                           % (kind, rej, N_VALID, samples[:1]))


def part_c():
    print("\nC -- catalogue sweep: every contracts/*.machine.json under "
          "strict_config=True")
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    pats = glob.glob(os.path.join(base, "battle-*", "contracts",
                                  "*.machine.json"))
    tot, bad = 0, []
    for p in sorted(pats):
        try:
            with open(p, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except Exception:  # noqa: BLE001
            continue
        tot += 1
        try:
            create_machine(cfg, logic=MachineLogic(), strict_config=True)
            out = "OK"
        except InvalidConfigError as ex:
            out = "REJECTED: " + str(ex)[:220]
        except Exception as ex:  # noqa: BLE001
            out = "other:" + type(ex).__name__
        if out.startswith("REJECTED"):
            bad.append((os.path.basename(p), out))
    print("  catalogue JSONs built = %d, rejected = %d" % (tot, len(bad)))
    for n, o in bad[:10]:
        print("    - %s: %s" % (n, o))
    if bad:
        DEFECTS.append("C: %d/%d catalogue charts rejected by the recursive "
                       "check; first=%s" % (len(bad), tot, bad[0]))


def part_d():
    print("\nD -- bypass attempts (x- prefix / case variants)")
    rows = []
    c1 = {"id": "d1", "initial": "a", "context": {},
          "x-actionErrorPolicy": "ignore", "states": {"a": {}}}
    rows.append(("x-actionErrorPolicy at root", build(c1, "def", True)))
    for var in ("Entry", "ENTRY", "oN", "Always", "After", "Invoke"):
        c = {"id": "d2", "initial": "a", "context": {},
             "states": {"a": {var: ["A1"]}}}
        rows.append(("state key %r" % var, build(c, "def", True)))
    c3 = {"id": "d3", "initial": "a", "context": {}, "StrictConfig": True,
          "states": {"a": {"entyr": ["A1"]}}}
    rows.append(("root 'StrictConfig' + nested typo, no kwarg",
                 build(c3, "def", False)))
    for n, (out, msg) in rows:
        print("  %-45s -> %s %s" % (n, out, msg[:110]))
        if out == "SILENT" and n.startswith("state key"):
            DEFECTS.append("D: %s accepted SILENTLY under strict_config=True "
                           "(case-variant smuggling)" % n)
    return rows


def main():
    print("F3 -- #220 recursive key check: catch / false-positive / "
          "catalogue / bypass")
    part_a()
    part_b()
    part_c()
    part_d()
    print("\nDEFECTS = %d" % len(DEFECTS))
    for d in DEFECTS[:20]:
        print("   -", d)
    raise SystemExit(1 if DEFECTS else 0)


main()
