import { useEffect, useState, type FormEvent, type JSX } from "react";
import { useNavigate } from "react-router-dom";
import { getStepUpExpiresAt, recordStepUp } from "../lib/auth/meCache";

function remainingSeconds(expiresAt: string | null, nowMs: number): number {
  if (!expiresAt) return 0;
  const ms = Date.parse(expiresAt) - nowMs;
  return Number.isNaN(ms) || ms <= 0 ? 0 : Math.ceil(ms / 1000);
}

function formatRemaining(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export interface StepUpGateProps {
  /** Path (+ query) to return to once step-up succeeds. */
  readonly redirectTo: string;
}

/**
 * M-020 step-up modal contract: re-enter a TOTP code, `POST
 * /api/v1/auth/step-up`, and on success navigate back to the original
 * destination without a full page reload (`docs/plan/22-api-openapi.yaml`
 * `/auth/step-up`; `docs/plan/12-sitemap.md` §4).
 */
export function StepUpGate({ redirectTo }: StepUpGateProps): JSX.Element {
  const navigate = useNavigate();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [expiresAt, setExpiresAt] = useState<string | null>(getStepUpExpiresAt);
  const [now, setNow] = useState(() => Date.now());
  const remaining = remainingSeconds(expiresAt, now);
  const windowLive = remaining > 0;

  useEffect(() => {
    if (!windowLive) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [windowLive]);

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/step-up", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      if (!response.ok) {
        setError("That code did not work. Try again.");
        return;
      }
      // Server elevates the class its last 403 challenged; the body carries only the code.
      const body: { elevated_until: string; step_up_expires_at?: string | null } =
        await response.json();
      const expires = body.step_up_expires_at ?? null;
      recordStepUp(body.elevated_until, expires);
      setExpiresAt(expires);
      setNow(Date.now());
      navigate(redirectTo, { replace: true });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="step-up-title">
      <h1 id="step-up-title">Confirm it&apos;s you</h1>
      <p>Enter your authenticator code to continue to the Admin area.</p>
      <p aria-live="polite" data-testid="step-up-grace">
        {remaining > 0 ? `Grace window: ${formatRemaining(remaining)} remaining` : ""}
      </p>
      <form onSubmit={(event) => void onSubmit(event)}>
        <label htmlFor="step-up-code">Authenticator code</label>
        <input
          id="step-up-code"
          name="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(event) => setCode(event.target.value)}
        />
        {error ? <p role="alert">{error}</p> : null}
        <button type="submit" disabled={submitting || code.length === 0}>
          Confirm
        </button>
      </form>
    </div>
  );
}
