"""Statechart *config* generator shared by the definition fuzzer (F1) and the
event fuzzer (F2).

Two modes:

* ``valid_machine()``  -- a hypothesis strategy for a statechart that is
  structurally well-formed by construction: every transition target
  resolves, every referenced action/guard/service/delay name is drawn from
  a fixed vocabulary that the accompanying ``make_logic()`` implements, and
  no rule in the library's documented validation set is knowingly broken.
  ``create_machine`` is expected to SUCCEED on these.
* ``mutated_machine()`` -- a valid config with one or more corruptions
  applied (type swaps, key drops, dangling targets, junk values). This is
  the "truly-invalid input" arm: ``create_machine`` is expected to raise
  one of ``ALLOWED_BUILD_ERRORS`` -- never ``TypeError`` /
  ``AttributeError`` / ``KeyError`` / ``RecursionError`` / anything else,
  and never to succeed *silently* when the damage is a dangling target
  (build-time validation, #29/#30, is a shipped guarantee).

Design note on shrinking: everything is drawn from hypothesis strategies
and assembled by pure functions, so hypothesis's built-in shrinker reduces
nesting depth, child count and mutation count automatically.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from hypothesis import strategies as st

# -----------------------------------------------------------------------------
# 🔤 Fixed vocabularies. Small and closed so collisions are frequent (good:
#    collisions are where ambiguity bugs live) and so logic can be complete.
# -----------------------------------------------------------------------------
ACTIONS = ["act_a", "act_b", "act_c"]
GUARDS = ["guard_true", "guard_false", "guard_ctx"]
SERVICES = ["svc_ok", "svc_fail", "svc_slow"]
DELAYS = ["delay_short"]
EVENTS = ["GO", "NEXT", "BACK", "PING", "PONG", "DONE_IT", "X"]
STATE_KEYS = ["a", "b", "c", "d", "e"]


def _names(n: int) -> List[str]:
    return STATE_KEYS[:n]


# -----------------------------------------------------------------------------
# 🌳 Structural generation
# -----------------------------------------------------------------------------
# A "skeleton" is a recursive plain-data description we build the JSON from in
# a second pass. Two passes are needed because transition targets must be
# chosen from ids that only exist once the whole tree is known.


@st.composite
def _skeleton(draw: Any, depth: int, max_depth: int) -> Dict[str, Any]:
    """Draw one node's SHAPE (kind + children), without transitions."""
    can_nest = depth < max_depth
    choices = ["atomic", "final"]
    if can_nest:
        choices += ["compound", "compound", "parallel"]
    kind = draw(st.sampled_from(choices))

    node: Dict[str, Any] = {"kind": kind, "children": {}}
    if kind == "compound":
        n = draw(st.integers(min_value=1, max_value=3))
        keys = _names(n)
        for k in keys:
            node["children"][k] = draw(_skeleton(depth + 1, max_depth))
        # 🕰️ Optionally add a history pseudo-state as an extra child.
        if draw(st.booleans()):
            node["children"]["hist"] = {
                "kind": "history",
                "children": {},
                "history": draw(st.sampled_from(["shallow", "deep"])),
            }
        node["initial"] = keys[0]
    elif kind == "parallel":
        n = draw(st.integers(min_value=2, max_value=3))
        for k in _names(n):
            # 🧩 A parallel region must itself be compound, per XState.
            sub = draw(_skeleton(depth + 1, max_depth))
            if sub["kind"] not in ("compound", "parallel"):
                sub = {
                    "kind": "compound",
                    "children": {"a": {"kind": "atomic", "children": {}}},
                    "initial": "a",
                }
            node["children"][k] = sub
    return node


def _walk(
    node: Dict[str, Any], path: str, out: List[Tuple[str, Dict[str, Any]]]
) -> None:
    out.append((path, node))
    for key, child in node["children"].items():
        _walk(child, f"{path}.{key}", out)


def _atomic_or_compound_ids(nodes: List[Tuple[str, Dict[str, Any]]]) -> List[str]:
    return [p for p, n in nodes if n["kind"] not in ("history",)]


