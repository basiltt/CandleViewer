import { useCallback, useEffect, useState, type FormEvent, type JSX } from "react";
import { StepUpGate } from "../../routes/StepUpGate";
import { inviteApi, type CreatedInvite, type PendingInvite } from "./inviteApi";

/** SCR-123 Admin: invite user (R-303). Link is shown once; only revoke/re-issue afterwards. */
export function AdminInviteScreen(): JSX.Element {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [error, setError] = useState<string | null>(null);
  const [needsStepUp, setNeedsStepUp] = useState(false);
  const [created, setCreated] = useState<CreatedInvite | null>(null);
  const [copied, setCopied] = useState(false);
  const [pending, setPending] = useState<readonly PendingInvite[]>([]);

  const refresh = useCallback(async () => {
    const res = await inviteApi.list();
    if (res.ok && res.data) setPending(res.data.items);
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  function show(invite: CreatedInvite): void {
    setCreated(invite);
    setCopied(false);
    void refresh();
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setNeedsStepUp(false);
    if (!/^[a-z0-9._-]{3,32}$/.test(username)) {
      setError("Username must be 3-32 characters of a-z, 0-9, dot, underscore or dash.");
      return;
    }
    const res = await inviteApi.create({ username, email, roles: [role] });
    if (res.ok && res.data) {
      show(res.data);
      return;
    }
    if (res.status === 403 && res.code === "step_up_required") setNeedsStepUp(true);
    else if (res.status === 409) setError("That email or username is already in use.");
    else setError("The invitation could not be created.");
  }

  async function copy(): Promise<void> {
    if (!created) return;
    await navigator.clipboard.writeText(`${window.location.origin}${created.invite_url}`);
    setCopied(true);
  }

  async function reissue(userId: string): Promise<void> {
    const res = await inviteApi.reissue(userId);
    if (res.ok && res.data) show(res.data);
    else setError("The invitation could not be re-issued.");
  }

  async function revoke(userId: string): Promise<void> {
    await inviteApi.revoke(userId);
    await refresh();
  }

  const link = created ? `${window.location.origin}${created.invite_url}` : "";

  return (
    <main>
      <h1>Invite user</h1>
      <p>
        The invitee also needs a Tailscale ACL grant before the link will open. Link delivery is
        manual: copy it and send it yourself.
      </p>
      {needsStepUp ? <StepUpGate redirectTo="/admin/users/new" /> : null}
      <form onSubmit={(event) => void onSubmit(event)}>
        <label htmlFor="inv-username">Username</label>
        <input id="inv-username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <label htmlFor="inv-email">Email</label>
        <input
          id="inv-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label htmlFor="inv-role">Role</label>
        <select id="inv-role" value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="viewer">Viewer</option>
          <option value="manager">Manager</option>
        </select>
        <p>Expires 72 hours after creation. Account access is granted after activation.</p>
        {error ? <p role="alert">{error}</p> : null}
        <button type="submit">Create invitation</button>
      </form>
      {created ? (
        <section aria-labelledby="inv-link-title">
          <h2 id="inv-link-title">Invitation link</h2>
          <p>
            This link grants access - treat it as a secret. It is shown only once and cannot be
            retrieved later, only revoked or re-issued.
          </p>
          <label htmlFor="inv-link">Invite link</label>
          <input id="inv-link" readOnly value={link} />
          <button type="button" onClick={() => void copy()}>
            Copy link
          </button>
          <span aria-live="polite">{copied ? "Copied" : ""}</span>
          <p>Expires at {new Date(created.invite_expires_at).toUTCString()}</p>
        </section>
      ) : null}
      <section aria-labelledby="inv-pending-title">
        <h2 id="inv-pending-title">Pending invitations</h2>
        <ul>
          {pending.map((p) => (
            <li key={p.user_id}>
              {p.username} ({p.role}) -{" "}
              {p.expired
                ? "Expired - re-issue to send a new link"
                : `expires ${new Date(p.expires_at).toUTCString()}`}{" "}
              <button type="button" onClick={() => void reissue(p.user_id)}>
                Re-issue
              </button>
              <button type="button" onClick={() => void revoke(p.user_id)}>
                Revoke
              </button>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
