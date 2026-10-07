// E17-T05: the single entry point the WS client feeds every `err` frame through.
import { classifyError, type ErrorTreatment } from "./errorMapping";

export interface WsErrorFrame {
  readonly t: "err";
  readonly p: { readonly code: string; readonly message?: string };
}

type Listener = (code: string, treatment: ErrorTreatment) => void;
const listeners = new Set<Listener>();

/** UI surfaces (modal host, staleness badge, toasts) subscribe here; returns teardown. */
export function onWsError(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function handleWsError(frame: WsErrorFrame): ErrorTreatment {
  const treatment = classifyError(frame.p.code);
  if (treatment.consoleError) {
    // Server-derived values go in as separate arguments, never in the format
    // string: a `%s`/`%d` inside `code` or `message` must print literally
    // (CodeQL js/tainted-format-string).
    console.error("[ws] client-bug error", frame.p.code, frame.p.message ?? "");
  }
  for (const l of listeners) l(frame.p.code, treatment);
  return treatment;
}
