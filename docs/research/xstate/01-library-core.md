# 01 — xstate-statemachine: Core Source Study

Source studied: `C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src/xstate_statemachine/`
Version: `__version__ = "0.7.0"` (`__init__.py:166`). All file:line refs are relative to that `src/xstate_statemachine/` root.

Scope: every non-CLI `.py` file read in full (models, events, machine_logic, factory, base_interpreter, interpreter, sync_interpreter, actions, helpers, plugins, resolver, logic_loader, task_manager, exceptions, logger, pythonic). The `cli/` subpackage (~5.9k lines, code generation from XState JSON) was surveyed structurally only — it is a codegen tool, not runtime.

---

## 1. Module map

| Module | Lines | Role |
|---|---|---|
| `__init__.py` | 232 | Public facade; `__all__` (`:176-232`) |
| `models.py` | 1378 | `ActionDefinition`, `GuardDefinition`, `TransitionDefinition`, `InvokeDefinition`, `StateNode`, `MachineNode`; config parsing + PlantUML/Mermaid export |
| `events.py` | 171 | `Event` (frozen dataclass), `DoneEvent`, `AfterEvent` (NamedTuples) |
| `machine_logic.py` | 255 | `MachineLogic` registry (actions/guards/services/delays) + subclass auto-registration |
| `factory.py` | 170 | `create_machine()` |
| `base_interpreter.py` | 3046 | Mode-agnostic SCXML algorithm, snapshots, guards, actor system, built-in action semantics |
| `interpreter.py` | 1292 | Async engine (`asyncio.Queue` loop, tasks, actors) |
| `sync_interpreter.py` | 1568 | Sync engine (deque loop, `threading.Thread` timers) |
| `actions.py` | 526 | Built-in action creators + alias table + `ActionEnqueuer` |
| `helpers.py` | 403 | `wait_for`, `to_promise`, pure transition API (`PureSnapshot`) |
| `plugins.py` | 432 | `PluginBase` hooks, `LoggingInspector` |
| `resolver.py` | 237 | `resolve_target_state()` — `#abs`, `.rel`, plain bubbling |
| `logic_loader.py` | 397 | Singleton auto-discovery of logic from modules/providers |
| `task_manager.py` | 165 | asyncio task bookkeeping by owner id |
| `exceptions.py` | 221 | Exception hierarchy |
| `logger.py` | 69 | NullHandler library logger |
| `pythonic.py` | 1542 | Three Python DSLs: functional `build_machine`, `MachineBuilder`, `StateMachine` metaclass |
| `cli/` | ~5.9k | Code generation from XState JSON (`__main__.py`, strategies, IR, validation) |

Dependency shape: `factory` → `logic_loader`/`models`; `models` → `events`/`machine_logic`/`resolver`; `base_interpreter` → everything; `interpreter`/`sync_interpreter` → `base_interpreter` + `actions`; `helpers` imports `sync_interpreter` lazily (`helpers.py:244`) to dodge a cycle.

---

## 2. Public API surface

### 2.1 Machine construction

```python
create_machine(
    config: Dict[str, Any],
    *,
    logic: Optional[MachineLogic] = None,
    logic_modules: Optional[List[Union[str, ModuleType]]] = None,
    logic_providers: Optional[List[Any]] = None,
) -> MachineNode                                   # factory.py:43-170
```
- `logic` wins over auto-discovery (`factory.py:116-133`).
- Validates only `id` (non-empty str) and presence of `states` (`factory.py:139-158`); everything else is validated during `MachineNode` tree construction.

```python
MachineLogic(
    actions: Optional[Dict[str, Callable]] = None,
    guards:  Optional[Dict[str, Callable[..., bool]]] = None,
    services:Optional[Dict[str, Union[Callable, MachineNode]]] = None,
    delays:  Optional[Dict[str, Union[int, float, Callable]]] = None,
)                                                   # machine_logic.py:115-181
```
Callable contracts (`machine_logic.py:77-89`):
- action: `(interpreter, context, event, action_def) -> None | Awaitable[None]`
- guard: `(context, event) -> bool`, optionally `(context, event, params)` (arity-sniffed, `base_interpreter.py:3000-3046`)
- service: `(interpreter, context, event) -> Any | Awaitable[Any]`