@st.composite
def _decorate(
    draw: Any,
    node: Dict[str, Any],
    path: str,
    all_ids: List[str],
    root_id: str,
    feature_budget: Dict[str, int],
) -> Dict[str, Any]:
    """Second pass: emit real XState JSON for one node."""
    kind = node["kind"]
    cfg: Dict[str, Any] = {}

    if kind == "final":
        cfg["type"] = "final"
        if draw(st.booleans()):
            cfg["output"] = {"ok": True}
        return cfg
    if kind == "history":
        cfg["type"] = "history"
        cfg["history"] = node["history"]
        return cfg
    if kind == "parallel":
        cfg["type"] = "parallel"
    if kind == "compound":
        cfg["initial"] = node["initial"]

    # 🎬 entry / exit actions
    if draw(st.booleans()):
        cfg["entry"] = draw(
            st.lists(st.sampled_from(ACTIONS), min_size=1, max_size=2)
        )
    if draw(st.booleans()):
        cfg["exit"] = draw(st.sampled_from(ACTIONS))

    # ➡️ `on` transitions. Targets are absolute `#root.path` ids so they
    #    always resolve regardless of where they sit -- the sibling-fallback
    #    ambiguity (#31) is a separate, already-filed concern and would
    #    otherwise swamp this fuzzer with known noise.
    n_tr = draw(st.integers(min_value=0, max_value=3))
    if n_tr:
        on: Dict[str, Any] = {}
        for _ in range(n_tr):
            ev = draw(st.sampled_from(EVENTS))
            on[ev] = draw(_transition(all_ids, root_id))
        cfg["on"] = on

    # ⏭️ `always` (eventless). Guarded, and never self-targeting -- an
    #    unguarded `always` back to self is rejected by build validation on
    #    purpose (#30), which is correct behaviour, not a finding.
    if feature_budget["always"] > 0 and draw(st.booleans()):
        feature_budget["always"] -= 1
        other = [i for i in all_ids if i != path]
        if other:
            cfg["always"] = {
                "target": "#" + draw(st.sampled_from(other)),
                "guard": draw(st.sampled_from(GUARDS)),
            }

    # ⏲️ `after`
    if feature_budget["after"] > 0 and kind != "parallel" and draw(st.booleans()):
        feature_budget["after"] -= 1
        delay = draw(
            st.one_of(st.integers(min_value=0, max_value=20), st.sampled_from(DELAYS))
        )
        cfg["after"] = {delay: draw(_transition(all_ids, root_id))}

    # 🧵 `invoke`
    if feature_budget["invoke"] > 0 and kind != "parallel" and draw(st.booleans()):
        feature_budget["invoke"] -= 1
        inv: Dict[str, Any] = {
            "id": "inv_" + path.replace(".", "_"),
            "src": draw(st.sampled_from(SERVICES)),
        }
        if draw(st.booleans()):
            inv["onDone"] = draw(_transition(all_ids, root_id))
        if draw(st.booleans()):
            inv["onError"] = draw(_transition(all_ids, root_id))
        cfg["invoke"] = inv

    if node["children"]:
        states: Dict[str, Any] = {}
        for key, child in node["children"].items():
            states[key] = draw(
                _decorate(
                    child, f"{path}.{key}", all_ids, root_id, feature_budget
                )
            )
        cfg["states"] = states
    return cfg


@st.composite
def _transition(draw: Any, all_ids: List[str], root_id: str) -> Any:
    """A transition: bare string target, or an object with guard/actions."""
    target = "#" + draw(st.sampled_from(all_ids))
    if draw(st.integers(min_value=0, max_value=2)) == 0:
        return target
    t: Dict[str, Any] = {"target": target}
    if draw(st.booleans()):
        t["actions"] = draw(
            st.lists(st.sampled_from(ACTIONS), min_size=1, max_size=2)
        )
    if draw(st.booleans()):
        t["guard"] = draw(st.sampled_from(GUARDS))
    if draw(st.booleans()):
        t["internal"] = draw(st.booleans())
    return t


