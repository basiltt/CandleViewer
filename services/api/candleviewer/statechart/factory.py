"""candleviewer.statechart.factory — the ONLY construction site (E50-T59).

`build()` and (a thin delegate to `persistence.restore`, landing in
E50-T10/T49) `restore()` are the sole functions in the whole codebase that
may call `create_machine`, `Interpreter` or `SyncInterpreter`
(29-statechart-adoption-plan.md §1.2, CV-LINT-IMPORT). They apply the FINAL
mandatory config block from `28-statechart-catalogue.md` §1.3c
unconditionally — no caller kwarg can opt out of any part of it.

Persistence (snapshot/HMAC/drain-journal restore, E50-T10/T49) and plugin
bodies (CvErrorHooks/CvMetricsPlugin/CvAuditPlugin, E50-T60) are out of
scope here; `restore()` accepts a `plugins` sequence so those tickets can
wire themselves in without touching this module's construction logic, and
ships with stub-safe defaults (`()`  ->  no extra plugins) until then.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import jsonschema
from xstate_statemachine import (
    Interpreter,
    MachineLogic,
    OverflowPolicy,
    PluginBase,
    create_machine,
)
from xstate_statemachine.clock import Clock

from candleviewer.statechart.bindings import load_binding_maps
from candleviewer.statechart.config import (
    CV_EVENT_SCHEMAS,
    CV_INBOX_BOUND,
    CV_SERVICE_POOL,
    CV_START_TIMEOUT,
    Lane,
)
from candleviewer.statechart.registry import Registry

#: Lazily constructed default registry (`machines/*.machine.json` under the
#: package). Tests inject their own via `build(..., registry=...)` so the
#: default one is never eagerly loaded (and never touched) unless a caller
#: actually asks for it.
_default_registry: Registry | None = None


def _get_default_registry() -> Registry:
    global _default_registry
    if _default_registry is None:
        _default_registry = Registry()
    return _default_registry


class SyncInterpreterRefusedError(AssertionError):
    """Raised when anything requests the sync engine from this factory
    (MUSTNOT-06). Async `Interpreter` only."""


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Return value of `build()`: the started interpreter plus the
    `machine_hash` it was built from, so callers can bind the two together
    for supervision/audit without re-hashing the chart themselves."""

    interpreter: Interpreter[Any]
    machine_hash: str


def _cv_bring_up(interp: Interpreter[Any]) -> None:
    """CV-C66': per-process bring-up work that must NOT hang off
    `on_interpreter_start`, because that hook never fires on a
    snapshot-restored interpreter (R13-02). Telemetry-only hooks may still
    use `on_interpreter_start`; anything that must run unconditionally
    (fresh build *and* restore) belongs here instead, called by both
    `build()` and `restore()` before `start()`.

    Currently a no-op placeholder: no bring-up work is registered yet
    (plugins land in E50-T60, persistence bring-up in E50-T10/T49). It
    exists now so both call sites route through one place and never grow
    a second one later.
    """
    return None


def _assert_async_engine_only(*, sync: bool) -> None:
    if sync:
        raise SyncInterpreterRefusedError(
            "cv.statechart.factory builds the async Interpreter only "
            "(MUSTNOT-06); SyncInterpreter is not available through build()"
        )


def _event_validators(schemas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Adapt JSON-Schema dicts to the validator objects the library calls
    (`schema.validate(payload)`); a bare dict is not callable (QA #1634)."""
    return {name: jsonschema.Draft202012Validator(schema) for name, schema in schemas.items()}


async def build(
    machine_key: str,
    *,
    ctx: Any = None,
    clock: Clock,
    lane: Lane,
    plugins: tuple[PluginBase[Any], ...] = (),
    registry: Registry | None = None,
    sync: bool = False,
) -> BuildResult:
    """Construct, configure and start an `Interpreter` for *machine_key*.

    Applies the FINAL mandatory config block (28-statechart-catalogue.md
    §1.3c) unconditionally: `strict_config=True` + the chart's own
    `strictConfig`/`strict`/`strictTargets`/`onUnhandled`/`maxIterations`
    keys (already asserted present by `registry.validate()`), `strict=True`
    + `event_schemas=CV_EVENT_SCHEMAS` on the interpreter, the per-lane
    inbox bound with `overflow_policy="refuse"`, the per-lane service pool
    size, the injected `clock=`, every plugin passed via `.use(...)`, bring-
    up, and a bounded `start()`.

    No extra kwargs reach the interpreter: `sync=True` raises
    `SyncInterpreterRefusedError` rather than constructing anything (there
    is no code path in this function that builds a `SyncInterpreter` at
    all — the parameter exists solely so a caller cannot get one by asking).
    """
    _assert_async_engine_only(sync=sync)

    reg = registry or _get_default_registry()
    chart = reg.get(machine_key)
    chart_hash = reg.hash(machine_key)

    maps = load_binding_maps(machine_key)
    logic: MachineLogic[Any] = MachineLogic(
        actions=maps.actions,
        guards=maps.guards,
        services=maps.services,
        strict=True,
    )

    machine = create_machine(
        chart,
        context_type=dict,
        logic=logic,
        strict_targets=True,
        event_schemas=_event_validators(CV_EVENT_SCHEMAS),
        strict_config=True,
    )

    interp: Interpreter[Any] = Interpreter(
        machine,
        input=ctx,
        clock=clock,
        max_queue_size=CV_INBOX_BOUND[lane],
        # "refuse" (28-statechart-catalogue.md §1.3c) == OverflowPolicy.RAISE:
        # nothing is ever dropped silently, on any lane (CV-C36). The order
        # lane's gateway turns the resulting QueueOverflowError into a 503
        # plus a page (29-statechart-adoption-plan.md §1.2); that mapping
        # lives in gateway.py (E50-T15), not here.
        overflow_policy=OverflowPolicy.RAISE,
        strict=True,
        service_pool_size=CV_SERVICE_POOL[lane],
    )
    for plugin in plugins:
        interp.use(plugin)

    _cv_bring_up(interp)
    try:
        await asyncio.wait_for(interp.start(), CV_START_TIMEOUT)
    except TimeoutError as exc:
        raise TimeoutError(
            f"'{machine_key}' start() did not settle within "
            f"{CV_START_TIMEOUT}s (CV-C56) — hard startup failure, never a "
            "retry"
        ) from exc

    return BuildResult(interpreter=interp, machine_hash=chart_hash)


async def restore(
    machine_key: str,
    blob: str,
    *,
    clock: Clock,
    lane: Lane,
    plugins: tuple[PluginBase[Any], ...] = (),
    registry: Registry | None = None,
    minimum_version: int = 3,
) -> BuildResult:
    """Restore an `Interpreter` for *machine_key* from a persisted snapshot
    *blob* (29-statechart-adoption-plan.md §1.3, CV-C52/CV-C60/CV-C66').

    Snapshot persistence — the HMAC envelope, tamper quarantine and
    drain-journal replay — is `statechart/persistence.py`'s job
    (E50-T10/T49, explicitly out of scope here) and is also the *only*
    module `from_snapshot()` may be called from (CV-LINT-RESTORE,
    CV-C52); this function is a thin, typed delegation point so callers
    write `factory.restore(...)` and never reach into `persistence`
    directly, but it cannot itself call `from_snapshot` before that
    module exists. Raises `NotImplementedError` until E50-T10/T49 lands
    and wires the delegation.
    """
    raise NotImplementedError(
        "candleviewer.statechart.factory.restore() delegates to "
        "statechart.persistence.restore(), which lands in E50-T10/T49; "
        "not yet available"
    )
