import { useEffect, useState, useSyncExternalStore } from "react";
import { createDispatcher } from "./dispatcher";
import { getBindings, subscribeBindings } from "./profile";
import type { KeymapCommand } from "./keymap";

/** Command handlers registered by views; a command with no handler / failing predicate is inert. */
const handlers = new Map<string, { run: () => void; isValid: () => boolean }>();
export function registerCommand(id: string, run: () => void, isValid: () => boolean = () => true) {
  handlers.set(id, { run, isValid });
  return () => void handlers.delete(id);
}

/** Active contexts come from `data-keymap-context` on the focused element's ancestors. */
export function activeContexts(el: Element | null = document.activeElement): Set<string> {
  const s = new Set<string>(["Global"]);
  for (let n = el; n; n = n.parentElement) {
    const c = n.getAttribute("data-keymap-context");
    if (c) s.add(c);
  }
  return s;
}

/** SCR-015 toast host: polite, non-modal, never steals focus. */
export function ToastHost({ messages }: { readonly messages: readonly string[] }): JSX.Element {
  return (
    <div role="status" aria-live="polite" data-testid="toast-host">
      {messages.map((m, i) => (
        <p key={`${i}-${m}`}>{m}</p>
      ))}
    </div>
  );
}

export function KeymapHost(): JSX.Element {
  const [toasts, setToasts] = useState<readonly string[]>([]);
  const bindings = useSyncExternalStore(subscribeBindings, getBindings);
  useEffect(() => {
    const dispatch = createDispatcher({
      bindings,
      now: () => Date.now(),
      isValid: (c: KeymapCommand) => handlers.get(c.id)?.isValid() ?? false,
      execute: (c: KeymapCommand) => handlers.get(c.id)?.run(),
      notify: (m) => {
        setToasts((t) => [...t, m]);
        window.setTimeout(() => setToasts((t) => t.slice(1)), 5000);
      },
    });
    const onKey = (e: KeyboardEvent) => {
      const r = dispatch(e, activeContexts());
      if (r.status === "executed") e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [bindings]);
  return <ToastHost messages={toasts} />;
}