Subclassing `MachineLogic` auto-registers methods **by arity** — 2 params → guard, 3 → service, 4 → action (`machine_logic.py:186-255`). This is a real footgun: an action helper that happens to take 3 args silently becomes a "service".

### 2.2 Interpreters

Async (`interpreter.py`):
```python
Interpreter(machine: MachineNode, input: Optional[Any] = None)      # :109
await start() -> Interpreter                                        # :169
await stop() -> None                                                # :275
await send(event_type: str, **payload) | send(event|dict)           # :335
await send_events(events: List[...])                                # :377
.is_running -> bool   # status=="running" AND loop task alive       # :147
.task_manager: TaskManager
```
Sync (`sync_interpreter.py`):
```python
SyncInterpreter(machine, input=None)   # :115
start() -> SyncInterpreter             # :145    (blocking, settles transients)
stop() -> None                         # :235
send(...) -> None                      # :299    (processes queue inline; blocking)
send_events(...) -> None               # :315
```

Shared on `BaseInterpreter`:
```python
.current_state_ids -> Set[str]         # base_interpreter.py:376  (atomic/final leaves)
.active_state_ids                      # :393 alias
.status: 'uninitialized'|'running'|'done'|'error'|'stopped'
.context, .output, .error, .input, .parent, .system -> ActorSystem
matches(state_id) -> bool              # :425  accepts '#id', full id, trailing partial
has_tag(tag) / .tags                   # :447 / :458
get_meta() -> Dict[str, Any]           # :470
can(event) -> bool                     # :482  evaluates guards, side-effect free
subscribe(listener) -> unsubscribe     # :533
on(event_type|'*', listener) -> off    # :1548 (for `emit`ted events)
use(plugin) -> self ; .plugins (get/set)# :640 / :574-638
get_snapshot() -> str (JSON)           # :669
get_persisted_snapshot() -> dict       # :690
classmethod from_snapshot(json, machine)# :814
```

### 2.3 Built-in action creators (`actions.py`)
`raise_`, `send_to`, `send_parent`, `forward_to`, `escalate`, `log`, `cancel`, `stop_child`, `spawn_child`, `emit`, `assign`, `pure`, `choose`, `enqueue_actions`, plus `ActionEnqueuer`. Canonical names `xstate.*` with camelCase and snake_case aliases in `BUILTIN_ACTION_ALIASES` (`actions.py:65-121`). `resolve_builtin()` / `is_builtin()` (`:124-151`).

Notable: `spawn_child` is deliberately **not** an alias for the built-in (`actions.py:96-104`) because `spawn_<serviceKey>` is the library's own spawn convention; you must write `spawnChild`/`xstate.spawnChild`.

### 2.4 Helpers (`helpers.py`)
```python
await wait_for(interp, predicate, *, timeout=10.0, poll_interval=0.005)   # :54
wait_for_sync(...)                                                        # :101
await to_promise(interp, *, timeout=None) -> output                       # :134
initial_transition(machine, *, input=None) -> (PureSnapshot, [ActionDefinition])  # :302
transition(machine, snapshot, event) -> (PureSnapshot, [ActionDefinition])        # :322  (exported as `pure_transition`)
get_initial_snapshot / get_next_snapshot                                  # :359 / :374
PureSnapshot(state_ids, configuration, context, status, output).matches() # :167
```
The pure API runs a throwaway `SyncInterpreter` subclass that records actions instead of executing them and suppresses timers/invokes (`helpers.py:226-276`). `assign` is still applied because it's part of next-state.

### 2.5 Pythonic DSL (`pythonic.py`)
Three styles: `build_machine(id=, states=[State...], transitions=[...], actions=, guards=, services=, context=, root=)` (`:1030`); fluent `MachineBuilder` (`:1082`, `.context/.state/.transition/.child_states/.action/.guard/.service/.root/.build`); class-based `StateMachine` with `_StateMachineMeta` (`:1387/:1487`) collecting `State` attrs, `a.to(b, event=...)` transitions combined with `|`, and `@action/@guard/@service` decorators (`:443/:487/:543`). Names are snake→camel converted (`:57-73`) to match JSON conventions. All three compile to the same JSON config and call `create_machine`.

---

## 3. Event object shape

