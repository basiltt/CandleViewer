import { KEYMAP } from "./keymap";

/** Live keymap profile (current bindings). Rebinds take effect without reload (SCR-113). */
const STORE_KEY = "cv.keymap-profile.v1";
const defaults = (): Map<string, string> => new Map(KEYMAP.map((c) => [c.id, c.defaultBinding]));

/** Only known command ids with string bindings are restored; anything else is ignored. */
function loadPersisted(): ReadonlyMap<string, string> {
  const m = defaults();
  try {
    const raw = typeof window === "undefined" ? null : window.localStorage.getItem(STORE_KEY);
    const v: unknown = raw ? JSON.parse(raw) : null;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      for (const [id, b] of Object.entries(v as Record<string, unknown>)) {
        if (m.has(id) && typeof b === "string" && b) m.set(id, b);
      }
    }
  } catch {
    /* corrupt or unavailable storage: fall back to defaults */
  }
  return m;
}
function persist(b: ReadonlyMap<string, string>): void {
  try {
    const overrides: Record<string, string> = {};
    for (const c of KEYMAP) {
      const cur = b.get(c.id);
      if (cur !== undefined && cur !== c.defaultBinding) overrides[c.id] = cur;
    }
    window.localStorage.setItem(STORE_KEY, JSON.stringify(overrides));
  } catch {
    /* storage unavailable: in-memory profile still applies this session */
  }
}

let bindings: ReadonlyMap<string, string> = loadPersisted();
const listeners = new Set<() => void>();

export const getBindings = (): ReadonlyMap<string, string> => bindings;
export function setBindings(next: ReadonlyMap<string, string>): void {
  bindings = next;
  persist(next);
  listeners.forEach((l) => l());
}
export function subscribeBindings(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
export function resetBindings(): void {
  setBindings(defaults());
}
