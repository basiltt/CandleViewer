import { useEffect } from "react";
import { RouterProvider } from "react-router-dom";
import { WsErrorHost } from "./lib/ws/WsErrorHost";
import { startTelemetry } from "./lib/telemetry/aggregator";
import { KeymapHost } from "./keymap/KeymapHost";
import { PreferencesProvider } from "./features/a11y-preferences/PreferencesContext";
import { usePublishEngineFlags } from "./features/a11y-preferences/consumers";
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
  const publishFlags = usePublishEngineFlags();
  return (
    <PreferencesProvider onEngineFlags={publishFlags}>
      <RouterProvider router={router} />
      <WsErrorHost />
      <KeymapHost />
    </PreferencesProvider>
  );
}