- `Event` is a **frozen dataclass** with `type: str` and `payload: Dict` (default_factory) — `events.py:44-90`. `.data` is an alias property that raises `TypeError` if payload isn't a dict (`:79-90`). Frozen, but `payload` is a mutable dict, so immutability is shallow.
- `DoneEvent(type, data, src)` — NamedTuple (`events.py:93-133`). Types: `done.invoke.<id>`, `done.state.<stateId>`. **`error.platform.<id>` is also delivered as a `DoneEvent`** (`interpreter.py:1121`), which is confusing naming.
- `AfterEvent(type)` — NamedTuple, type `after.<delay>.<stateId>` (`events.py:136-171`). Carries no payload.
- Coercion: `_coerce_event` (`base_interpreter.py:504-531`) and `_prepare_event` (`:1104-1158`) accept str / dict-with-`type` / event instance / duck-typed object. Dict form folds all non-`type` keys into `payload`.

Asymmetry worth noting: user events carry `payload`, internal events carry `data`; user code must branch (`plugins.py:286-292` does exactly this).

---

## 4. Transition algorithm

Entry point `BaseInterpreter._process_event` (`base_interpreter.py:1263-1293`):
1. `_select_transitions(event)` — one transition per orthogonal region.
2. Execute each in order, skipping any whose source went inactive (`:1283-1293`).

### 4.1 Selection (`_select_transitions`, `:2536-2599`)
- Seeds from active **leaves** (atomic/final/childless), sorted `(-depth, id)` for determinism.
- For each leaf, `_collect_eligible_transitions` (`:2426-2534`) walks up the ancestor chain collecting matching + guard-passing transitions; winner is `max(..., key=source.depth)`.
- De-dupes by `id(transition)` so a shared-ancestor transition fires once.
- Guard results memoised per selection pass in `guard_cache` keyed by `id(transition)` (`:2454-2472`) — explicitly to keep side-effecting guards from firing once per region.
- Final ordering: deepest-source-first.

### 4.2 Event descriptor matching (`_matching_descriptors`, `:2361-2424`)
- Exact key first; then partial `a.b.*` sorted longest-prefix-first; then bare `*`.
- **Internal events are excluded from wildcards**: any type starting `done.`, `error.`, `after.`, `xstate.` only matches exactly (`:2405-2406`). Matches XState's line.

### 4.3 Eventless / `always`
- `always` at config level is merged into the `on[""]` bucket (`models.py:863-870`), i.e. v4 `on: {"": ...}` is the internal representation.
- Settled after every macrostep and after `start()` in both engines (`interpreter.py:550-586`, `sync_interpreter.py:562-608`), bounded by `machine.max_iterations` (default 1000, from `config["maxIterations"]`, `models.py:1154-1156`).

### 4.4 Internal vs external
- Targetless transition → actions only (`base_interpreter.py:1746-1760`).
- Self-transition without `reenter: True` → internal, no exit/entry (`:1767-1782`). `reenter` is read from config (`models.py:397`).
- Otherwise external: domain = LCCA via `_find_transition_domain` (`:2649-2703`), with special handling when target is an ancestor of source (steps up to `target.parent`, `:2695-2696`).
- Exit set `_compute_states_to_exit` (`:2601-2647`) scopes to the containing region when the domain is `parallel`, so orthogonal siblings survive.

### 4.5 Ordering & atomicity (`_execute_transition`, `:1732-1890`)
Order: record history → exit (sorted `(depth, id)` descending) → transition actions → enter (outer→inner). Entry: add to config, run `entry`, `_schedule_state_tasks`, final-state check, then descend into `initial`/regions (`:1896-1987`).

**Atomicity:** the whole exit/actions/enter block is wrapped in try/except; on failure the pre-transition configuration is restored *and* timers/services for rolled-back states are re-scheduled, then the exception re-raised (`:1823-1880`). Mirrored in sync (`sync_interpreter.py:503-550`).

