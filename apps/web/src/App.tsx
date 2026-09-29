import { RouterProvider } from "react-router-dom";
import { createRouteTree } from "./routes/tree";

/**
 * Root application shell (E10-T01). Renders the React Router data router
 * built from the route manifest (`docs/plan/12-sitemap.md` §2). The router
 * instance is created once per app instance, not per render.
 */
const router = createRouteTree();

export function App(): JSX.Element {
  return <RouterProvider router={router} />;
}
