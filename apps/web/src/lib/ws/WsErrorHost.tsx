// E17-T05: renders the 23-ws-protocol.md 10.3 treatments for err frames:
// fatal -> blocking modal, transient -> staleness badge, client bug / capacity -> toast.
import { useEffect, useState } from "react";
import { onWsError } from "./errorHandler";
import type { ErrorTreatment } from "./errorMapping";

interface Surface {
  readonly modal: string | null;
  readonly badge: string | null;
  readonly toast: { readonly code: string; readonly kind: "reportBug" | "fewerPanes" } | null;
}

const EMPTY: Surface = { modal: null, badge: null, toast: null };

export function reduceSurface(s: Surface, code: string, t: ErrorTreatment): Surface {
  return {
    modal: t.modal ? code : s.modal,
    badge: t.inlineBadge ? code : s.badge,
    toast: t.toast === "none" ? s.toast : { code, kind: t.toast },
  };
}

export function WsErrorHost(): JSX.Element | null {
  const [s, setS] = useState<Surface>(EMPTY);
  useEffect(() => onWsError((code, t) => setS((prev) => reduceSurface(prev, code, t))), []);
  if (!s.modal && !s.badge && !s.toast) return null;
  return (
    <>
      {s.modal ? (
        <div role="alertdialog" aria-modal="true" aria-label="Connection error">
          <p>Session error ({s.modal}). Sign in again or contact an owner.</p>
          <button type="button" onClick={() => setS((p) => ({ ...p, modal: null }))}>
            Dismiss
          </button>
        </div>
      ) : null}
      {s.badge ? (
        <div role="status" aria-live="polite">
          Data may be stale ({s.badge})
        </div>
      ) : null}
      {s.toast ? (
        <div role="status" aria-live="polite">
          {s.toast.kind === "reportBug"
            ? `Unexpected client error (${s.toast.code}). Please report a bug.`
            : `Server capacity reached (${s.toast.code}). Try fewer panes.`}
        </div>
      ) : null}
    </>
  );
}