### 4.6 Parallel / history / final
- Parallel entry enters all non-history regions except those explicitly on the entry path (`:1973-1987`).
- History: `type: "history"`, `history: "shallow"|"deep"` (`models.py:647-658`), recorded per *parent id* on exit (`_record_history`, `:1989-2036`), expanded at transition time into one combined entry path (`:1841-1860`) — a specific fix for deep history into parallel states. Unvisited history falls back to declared `target` then parent's `initial` (`:2038-2084`).
- Final: `_is_state_done` (`:2143-2201`) — compound done if active child done; parallel done if every non-history region has a done active descendant. `_check_and_fire_on_done` (`:2203-2242`) sends `done.state.<ancestorId>` to the nearest done ancestor with an `onDone`, carrying the final state's `output`. Top-level final → `_complete()` sets `status="done"` and `output` (machine-level `output` wins over final-state output, `:2237-2242`).
- `_fail()` sets `status="error"` + `.error`, fires plugin `on_error` (`:2309-2333`).

### 4.7 Guards
`_is_guard_satisfied` (`:2829-2937`):
- `None` → True. Bare string accepted for back-compat.
- Composite `and`/`or`/`not` recursed with short-circuit (`:2868-2880`).
- `stateIn` built-in answered from active config, but a **user-registered guard named `stateIn` wins** (`:2890-2891`).
- Missing named guard → `ImplementationMissingError` (fatal). A guard that **raises is treated as `False`** and logged (`:2911-2925`) — deliberate, but it means a bug in a predicate silently blocks a transition.
- `params` may be a callable of `{context, event}` (`_resolve_params`, `:2978-2998`).
- `cond` accepted as v4 alias for `guard` (`models.py:393`).

### 4.8 Target resolution
`resolver.resolve_target_state` (`resolver.py:105-237`): `#abs` (machine key first, then custom-id registry), `.` → parent, `.rel` from parent, else plain id bubbling up. Custom `id:` on any state registered in `MachineNode._custom_ids` (`models.py:561-580`, duplicates rejected).

On top of that, both interpreters wrap resolution in a **multi-stage fallback** (`base_interpreter.py:1164-1261`, `sync_interpreter.py:1431-1526`): try source → parent → root → `root.id + "." + target`, then `getattr(root, target)`, then root's `states` dict by key or by last-id-segment, then an **exhaustive tree walk matching on the last id segment**. This is very forgiving and a correctness hazard (see §10).

---

## 5. Context handling

- Mutable `dict`, mutated **in place** by user actions (`interpreter.py:669-673`). No immutability, no structural sharing, no copy-on-write.
- Initial context deep-copied per interpreter (`_build_initial_context`, `base_interpreter.py:342-369`); supports a **context factory** callable receiving `{"input": input}`; `input` is also `setdefault`-ed into a dict context.
- String context (Stately `"{{initialContext}}"` placeholder) downgraded to warning + empty dict (`models.py:1138-1146`).
- `assign` (`_apply_assign`, `:1570-1592`): callable form must return a dict → `context.update()`; dict form assigns per key, values may be callables of `{context, event}`. **Only top-level key merge** — no nested path assignment.
- Typing: `TContext = TypeVar("TContext", bound=Dict[str, Any])` (`models.py:66`). So generics exist but context is always a dict — no TypedDict/dataclass support, no static guarantees; everything is `Dict[str, Any]` in practice.

---

## 6. Invoke / services

Config: `invoke: {src, id, input, onDone, onError}` (list or single, `models.py:930-969`). `id` defaults to the state id. Done event `done.invoke.<id>`, error `error.platform.<id>`.

Async (`interpreter.py:1042-1171`):
- Service resolved from `logic.services`; **missing service raises `ImplementationMissingError` during state entry** (`base_interpreter.py:2812-2819`) — which, inside a transition, triggers the rollback path.
- Runs as an `asyncio.Task` registered under `owner_id = state.id`; `sleep(0)` first to avoid a registration race (`:1162-1171`).
- Accepts sync *and* async callables (`inspect.isawaitable`, `:1082-1085`).
- Cancellation: state exit → `task_manager.cancel_by_owner(state.id)` (`:986-997`) → `cancel()` + `gather(return_exceptions=True)` (`task_manager.py:99-136`).
- Unhandled service error (no `onError` declared) → `_fail()` → terminal `error` status (`:1126-1133`).
- `src` may be a `MachineNode` → spawned as a child actor, and the parent **polls** the child's status every 5 ms until it leaves `running` (`_ACTOR_POLL_INTERVAL = 0.005`, `interpreter.py:81`, loop at `:1214-1215`). Child `error` → `onError`; success → `done.invoke.<id>` carrying the **child's whole context** (`:1244-1248`). `finally` always stops the child (`:1281-1292`).

