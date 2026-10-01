import { useEffect } from "react";
import { RouterProvider } from "react-router-dom";
import { startTelemetry } from "./lib/telemetry/aggregator";
import { createRouteTree } from "./routes/tree";

/**
 * Root application shell (E10-T01). Renders the React Router data router
 * built from the route manifest (`docs/plan/12-sitemap.md` §2). The router
 * instance is created once per app instance, not per render.
 */
const router = createRouteTree();

export function App(): JSX.Element {
  // E04-T06: frontend telemetry push loop lives exactly as long as the app.
  useEffect(() => startTelemetry().stop, []);
  return <RouterProvider router={router} />;
}
