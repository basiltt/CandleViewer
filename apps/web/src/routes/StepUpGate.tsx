import { useState, type FormEvent, type JSX } from "react";
import { useNavigate } from "react-router-dom";
import { recordStepUp } from "../lib/auth/meCache";

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
      const body: { elevated_until: string } = await response.json();
      recordStepUp(body.elevated_until);
      navigate(redirectTo, { replace: true });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="step-up-title">
      <h1 id="step-up-title">Confirm it&apos;s you</h1>
      <p>Enter your authenticator code to continue to the Admin area.</p>
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