Sync (`sync_interpreter.py:1329-1425`): async services rejected with `NotSupportedError`; services run **inline, blocking**, result queued as `DoneEvent`. `MachineNode` src → `_spawn_actor(..., on_complete=invocation.id)` on a background thread.

---

## 7. Delays / `after`

- Config keys may be int ms or a symbolic name (`models.py:896-928`); symbolic resolved from `MachineLogic.delays` via `_resolve_delay` (`base_interpreter.py:1439-1489`), which accepts number / callable-of-`{context,event}` / named. Named callables are invoked under either calling convention by arity sniffing (`_call_delay_callable`, `:1491-1528`). Unresolvable delay → warn + skip that timer (`:2790-2798`), not an error.
- Async timer: `asyncio.create_task(sleep(delay); send(AfterEvent))` owned by the state id (`interpreter.py:999-1040`).
- Sync timer: a **daemon `threading.Thread` per timer** with a `threading.Event` cancel flag, keyed `"{state_id}::{uuid}"` (`sync_interpreter.py:1257-1327`). Before firing it re-checks `status == "running"` and owner still active.
- Cancellation on exit: async via TaskManager; sync via the `_after_events` flag dict (`sync_interpreter.py:1221-1255`).
- **No clock injection.** Both engines call `asyncio.sleep` / `threading.Event.wait` directly. There is no `Clock` abstraction, no virtual time, no `SimulatedClock` — see §10.

---

## 8. Actors / actor system

- Spawn via action type `spawn_<serviceKey>` (or `spawn_blocking_<key>` in sync), key derived by `spawn_service_key` (`models.py:92-128`).
- Actor id: `"{parent.id}:{explicit_id}"` or `"{parent.id}:{key}:{uuid4}"` (`interpreter.py:958-964`).
- `params`: `id`, `systemId`, `input`. Input is `setdefault`-ed into child context (`:968-971`).
- Registry: `self._actors: Dict[str, BaseInterpreter]`, `self._actor_sources: Dict[actor_id, service_key]`, and a **root-held** `_system` registry reached by walking `parent` (`_system_registry`, `base_interpreter.py:1393-1406`). `ActorSystem` view with `get/get_all/__contains__` (`:96-142`).
- Target resolution for `sendTo`/`forwardTo`/`stopChild` (`_resolve_actor_target`, `:1329-1391`): systemId → exact actor id → match on any `actor_id.split(":")[1:]` segment (ambiguity → warn + **drop the event**) → originating service key → `"parent"`/`"#parent"`.
- `escalate` sends `xstate.error.actor.<id>` to the parent (`interpreter.py:766-777`).
- `stop_child` removes from `_actors`, `_actor_sources` and the system registry, then stops (`:864-888`).

---

## 9. Persistence

`get_persisted_snapshot()` (`base_interpreter.py:690-745`) →
```json
{status, context (deepcopy), state_ids, configuration, output,
 error (str), history {parentId: [nodeId]}, actors {id: {machine_id, src, snapshot}}, system {systemId: actorId}}
```
- Recursive over child actors with cycle detection via `id()` set (`:708-714`).
- `get_snapshot()` = `json.dumps(..., default=str)` (`:684`) — lossy for non-JSON values.
- `from_snapshot(json_str, machine)` (`:814-958`): restores context (**by reference from the parsed JSON, not deep-copied**, `:872`), status, configuration (+ ancestors), output, `error` wrapped in `RestoredError`, history, child actors (resolved through `logic.services`; unresolvable ones parked in `_pending_actor_snapshots` and re-emitted on the next save, `:747-779`), and systemId mappings.
- Restoration is **static**: entry actions are not re-run, timers and invokes are **not** restarted (docstring `:827-831`). `Interpreter.start()` has a resume path that re-attaches an event loop to a restored `running` actor and restarts children (`interpreter.py:187-210`).
- **No schema version field** in the snapshot — see §10.

---

## 10. Plugins, logging, exceptions

