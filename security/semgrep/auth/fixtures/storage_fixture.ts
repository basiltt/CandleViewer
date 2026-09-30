// Fixtures for no-jwt-in-browser-storage (E09-X03). Scanned only, never built.
export function saveBad(t: string): void {
  localStorage.setItem("access_token", t); // ruleid: no-jwt-in-browser-storage
}

export function saveSessionBad(t: string): void {
  sessionStorage.setItem("session", t); // ruleid: no-jwt-in-browser-storage
}

export function savePrefOk(theme: string): void {
  localStorage.setItem("theme", theme); // ok: no-jwt-in-browser-storage
}
