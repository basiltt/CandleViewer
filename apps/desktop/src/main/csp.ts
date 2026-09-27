/**
 * Content-Security-Policy string builder for the Electron renderer.
 * `'unsafe-inline'` is scoped to `style-src` only, pending a nonce-based
 * approach once E05 fixes the design system's styling method
 * (20-architecture.md notes, E02-T04 Technical notes).
 */
export function buildCsp(): string {
  return [
    "default-src 'self'",
    "connect-src 'self' ws: wss:",
    "img-src 'self' data:",
    "style-src 'self' 'unsafe-inline'",
  ].join("; ");
}
