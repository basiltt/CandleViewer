import type { JSX } from "react";

export interface StubRouteProps {
  readonly routeId: string;
  readonly owner: string;
}

/** Placeholder element for a route whose real screen ships in a later epic. */
export function StubRoute({ routeId, owner }: StubRouteProps): JSX.Element {
  return (
    <main>
      <h1>
        {routeId} — owned by {owner}
      </h1>
      <p>This screen has not shipped yet.</p>
    </main>
  );
}
