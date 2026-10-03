import { KEYMAP } from "./keymap";

/** Live keymap profile (current bindings). Rebinds take effect without reload (SCR-113). */
let bindings: ReadonlyMap<string, string> = new Map(KEYMAP.map((c) => [c.id, c.defaultBinding]));
const listeners = new Set<() => void>();

export const getBindings = (): ReadonlyMap<string, string> => bindings;
export function setBindings(next: ReadonlyMap<string, string>): void {
  bindings = next;
  listeners.forEach((l) => l());
}
export function subscribeBindings(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
export function resetBindings(): void {
  setBindings(new Map(KEYMAP.map((c) => [c.id, c.defaultBinding])));
}
