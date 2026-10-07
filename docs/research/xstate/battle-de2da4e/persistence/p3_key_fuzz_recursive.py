# -*- coding: utf-8 -*-
"""P3 (#220) -- the recursive unknown-key check, two-sided.  STANDALONE.

A  SOUNDNESS (no false positives): generate N VALID charts from the full
   documented key grammar -- nested states, parallel regions, on/always/
   after/onDone transition bodies (dict + list + string shorthand),
   invoke with onDone/onError, x-/meta/description/tags at EVERY level --
   and assert 0 rejections under strict_config=True.
B  COMPLETENESS (no false negatives): inject ONE typo at a RANDOM nesting
   level / object kind; assert strict_config=True raises AND the message
   names the offending key.
C  Catalogue JSON: every *.machine.json under the battle contracts dirs
   through the recursive check.
D  Case variants / x- abuse: can `Strict` / `STRICT` / `x-strict` smuggle
   a policy past the checker?
"""
from __future__ import annotations

import copy
import glob
import json
import os
import random
import sys

from xstate_statemachine import MachineLogic, create_machine
from xstate_statemachine.exceptions import InvalidConfigError
from xstate_statemachine.validation import validate_top_level_keys

KIND = os.environ.get("XS_SVC", "async")
N = int(os.environ.get("XS_N", "250"))
SEED = int(os.environ.get("XS_SEED", "220"))

META = ["meta", "description", "tags", "x-owner", "x-note"]


def meta_blob(rnd):
    d = {}
    for k in rnd.sample(META, rnd.randint(0, 3)):
        d[k] = {"v": 1} if k == "meta" else "z"
    return d


_CTR = [0]


def nxt():
    _CTR[0] += 1
    return "n%d" % _CTR[0]


def gen_state(rnd, depth, names, path):
    s = {}
    s.update(meta_blob(rnd))
    kids = []
    if depth > 0 and rnd.random() < 0.6:
        nk = rnd.randint(1, 2)
        kids = [nxt() for _ in range(nk)]
        s["states"] = {k: gen_state(rnd, depth - 1, kids, path + [k])
                       for k in kids}
        if rnd.random() < 0.3 and nk > 1:
            s["type"] = "parallel"
        else:
            s["initial"] = kids[0]
    if rnd.random() < 0.7:
        s["entry"] = ["act"]
    if rnd.random() < 0.4:
        s["exit"] = ["act"]
    peers = [n for n in names if n != path[-1]] or names
    tgt = rnd.choice(peers) if peers else None
    if tgt and rnd.random() < 0.8:
        form = rnd.choice(["str", "dict", "list"])
        body = {"target": tgt, "actions": ["act"], "guard": "g"}
        body.update(meta_blob(rnd))
        if rnd.random() < 0.3:
            body["reenter"] = True
        s["on"] = {"E": tgt if form == "str"
                   else (body if form == "dict" else [body])}
    if tgt and rnd.random() < 0.3:
        body2 = {"target": tgt, "actions": ["act"]}
        body2.update(meta_blob(rnd))
        s["after"] = {"50": body2}
    if tgt and rnd.random() < 0.25:
        body3 = {"target": tgt, "guard": "gfalse"}
        body3.update(meta_blob(rnd))
        s["always"] = [body3]
    if not kids and rnd.random() < 0.35:
        inv = {"src": "svc", "id": "iv", "input": {"a": 1},
               "onDone": {"target": tgt or path[-1], "actions": ["act"]},
               "onError": [{"target": tgt or path[-1]}]}
        inv.update(meta_blob(rnd))
        if rnd.random() < 0.3:
            inv["systemId"] = "sid"
        s["invoke"] = inv if rnd.random() < 0.5 else [inv]
    return s


def gen_chart(rnd):
    top = [nxt() for _ in range(rnd.randint(2, 3))]
    cfg = {"id": "m", "initial": top[0], "context": {"n": 0},
           "states": {k: gen_state(rnd, 2, top, [k]) for k in top}}
    cfg.update(meta_blob(rnd))
    if rnd.random() < 0.5:
        cfg["maxIterations"] = 50
    if rnd.random() < 0.3:
        cfg["strict"] = False
    if rnd.random() < 0.3:
        cfg["version"] = "1.0"
    return cfg


TYPOS = {"entry": "entyr", "exit": "exti", "on": "onn", "after": "aftr",
         "always": "alwasy", "invoke": "invok", "states": "staets",
         "initial": "initail", "type": "tpye", "target": "targt",
         "actions": "actiosn", "guard": "gaurd", "src": "srcc",
         "onDone": "onDoen", "onError": "onErorr", "input": "inupt",
         "maxIterations": "maxIteration", "strict": "Strict"}


