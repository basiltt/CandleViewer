import { PlaceholderRoute } from "./routes/PlaceholderRoute";

/**
 * Root application shell. E02-T04 ships a single placeholder route to prove
 * the build/test/e2e/a11y harness; the real route tree (12-sitemap.md),
 * auth/RBAC guards and env badge land in E10.
 */
export function App(): JSX.Element {
  return <PlaceholderRoute />;
}
