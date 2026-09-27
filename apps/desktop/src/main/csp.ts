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
const ALLOWED_LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

/**
 * Parses `rawOrigin` and returns its normalised origin, restricted to a
 * loopback host (per `50-security.md`: "Backend binds 127.0.0.1 /
 * WSL-internal only"). Falls back to `DEFAULT_BACKEND_ORIGIN` if the value
 * is unparsable or not loopback, so an unvalidated `CV_BACKEND_ORIGIN` env
 * var can never inject extra CSP directives/tokens or widen `connect-src`
 * to an arbitrary host.
 */
function resolveBackendOrigin(rawOrigin: string): string {
  let parsed: URL;
  try {
    parsed = new URL(rawOrigin);
  } catch {
    return DEFAULT_BACKEND_ORIGIN;
  }
  if (!ALLOWED_LOOPBACK_HOSTS.has(parsed.hostname)) {
    return DEFAULT_BACKEND_ORIGIN;
  }
  return parsed.origin;
}

export function buildCsp(backendOrigin: string = process.env["CV_BACKEND_ORIGIN"] ?? DEFAULT_BACKEND_ORIGIN): string {
  const safeOrigin = resolveBackendOrigin(backendOrigin);
  const wsOrigin = safeOrigin.replace(/^http/, "ws");
  return [
    "default-src 'self'",
    `connect-src 'self' ${safeOrigin} ${wsOrigin}`,
    "img-src 'self' data:",
    "style-src 'self' 'unsafe-inline'",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
  ].join("; ");
}