- `PluginBase` hooks (`plugins.py:70-256`): `on_interpreter_start/stop`, `on_event_received`, `on_transition(from_states,to_states,transition)`, `on_action_execute`, `on_action_error`, `on_guard_evaluated`, `on_service_start/done/error`. Also duck-typed `on_error` and `on_done` looked up dynamically (`base_interpreter.py:2329-2332`, `:2356-2359`) but **not declared on `PluginBase`**.
- Every plugin is wrapped in `_SafePlugin` (`base_interpreter.py:148-232`), which swallows and logs hook exceptions and returns a no-op for missing hooks. `plugins` setter validates structurally (`on_transition` + `on_event_received` callable) (`:601-638`).
- Logging: `logging.getLogger(__name__)` per module under the `xstate_statemachine` namespace with a `NullHandler` (`logger.py:63-69`). Good citizen. However **the hot path logs heavily at INFO** — e.g. guard evaluation logs INFO per guard (`base_interpreter.py:2927-2931`), event processing logs INFO per event in the sync engine (`sync_interpreter.py:365`), state entry/exit INFO (`sync_interpreter.py:643`, `:747`). At CandleViewer tick rates this matters.
- Exceptions (`exceptions.py`): `XStateMachineError` → `InvalidConfigError`, `StateNotFoundError(target, reference_id)`, `ImplementationMissingError`, `ActorSpawningError`, `NotSupportedError`, `RestoredError`. `RestoredError` is **not** exported in `__init__.__all__`.

---

## 11. Concurrency / asyncio safety

- Async engine: single `asyncio.Queue`, single consumer task `_run_event_loop` (`interpreter.py:406-529`). Serial by construction, **no locks anywhere** in the codebase (`grep` for `asyncio.Lock`/`threading.Lock` → none).
- `send()` is `await queue.put(...)` — fire-and-forget; the caller cannot await the resulting transition. Post-`stop/done/error` sends are dropped with a warning to avoid a queue leak (`:357-369`).
- Loop survives per-event errors: exceptions inside `_process_event_and_transient_transitions` are logged and the loop continues (`:470-489`). The sync engine, by contrast, **propagates** to the caller of `send()`. This is a real behavioural divergence between engines.
- Self-feeding protection: `_raise_depth` counts events enqueued to self *while processing*, bounded by `max_iterations` (`:409-440`, `:800-808`).
- Cancellation hygiene: `_run_event_loop` deliberately does not set `status` on `CancelledError` so a later `stop()` still tears down actors/tasks (`:493-507`).
- Sync engine uses raw daemon threads for `after` timers and delayed sends and for non-blocking actors (`sync_interpreter.py:1087-1090`, `:1185-1187`, `:1323-1327`). Those threads call `self.send(...)`, which mutates `_event_queue` (a `deque`) and reads `_active_state_nodes` **without any lock** — cross-thread mutation of interpreter state. `deque.append` is atomic, but `_process_event_queue`'s `_is_processing` re-entrancy flag is a plain bool check-then-set (`:337-340`): a timer thread firing concurrently with a main-thread `send()` can have its event silently deferred or processed on the wrong thread.
- **The async engine is not thread-safe either**: `Interpreter.send` must be awaited on the loop; there is no `call_soon_threadsafe` path for producers on other threads.

---

## 12. Performance-relevant details

- Per event: `_select_transitions` builds a fresh `leaves` list, sorts it, and for each leaf walks the full ancestor chain building a new `eligible` list and a `guard_cache` dict (`base_interpreter.py:2562-2599`). Allocation is O(leaves × depth) per event; nothing is precomputed or cached across events.
- `_matching_descriptors` iterates **all** keys of each `on` map on every state on every ancestor walk to find `*`-suffixed descriptors, then sorts (`:2408-2418`). No precompiled descriptor index.
- `_is_descendant` uses **string prefix comparison on ids** (`:2751-2771`), called in loops over `_active_state_nodes`. O(len(id)) string work in the hot path, despite `depth` being cached as an int.
- Target resolution mutates `transition.target_str` as a side effect on first resolution (`:1195`, `sync_interpreter.py:1478`) — an accidental cache, but it also means the definition object is shared mutable state across interpreters of the same machine.
- `get_persisted_snapshot` deep-copies the entire context (`:721`); `_build_initial_context` deep-copies per interpreter (`:365`). Fine at machine-per-order scale, costly if context holds order books.
- `_spawn_and_manage_actor` **polls at 5 ms** for child completion (`interpreter.py:1214-1215`) rather than awaiting an event — one busy-ish task per invoked child machine.
- Sync `after` = **one OS thread per timer** (`sync_interpreter.py:1323`). With CandleViewer's per-order TWAP/iceberg timers this is disqualifying for the sync engine.
- Logging at INFO on hot paths (§10) — each `logger.info` with args still pays a level check plus arg tuple allocation.

