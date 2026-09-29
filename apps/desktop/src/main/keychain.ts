import { randomUUID } from "node:crypto";

/**
 * KEK handle bridge (SR-119). The Electron main process never holds Bybit
 * credentials, the KEK, or DEK material — it only mints an opaque,
 * per-session handle string the backend can resolve on its own side. There
 * is no function anywhere in this module (or reachable from it) that
 * accepts or returns key material; the handle carries no key bytes, only an
 * identifier.
 */
const SESSION_HANDLE = `kek-handle-${randomUUID()}`;

/** Returns an opaque handle only — never key material (SR-119). */
export function getKekHandle(): string {
  return SESSION_HANDLE;
}