def walk_objs(cfg, path="m"):
    """Yield (obj, kind, path) for every checkable config object."""
    yield cfg, "state", path
    on = cfg.get("on")
    if isinstance(on, dict):
        for ev, raw in on.items():
            for t in (raw if isinstance(raw, list) else [raw]):
                if isinstance(t, dict):
                    yield t, "transition", path + " on:" + str(ev)
    for key in ("always", "onDone"):
        raw = cfg.get(key)
        for t in (raw if isinstance(raw, list) else [raw]):
            if isinstance(t, dict):
                yield t, "transition", path + " " + key
    aft = cfg.get("after")
    if isinstance(aft, dict):
        for d, raw in aft.items():
            for t in (raw if isinstance(raw, list) else [raw]):
                if isinstance(t, dict):
                    yield t, "transition", path + " after:" + str(d)
    inv = cfg.get("invoke")
    for iv in (inv if isinstance(inv, list) else [inv]):
        if isinstance(iv, dict):
            yield iv, "invoke", path + " invoke"
            for lab in ("onDone", "onError"):
                raw = iv.get(lab)
                for t in (raw if isinstance(raw, list) else [raw]):
                    if isinstance(t, dict):
                        yield t, "transition", path + " invoke " + lab
    st = cfg.get("states")
    if isinstance(st, dict):
        for k, ch in st.items():
            if isinstance(ch, dict):
                for r in walk_objs(ch, path + "." + k):
                    yield r


def logic():
    def act(i, c, e, a):
        pass

    def g(i, c, e):
        return True

    def gfalse(i, c, e):
        return False

    async def svc(i, c, e):
        return 1

    def svcd(i, c, e):
        return 1

    return MachineLogic(actions={"act": act}, guards={"g": g,
                                                      "gfalse": gfalse},
                        services={"svc": svc if KIND == "async" else svcd})


def mk(cfg, strict):
    return create_machine(copy.deepcopy(cfg), strict_config=strict,
                          logic=logic())


def main():
    rnd = random.Random(SEED)
    charts, fp, other = [], [], []
    for _ in range(N):
        c = gen_chart(rnd)
        try:
            mk(c, True)
            charts.append(c)
        except InvalidConfigError as e:
            charts.append(None)
            if "unknown config key" in str(e):
                fp.append(str(e)[:250])
            else:
                other.append(str(e)[:150])
        except Exception as e:
            charts.append(None)
            other.append("%s: %s" % (type(e).__name__, str(e)[:150]))
    misses, wrongmsg = [], []
    n_inj = 0
    structural = 0
    for c in charts:
        if c is None:
            continue
        objs = [o for o in walk_objs(c)
                if any(k in TYPOS for k in o[0] if isinstance(k, str))]
        if not objs:
            continue
        obj, kind, path = rnd.choice(objs)
        key = rnd.choice([k for k in obj if isinstance(k, str)
                          and k in TYPOS])
        bad = copy.deepcopy(c)
        for o2, _k, p2 in walk_objs(bad):
            if p2 == path and key in o2:
                o2[TYPOS[key]] = o2.pop(key)
                break
        else:
            continue
        n_inj += 1
        try:
            mk(bad, True)
            misses.append({"path": path, "kind": kind, "key": key,
                           "typo": TYPOS[key]})
        except InvalidConfigError as e:
            if "unknown config key" not in str(e):
                structural += 1
            elif TYPOS[key] not in str(e):
                wrongmsg.append({"path": path, "typo": TYPOS[key],
                                 "msg": str(e)[:200]})
        except Exception:
            structural += 1
    base = ("<workspace>/CandleViewer/"
            "docs/research/xstate")
    cat, n_cat = [], 0
    for d in ("battle-c78ce99", "battle-19cb1f1", "battle-3ed3099"):
        for f in glob.glob(base + "/" + d + "/contracts/*.machine.json"):
            try:
                raw = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            n_cat += 1
            try:
                validate_top_level_keys(raw, strict_config=True)
            except InvalidConfigError as e:
                cat.append({"file": os.path.basename(f),
                            "msg": str(e)[:300]})
    d_out = {}
    for k in ("Strict", "STRICT", "x-strict", "X-strict"):
        cfg = {"id": "d", "initial": "a", "states": {"a": {}}, k: True}
        try:
            validate_top_level_keys(cfg, strict_config=True)
            reported = False
        except InvalidConfigError:
            reported = True
        m = mk(cfg, False)
        d_out[k] = {"reported": reported,
                    "policy_took_effect": bool(getattr(m, "strict", False))}

    ok = (not fp and not misses and not wrongmsg
          and all(not v["policy_took_effect"] for v in d_out.values())
          and d_out["Strict"]["reported"] and d_out["STRICT"]["reported"]
          and not d_out["x-strict"]["reported"])
    print(json.dumps({"kind": KIND, "N": N,
                      "A_valid_built": len(charts) - charts.count(None),
                      "A_false_positives": len(fp), "A_sample": fp[:3],
                      "A_other_build_errors": len(other),
                      "A_other_sample": other[:3],
                      "B_injected": n_inj, "B_missed": len(misses),
                      "B_structural_reject": structural,
                      "B_missed_sample": misses[:6],
                      "B_wrong_msg": len(wrongmsg),
                      "B_wrong_sample": wrongmsg[:3],
                      "C_catalogue_files": n_cat,
                      "C_findings": len(cat), "C_sample": cat[:6],
                      "D_case_and_x": d_out,
                      "VERDICT": "PASS" if ok else "FAIL"}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