@st.composite
def valid_machine(draw: Any, max_depth: int = 4) -> Dict[str, Any]:
    """A structurally well-formed statechart config, nesting <= max_depth."""
    root_id = "m"
    n = draw(st.integers(min_value=1, max_value=3))
    children: Dict[str, Any] = {}
    for k in _names(n):
        children[k] = draw(_skeleton(1, max_depth))
    root = {"kind": "compound", "children": children, "initial": _names(n)[0]}

    nodes: List[Tuple[str, Dict[str, Any]]] = []
    _walk(root, root_id, nodes)
    all_ids = _atomic_or_compound_ids(nodes)

    budget = {"always": 2, "after": 2, "invoke": 2}
    cfg = draw(_decorate(root, root_id, all_ids, root_id, budget))
    cfg["id"] = root_id
    cfg["context"] = {"n": 0, "log": []}
    # ⚙️ Policy knobs, drawn so every combination gets exercised.
    cfg["actionErrorPolicy"] = draw(
        st.sampled_from(["continue", "rollback", "fail"])
    )
    cfg["guardErrorPolicy"] = draw(st.sampled_from(["false", "true", "raise"]))
    cfg["onUnhandled"] = draw(st.sampled_from(["ignore", "defer", "error"]))
    if draw(st.booleans()):
        cfg["maxIterations"] = draw(st.integers(min_value=1, max_value=50))
    return cfg


# -----------------------------------------------------------------------------
# 💣 Mutation: turn a valid config into an invalid one
# -----------------------------------------------------------------------------
JUNK: List[Any] = [
    None,
    0,
    -1,
    3.5,
    True,
    "",
    "   ",
    [],
    {},
    [1, 2],
    {"x": 1},
    "\x00",
    "ünïcødé",
    "a" * 300,
    float("nan"),
    float("inf"),
]

MUTABLE_KEYS = [
    "id",
    "initial",
    "states",
    "on",
    "type",
    "entry",
    "exit",
    "always",
    "after",
    "invoke",
    "context",
    "history",
    "output",
    "tags",
    "meta",
    "actionErrorPolicy",
    "guardErrorPolicy",
    "onUnhandled",
    "maxIterations",
]

MUTATIONS = [
    "swap_type",  # replace a key's value with junk
    "drop_key",  # delete a key
    "dangle_target",  # point a target at a state that does not exist
    "cycle_always",  # unguarded always self-loop (must be rejected, #30)
    "dup_custom_id",  # two states declaring the same custom id
    "bad_state_value",  # a state entry that is not a dict
    "deep_nest",  # nest beyond anything reasonable
    "self_parent",  # make "states" reference a shared dict (aliasing)
    "unknown_logic",  # reference an action name nothing implements
]