---

## 13. XState v5 feature parity

Present:
- `assign`, `raise`, `sendTo`, `sendParent`, `forwardTo`, `escalate`, `log`, `cancel`, `stopChild`, `spawnChild`, `emit`, `pure`, `choose`, `enqueueActions` (`actions.py`).
- Guard composition `and`/`or`/`not` + `stateIn` (`models.py:210-333`, `base_interpreter.py:2866-2891`).
- Wildcard and partial event descriptors (`:2361-2424`).
- `state.matches`, `tags`, `has_tag`, `meta`, `get_meta`, `output` (machine + final-state, callable form), `can()`, `subscribe`, actor `system`/`systemId`, `input`, context factory.
- `always`, forbidden transitions (`on: {E: null}`), history shallow/deep, `maxIterations`.
- Pure transition API (`transition`/`initialTransition`/`getNextSnapshot`), `waitFor`, `toPromise`, `getPersistedSnapshot`.
- v4 compatibility: `cond`, `on: {"": ...}`.

Missing or weaker than XState v5:
1. **No typed context/events.** `TContext` is bound to `Dict[str, Any]`; no `setup({types})` equivalent, no typestate. Everything is stringly-typed.
2. **No `assign` with nested paths / no immutable updates.** Context is mutated in place; no draft/producer semantics.
3. **No `invoke` `input` as a callable of `{context, event}`** — `InvokeDefinition.input` is a static dict (`models.py:469`); it is passed as `event.payload["input"]` to the service, not merged into a child machine's context (child spawn via `invoke` ignores `input` entirely: `_spawn_and_manage_actor` never reads `invocation.input`, `interpreter.py:1173-1252`).
4. **No `onSnapshot` for invoked actors**, no actor `subscribe`-through, no `fromPromise`/`fromCallback`/`fromObservable`/`fromTransition` actor-logic constructors. Services are plain callables; a callback-style long-running service that emits multiple events has no first-class form (you must capture `interpreter` and call `send`).
5. **No clock injection / virtual time.** No `SimulatedClock`, no way to make `after` deterministic in tests except real sleeps (`helpers.wait_for` polls real time).
6. **No `stateIn` as `in:` transition key** (only guard form), and no `#id`-relative `in` semantics.
7. **`description`, `meta` present but no `state.value` object form** — active states are a flat `Set[str]` of ids; there is no hierarchical `{parent: 'child'}` state value, which XState consumers and visualisers expect.
8. **No `snapshot.can` / `snapshot.hasTag` on a snapshot object** — those live on the interpreter; `PureSnapshot` only has `matches`.
9. **No event emit typing / `emit` in `setup`**, no `actor.on` unsubscribe-all.
10. **No `reenter` on ancestors / no explicit `internal: false` key** (only `reenter`).
11. **No `spawn` inside `assign`** (XState's `spawn(...)` in an assigner); spawning is only via the `spawn_<key>` action naming convention or `spawnChild`.
12. **No snapshot schema version** — `from_snapshot` will happily load an old-shaped snapshot and partially mis-restore it.
13. **No `systemId` uniqueness enforcement** — duplicate registration warns and silently replaces (`base_interpreter.py:1429-1437`).
14. **No `inspect` API** (XState's inspection events); plugins are the substitute but have no event-bus form.

---

## 14. Code smells and design concerns

1. **Dead code after `return`** — `TransitionDefinition.guard` property has 8 lines of unreachable `logger.debug` after `return` (`models.py:414-423`); same pattern at `models.py:1032-1034` (a misindented comment block inside a method body).
2. **Duplicated engine logic.** `Interpreter` and `SyncInterpreter` each reimplement target resolution (`base_interpreter.py:1164` vs `sync_interpreter.py:1431`), transition execution (`:1732` vs `:456`), entry/exit (`:1896/:2108` vs `:614/:724`), and built-in action dispatch (`:695` vs `:901`). The "shared" base only covers `_collect_builtin_followups`. Every fix has to be made twice; the file comments themselves repeatedly document cases where the two engines had diverged.
3. **`BaseInterpreter._process_event` and `_execute_transition` are `async def` but live in the "mode-agnostic" base**, and `SyncInterpreter` overrides them with sync versions of different names (`_process_event`, `_execute_transition_sync`). The base class's async methods are therefore unused by the sync engine — the Template Method pattern is broken in practice.
4. **Over-forgiving target resolution.** The 4-stage fallback ending in an exhaustive tree walk matching on the last id segment (`base_interpreter.py:1238-1250`) will resolve a typo'd target to *some* unrelated state with the same leaf name, silently. For a trading OMS this is a live hazard: `target: "filled"` matching `orders.child.filled` from the wrong branch.
5. **Guard exceptions → `False`** (`:2911-2925`). Defensible, but for a risk-gating guard ("is live trading enabled?") a raising guard silently blocks or, in an `or` composition, may let a fallback branch fire.
6. **Action exceptions → logged and remaining actions skipped, transition completes** (`interpreter.py:667-689`). The state change happens even though half its actions did not. For an OMS this can produce a state that says "submitted" with no order actually sent. The only programmatic signal is the `on_action_error` plugin hook.
7. **`MachineLogic` arity-based auto-registration** (`machine_logic.py:220-255`) silently misclassifies callables; `*args` or default params shift arity.
8. **Mutation of shared definition objects.** `transition.target_str` is rewritten during resolution (`:1195`) on `TransitionDefinition` objects owned by the `MachineNode`, which is shared across all interpreters of that machine. Two interpreters resolving from different sources can race on this field (async engine: same loop, so serialized; sync engine with threads: genuinely racy).
9. **`from_snapshot` does not deep-copy the restored context** (`:872`), so the caller's parsed dict aliases live machine state.
10. **State-key dot handling is a warning, not an error**, in the non-ambiguous case (`models.py:702-718`) — leaves a latent id-collision hazard.
11. **`_prepare_event` duck-typing branch** (`:1148-1153`) forwards arbitrary objects with `.type`/`.payload` unchecked.
12. **Polling everywhere**: actor completion (5 ms), `wait_for` (5 ms), sync actor runner (10 ms). No condition variables or futures.
13. **`SyncInterpreter._is_async_callable`** checks `__code__.co_flags & 0x80` (`:1532-1548`) — misses `functools.partial`, callables with `__call__`, and async generators.
14. **`spawn_blocking_` handling is sync-only**; the async engine's `_execute_actions` tests `startswith("spawn_")` (`interpreter.py:615`) so `spawn_blocking_x` resolves to service key `x` and spawns non-blocking — a silent semantic difference between engines.
15. **`send()` on the async engine can't be awaited to completion**, so there is no natural back-pressure or "did my event actually transition" answer. `can()` before send + `subscribe` after is the workaround.
16. **Error-event class naming**: `error.platform.*` carries an exception instance in `DoneEvent.data` (`interpreter.py:1121-1125`). `DoneEvent` for errors is misleading and forces consumers to inspect `type`.

---

## 15. Relevance notes for CandleViewer (facts only)

- Per-order machines (OMS, OCO, iceberg, TWAP, chase) map cleanly onto `Interpreter` + `invoke` + `after`, but: `after` has no injectable clock, so deterministic replay of a TWAP schedule would need either real sleeps or a custom interpreter subclass overriding `_after_timer`.
- Replay/recorder: `get_persisted_snapshot`/`from_snapshot` cover configuration + context + history + child actors, but do **not** restore timers or in-flight invokes, and carry no schema version — a replay/failover design would need its own versioning and re-arming layer.
- Fan-out / trade groups: the actor system (`systemId`, `sendTo`, `forwardTo`) exists, but ambiguous key resolution drops events with only a log warning (`:1377-1384`).
- Throughput: ingestion/book-engine hot paths should not be modelled as machines given per-event allocation and INFO-level logging on the hot path (§12).
- The sync engine's thread-per-timer and lock-free cross-thread `send` make it unsuitable for the backend; only `Interpreter` is viable.
