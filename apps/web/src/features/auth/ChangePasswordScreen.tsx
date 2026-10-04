import { useState, type FormEvent, type JSX } from "react";
import { changePassword } from "./authApi";

const MIN = 12;

function strength(pw: string): "Weak" | "Fair" | "Strong" {
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length;
  if (pw.length < MIN) return "Weak";
  return pw.length >= 16 && classes >= 3 ? "Strong" : "Fair";
}

/** SCR-004 Forced password change (R-007): no dismiss path. */
export function ChangePasswordScreen(): JSX.Element {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const longEnough = next.length >= MIN;
  const matches = next !== "" && next === confirm;

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!longEnough) return setError("Use at least 12 characters.");
    if (!matches) return setError("Passwords don't match.");
    setError(null);
    setBusy(true);
    const out = await changePassword(current, next);
    setBusy(false);
    if (out === "ok") setDone(true);
    else if (out === "reused") setError("You cannot reuse any of your last 5 passwords.");
    else if (out === "breached") setError("This password appears in a known breach list.");
    else if (out === "unreachable") setError("Cannot reach the server. Try again.");
    else setError("That password was not accepted.");
  }

  if (done) {
    return (
      <main>
        <h1>Password changed</h1>
        <a href="/login">Continue to sign in</a>
      </main>
    );
  }
  const type = reveal ? "text" : "password";
  return (
    <main>
      <h1>Choose a new password</h1>
      <p>You must change your password before continuing.</p>
      <form onSubmit={(e) => void onSubmit(e)} noValidate>
        <div role="alert">{error}</div>
        <label htmlFor="cp-cur">Current password</label>
        <input
          id="cp-cur"
          type={type}
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <label htmlFor="cp-new">New password</label>
        <input
          id="cp-new"
          type={type}
          autoComplete="new-password"
          value={next}
          aria-describedby="cp-req cp-strength"
          onChange={(e) => setNext(e.target.value)}
        />
        <p id="cp-strength">Strength: {strength(next)}</p>
        <label htmlFor="cp-conf">Confirm new password</label>
        <input
          id="cp-conf"
          type={type}
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <ul id="cp-req" aria-live="polite" aria-label="Password requirements">
          <li>
            {longEnough ? "Met" : "Not met"}: at least {MIN} characters
          </li>
          <li>{matches ? "Met" : "Not met"}: passwords match</li>
        </ul>
        <button type="button" aria-pressed={reveal} onClick={() => setReveal((r) => !r)}>
          {reveal ? "Hide passwords" : "Show passwords"}
        </button>
        <button type="submit" disabled={busy}>
          Change password
        </button>
      </form>
    </main>
  );
}