def _paths(obj: Any, prefix: Tuple[Any, ...] = ()) -> List[Tuple[Any, ...]]:
    out: List[Tuple[Any, ...]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(prefix + (k,))
            out.extend(_paths(v, prefix + (k,)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.append(prefix + (i,))
            out.extend(_paths(v, prefix + (i,)))
    return out


def _get(obj: Any, path: Tuple[Any, ...]) -> Any:
    for p in path:
        obj = obj[p]
    return obj


def _set(obj: Any, path: Tuple[Any, ...], value: Any) -> None:
    for p in path[:-1]:
        obj = obj[p]
    obj[path[-1]] = value


def _del(obj: Any, path: Tuple[Any, ...]) -> None:
    for p in path[:-1]:
        obj = obj[p]
    del obj[path[-1]]


def apply_mutation(
    cfg: Dict[str, Any], kind: str, i: int, junk_i: int
) -> Tuple[Dict[str, Any], str]:
    """Apply mutation *kind*; returns (config, description). Deterministic
    in (i, junk_i) so a recorded repro replays exactly."""
    cfg = copy.deepcopy(cfg)
    desc = kind
    if kind == "swap_type":
        cand = [p for p in _paths(cfg) if p[-1] in MUTABLE_KEYS]
        if not cand:
            return cfg, "noop"
        p = cand[i % len(cand)]
        v = JUNK[junk_i % len(JUNK)]
        _set(cfg, p, v)
        desc = f"swap_type at {'/'.join(map(str, p))} -> {v!r}"
    elif kind == "drop_key":
        cand = [p for p in _paths(cfg) if p[-1] in MUTABLE_KEYS]
        if not cand:
            return cfg, "noop"
        p = cand[i % len(cand)]
        _del(cfg, p)
        desc = f"drop_key {'/'.join(map(str, p))}"
    elif kind == "dangle_target":
        cand = [p for p in _paths(cfg) if p[-1] == "target"]
        if not cand:
            return cfg, "noop"
        p = cand[i % len(cand)]
        _set(cfg, p, "#m.NO_SUCH_STATE_" + str(i))
        desc = f"dangle_target at {'/'.join(map(str, p))}"
    elif kind == "cycle_always":
        cfg["states"]["a"] = {"always": {"target": "#m.a"}}
        cfg["initial"] = "a"
        desc = "unguarded always self-loop on m.a"
    elif kind == "dup_custom_id":
        cfg.setdefault("states", {})
        cfg["states"]["dup1"] = {"id": "SAME"}
        cfg["states"]["dup2"] = {"id": "SAME"}
        desc = "two states with custom id 'SAME'"
    elif kind == "bad_state_value":
        cfg.setdefault("states", {})["junky"] = JUNK[junk_i % len(JUNK)]
        desc = f"states.junky = {JUNK[junk_i % len(JUNK)]!r}"
    elif kind == "deep_nest":
        depth = 200 + (i % 3) * 400
        node: Dict[str, Any] = {"type": "final"}
        for d in range(depth):
            node = {"initial": "s", "states": {"s": node}}
        cfg.setdefault("states", {})["deep"] = node
        desc = f"nested {depth} levels under m.deep"
    elif kind == "self_parent":
        shared = cfg.get("states")
        if isinstance(shared, dict) and shared:
            k = list(shared)[i % len(shared)]
            if isinstance(shared[k], dict):
                shared[k].setdefault("states", {})["loop"] = shared[k]
        desc = "a state dict that contains itself (aliased cycle)"
    elif kind == "unknown_logic":
        cfg.setdefault("states", {}).setdefault(
            "a", {"type": "final"}
        )
        tgt = cfg["states"]["a"]
        if isinstance(tgt, dict):
            tgt["entry"] = "no_such_action_" + str(i)
        desc = "entry references an unimplemented action"
    return cfg, desc


# -----------------------------------------------------------------------------
# 🧠 Logic implementing the fixed vocabulary
# -----------------------------------------------------------------------------
def make_logic(sync: bool = False) -> Any:
    from xstate_statemachine import MachineLogic

    def act(i: Any, ctx: Any, e: Any, a: Any) -> None:
        if isinstance(ctx, dict):
            ctx["n"] = ctx.get("n", 0) + 1

    # 🛡️ Guards are `(context, event)` -- `GuardCallable = Callable[[Any,
    #    Any], bool]` in machine_logic.py, and every guard in the library's
    #    own test suite has that arity.
    def g_true(ctx: Any, e: Any) -> bool:
        return True

    def g_false(ctx: Any, e: Any) -> bool:
        return False

    def g_ctx(ctx: Any, e: Any) -> bool:
        return bool(isinstance(ctx, dict) and ctx.get("n", 0) % 2 == 0)

    if sync:

        def svc_ok(i: Any, ctx: Any, e: Any) -> Any:
            return {"ok": 1}

        def svc_fail(i: Any, ctx: Any, e: Any) -> Any:
            raise RuntimeError("svc_fail")

        def svc_slow(i: Any, ctx: Any, e: Any) -> Any:
            return {"slow": 1}

    else:

        async def svc_ok(i: Any, ctx: Any, e: Any) -> Any:  # type: ignore[misc]
            return {"ok": 1}

        async def svc_fail(i: Any, ctx: Any, e: Any) -> Any:  # type: ignore[misc]
            raise RuntimeError("svc_fail")

        async def svc_slow(i: Any, ctx: Any, e: Any) -> Any:  # type: ignore[misc]
            import asyncio

            await asyncio.sleep(0.001)
            return {"slow": 1}

    return MachineLogic(
        actions={n: act for n in ACTIONS},
        guards={
            "guard_true": g_true,
            "guard_false": g_false,
            "guard_ctx": g_ctx,
        },
        services={
            "svc_ok": svc_ok,
            "svc_fail": svc_fail,
            "svc_slow": svc_slow,
        },
        delays={"delay_short": 1},
    )
