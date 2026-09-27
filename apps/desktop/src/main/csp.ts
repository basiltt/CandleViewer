/**
 * Content-Security-Policy string builder for the Electron renderer.
 * `'unsafe-inline'` is scoped to `style-src` only, pending a nonce-based
 * approach once E05 fixes the design system's styling method
 * (20-architecture.md notes, E02-T04 Technical notes).
 *
 * `connect-src` is scoped to the app itself plus the backend origin (default
 * the local FastAPI backend at 127.0.0.1, per `50-security.md`: "Backend
 * binds 127.0.0.1 / WSL-internal only"). It never opens WebSocket/fetch
 * connections to an arbitrary host.
 */
const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:8000";

export function buildCsp(backendOrigin: string = process.env["CV_BACKEND_ORIGIN"] ?? DEFAULT_BACKEND_ORIGIN): string {
  const wsOrigin = backendOrigin.replace(/^http/, "ws");
  return [
    "default-src 'self'",
    `connect-src 'self' ${backendOrigin} ${wsOrigin}`,
    "img-src 'self' data:",
    "style-src 'self' 'unsafe-inline'",
  ].join("; ");
}
