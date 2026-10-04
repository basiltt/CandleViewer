import { KEYMAP, eventBinding, type KeyEventLike, type KeymapCommand } from "./keymap";

export const INERT_NOTICE_WINDOW_MS = 5000;

export type DispatchResult =
  | { readonly status: "executed"; readonly commandId: string }
  | { readonly status: "inert"; readonly commandId: string; readonly notified: boolean }
  | { readonly status: "unbound" };

export interface DispatcherDeps {
  /** Is the command's `validWhen` satisfied in the current focus/context? */
  readonly isValid: (cmd: KeymapCommand) => boolean;
  readonly execute: (cmd: KeymapCommand) => void;
  /** Non-modal polite notice (toast host, role="status"); must not steal focus. */
  readonly notify: (message: string) => void;
  readonly now: () => number;
  /** Counter of inert presses by command id (observability). */
  readonly countInert?: (commandId: string) => void;
  /** Current bindings (profile); defaults to the keymap defaults. */
  readonly bindings?: ReadonlyMap<string, string>;
}

/** Contextual explanation: what the command needs and where its visible control lives. */
export function inertMessage(c: KeymapCommand): string {
  const where = typeof c.visibleControl === "string" ? ` Use ${c.visibleControl} instead.` : "";
  const ctx = c.context === "Global" ? "" : ` (${c.context} view)`;
  return `${c.label} is not available here${ctx}: it needs ${c.validWhen}.${where}`;
}

/** Resolve binding -> command -> validWhen -> execute, or explain why it is inert here. */
export function createDispatcher(deps: DispatcherDeps) {
  const lastNotified = new Map<string, number>();
  const bound = (c: KeymapCommand): string => deps.bindings?.get(c.id) ?? c.defaultBinding;
  return (e: KeyEventLike, activeContexts: ReadonlySet<string>): DispatchResult => {
    const got = eventBinding(e);
    const cmd = KEYMAP.find((c) => activeContexts.has(c.context) && bound(c) === got);
    if (cmd && deps.isValid(cmd)) {
      deps.execute(cmd);
      return { status: "executed", commandId: cmd.id };
    }
    const target = cmd ?? KEYMAP.find((c) => bound(c) === got);
    if (!target) return { status: "unbound" };
    deps.countInert?.(target.id);
    const t = deps.now();
    const prev = lastNotified.get(target.id);
    const notified = prev === undefined || t - prev >= INERT_NOTICE_WINDOW_MS;
    if (notified) {
      lastNotified.set(target.id, t);
      deps.notify(inertMessage(target));
    }
    return { status: "inert", commandId: target.id, notified };
  };
}
